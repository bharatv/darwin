"""
Unit tests for deployment strategy executors.

Tests the three strategy implementations (Rolling, Canary, Blue-Green)
with mocked DCM and orchestrator dependencies.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ml_serve_core.strategies import (
    RollingDeploymentExecutor,
    CanaryDeploymentExecutor,
    BlueGreenDeploymentExecutor,
    DeploymentContext,
    DeploymentResult
)


@pytest.fixture
def deployment_context():
    """Create a sample deployment context for testing."""
    return DeploymentContext(
        serve_name="test-serve",
        environment="local",
        namespace="serve",
        kube_cluster="kind-cluster",
        artifact_id="local-test-serve-v1",
        runtime_image="localhost:5000/test:v1",
        version="v1",
        base_values={
            "name": "test-serve-local",
            "replicaCount": 2,
            "hpa": {"maxReplicas": 5},
            "envs": {"ENV": "local"}
        },
        strategy_config={},
        environment_variables={"LOG_LEVEL": "INFO"},
        darwin_resource="fastapi-serve"
    )


@pytest.fixture
def mock_dcm_client():
    """Create a mocked DCM client."""
    mock_client = AsyncMock()
    mock_client.build_resource.return_value = {"resource_id": "test-resource-123"}
    mock_client.start_resource.return_value = {"status": "RUNNING"}
    mock_client.get_status.return_value = "RUNNING"
    mock_client.stop_resource.return_value = {"status": "STOPPED"}
    return mock_client


@pytest.fixture
def mock_orchestrator():
    """Create a mocked deployment orchestrator."""
    mock_orch = AsyncMock()
    mock_orch.deploy_version.return_value = {
        "resource_id": "test-resource-123",
        "version": "v1",
        "status": "RUNNING"
    }
    return mock_orch


class TestRollingDeploymentExecutor:
    """Tests for RollingDeploymentExecutor."""
    
    @pytest.mark.anyio
    async def test_executor_initialization(self):
        """Test that rolling executor initializes correctly."""
        executor = RollingDeploymentExecutor()
        assert executor.strategy_name == "ROLLING"
        assert executor.orchestrator is not None
        assert executor.dcm_client is not None
    
    @pytest.mark.anyio
    async def test_validate_config_valid(self):
        """Test validation with valid rolling config."""
        executor = RollingDeploymentExecutor()
        config = {
            "steps": 3,
            "interval_seconds": 30,
            "health_check_duration_seconds": 60
        }
        assert executor.validate_config(config) is True
    
    @pytest.mark.anyio
    async def test_validate_config_invalid_steps(self):
        """Test validation rejects invalid steps."""
        executor = RollingDeploymentExecutor()
        config = {
            "steps": 15,  # > 10
            "interval_seconds": 30,
            "health_check_duration_seconds": 60
        }
        with pytest.raises(ValueError, match="steps must be between 1 and 10"):
            executor.validate_config(config)
    
    @pytest.mark.anyio
    async def test_validate_config_invalid_interval(self):
        """Test validation rejects invalid interval."""
        executor = RollingDeploymentExecutor()
        config = {
            "steps": 3,
            "interval_seconds": 5,  # < 10
            "health_check_duration_seconds": 60
        }
        with pytest.raises(ValueError, match="interval_seconds must be between 10 and 600"):
            executor.validate_config(config)
    
    @pytest.mark.anyio
    async def test_execute_success(self, deployment_context, mock_orchestrator):
        """Test successful rolling deployment execution."""
        executor = RollingDeploymentExecutor()
        executor.orchestrator = mock_orchestrator
        
        # Mock health check
        with patch.object(executor, '_check_rollout_health', return_value=True):
            deployment_context.strategy_config = {
                "steps": 3,
                "interval_seconds": 30,
                "health_check_duration_seconds": 60
            }
            
            result = await executor.execute(deployment_context)
            
            assert result.success is True
            assert result.status == "ACTIVE"
            assert result.primary_resource_id == "test-resource-123"
            assert result.metadata["strategy"] == "ROLLING"
            assert result.metadata["steps"] == 3
    
    @pytest.mark.anyio
    async def test_execute_health_check_failure(self, deployment_context, mock_orchestrator):
        """Test rolling deployment with health check failure."""
        executor = RollingDeploymentExecutor()
        executor.orchestrator = mock_orchestrator
        
        # Mock health check failure
        with patch.object(executor, '_check_rollout_health', return_value=False):
            deployment_context.strategy_config = {
                "steps": 3,
                "interval_seconds": 30,
                "health_check_duration_seconds": 60
            }
            
            result = await executor.execute(deployment_context)
            
            assert result.success is False
            assert result.status == "FAILED"
    
    @pytest.mark.anyio
    async def test_rollback_success(self, mock_dcm_client):
        """Test successful rolling deployment rollback."""
        executor = RollingDeploymentExecutor()
        executor.dcm_client = mock_dcm_client
        
        success = await executor.rollback(
            deployment_id=123,
            resource_ids=["resource-123"],
            kube_cluster="kind-cluster",
            namespace="serve"
        )
        
        assert success is True
        mock_dcm_client.cleanup_failed_resources.assert_called_once()


class TestCanaryDeploymentExecutor:
    """Tests for CanaryDeploymentExecutor."""
    
    @pytest.mark.anyio
    async def test_executor_initialization(self):
        """Test that canary executor initializes correctly."""
        executor = CanaryDeploymentExecutor()
        assert executor.strategy_name == "CANARY"
        assert executor.orchestrator is not None
        assert executor.traffic_splitter is not None
    
    @pytest.mark.anyio
    async def test_validate_config_valid(self):
        """Test validation with valid canary config."""
        executor = CanaryDeploymentExecutor()
        config = {
            "traffic_splits": [10, 50, 100],
            "rollback_on_errors": True,
            "canary_health_check_duration_seconds": 120
        }
        assert executor.validate_config(config) is True
    
    @pytest.mark.anyio
    async def test_validate_config_invalid_splits_not_ascending(self):
        """Test validation rejects non-ascending splits."""
        executor = CanaryDeploymentExecutor()
        config = {
            "traffic_splits": [50, 10, 100],  # Not ascending
            "rollback_on_errors": True
        }
        with pytest.raises(ValueError, match="must be in ascending order"):
            executor.validate_config(config)
    
    @pytest.mark.anyio
    async def test_validate_config_invalid_splits_not_ending_100(self):
        """Test validation rejects splits not ending with 100."""
        executor = CanaryDeploymentExecutor()
        config = {
            "traffic_splits": [10, 50, 75],  # Doesn't end with 100
            "rollback_on_errors": True
        }
        with pytest.raises(ValueError, match="Final traffic split must be 100%"):
            executor.validate_config(config)
    
    @pytest.mark.anyio
    async def test_execute_success(self, deployment_context, mock_orchestrator):
        """Test successful canary deployment execution."""
        executor = CanaryDeploymentExecutor()
        executor.orchestrator = mock_orchestrator
        
        # Mock stable and canary deployments
        mock_orchestrator.deploy_version.side_effect = [
            {"resource_id": "stable-123", "version": "v1-stable", "status": "RUNNING"},
            {"resource_id": "canary-123", "version": "v1-canary", "status": "RUNNING"}
        ]
        
        # Mock health check
        with patch.object(executor, '_check_canary_health', return_value=True):
            deployment_context.strategy_config = {
                "traffic_splits": [10, 50, 100],
                "rollback_on_errors": True,
                "canary_health_check_duration_seconds": 120
            }
            
            result = await executor.execute(deployment_context)
            
            assert result.success is True
            assert result.status == "CANARY"
            assert result.primary_resource_id == "stable-123"
            assert result.secondary_resource_id == "canary-123"
            assert result.metadata["strategy"] == "CANARY"
    
    @pytest.mark.anyio
    async def test_execute_health_check_failure_with_rollback(
        self, deployment_context, mock_orchestrator, mock_dcm_client
    ):
        """Test canary deployment with health check failure and automatic rollback."""
        executor = CanaryDeploymentExecutor()
        executor.orchestrator = mock_orchestrator
        executor.dcm_client = mock_dcm_client
        
        # Mock stable and canary deployments
        mock_orchestrator.deploy_version.side_effect = [
            {"resource_id": "stable-123", "version": "v1-stable", "status": "RUNNING"},
            {"resource_id": "canary-123", "version": "v1-canary", "status": "RUNNING"}
        ]
        
        # Mock health check failure
        with patch.object(executor, '_check_canary_health', return_value=False):
            deployment_context.strategy_config = {
                "traffic_splits": [10, 50, 100],
                "rollback_on_errors": True,
                "canary_health_check_duration_seconds": 120
            }
            
            result = await executor.execute(deployment_context)
            
            assert result.success is False
            # Should have attempted to stop canary
            mock_dcm_client.stop_resource.assert_called_once()
    
    @pytest.mark.anyio
    async def test_promote_canary_partial(self, mock_dcm_client):
        """Test partial canary promotion (e.g., 10% -> 50%)."""
        executor = CanaryDeploymentExecutor()
        executor.dcm_client = mock_dcm_client
        
        success = await executor.promote_canary(
            stable_resource_id="stable-123",
            canary_resource_id="canary-123",
            kube_cluster="kind-cluster",
            namespace="serve",
            next_traffic_percentage=50
        )
        
        assert success is True
    
    @pytest.mark.anyio
    async def test_promote_canary_full(self, mock_dcm_client):
        """Test full canary promotion (100%)."""
        executor = CanaryDeploymentExecutor()
        executor.dcm_client = mock_dcm_client
        
        success = await executor.promote_canary(
            stable_resource_id="stable-123",
            canary_resource_id="canary-123",
            kube_cluster="kind-cluster",
            namespace="serve",
            next_traffic_percentage=100
        )
        
        assert success is True
        # Should have stopped old stable
        mock_dcm_client.stop_resource.assert_called_once_with(
            resource_id="stable-123",
            kube_cluster="kind-cluster",
            namespace="serve"
        )


class TestBlueGreenDeploymentExecutor:
    """Tests for BlueGreenDeploymentExecutor."""
    
    @pytest.mark.anyio
    async def test_executor_initialization(self):
        """Test that blue-green executor initializes correctly."""
        executor = BlueGreenDeploymentExecutor()
        assert executor.strategy_name == "BLUE_GREEN"
        assert executor.orchestrator is not None
    
    @pytest.mark.anyio
    async def test_validate_config_valid(self):
        """Test validation with valid blue-green config."""
        executor = BlueGreenDeploymentExecutor()
        config = {
            "switch_mode": "manual",
            "cutover_delay_seconds": 60,
            "green_health_check_duration_seconds": 120
        }
        assert executor.validate_config(config) is True
    
    @pytest.mark.anyio
    async def test_validate_config_invalid_switch_mode(self):
        """Test validation rejects invalid switch mode."""
        executor = BlueGreenDeploymentExecutor()
        config = {
            "switch_mode": "immediate",  # Not 'manual' or 'auto'
            "cutover_delay_seconds": 60
        }
        with pytest.raises(ValueError, match="switch_mode must be 'manual' or 'auto'"):
            executor.validate_config(config)
    
    @pytest.mark.anyio
    async def test_execute_manual_mode_success(self, deployment_context, mock_orchestrator):
        """Test successful blue-green deployment in manual mode."""
        executor = BlueGreenDeploymentExecutor()
        executor.orchestrator = mock_orchestrator
        
        # Mock blue and green deployments
        mock_orchestrator.deploy_version.side_effect = [
            {"resource_id": "blue-123", "version": "v1-blue", "status": "RUNNING"},
            {"resource_id": "green-123", "version": "v1-green", "status": "RUNNING"}
        ]
        
        # Mock health check
        with patch.object(executor, '_check_green_health', return_value=True):
            deployment_context.strategy_config = {
                "switch_mode": "manual",
                "cutover_delay_seconds": 60,
                "green_health_check_duration_seconds": 120
            }
            
            result = await executor.execute(deployment_context)
            
            assert result.success is True
            assert result.status == "CANARY"  # Awaiting manual cutover
            assert result.primary_resource_id == "blue-123"
            assert result.secondary_resource_id == "green-123"
            assert result.metadata["green_healthy"] is True
    
    @pytest.mark.anyio
    async def test_execute_auto_mode_success(self, deployment_context, mock_orchestrator):
        """Test successful blue-green deployment with auto cutover."""
        executor = BlueGreenDeploymentExecutor()
        executor.orchestrator = mock_orchestrator
        
        # Mock blue and green deployments
        mock_orchestrator.deploy_version.side_effect = [
            {"resource_id": "blue-123", "version": "v1-blue", "status": "RUNNING"},
            {"resource_id": "green-123", "version": "v1-green", "status": "RUNNING"}
        ]
        
        # Mock health check and cutover
        with patch.object(executor, '_check_green_health', return_value=True), \
             patch.object(executor, 'cutover_to_green', return_value=True):
            
            deployment_context.strategy_config = {
                "switch_mode": "auto",
                "cutover_delay_seconds": 0,  # No delay for test
                "green_health_check_duration_seconds": 120
            }
            
            result = await executor.execute(deployment_context)
            
            assert result.success is True
            assert result.status == "ACTIVE"  # Auto-cutover completed
    
    @pytest.mark.anyio
    async def test_cutover_to_green(self, mock_dcm_client):
        """Test blue-green cutover operation."""
        executor = BlueGreenDeploymentExecutor()
        executor.dcm_client = mock_dcm_client
        
        success = await executor.cutover_to_green(
            blue_resource_id="blue-123",
            green_resource_id="green-123",
            kube_cluster="kind-cluster",
            namespace="serve"
        )
        
        assert success is True
    
    @pytest.mark.anyio
    async def test_rollback_to_blue(self, mock_dcm_client):
        """Test blue-green rollback to blue."""
        executor = BlueGreenDeploymentExecutor()
        executor.dcm_client = mock_dcm_client
        
        success = await executor.rollback(
            deployment_id=123,
            resource_ids=["blue-123", "green-123"],
            kube_cluster="kind-cluster",
            namespace="serve"
        )
        
        assert success is True
        # Should have stopped green
        mock_dcm_client.stop_resource.assert_called_once_with(
            resource_id="green-123",
            kube_cluster="kind-cluster",
            namespace="serve"
        )
    
    @pytest.mark.anyio
    async def test_cleanup_superseded(self, mock_dcm_client):
        """Test cleanup of superseded blue deployment."""
        executor = BlueGreenDeploymentExecutor()
        executor.dcm_client = mock_dcm_client
        
        success = await executor.cleanup_superseded(
            blue_resource_id="blue-123",
            kube_cluster="kind-cluster",
            namespace="serve"
        )
        
        assert success is True
        mock_dcm_client.stop_resource.assert_called_once_with(
            resource_id="blue-123",
            kube_cluster="kind-cluster",
            namespace="serve"
        )
