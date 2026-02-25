# Test Strategy: Advanced Deployment Strategies

**Version:** 1.0  
**Last Updated:** February 2025  
**PRD Reference:** [PRD-advanced-deployment-strategies.md](../docs/PRD-advanced-deployment-strategies.md)  
**Architecture Reference:** [ARCHITECTURE-advanced-deployment-strategies.md](../docs/ARCHITECTURE-advanced-deployment-strategies.md)

---

## 1. Test Coverage Goals

### 1.1 Unit Test Coverage

| Target | Coverage Goal | Priority |
|--------|---------------|----------|
| DeploymentStrategyService | 80%+ | High |
| TrafficManagementService | 80%+ | High |
| DeploymentLockService | 90%+ | High |
| MetricsService | 75%+ | Medium |
| ResourceValidationService | 80%+ | High |
| DeploymentService (strategy-related changes) | 80%+ | High |

### 1.2 Integration Test Coverage

| Scenario | Coverage | Priority |
|----------|----------|----------|
| Canary deploy → step → promote | Full flow | High |
| Canary abort | Full flow | High |
| Blue-green deploy → promote | Full flow | High |
| Rolling with custom maxSurge/maxUnavailable | Full flow | Medium |
| Deployment locking during canary | Full flow | High |
| Rollback (all strategies) | Full flow | High |
| One-click deploy-model with strategies | Full flow | Medium |

### 1.3 What's NOT Tested (and Why)

| Area | Reason |
|------|--------|
| Istio control plane behavior | Istio is external; we mock K8s API |
| DCM Helm chart rendering | DCM is external; we mock DCMClient |
| Prometheus/Istio metrics scraping | External; we mock metrics API |
| E2E with real Kubernetes cluster | Covered by integration tests with mocked K8s |
| UI components | API-only feature; no UI |
| Workflow serves | Out of scope per PRD |

---

## 2. Test Data Strategy

### 2.1 Factory Patterns for New Models

| Model | Factory | Location |
|-------|---------|----------|
| DeploymentLock | DeploymentLockFactory | tests/fixtures/factories.py |
| DeploymentMetric | DeploymentMetricFactory | tests/fixtures/factories.py |
| AppLayerDeployment (canary/blue-green) | AppLayerDeploymentFactory (extended) | tests/fixtures/factories.py |

### 2.2 Test Data Defaults

```python
# DeploymentLockFactory defaults
serve_id=1, environment_id=1, deployment_id=None, locked_at=now

# DeploymentMetricFactory defaults
deployment_id=1, metric_name="request_rate", value=100.0,
timestamp=now, labels={"version": "stable"}
```

### 2.3 Database State Management

- **Unit tests:** SQLite in-memory; fresh schema per test via `db_session` fixture
- **Integration tests:** Real MySQL; `cleanup_test_resources` and `cleanup_database` fixtures
- **Isolation:** Each test creates its own serve/artifact/deployment; no shared state

---

## 3. Mocking Strategy

### 3.1 DCMClient Mocking

| Method | Mock Return | Use Case |
|--------|-------------|----------|
| build_resource | `{"body": {"status": "success"}}` | Successful build |
| start_resource | `{"body": {"status": "running"}}` | Successful start |
| stop_resource | `{"body": {"status": "stopped"}}` | Abort/rollback |
| build_resource (failure) | Raise exception | Failed deployment |

### 3.2 K8s Client Mocking (Istio Resources)

| Method | Mock Return | Use Case |
|--------|-------------|----------|
| apply_virtual_service | None (success) | Traffic split update |
| apply_destination_rule | None (success) | Subset creation |
| apply_virtual_service (409) | ApiException(409) | Update existing VS |

### 3.3 Metrics API Mocking

| Source | Mock | Use Case |
|--------|------|----------|
| K8s metrics-server | `{"cpu": 0.5, "memory": 512}` | CPU/memory collection |
| Istio/Prometheus | `{"request_rate": 100, "error_rate": 0.01}` | Request/error metrics |
| MetricsService.collect | List of DeploymentMetric | Storage verification |

### 3.4 DeploymentLockService Mocking

- **acquire_lock:** Return DeploymentLock or raise HTTPException(409)
- **release_lock:** Return None
- **is_locked:** Return True/False

---

## 4. Test Execution

### 4.1 Running Unit Tests

```bash
# All unit tests
./ml-serve-app/tests/scripts/test-unit.sh

# Specific test file
pytest ml-serve-app/tests/unit/test_deployment_strategy_service.py -v -m unit

# With coverage
pytest ml-serve-app/tests/unit/ -v -m unit --cov=ml_serve_core.service --cov-report=term-missing
```

