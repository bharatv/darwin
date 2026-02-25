# Architecture Fixes for Critical Issues

**Date:** February 2025  
**Status:** Addressing verification failures

This document addresses the 7 critical issues identified by the architecture verifier.

---

## Critical Issue #1: Canary Lock Acquisition Order

### Problem
Lock is acquired at step 6 in the canary flow, after deployment work. This allows a race where two concurrent deploy requests both pass the initial check and one acquires the lock after the other has already started.

### Fix

**Updated Canary Deployment Flow:**

```
1. Validate serve, artifact, environment, serve_config
2. **Acquire lock FIRST:** DeploymentLockService.acquire_lock(serve_id, environment_id)
   - INSERT INTO deployment_locks with unique constraint on (serve_id, environment_id)
   - If IntegrityError (unique constraint violation), return 409 Conflict
   - Lock acquired with deployment_id=NULL initially
3. Deploy canary with 0% traffic:
   - artifact_id = f"{env.name}-{serve.name}-{artifact.version}-canary"
   - resource_id = f"{env.name}-{serve.name}-canary"
   - Generate Helm values with version: canary label
   - DCMClient.build_resource(artifact_id, values)
   - DCMClient.start_resource(resource_id, artifact_id)
4. Create Deployment record with status=ACTIVE
5. Create AppLayerDeployment with deployment_strategy=canary
6. **Update lock with deployment_id:** UPDATE deployment_locks SET deployment_id=... WHERE serve_id=... AND environment_id=...
7. Create/update Istio resources (VirtualService with 100% stable, 0% canary)
8. **DO NOT update ActiveDeployment** (traffic stays on stable until promote)
9. Return response with deployment_id, status=canary_in_progress, locked=true
```

**Implementation:**

```python
# deployment_lock_service.py
async def acquire_lock(self, serve_id: int, environment_id: int) -> DeploymentLock:
    """Acquire deployment lock. Raises 409 if already locked."""
    try:
        lock = await DeploymentLock.create(
            serve_id=serve_id,
            environment_id=environment_id,
            deployment_id=None,  # Will be updated after deployment creation
            locked_at=datetime.now(timezone.utc)
        )
        return lock
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Deployment locked: canary in progress for this serve/environment"
        )

async def update_lock_deployment_id(self, serve_id: int, environment_id: int, deployment_id: int):
    """Update lock with deployment ID after deployment is created."""
    await DeploymentLock.filter(
        serve_id=serve_id,
        environment_id=environment_id
    ).update(deployment_id=deployment_id)
```

---

## Critical Issue #2: Rollback for Rolling Strategy

### Problem
Architecture only describes rollback via VirtualService/DestinationRule. For rolling, there is no Istio traffic split; rollback must redeploy the previous version via DCM.

### Fix

**Updated Rollback Flow:**

```python
async def rollback_deployment(self, serve_name: str, env_name: str, user: User):
    """Rollback to previous deployment."""
    serve = await Serve.get(name=serve_name)
    env = await Environment.get(name=env_name)
    
    active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
    if not active or not active.previous_deployment:
        raise HTTPException(400, "No previous version available for rollback")
    
    current_deployment = await active.deployment
    previous_deployment = await active.previous_deployment
    current_app_layer = await AppLayerDeployment.get(deployment=current_deployment)
    
    strategy = current_app_layer.deployment_strategy
    
    if strategy in ["blue_green", "canary"]:
        # Istio-based rollback: switch traffic to previous version
        await self.traffic_service.switch_to_previous_version(serve, env, previous_deployment)
    else:
        # Rolling strategy: redeploy previous artifact via DCM
        previous_artifact = await previous_deployment.artifact
        
        # Stop current deployment
        await self.dcm_client.stop_resource(
            resource_id=f"{env.name}-{serve.name}",
            kube_cluster=env.cluster_name,
            namespace=env.namespace
        )
        
        # Redeploy previous artifact
        values = generate_fastapi_values(
            name=serve.name,
            env=env.name,
            runtime=previous_artifact.image_url,
            env_config=EnvConfig(**env.env_configs),
            user_email=user.username,
            serve_infra_config=await APIServeInfraConfig.get(serve=serve, environment=env),
            environment_variables=current_app_layer.environment_variables,
            is_environment_protected=env.is_protected
        )
        
        await self.dcm_client.build_resource(
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            artifact_id=f"{env.name}-{serve.name}-{previous_artifact.version}",
            values=values,
            version=FASTAPI_SERVE_CHART_VERSION
        )
        
        await self.dcm_client.start_resource(
            resource_id=f"{env.name}-{serve.name}",
            artifact_id=f"{env.name}-{serve.name}-{previous_artifact.version}",
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME
        )
    
    # Update ActiveDeployment
    active.deployment = previous_deployment
    active.previous_deployment = None  # Clear previous
    await active.save()
    
    # Mark current as ENDED
    current_deployment.status = DeploymentStatus.ENDED.value
    current_deployment.ended_at = datetime.now(timezone.utc)
    await current_deployment.save()
```

