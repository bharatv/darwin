# Architecture: Advanced Deployment Strategies for ML Serve App

**Version:** 1.0  
**Status:** Draft  
**Last Updated:** February 2025  
**PRD Reference:** [PRD-advanced-deployment-strategies.md](./PRD-advanced-deployment-strategies.md)

---

## 1. System Architecture Overview

### 1.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           ml-serve-app (Control Plane)                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│  REST API (FastAPI)                                                               │
│  ├── POST /api/v1/serve/{serve_name}/deploy                                      │
│  ├── GET  /api/v1/serve/{serve_name}/deployments/{id}/status                      │
│  ├── POST /api/v1/serve/{serve_name}/deployments/{id}/promote                     │
│  ├── POST /api/v1/serve/{serve_name}/deployments/{id}/abort                       │
│  ├── POST /api/v1/serve/{serve_name}/rollback                                     │
│  └── GET  /api/v1/serve/{serve_name}/deployments/{id}/metrics                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│  Service Layer                                                                    │
│  ├── DeploymentService (orchestration, strategy dispatch)                         │
│  ├── DeploymentStrategyService (rolling/blue-green/canary logic)                  │
│  ├── TrafficManagementService (Istio VirtualService/DestinationRule updates)     │
│  ├── DeploymentLockService (canary locking)                                       │
│  └── MetricsService (K8s/Istio metrics collection)                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│  Clients                                                                          │
│  ├── DCMClient (Helm build/start/stop/update)                                     │
│  └── K8sMetricsClient (metrics.k8s.io, custom metrics)                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│  Data Layer (Tortoise ORM)                                                        │
│  ├── Deployment, AppLayerDeployment, ActiveDeployment                              │
│  └── DeploymentLock (new)                                                         │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    Darwin Cluster Manager (DCM)                                    │
│  build_resource → start_resource → Helm install/upgrade                            │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  Namespace: {env.namespace}                                                  │ │
│  │  ┌─────────────────────┐  ┌─────────────────────┐                          │ │
│  │  │ Deployment (stable) │  │ Deployment (canary) │  ← Blue-Green / Canary   │ │
│  │  │ version: stable     │  │ version: canary     │                          │ │
│  │  └─────────┬───────────┘  └─────────┬───────────┘                          │ │
│  │            │                        │                                        │ │
│  │  ┌─────────▼───────────┐  ┌────────▼───────────┐                          │ │
│  │  │ Service (stable)     │  │ Service (canary)    │                          │ │
│  │  └─────────┬───────────┘  └─────────┬───────────┘                          │ │
│  │            │                        │                                        │ │
│  │  ┌─────────▼───────────────────────▼───────────┐                          │ │
│  │  │ Istio VirtualService (traffic split)         │                          │ │
│  │  │ Istio DestinationRule (subsets)              │                          │ │
│  │  └─────────────────────┬───────────────────────┘                          │ │
│  │                          │                                                  │ │
│  │  ┌──────────────────────▼───────────────────────┐                          │ │
│  │  │ Istio Gateway / Ingress                      │                          │ │
│  │  └─────────────────────────────────────────────┘                          │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Data Flow by Strategy

| Strategy   | Deploy Flow                                                                 | Traffic Flow                                                                 |
|------------|-----------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| **Rolling** | Single Helm release; update Deployment with new image; K8s RollingUpdate  | Direct to single Service; no Istio required                                   |
| **Blue-Green** | Two Helm releases (blue + green); deploy green alongside blue; traffic on blue | Istio VirtualService routes 100% to blue or green subset; promote = switch   |
| **Canary** | Two Helm releases (stable + canary); deploy canary with 0% traffic           | Istio VirtualService splits traffic (e.g., 75% stable, 25% canary); step API updates |

### 1.3 Istio Integration Architecture

- **Assumption:** Istio is pre-installed cluster-wide; Darwin does not install Istio.
- **When ENABLE_ISTIO=false:** Rolling only; ingress routes directly to Service.
- **When ENABLE_ISTIO=true:** Blue-Green and Canary use Istio VirtualService + DestinationRule.
- **Ingress:** Existing ALB/nginx Ingress routes to Istio Gateway; Istio routes to Service(s) based on VirtualService.
- **Subsets:** DestinationRule defines subsets by `version` label (stable, canary, blue, green).
- **Traffic split:** VirtualService `http.route.destination` with `weight` for canary; single destination for blue-green.