### 4.2 Running Integration Tests

```bash
# All integration tests (requires Kind cluster)
./ml-serve-app/tests/scripts/test-integration.sh

# Specific deployment strategy tests
pytest ml-serve-app/tests/integration/test_canary_deployment_flow.py -v -m integration
pytest ml-serve-app/tests/integration/test_blue_green_deployment_flow.py -v -m integration
```

### 4.3 CI/CD Integration

- **Unit tests:** Run on every PR; no external dependencies
- **Integration tests:** Run on merge to main; require Kind cluster + services
- **Test markers:** `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`

---

## 5. Edge Cases Covered

### 5.1 Failed Deployments

| Scenario | Test | Expected |
|----------|------|----------|
| DCM build fails | test_deploy_rolling_dcm_build_fails | HTTPException 500 |
| DCM start fails | test_deploy_canary_dcm_start_fails | Rollback; return error |
| Canary pods crash | test_canary_failed_stays_at_zero_traffic | Traffic remains 0%; manual abort |

### 5.2 Race Conditions

| Scenario | Test | Expected |
|----------|------|----------|
| Concurrent lock acquisition | test_concurrent_lock_attempts_race_condition | One succeeds; other gets 409 |
| Promote during deploy | test_promote_while_canary_deploying_rejected | 400 "not ready" |
| New deploy during canary | test_deploy_while_canary_locked_returns_409 | 409 Conflict |

### 5.3 Insufficient Resources

| Scenario | Test | Expected |
|----------|------|----------|
| Cluster CPU insufficient | test_check_resources_insufficient_cpu_fail_fast | 400 "Insufficient cluster resources" |
| Cluster memory insufficient | test_check_resources_insufficient_memory_fail_fast | 400 "Insufficient cluster resources" |

### 5.4 Rollback Scenarios

| Scenario | Test | Expected |
|----------|------|----------|
| Rollback with previous version | test_rollback_with_previous_success | Traffic switched; ActiveDeployment updated |
| Rollback without previous | test_rollback_no_previous_returns_400 | 400 "No previous version" |
| Rolling rollback via DCM | test_rolling_rollback_redeploys_previous | DCM stop + start previous |

### 5.5 Invalid Input

| Scenario | Test | Expected |
|----------|------|----------|
| Invalid step (30%) | test_step_invalid_traffic_percent_returns_400 | 400 "Must be 25, 50, or 100" |
| Istio required but disabled | test_blue_green_requires_istio | 400 "Istio is required" |

---

## 6. Test File Mapping

| Test File | Services/Components Tested | Test Count (Est.) |
|-----------|---------------------------|-------------------|
| test_deployment_strategy_service.py | DeploymentStrategyService | ~12 |
| test_traffic_management_service.py | TrafficManagementService | ~8 |
| test_deployment_lock_service.py | DeploymentLockService | ~6 |
| test_metrics_service.py | MetricsService | ~6 |
| test_resource_validation_service.py | ResourceValidationService | ~4 |
| test_artifact_deployment.py (modified) | DeploymentService + ActiveDeployment | +4 |
| test_canary_deployment_flow.py | Full canary flow | ~6 |
| test_blue_green_deployment_flow.py | Full blue-green flow | ~4 |
| test_rolling_deployment_flow.py | Enhanced rolling | ~3 |
| test_artifact_flow.py (modified) | Deploy with strategies | +3 |

---

## 7. Prerequisites for Running Tests

### 7.1 Unit Tests

- Python 3.9+
- Tortoise ORM with SQLite (in-memory)
- pytest, pytest-asyncio
- All ml-serve-app packages installed (model, core, app_layer)

### 7.2 Integration Tests

- Kind cluster running
- ml-serve-app, DCM, Artifact Builder, MLflow deployed
- MySQL database
- TEST_AUTH_TOKEN env var (or default bootstrap token)

---

## 8. Implementation Order (TDD)

Tests are written **before** implementation. Recommended implementation order:

1. **DeploymentLock** model + **DeploymentLockService** → test_deployment_lock_service.py
2. **TrafficManagementService** + K8s client → test_traffic_management_service.py
3. **DeploymentStrategyService** → test_deployment_strategy_service.py
4. **ResourceValidationService** → test_resource_validation_service.py
5. **MetricsService** + DeploymentMetric model → test_metrics_service.py
6. **DeploymentService** modifications → test_artifact_deployment.py
7. API routes + full flow → integration tests

---

*End of Test Strategy*