---

## Critical Issue #3: One-Click deploy-model in Scope

### Problem
PRD Section 7.1 shows `deploy-model` with `deployment_strategy` and `deployment_strategy_config`. Architecture leaves this unresolved.

### Fix

**Decision: Include deploy-model strategy support in v1**

**Updated ModelDeploymentRequest:**

```python
class ModelDeploymentRequest(BaseModel):
    serve_name: str
    artifact_version: str
    model_uri: str
    env: str
    storage_strategy: Optional[Literal["auto", "emptydir", "pvc"]] = "auto"
    
    # Resource configuration
    cores: int = Field(4, ge=1, le=64)
    memory: int = Field(8, ge=1, le=512)
    node_capacity: Literal["spot", "ondemand"] = "spot"
    min_replicas: int = Field(1, ge=1, le=100)
    max_replicas: int = Field(1, ge=1, le=100)
    
    # NEW: Deployment strategy support
    deployment_strategy: Optional[Literal["rolling", "blue_green", "canary"]] = "rolling"
    deployment_strategy_config: Optional[dict] = Field(None, description="Strategy-specific config")
```

**Updated deploy_model flow:**

```python
async def deploy_model(self, request: ModelDeploymentRequest, user: User):
    # ... existing validation ...
    
    # Check deployment strategy and route accordingly
    if request.deployment_strategy == "canary":
        # Acquire lock
        await self.deployment_lock_service.acquire_lock(serve.id, env.id)
        
        # Use canary resource naming
        resource_id = f"{serve.name}-canary"  # For one-click: no env prefix
        artifact_identifier = f"{env.name}-{serve.name}-{artifact.version}-canary"
    elif request.deployment_strategy == "blue_green":
        # Determine blue/green slot
        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        current_slot = "blue" if active else "green"
        next_slot = "green" if current_slot == "blue" else "blue"
        
        resource_id = f"{serve.name}-{next_slot}"
        artifact_identifier = f"{env.name}-{serve.name}-{artifact.version}-{next_slot}"
    else:
        # Rolling (default)
        resource_id = serve.name
        artifact_identifier = f"{env.name}-{serve.name}-{artifact.version}"
    
    # Generate values with strategy-specific config
    values_json = generate_fastapi_values_for_one_click_model_deployment(
        name=serve.name,
        env=request.env,
        runtime=DEFAULT_RUNTIME,
        env_config=env_config,
        user_email=user.username,
        environment_variables=environment_variables,
        cores=request.cores,
        memory=request.memory,
        min_replicas=request.min_replicas,
        max_replicas=request.max_replicas,
        node_capacity_type=request.node_capacity,
        storage_strategy=storage_strategy,
        model_uri=request.model_uri,
        # ... other params ...
        deployment_strategy=request.deployment_strategy,  # NEW
        version_label=self._get_version_label(request.deployment_strategy)  # NEW: stable/canary/blue/green
    )
    
    # Deploy via DCM
    await self.dcm_client.build_resource(...)
    await self.dcm_client.start_resource(
        resource_id=resource_id,  # Strategy-specific naming
        artifact_id=artifact_identifier,
        ...
    )
    
    # Create deployment record
    deployment = await Deployment.create(...)
    await AppLayerDeployment.create(
        deployment=deployment,
        deployment_strategy=request.deployment_strategy,
        deployment_params=request.deployment_strategy_config,
        environment_variables=environment_variables
    )
    
    # Update ActiveDeployment ONLY for rolling
    if request.deployment_strategy == "rolling":
        await self._update_active_deployment(serve, env, deployment)
    
    # For canary/blue-green, create Istio resources
    if request.deployment_strategy in ["canary", "blue_green"]:
        await self.traffic_service.setup_traffic_management(serve, env, request.deployment_strategy)
    
    return {"deployment_id": deployment.id, ...}
```

---

## Critical Issue #4: deploy_artifact Always Updates ActiveDeployment