---

## 2. Database Schema Changes

### 2.1 New Table: `deployment_locks`

| Column           | Type         | Constraints | Description                                      |
|------------------|--------------|-------------|--------------------------------------------------|
| id               | INT          | PK          | Primary key                                      |
| serve_id         | INT          | FK, UNIQUE   | Serve (one lock per serve per environment)       |
| environment_id   | INT          | FK          | Environment                                      |
| deployment_id    | INT          | FK, nullable | Deployment holding the lock (canary in progress) |
| locked_at        | DATETIME     | NOT NULL    | When lock was acquired                            |
| locked_by        | INT          | FK, nullable | User who started the canary                       |

**Unique constraint:** `(serve_id, environment_id)` — one lock per serve+env.

**Purpose:** Prevent new deployments when a canary is in progress. Lock is acquired on canary deploy, released on promote or abort.

### 2.2 Modified Tables

#### `app_layer_deployments` (existing; populate unused fields)

| Column              | Change | Notes                                                                 |
|---------------------|--------|----------------------------------------------------------------------|
| deployment_strategy | Use    | Values: `rolling`, `blue_green`, `canary` (lowercase, snake_case)   |
| deployment_params   | Use    | JSON: `{maxSurge, maxUnavailable}` for rolling; `{initial_traffic_percent}` for canary; `{}` for blue-green |

#### `deployments` (optional extension)

| Column   | Change | Notes                                                       |
|----------|--------|-------------------------------------------------------------|
| status   | Extend | Add: `DEPLOYING`, `CANARY_IN_PROGRESS`, `PROMOTED`, `ABORTED` (if not using DeploymentStatus.ACTIVE/ENDED only) |

**Recommendation:** Use `DeploymentStatus` enum extension: add `DEPLOYING`, `CANARY_IN_PROGRESS`, `PROMOTED`, `ABORTED` for finer state tracking. Existing `ACTIVE`/`ENDED` remain for backward compatibility.

#### `active_deployments` (no schema change)

- `deployment` = current active (100% traffic)
- `previous_deployment` = rollback target
- For canary: `deployment` remains the stable deployment until promote; canary deployment is tracked via `DeploymentLock.deployment_id` or a separate field.

**Refinement:** For canary, we need to track both stable and canary deployments. Options:
- **Option A:** Add `canary_deployment_id` (nullable FK) to `ActiveDeployment` — when canary in progress, both stable and canary are tracked.
- **Option B:** Use `DeploymentLock.deployment_id` as the canary deployment; `ActiveDeployment.deployment` is always the stable (100% traffic) version.

**Chosen:** Option B — `DeploymentLock.deployment_id` = canary deployment; `ActiveDeployment.deployment` = stable. On promote, update `ActiveDeployment` and clear lock.

### 2.3 New Table: `deployment_metrics` (Step 8)

| Column        | Type      | Constraints | Description                    |
|---------------|-----------|-------------|--------------------------------|
| id            | INT       | PK          | Primary key                    |
| deployment_id | INT       | FK          | Deployment                     |
| timestamp     | DATETIME  | NOT NULL    | Metric timestamp (1-min grain) |
| metric_name   | VARCHAR   | NOT NULL    | request_rate, error_rate, latency_p50, cpu, memory |
| value         | FLOAT     | NOT NULL    | Metric value                   |
| labels        | JSON      | nullable    | e.g. {"version": "canary"}      |

**Index:** `(deployment_id, timestamp)` for efficient range queries.  
**Retention:** Cron job or trigger to delete rows where `timestamp < NOW() - 5 days`.

### 2.4 Migration Strategy

1. **Migration 1:** Create `deployment_locks` table.
2. **Migration 2:** Create `deployment_metrics` table (Step 8).
3. **Migration 3 (optional):** Extend `DeploymentStatus` enum if new statuses are added.
4. **Backward compatibility:** Existing rows have `deployment_strategy=NULL` → treat as `rolling`. No data backfill required.

---

## 3. Service Layer Design

### 3.1 New Services