### Problem
`deployment_service.py` (lines 177–183) always updates `ActiveDeployment` after deploy. For blue-green and canary, traffic must stay on the current version until promote.

### Fix

**Updated deploy_artifact method:**

```python
async def deploy_artifact(
    self,
    serve: Serve,
    artifact: Artifact,
    serve_config: ServeConfig,
    env: Environment,
    deployment_request: DeploymentRequest,
    user: User
):
    # ... existing validation ...
    
    deployment = None
    if serve.type == ServeType.API.value:
        deployment, api_deployment_resp = await self.deploy_api_serve(
            serve,
            artifact,
            env,
            serve_config,
            deployment_request.api_serve_deployment_config,
            user
        )
    
    # Get deployment strategy
    strategy = None
    if deployment_request.api_serve_deployment_config:
        strategy = deployment_request.api_serve_deployment_config.deployment_strategy
    
    # Update ActiveDeployment ONLY for rolling or if no strategy specified
    if strategy in [None, "rolling"]:
        if not previous_active_deployment:
            await ActiveDeployment.create(serve=serve, environment=env, deployment=deployment)
        else:
            previous_active_deployment.previous_deployment = await previous_active_deployment.deployment
            previous_active_deployment.deployment = deployment
            await previous_active_deployment.save()
    # For canary/blue-green, DO NOT update ActiveDeployment
    # Traffic stays on current version until promote
    
    return api_deployment_resp
```

---

## Critical Issue #5: Helm Chart Uses flagger for Rolling Params

### Problem
`deployment.yaml` (lines 22–24) uses `flagger.maxSurge` and `flagger.maxUnavailable`. Architecture proposes `deploymentStrategyConfig.maxSurge` / `maxUnavailable`.

### Fix

**Updated Helm template (deployment.yaml):**

```yaml
spec:
  strategy:
    {{- if eq .Values.deploymentStrategy "Recreate" }}
    type: Recreate
    {{- else }}
    type: RollingUpdate
    rollingUpdate:
      maxSurge: {{ .Values.deploymentStrategyConfig.maxSurge | default "25%" }}
      maxUnavailable: {{ .Values.deploymentStrategyConfig.maxUnavailable | default 0 }}
    {{- end }}
```

**Updated values.yaml:**

```yaml
deploymentStrategy: RollingUpdate  # or Recreate

deploymentStrategyConfig:
  maxSurge: "25%"
  maxUnavailable: 0
```

**Updated yaml_utils.py:**

```python
def generate_fastapi_values(..., deployment_strategy_config: dict = None):
    # ... existing code ...
    
    # Set deployment strategy config
    if deployment_strategy_config:
        values['deploymentStrategyConfig'] = {
            'maxSurge': deployment_strategy_config.get('maxSurge', '25%'),
            'maxUnavailable': deployment_strategy_config.get('maxUnavailable', 0)
        }
    else:
        # Defaults
        values['deploymentStrategyConfig'] = {
            'maxSurge': '25%',
            'maxUnavailable': 0
        }
    
    return values
```

---

## Critical Issue #6: Deploy Response Missing deployment_id

### Problem
PRD requires deploy response to include `deployment_id`. Current `deploy_fastapi_serve` returns only `{"service_url": ...}`.

### Fix

**Updated deploy_api_serve method:**

```python
async def deploy_api_serve(
    self,
    serve: Serve,
    artifact: Artifact,
    env: Environment,
    api_serve_config: APIServeInfraConfig,
    api_deployment_config: APIServeDeploymentConfigRequest,
    user: User
):
    resp = None
    if api_serve_config.backend_type == BackendType.FastAPI.value:
        resp = await self.deploy_fastapi_serve(
            serve, artifact, env, api_deployment_config, api_serve_config, user
        )
    
    async with in_transaction():
        deployment = await Deployment.create(
            serve=serve,
            artifact=artifact,
            environment=env,
            created_by=user,
        )
        
        # ... create AppLayerDeployment ...
    
    # Add deployment_id to response
    if resp:
        resp['deployment_id'] = deployment.id
        resp['artifact_version'] = artifact.version
        resp['strategy'] = api_deployment_config.deployment_strategy if api_deployment_config else 'rolling'
        resp['status'] = 'deploying'
    
    return deployment, resp
```

**Updated API response:**

```python
# deployment.py router
async def deploy_artifact(self, serve_name: str, request: DeploymentRequest, user: AuthorizedUser):
    # ... existing code ...
    
    resp = await self.deployment_service.deploy_artifact(...)
    
    return Response.success_response(
        f"Deployment started for artifact {request.artifact_version} to {request.env}",
        {
            "deployment_id": resp.get('deployment_id'),
            "serve_name": serve_name,
            "environment": request.env,
            "artifact_version": request.artifact_version,
            "strategy": resp.get('strategy', 'rolling'),
            "status": resp.get('status', 'deploying'),
            "service_url": resp.get('service_url'),
            "message": "Use GET /deployments/{id}/status for progress."
        }
    )
```

---

## Critical Issue #7: Istio Resources via K8s API

### Problem
Architecture proposes ml-serve-app applying VirtualService/DestinationRule via a new K8s client. This diverges from the current pattern (all K8s via DCM).

### Fix

**Decision: Use K8s client directly for Istio resources**

**Rationale:**
1. DCM is designed for Helm chart lifecycle management
2. Istio resources are dynamic (traffic splits change frequently during canary)
3. Helm charts are immutable artifacts; updating traffic split shouldn't require rebuild
4. Istio resources are cluster-scoped CRDs, not Helm-managed resources

**Implementation:**

**1. K8s Client Setup:**

```python
# core/src/ml_serve_core/client/kubernetes_client.py

from kubernetes import client, config
from kubernetes.client.rest import ApiException
import os

class KubernetesClient:
    """Direct Kubernetes API client for Istio resources."""
    
    def __init__(self):
        # Load in-cluster config if running in K8s, else load from kubeconfig
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()
        
        self.custom_api = client.CustomObjectsApi()
        self.core_api = client.CoreV1Api()
        self.apps_api = client.AppsV1Api()
    
    async def apply_virtual_service(self, namespace: str, vs_manifest: dict):
        """Apply Istio VirtualService."""
        try:
            self.custom_api.create_namespaced_custom_object(
                group="networking.istio.io",
                version="v1beta1",
                namespace=namespace,
                plural="virtualservices",
                body=vs_manifest
            )
        except ApiException as e:
            if e.status == 409:  # Already exists, update
                self.custom_api.patch_namespaced_custom_object(
                    group="networking.istio.io",
                    version="v1beta1",
                    namespace=namespace,
                    plural="virtualservices",
                    name=vs_manifest['metadata']['name'],
                    body=vs_manifest
                )
            else:
                raise
    
    async def apply_destination_rule(self, namespace: str, dr_manifest: dict):
        """Apply Istio DestinationRule."""
        # Similar to apply_virtual_service
```

**2. RBAC Configuration:**

ml-serve-app needs K8s ServiceAccount with permissions to manage Istio resources:

```yaml
# helm/darwin/charts/services/ml-serve-app/templates/rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: darwin-ml-serve-app
  namespace: {{ .Release.Namespace }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: darwin-ml-serve-app-istio
rules:
  - apiGroups: ["networking.istio.io"]
    resources: ["virtualservices", "destinationrules"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: darwin-ml-serve-app-istio
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: darwin-ml-serve-app-istio
subjects:
  - kind: ServiceAccount
    name: darwin-ml-serve-app
    namespace: {{ .Release.Namespace }}
```

**3. Deployment Configuration:**

```yaml
# helm/darwin/charts/services/ml-serve-app/templates/deployment.yaml
spec:
  template:
    spec:
      serviceAccountName: darwin-ml-serve-app  # Use custom SA
```

**4. Documentation:**

Add to architecture document:
- ml-serve-app uses K8s API directly for Istio resources (not DCM)
- Requires in-cluster ServiceAccount with Istio RBAC
- DCM remains responsible for Helm chart lifecycle
- Istio resources are created/updated by TrafficManagementService

---

## Summary of Fixes

| Issue # | Category | Fix Applied |
|---------|----------|-------------|
| 1 | Lock acquisition | Move acquire_lock to step 2 (before deploy work) |
| 2 | Rolling rollback | Add DCM-based rollback path for rolling strategy |
| 3 | deploy-model scope | Add deployment_strategy support to ModelDeploymentRequest |
| 4 | ActiveDeployment update | Only update for rolling; skip for canary/blue-green |
| 5 | Helm rolling params | Use deploymentStrategyConfig instead of flagger |
| 6 | Deploy response | Add deployment_id, strategy, status to response |
| 7 | Istio resources | Use K8s client directly; document RBAC requirements |

All fixes maintain backward compatibility and follow existing codebase patterns.