| Service                    | Responsibility                                                                 | Reuse |
|----------------------------|---------------------------------------------------------------------------------|-------|
| `DeploymentStrategyService`| Dispatch to rolling/blue-green/canary; orchestrate deploy/promote/abort/rollback | Extends DeploymentService |
| `TrafficManagementService` | Build/update Istio VirtualService and DestinationRule YAML; call DCM or K8s API | New; uses DCMClient or K8s client |
| `DeploymentLockService`    | Acquire/release lock; check if locked; used by DeploymentService               | New |
| `MetricsService`          | Collect metrics from K8s metrics API + Istio; store with retention             | New |

### 3.2 Modified Services

| Service           | Changes                                                                 |
|-------------------|-------------------------------------------------------------------------|
| `DeploymentService`| Add strategy dispatch in `deploy_artifact`; call DeploymentLockService for canary; call TrafficManagementService for blue-green/canary; add `promote`, `abort`, `rollback`, `get_deployment_status` |
| `DCMClient`        | Optional: add `apply_istio_resources(values)` or rely on Helm chart to render Istio resources; or add K8s client for direct Istio CR apply |

### 3.3 Service Interactions

```
deploy_artifact (DeploymentService)
  ├── [canary] DeploymentLockService.acquire_lock() → 409 if locked
  ├── [all]   ResourceValidationService.check_resources() (Step 9)
  ├── [rolling] generate_fastapi_values + deployment_params (maxSurge, maxUnavailable)
  │            → DCM build + start (single release)
  ├── [blue_green] DeploymentStrategyService.deploy_blue_green()
  │                → build green artifact, start green release
  │                → TrafficManagementService.update_virtual_service(blue=100%, green=0%)
  ├── [canary] DeploymentStrategyService.deploy_canary()
  │            → build canary artifact, start canary release
  │            → TrafficManagementService.update_virtual_service(stable=100%, canary=0%)
  │            → DeploymentLockService.acquire_lock()
  └── _update_active_deployment (rolling/blue-green after promote; canary after promote)

promote (DeploymentService)
  ├── [canary] TrafficManagementService.update_virtual_service(stable=0%, canary=100%)
  ├── [canary] ActiveDeployment: deployment=canary, previous=stable
  ├── [canary] DeploymentLockService.release_lock()
  ├── [canary] Stop/remove stable release (optional: keep for quick rollback)
  └── [blue_green] Similar: switch to green, optionally remove blue

abort (DeploymentService)
  ├── TrafficManagementService.update_virtual_service(stable=100%, canary=0%)
  ├── DCM stop_resource(canary)
  └── DeploymentLockService.release_lock()

rollback (DeploymentService)
  ├── Validate ActiveDeployment.previous_deployment exists
  ├── TrafficManagementService: route 100% to previous
  └── ActiveDeployment: deployment=previous, previous_deployment=current
```

---

## 4. API Design

### 4.1 New Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/serve/{serve_name}/deployments/{deployment_id}/status` | Deployment status (strategy, traffic split, versions, locked) |
| POST | `/api/v1/serve/{serve_name}/deployments/{deployment_id}/promote` | Promote canary or blue-green to 100% |
| POST | `/api/v1/serve/{serve_name}/deployments/{deployment_id}/abort` | Abort canary; traffic stays on stable |
| POST | `/api/v1/serve/{serve_name}/rollback` | Rollback to previous version |
| POST | `/api/v1/serve/{serve_name}/deployments/{deployment_id}/step` | (Canary) Advance traffic: 25%, 50%, 100% |
| GET | `/api/v1/serve/{serve_name}/deployments/{deployment_id}/metrics` | Metrics for canary vs stable |

### 4.2 Modified Endpoints

| Endpoint | Change |
|----------|--------|
| `POST /api/v1/serve/{serve_name}/deploy` | Accept `deployment_strategy`, `deployment_strategy_config`; return `deployment_id` in response |

### 4.3 Request/Response Schemas

#### Deploy (Enhanced Response)

```json
// Response 201
{
  "deployment_id": 123,
  "serve_name": "my-model",
  "environment": "prod",
  "artifact_version": "v1.0.0",
  "strategy": "canary",
  "status": "deploying",
  "message": "Deployment initiated. Use GET /deployments/{id}/status for progress."
}
```

#### Deployment Status

```json
// GET /deployments/{id}/status → 200
{
  "deployment_id": 123,
  "serve_name": "my-model",
  "environment": "prod",
  "artifact_version": "v1.0.0",
  "strategy": "canary",
  "status": "canary_in_progress",
  "traffic_split": { "stable": 75, "canary": 25 },
  "versions": { "stable": "v0.9.0", "canary": "v1.0.0-canary" },
  "canary_step": "25%",
  "locked": true
}
```

#### Promote

```json
// POST /deployments/{id}/promote → 200
{
  "deployment_id": 123,
  "serve_name": "my-model",
  "environment": "prod",
  "status": "promoted",
  "message": "Canary promoted to 100%. New version is now active."
}
```

#### Rollback

```json
// POST /serve/{serve_name}/rollback
// Request: { "env": "prod" }
// Response 200
{
  "serve_name": "my-model",
  "environment": "prod",
  "previous_version": "v0.9.0",
  "current_version": "v1.0.0",
  "message": "Rolled back to v0.9.0."
}
// Error 400: { "detail": "No previous version available for rollback." }
```

#### Abort

```json
// POST /deployments/{id}/abort → 200
{
  "deployment_id": 123,
  "status": "aborted",
  "message": "Canary aborted. Traffic remains on stable version."
}
```

#### Step (Canary)

```json
// POST /deployments/{id}/step
// Request: { "traffic_percent": 25 }
// Response 200
{
  "deployment_id": 123,
  "traffic_split": { "stable": 75, "canary": 25 },
  "message": "Canary traffic set to 25%."
}
// Error 400: { "detail": "Invalid traffic_percent. Must be 25, 50, or 100." }
```

### 4.4 Error Handling

| Scenario | HTTP | Response |
|---------|------|----------|
| Canary in progress, new deploy requested | 409 | `{"detail": "Deployment locked. Cannot deploy while canary is in progress."}` |
| No previous version for rollback | 400 | `{"detail": "No previous version available for rollback."}` |
| Promote when canary not ready | 400 | `{"detail": "Canary deployment is not ready. Wait for pods to be healthy."}` |
| Promote when green failed (blue-green) | 400 | `{"detail": "Green deployment has failed. Cannot promote."}` |
| Invalid step (e.g., 30%) | 400 | `{"detail": "Invalid traffic_percent. Must be 25, 50, or 100."}` |
| Insufficient cluster resources | 400 | `{"detail": "Insufficient cluster resources. ..."}` |
| Istio required but not available | 400 | `{"detail": "Istio is required for blue-green/canary. Set ENABLE_ISTIO=true."}` |

---

## 5. Helm Chart Changes

### 5.1 Naming Convention for Multi-Version Deployments

| Strategy   | Stable/Blue Release Name | Canary/Green Release Name |
|------------|---------------------------|---------------------------|
| Rolling    | `{env}-{serve}`           | N/A (single release)      |
| Blue-Green | `{env}-{serve}-blue`      | `{env}-{serve}-green`     |
| Canary     | `{env}-{serve}-stable`    | `{env}-{serve}-canary`    |

**DCM resource_id:** Used as Helm release name. For blue-green/canary, we deploy two releases.

**artifact_id:** `{env}-{serve}-{version}` e.g. `prod-my-model-v1.0.0` (stable), `prod-my-model-v1.0.0-canary` (canary).

### 5.2 New Templates

| File | Purpose |
|------|---------|
| `templates/virtual-service.yaml` | Istio VirtualService; conditionally rendered when `deploymentStrategy` is blue_green or canary |
| `templates/destination-rule.yaml` | Istio DestinationRule; defines subsets (stable, canary, blue, green) |

### 5.3 Modified Templates

| File | Changes |
|------|---------|
| `templates/deployment.yaml` | Add `version` label to pod template (e.g. `version: stable` or `version: canary`); use `deploymentStrategy.rolling.maxSurge` / `maxUnavailable` from values when strategy=rolling |
| `values.yaml` | Add `deploymentStrategy`, `deploymentStrategyConfig`, `versionLabel` (stable/canary/blue/green) |
| `templates/service.yaml` | Add `version` to selector when multi-version; or use separate Services per version (recommended: one Service per Deployment, selector matches version) |

### 5.4 Values Structure

```yaml
# New/updated values
deploymentStrategy: rolling  # rolling | blue_green | canary
deploymentStrategyConfig:
  maxSurge: "25%"
  maxUnavailable: 0
  initial_traffic_percent: 0
versionLabel: stable  # stable | canary | blue | green
trafficSplit:  # For canary; used by ml-serve-app to render VirtualService
  stable: 100
  canary: 0
```

### 5.5 Istio VirtualService Structure

**Important:** The VirtualService is shared across stable and canary releases. Since we have two Helm releases (stable + canary), the VirtualService cannot be rendered by a single release. **Recommendation:** ml-serve-app applies the VirtualService directly via Kubernetes API (TrafficManagementService), using a deterministic name e.g. `{env}-{serve}-vs`. DCM/Helm does not own this resource.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: {env}-{serve}-vs
  namespace: {namespace}
spec:
  hosts:
    - {host}
  http:
    - route:
        - destination:
            host: {serve}-stable.{namespace}.svc.cluster.local
            subset: stable
          weight: 75
        - destination:
            host: {serve}-canary.{namespace}.svc.cluster.local
            subset: canary
          weight: 25
```

### 5.6 Istio DestinationRule Structure

**One DestinationRule per Service.** Each Deployment (stable, canary) has its own Service. The DestinationRule defines subsets for each Service. Alternatively, use a single DestinationRule with host matching the primary service.

```yaml
# For canary: two Services, two DestinationRules (or one DR with multiple hosts)
# Stable Service: {serve}-stable, selector: version=stable
# Canary Service: {serve}-canary, selector: version=canary
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: {serve}-stable-dr
  namespace: {namespace}
spec:
  host: {serve}-stable.{namespace}.svc.cluster.local
  subsets:
    - name: stable
      labels:
        version: stable
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: {serve}-canary-dr
  namespace: {namespace}
spec:
  host: {serve}-canary.{namespace}.svc.cluster.local
  subsets:
    - name: canary
      labels:
        version: canary
```

**Note:** For blue-green, same pattern: `{serve}-blue` and `{serve}-green` Services; VirtualService routes to both with weight 0/100 or 100/0.

---

## 6. Deployment Strategy Execution Flows

### 6.1 Rolling Deployment Flow

```
1. Validate serve, artifact, env, config
2. Check deployment_strategy_config for maxSurge, maxUnavailable (default: 25%, 0)
3. generate_fastapi_values() + deployment_params
4. DCM build_resource(artifact_id={env}-{serve}-{version})
5. DCM start_resource(resource_id={env}-{serve}, artifact_id=...)
6. Create Deployment + AppLayerDeployment (strategy=rolling, params=...)
7. _update_active_deployment(serve, env, deployment)
8. Return deployment_id, status
```

### 6.2 Blue-Green Deployment Flow

```
1. Validate; require ENABLE_ISTIO
2. Get ActiveDeployment; current = blue (or first deploy = blue)
3. Build green artifact: artifact_id={env}-{serve}-{version}
4. Deploy green: start_resource(resource_id={env}-{serve}-green, artifact_id=...)
5. Create Deployment (green), AppLayerDeployment (strategy=blue_green)
6. Do NOT update ActiveDeployment yet; traffic stays on blue
7. Create/update VirtualService: 100% blue, 0% green
8. Return deployment_id; user calls promote when ready
```

**Promote Blue-Green:**
```
1. Validate deployment is blue_green and green is healthy
2. Update VirtualService: 0% blue, 100% green
3. ActiveDeployment.deployment = green deployment; previous = blue
4. Optionally stop blue release to free resources
```

### 6.3 Canary Deployment Flow

**Deploy:**
```
1. Check DeploymentLockService: if locked → 409
2. Validate; require ENABLE_ISTIO
3. Build canary artifact: version suffix "-canary", artifact_id={env}-{serve}-{version}-canary
4. Deploy canary: start_resource(resource_id={env}-{serve}-canary, artifact_id=...)
5. Create Deployment (canary), AppLayerDeployment (strategy=canary)
6. DeploymentLockService.acquire_lock(serve, env, deployment)
7. Create/update VirtualService: stable=100%, canary=0%
8. Return deployment_id
```

**Step (25%, 50%):**
```
1. Validate deployment is canary and locked
2. Update VirtualService: e.g. stable=75%, canary=25%
3. Persist traffic split in AppLayerDeployment.deployment_params or in-memory
4. Return updated traffic_split
```

**Promote Canary:**
```
1. Update VirtualService: stable=0%, canary=100%
2. ActiveDeployment.deployment = canary; previous = stable
3. DeploymentLockService.release_lock()
4. Optionally stop stable release
5. Rename canary → stable (new release or just update labels)
```

**Abort Canary:**
```
1. Update VirtualService: stable=100%, canary=0%
2. DCM stop_resource(canary)
3. DeploymentLockService.release_lock()
4. Mark canary deployment as ABORTED/ENDED
```

### 6.4 Rollback Flow

```
1. Get ActiveDeployment for serve+env
2. If previous_deployment is None → 400
3. Update VirtualService/DestinationRule to route 100% to previous
4. ActiveDeployment.deployment = previous; previous_deployment = current
5. Optionally stop current release
6. Return success
```

---

## 7. Traffic Management Design

### 7.1 Istio VirtualService Structure

- **One VirtualService per serve** (not per version). Host: ingress host(s).
- **Routes:** Single `http` route with multiple `destination` entries and `weight` for canary.
- **Blue-Green:** Two destinations, weights 0/100 or 100/0.
- **Canary:** Two destinations, weights e.g. 75/25.

### 7.2 DestinationRule Structure

- **One DestinationRule per subset** or one DR with multiple subsets.
- **Subsets:** `stable`, `canary`, `blue`, `green` — match pod labels `version: stable` etc.
- **Services:** Each version has its own Deployment and Service. Service selector: `version: canary`.

### 7.3 How Traffic Splits Are Applied

1. ml-serve-app computes desired traffic split (e.g. 75% stable, 25% canary).
2. TrafficManagementService builds VirtualService YAML with `weight` values.
3. Apply via: (a) Helm chart with values override, or (b) K8s API (apply VirtualService CR).
4. Istio pilot propagates config; Envoy enforces routing.

---

## 8. Metrics Collection Design

### 8.1 Data Sources

| Metric | Source | Method |
|--------|--------|--------|
| Request rate | Istio sidecar `istio_requests_total` | Prometheus scrape (if available) or K8s custom metrics |
| Error rate (5xx) | Istio `istio_requests_total{response_code=~"5.."}` | Same |
| Latency (p50, p95, p99) | Istio `istio_request_duration_milliseconds` | Same |
| CPU/Memory | Kubernetes metrics.k8s.io | metrics-server or Prometheus node-exporter |

### 8.2 Collection Mechanism

- **Option A:** Prometheus + PromQL — if Prometheus is deployed, ml-serve-app queries Prometheus API.
- **Option B:** metrics-server + custom collector — ml-serve-app runs a background job that:
  - Calls K8s metrics API for CPU/memory
  - Calls Istio metrics endpoint (if exposed) or Prometheus
- **Option C:** Store in DB — new table `deployment_metrics` with (deployment_id, timestamp, metric_name, value); 1-min frequency; 5-day retention via TTL or cron cleanup.

### 8.3 Storage and Retention

- **Table:** `deployment_metrics` (deployment_id, timestamp, metric_name, value, labels)
- **Retention:** Delete rows older than 5 days (cron or on insert).
- **API:** `GET /deployments/{id}/metrics?from=&to=&metric=` returns time-series.

---

## 9. Deployment Locking Mechanism

### 9.1 Lock Acquisition

- **When:** On canary deploy, before creating canary Deployment.
- **How:** `DeploymentLockService.acquire_lock(serve_id, environment_id, deployment_id)`.
- **Implementation:** INSERT into `deployment_locks` with unique (serve_id, environment_id). On conflict → 409.

### 9.2 Lock Release

- **When:** On promote or abort.
- **How:** `DeploymentLockService.release_lock(serve_id, environment_id)` — DELETE from deployment_locks.

### 9.3 Race Condition Prevention

- **DB unique constraint** on (serve_id, environment_id) prevents duplicate locks.
- **Optimistic locking:** Use `SELECT ... FOR UPDATE` or `INSERT ... ON CONFLICT` in transaction.
- **Check before deploy:** In `deploy_artifact`, if strategy=canary, first check `DeploymentLockService.is_locked(serve, env)` → 409 if true.

---

## 10. File-Level Change List

### 10.1 Files to Create

| File | Purpose | Est. LOC |
|------|---------|----------|
| `model/src/ml_serve_model/deployment_lock.py` | DeploymentLock model | ~25 |
| `model/src/ml_serve_model/deployment_metric.py` | DeploymentMetric model (Step 8) | ~20 |
| `core/src/ml_serve_core/service/deployment_strategy_service.py` | Strategy-specific deploy logic | ~200 |
| `core/src/ml_serve_core/service/traffic_management_service.py` | Istio VirtualService/DestinationRule | ~150 |
| `core/src/ml_serve_core/service/deployment_lock_service.py` | Lock acquire/release | ~80 |
| `core/src/ml_serve_core/service/metrics_service.py` | Metrics collection | ~120 |
| `core/src/ml_serve_core/service/resource_validation_service.py` | Pre-deploy resource check | ~80 |
| `core/src/ml_serve_core/client/k8s_client.py` | K8s API client for applying Istio CRs (VirtualService, DestinationRule) | ~100 |
| `app_layer/src/ml_serve_app_layer/dtos/responses.py` | Response DTOs (optional) | ~50 |
| `darwin-cluster-manager/charts/darwin-fastapi-serve/templates/virtual-service.yaml` | Istio VirtualService | ~50 |
| `darwin-cluster-manager/charts/darwin-fastapi-serve/templates/destination-rule.yaml` | Istio DestinationRule | ~40 |
| `model/migrations/xxx_create_deployment_locks.py` | Tortoise migration for deployment_locks | ~30 |
| `model/migrations/xxx_create_deployment_metrics.py` | Tortoise migration for deployment_metrics | ~25 |
| `tests/unit/test_deployment_strategy_service.py` | Unit tests | ~150 |
| `tests/unit/test_deployment_lock_service.py` | Unit tests | ~80 |
| `tests/unit/test_traffic_management_service.py` | Unit tests | ~100 |
| `tests/integration/test_canary_flow.py` | Integration tests | ~120 |

### 10.2 Files to Modify

| File | Changes | Est. LOC delta |
|------|---------|----------------|
| `model/src/ml_serve_model/enums.py` | Add DeploymentStatus values | +5 |
| `model/src/ml_serve_model/__init__.py` | Export DeploymentLock | +1 |
| `core/src/ml_serve_core/service/deployment_service.py` | Strategy dispatch, promote, abort, rollback, status | +250 |
| `core/src/ml_serve_core/utils/yaml_utils.py` | Pass deployment_strategy, deployment_params to values | +40 |
| `app_layer/src/ml_serve_app_layer/rest/deployment.py` | New routes: status, promote, abort, rollback, step | +120 |
| `app_layer/src/ml_serve_app_layer/dtos/requests.py` | RollbackRequest, StepRequest, validate strategy | +30 |
| `darwin-cluster-manager/charts/darwin-fastapi-serve/templates/deployment.yaml` | version label, rolling params from values | +15 |
| `darwin-cluster-manager/charts/darwin-fastapi-serve/values.yaml` | deploymentStrategy, versionLabel, trafficSplit | +20 |
| `core/src/ml_serve_core/resources/fastapi_values.yaml` | Same as above | +15 |
| `core/src/ml_serve_core/constants/constants.py` | ENABLE_ISTIO doc | +2 |

### 10.3 Estimated Total

- **New:** ~1,200 LOC
- **Modified:** ~530 LOC
- **Total:** ~1,730 LOC

---

## 11. Security Considerations

### 11.1 Authentication/Authorization

- **Same as deploy:** Promote, abort, rollback use existing `AuthorizedUser` dependency.
- **No special roles:** No new permissions; deployers can promote/rollback their deployments.

### 11.2 Istio mTLS

- **Recommendation:** Use `DISABLE` for traffic policy (as in existing flagger) unless platform enables mTLS.
- **Document:** If mTLS is enabled, set `trafficPolicy.tls.mode: ISTIO_MUTUAL` in VirtualService.

### 11.3 Secrets Management

- **No new secrets** for deployment strategies.
- **Existing:** Model cache, MLflow credentials — unchanged.

---

## 12. Error Handling & Observability

### 12.1 Error Scenarios and Handling

| Scenario | Handling |
|----------|----------|
| DCM build/start fails | Rollback DB state if partial; return 500 with message |
| Istio update fails | Retry (e.g. 3x); return 500; do not leave traffic in inconsistent state |
| Canary pods crash | Keep at 0%; mark canary failed; require abort or retry |
| Promotion during deploy | Reject with 400; poll status until ready |

### 12.2 Logging Strategy

- **Structured logging:** `logger.info("deploy_started", strategy=..., serve=..., env=...)`
- **Key events:** deploy_started, deploy_completed, promote_called, rollback_called, lock_acquired, lock_released
- **Errors:** Include traceback, deployment_id, serve_name

### 12.3 Monitoring Integration Points

- **Existing:** OpenTelemetry, Datadog (if configured)
- **New:** Emit spans for deploy/promote/rollback; add deployment_strategy tag to metrics

---

## 13. Backward Compatibility

### 13.1 Existing Deployments

- **deployment_strategy=NULL** → treat as `rolling`
- **No migration:** Existing ActiveDeployment, Deployment rows unchanged
- **Helm:** Default values for `deploymentStrategy: rolling`, `maxSurge: 25%`, `maxUnavailable: 0`

### 13.2 Migration Path

1. Deploy new code; existing serves continue with rolling (no Istio required).
2. New deployments can opt into blue_green/canary when ENABLE_ISTIO=true.
3. No breaking API changes; deploy response enhanced with deployment_id (existing clients can ignore).

---

## 14. Testing Strategy

### 14.1 Unit Tests

| Target | Scenarios |
|--------|-----------|
| DeploymentStrategyService | deploy_rolling, deploy_blue_green, deploy_canary; correct DCM params |
| DeploymentLockService | acquire_lock, release_lock, is_locked; 409 on double acquire |
| TrafficManagementService | build_virtual_service_yaml with correct weights |
| DeploymentService | promote, abort, rollback; 400 when no previous |
| ResourceValidationService | insufficient resources → 400 |

### 14.2 Integration Tests

| Scenario | Setup | Assertion |
|----------|-------|-----------|
| Canary deploy → step → promote | Mock DCM, DB | Lock acquired, released; traffic split updated |
| Canary deploy while locked | Lock held | 409 on second deploy |
| Rollback with previous | ActiveDeployment with previous | Traffic switched, ActiveDeployment updated |
| Rollback without previous | No previous_deployment | 400 |

### 14.3 E2E Test Requirements

- **Minimal:** Deploy canary in dev cluster with Istio; step to 25%; promote; verify traffic.
- **Rollback:** Deploy v1, deploy v2, rollback; verify v1 receives traffic.
- **Resource validation:** Mock K8s API to return insufficient resources; verify 400.

---

## 15. Risk Areas

| Risk | Mitigation |
|------|------------|
| DCM does not support multiple releases per serve | Extend DCM or use distinct resource_id (e.g. {env}-{serve}-canary); confirm with DCM team |
| Istio VirtualService applied outside Helm | May require K8s client in ml-serve-app; or DCM supports applying extra manifests |
| Flagger CRD conflicts | Keep flagger disabled; our canary uses custom VirtualService only |
| Metrics collection adds latency | Async job; 1-min interval; limit query scope |

---

## 16. Open Questions

1. **DCM multi-release:** Does DCM support multiple Helm releases per logical serve (e.g. prod-my-model-stable and prod-my-model-canary)?
2. **Istio resource ownership:** Should VirtualService/DestinationRule be part of the Helm chart (per release) or applied separately by ml-serve-app? Per-release would mean two VirtualServices for canary (stable + canary releases) — need one shared VirtualService.
3. **Metrics backend:** Is Prometheus available in-cluster? If not, what is the fallback for request rate/error rate/latency?
4. **One-click deploy-model:** Should it support deployment_strategy? PRD shows it in the example; extend ModelDeploymentRequest.

---

## 17. Step-to-Architecture Mapping

| Step PRD | Architecture Components |
|----------|-------------------------|
| Step 1: Istio Readiness | VirtualService, DestinationRule templates; ENABLE_ISTIO check |
| Step 2: Enhanced Rolling | deployment_params in yaml_utils; Helm values maxSurge/maxUnavailable |
| Step 3: Blue-Green | DeploymentStrategyService.deploy_blue_green; TrafficManagementService |
| Step 4: Canary Core | deploy_canary; step API; version naming |
| Step 5: Canary Promotion & Locking | DeploymentLockService; promote; abort |
| Step 6: Rollback API | rollback flow; ActiveDeployment.previous_deployment |
| Step 7: Deployment Status API | get_deployment_status; traffic_split, versions, locked |
| Step 8: Metrics | MetricsService; deployment_metrics table |
| Step 9: Resource Validation | ResourceValidationService; pre-deploy check |

---

*End of Architecture Document*
