# PRD: Advanced Deployment Strategies for ML Serve App

**Version:** 1.0  
**Status:** Draft  
**Last Updated:** February 2025

---

## 1. Overview

### 1.1 Feature Summary

This PRD defines the implementation of advanced deployment strategies—**Rolling** (enhanced), **Blue-Green**, and **Canary**—for FastAPI-based ML model serves in the Darwin Platform. The ml-serve-app control plane will manage these strategies via Istio-based traffic routing, with manual promotion and rollback capabilities exposed through the API.

### 1.2 Business Value

| Value | Description |
|-------|-------------|
| **Reduced risk** | Canary deployments allow gradual validation of new model versions before full traffic cutover |
| **Zero downtime** | Blue-Green enables instant switchover with no user-facing interruption |
| **Operational control** | Manual promotion and rollback give operators explicit control over release decisions |
| **Platform maturity** | Aligns Darwin with industry-standard deployment practices for production ML workloads |

### 1.3 Scope

- **In scope:** FastAPI serves only (artifact-based and one-click model deployments)
- **Out of scope:** Workflow serves, deployment history tracking, UI, automated canary analysis

---

## 2. Goals & Non-Goals

### 2.1 Goals

1. **Rolling (enhanced):** Configurable maxSurge/maxUnavailable; existing serves default to rolling with no migration
2. **Blue-Green:** Deploy new version alongside current; switch 100% traffic atomically; zero downtime
3. **Canary:** Deploy new version; manually step traffic 0% → 25% → 50% → 100%; lock deployments during canary
4. **Traffic management:** Istio VirtualService/DestinationRule for traffic splitting
5. **Promotion:** API to promote canary to 100% or blue-green to active
6. **Rollback:** API to revert to immediate previous version
7. **Basic metrics:** Collect request rate, error rate, latency, CPU/memory from Kubernetes/Istio; 1-min frequency, 5-day retention

### 2.2 Non-Goals

| Item | Rationale |
|------|-----------|
| Workflow serves | Out of scope per requirements |
| Deployment history | Keep simple; only previous version for rollback |
| Automated canary analysis | Manual promotion only |
| External monitoring (Datadog, etc.) | Basic metrics from K8s/Istio only |
| UI for deployment management | API-only |
| A/B testing or shadow traffic | Future consideration |

---

## 3. User Stories

### 3.1 Primary Personas

**ML Engineer (deployer)**  
- As an ML engineer, I want to deploy a new model version using a canary strategy so that I can validate it with a small percentage of traffic before full rollout.  
- As an ML engineer, I want to promote my canary to 100% when metrics look good so that the new version becomes the active deployment.  
- As an ML engineer, I want to rollback to the previous version if the new deployment fails so that I can restore service quickly.

**Platform Operator**  
- As a platform operator, I want to deploy using blue-green so that I can switch traffic instantly with zero downtime.  
- As a platform operator, I want deployment locking during canary so that no one can start another deployment until the current canary is promoted or aborted.

**SRE / On-call**  
- As an SRE, I want real-time deployment status via API so that I can monitor active canaries and blue-green states.  
- As an SRE, I want to see basic metrics (error rate, latency) for canary vs stable so that I can decide whether to promote.

### 3.2 Edge-Case Personas

- As a deployer, I want the system to fail fast if cluster resources are insufficient so that I am not left with a partial deployment.
- As a deployer, I want a failed canary to stay at 0% traffic until I manually intervene so that users are never exposed to a broken version.

---

## 4. Functional Requirements

### 4.1 Deployment Strategies

| ID | Requirement |
|----|-------------|
| FR-1 | The system shall support three deployment strategies: `rolling`, `blue_green`, and `canary`. |
| FR-2 | The system shall default existing serves to `rolling` with no migration required. |
| FR-3 | For `rolling`, the system shall allow configurable `maxSurge` and `maxUnavailable` (Helm values). |
| FR-4 | For `blue_green`, the system shall deploy the new version alongside the current version and switch 100% traffic atomically upon promotion. |
| FR-5 | For `canary`, the system shall support manual traffic steps: 0% → 25% → 50% → 100%. |
| FR-6 | The system shall use version naming: `v1.0.0` (stable) and `v1.0.0-canary` (canary). |
| FR-7 | The system shall allow only one concurrent canary per serve per environment. |
| FR-8 | The system shall lock new deployments when a canary is in progress for that serve/environment. |

### 4.2 Traffic Management

| ID | Requirement |
|----|-------------|
| FR-9 | The system shall use Istio VirtualService and DestinationRule for traffic splitting. |
| FR-10 | The system shall route traffic based on subset labels (e.g., `version: stable`, `version: canary`). |
| FR-11 | The system shall require Istio to be available when using blue-green or canary strategies. |

### 4.3 Promotion & Rollback

| ID | Requirement |
|----|-------------|
| FR-12 | The system shall provide an API to promote a canary to 100% traffic. |
| FR-13 | The system shall provide an API to promote a blue-green deployment (switch traffic to new version). |
| FR-14 | The system shall provide an API to rollback to the immediate previous version. |
| FR-15 | Rollback shall only target the immediate previous version (no arbitrary version selection). |
| FR-16 | Promotion and rollback shall require the same authentication as regular deployments. |

### 4.4 Status & Metrics

| ID | Requirement |
|----|-------------|
| FR-17 | The system shall expose deployment status via API (strategy, current traffic split, canary/blue-green state). |
| FR-18 | The system shall collect metrics: request rate, error rate (5xx), latency (p50, p95, p99), CPU/memory usage. |
| FR-19 | Metrics shall be collected at 1-minute frequency with 5-day retention. |
| FR-20 | Metrics shall be sourced from Kubernetes and Istio (no external monitoring system). |

### 4.5 Deployment Validation

| ID | Requirement |
|----|-------------|
| FR-21 | The system shall check resource availability before deployment and fail fast if insufficient. |
| FR-22 | For failed canaries, the system shall keep traffic at 0% and require manual intervention. |

---

## 5. Non-Functional Requirements

| Category | Requirement |
|----------|--------------|
| **Scale** | Support ~50 serves, ~20 deployments/day, 1–3 concurrent canaries |
| **Backward compatibility** | Existing serves default to rolling; no migration required |
| **Security** | Same auth as regular deployments; no special permissions for promotion/rollback |
| **Latency** | API responses for deploy/promote/rollback within 30 seconds |

---

## 6. Edge Cases

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| 1 | Canary deployment fails (pods crash, health check fails) | Keep at 0% traffic; mark canary as failed; require manual abort or retry |
| 2 | Canary at 25% shows high error rate | Operator can rollback or abort; traffic returns to previous version |
| 3 | Blue-green: new version fails during deploy | Do not switch traffic; keep previous version active |
| 4 | Insufficient cluster resources | Fail fast before deployment; return clear error |
| 5 | Promotion requested while canary is still deploying | Reject or wait until canary is ready |
| 6 | Rollback when no previous version exists | Return 400 with clear message |
| 7 | New deployment requested while canary in progress | Reject with 409 Conflict; deployment locked |

---

## 7. API Contract Examples

### 7.1 Deploy (Existing, Enhanced)

**POST** `/api/v1/serve/{serve_name}/deploy`

```json
{
  "env": "prod",
  "artifact_version": "v1.0.0",
  "api_serve_deployment_config": {
    "deployment_strategy": "canary",
    "deployment_strategy_config": {
      "initial_traffic_percent": 0
    }
  }
}
```

**POST** `/api/v1/serve/deploy-model`

```json
{
  "serve_name": "my-model",
  "artifact_version": "v1.0.0",
  "model_uri": "mlflow-artifacts:/45/abc123/artifacts/model",
  "env": "prod",
  "deployment_strategy": "blue_green",
  "deployment_strategy_config": {},
  "cores": 4,
  "memory": 8,
  "min_replicas": 1,
  "max_replicas": 3
}
```

**Response (201 Created):**

```json
{
  "deployment_id": 123,
  "serve_name": "my-model",
  "environment": "prod",
  "artifact_version": "v1.0.0",
  "strategy": "blue_green",
  "status": "deploying",
  "message": "Deployment initiated. Use GET /deployments/{id}/status for progress."
}
```

### 7.2 Deployment Status

**GET** `/api/v1/serve/{serve_name}/deployments/{deployment_id}/status`

**Response (200 OK):**

```json
{
  "deployment_id": 123,
  "serve_name": "my-model",
  "environment": "prod",
  "artifact_version": "v1.0.0",
  "strategy": "canary",
  "status": "canary_in_progress",
  "traffic_split": {
    "stable": 75,
    "canary": 25
  },
  "versions": {
    "stable": "v0.9.0",
    "canary": "v1.0.0-canary"
  },
  "canary_step": "25%",
  "locked": true
}
```

### 7.3 Promote Canary

**POST** `/api/v1/serve/{serve_name}/deployments/{deployment_id}/promote`

```json
{}
```

**Response (200 OK):**

```json
{
  "deployment_id": 123,
  "serve_name": "my-model",
  "environment": "prod",
  "status": "promoted",
  "message": "Canary promoted to 100%. New version is now active."
}
```

### 7.4 Promote Blue-Green

**POST** `/api/v1/serve/{serve_name}/deployments/{deployment_id}/promote`

(Same as canary; context determines behavior.)

### 7.5 Rollback

**POST** `/api/v1/serve/{serve_name}/rollback`

```json
{
  "env": "prod"
}
```

**Response (200 OK):**

```json
{
  "serve_name": "my-model",
  "environment": "prod",
  "previous_version": "v0.9.0",
  "current_version": "v1.0.0",
  "message": "Rolled back to v0.9.0."
}
```

**Error (400 Bad Request):**

```json
{
  "detail": "No previous version available for rollback."
}
```

### 7.6 Abort Canary

**POST** `/api/v1/serve/{serve_name}/deployments/{deployment_id}/abort`

**Response (200 OK):**

```json
{
  "deployment_id": 123,
  "status": "aborted",
  "message": "Canary aborted. Traffic remains on stable version."
}
```

---

## 8. Step PRDs (Independently Shippable)

### Step 1: Istio Readiness & Service Mesh Foundation

| Attribute | Value |
|-----------|-------|
| **Description** | Ensure Istio is available and document installation approach. Add Istio VirtualService/DestinationRule templates to Helm chart for traffic routing. No deployment strategy logic yet. |
| **Goals** | (1) Document Istio installation (cluster-wide vs per-namespace); (2) Add Istio resources to darwin-fastapi-serve chart; (3) Validate Istio integration in dev. |
| **Acceptance Criteria** | Given Istio is installed, When a serve is deployed, Then Istio VirtualService and DestinationRule are created. Given Istio is not installed, When ENABLE_ISTIO=false, Then deployment works without Istio (rolling only). |
| **Dependencies** | None |
| **Complexity** | Medium |

**Risks:** Istio version compatibility. **Assumption:** Istio is pre-installed by platform team; Darwin does not install Istio.

---

### Step 2: Enhanced Rolling Deployment

| Attribute | Value |
|-----------|-------|
| **Description** | Make rolling deployment configurable via `deployment_strategy_config` (maxSurge, maxUnavailable). Persist strategy in AppLayerDeployment. Default existing serves to rolling. |
| **Goals** | (1) Expose rolling params in API; (2) Pass to Helm values; (3) Backward compatible. |
| **Acceptance Criteria** | Given deployment_strategy=rolling and config {maxSurge: "25%", maxUnavailable: 0}, When deploy is called, Then Helm receives these values. Given no strategy specified, When deploy is called, Then default rolling is used. |
| **Dependencies** | None |
| **Complexity** | Low |

---

### Step 3: Blue-Green Deployment

| Attribute | Value |
|-----------|-------|
| **Description** | Implement blue-green: deploy new version as "green", keep "blue" (current) active. Traffic stays on blue until promotion. Promotion switches 100% to green. |
| **Goals** | (1) Deploy green alongside blue; (2) Istio routes to blue by default; (3) Promote API switches to green; (4) Zero downtime. |
| **Acceptance Criteria** | Given strategy=blue_green, When deploy is called, Then green deployment is created, traffic on blue. Given promote is called, When green is ready, Then 100% traffic switches to green. Given promote is called, When green has failed, Then return error, traffic stays on blue. |
| **Dependencies** | Step 1 (Istio) |
| **Complexity** | High |

---

### Step 4: Canary Deployment (Core)

| Attribute | Value |
|-----------|-------|
| **Description** | Implement canary: deploy new version with 0% traffic. Support manual traffic steps 0% → 25% → 50% → 100% via API. Use Istio for traffic splitting. |
| **Goals** | (1) Deploy canary with 0% traffic; (2) Step API to advance traffic; (3) Version naming: v1.0.0 (stable), v1.0.0-canary (canary). |
| **Acceptance Criteria** | Given strategy=canary, When deploy is called, Then canary deployment exists with 0% traffic. Given step API with 25%, When called, Then VirtualService routes 25% to canary. Given invalid step (e.g., 30%), When called, Then return 400. |
| **Dependencies** | Step 1 (Istio) |
| **Complexity** | High |

---

### Step 5: Canary Promotion & Deployment Locking

| Attribute | Value |
|-----------|-------|
| **Description** | Add promote API for canary (move to 100%). Add deployment lock: reject new deployments when canary in progress. |
| **Goals** | (1) Promote canary to 100%; (2) Lock deployments during canary; (3) Unlock after promote/abort. |
| **Acceptance Criteria** | Given canary at 50%, When promote is called, Then traffic goes to 100%, canary becomes stable, lock released. Given canary in progress, When new deploy is requested, Then return 409 Conflict. Given abort is called, When canary is active, Then traffic returns to stable, canary removed, lock released. |
| **Dependencies** | Step 4 |
| **Complexity** | Medium |

---

### Step 6: Rollback API

| Attribute | Value |
|-----------|-------|
| **Description** | Implement rollback to immediate previous version. Use ActiveDeployment.previous_deployment. |
| **Goals** | (1) Rollback API; (2) Switch traffic to previous version; (3) Update ActiveDeployment. |
| **Acceptance Criteria** | Given previous version exists, When rollback is called, Then traffic switches to previous, ActiveDeployment updated. Given no previous version, When rollback is called, Then return 400. |
| **Dependencies** | Step 1 (Istio for traffic switch) |
| **Complexity** | Medium |

---

### Step 7: Deployment Status API

| Attribute | Value |
|-----------|-------|
| **Description** | Expose real-time deployment status: strategy, traffic split, canary/blue-green state, locked status. |
| **Goals** | (1) GET deployment status; (2) Include traffic_split, versions, canary_step, locked. |
| **Acceptance Criteria** | Given deployment exists, When status is requested, Then return strategy, traffic_split, versions, locked. |
| **Dependencies** | Steps 3, 4, 5 |
| **Complexity** | Low |

---

### Step 8: Basic Metrics Collection

| Attribute | Value |
|-----------|-------|
| **Description** | Implement basic metrics collection from Kubernetes and Istio: request rate, error rate (5xx), latency (p50, p95, p99), CPU/memory. 1-min frequency, 5-day retention. |
| **Goals** | (1) Scrape metrics from K8s/Istio; (2) Store with retention; (3) Expose via API for canary/stable comparison. |
| **Acceptance Criteria** | Given deployment is running, When 1 minute has passed, Then metrics are collected. Given 5 days have passed, When querying metrics, Then data older than 5 days is not returned. |
| **Dependencies** | Step 1 (Istio for request metrics) |
| **Complexity** | High |

---

### Step 9: Resource Validation & Fail-Fast

| Attribute | Value |
|-----------|-------|
| **Description** | Check cluster resource availability before deployment. Fail fast with clear error if insufficient. |
| **Goals** | (1) Pre-deploy resource check; (2) Clear error messages; (3) No partial deployments. |
| **Acceptance Criteria** | Given insufficient CPU/memory in cluster, When deploy is called, Then return 400 with "Insufficient cluster resources" before any deployment. |
| **Dependencies** | None |
| **Complexity** | Medium |

---

## 9. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Deployment success rate | (current) | ≥ 95% | Successful deploys / total deploys |
| Rollback time | N/A | < 2 min | Time from rollback API call to traffic switched |
| Canary adoption | 0% | 30% of prod deploys use canary within 6 months | Strategy distribution in deployments |
| Zero-downtime blue-green | N/A | 100% | No 5xx spike during blue-green switch |
| API latency (deploy/promote/rollback) | N/A | p95 < 30s | Response time percentiles |

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Istio upgrade breaks traffic routing | Medium | High | Pin Istio version; test upgrades in staging; document version compatibility |
| Flagger CRD conflicts with custom canary | Low | Medium | Disable Flagger when using custom canary; use separate Helm values |
| Metrics collection adds latency | Low | Medium | Run collection async; use 1-min interval to limit load |
| Rollback fails (K8s/Istio inconsistency) | Medium | High | Idempotent rollback; retry logic; manual fallback runbook |
| Concurrent promotion/rollback race | Medium | Medium | Use deployment lock; optimistic locking in DB |
| Istio not installed in some envs | High | Medium | Require Istio for blue-green/canary; graceful degradation to rolling |

---

## 11. Service Mesh Integration Recommendation

### 11.1 Istio Installation

| Approach | Recommendation | Rationale |
|----------|----------------|-----------|
| **Cluster-wide vs per-namespace** | **Cluster-wide** | Darwin manages multiple serves across namespaces; single Istio control plane simplifies operations. |
| **Darwin install vs pre-installed** | **Pre-installed** | Istio is infrastructure; platform team should own installation, upgrades, and mesh config. Darwin assumes Istio is available when ENABLE_ISTIO=true. |

### 11.2 Istio Version

- Target **latest stable** (e.g., Istio 1.20+ as of 2025). Document in Darwin setup guide.
- Validate compatibility with Kubernetes version used in Darwin clusters.

### 11.3 Integration Approach

1. **VirtualService:** One per serve; defines routes and traffic splits (canary %).
2. **DestinationRule:** Defines subsets (stable, canary, blue, green) with version labels.
3. **Gateway:** Reuse existing Istio ingress gateway; Darwin serves use host-based routing.
4. **Metrics:** Use Istio sidecar metrics (e.g., `istio_requests_total`) for request rate and error rate; supplement with Kubernetes metrics for CPU/memory.

### 11.4 Flagger Consideration

- Existing `flagger.yaml` uses Datadog and automated analysis. For this PRD, we use **manual** canary with custom logic.
- **Recommendation:** Keep Flagger disabled by default. When `deployment_strategy=canary`, use custom Istio VirtualService updates instead of Flagger CRD. This avoids Datadog dependency and gives full control over traffic steps.

---

## 12. Rollout Plan

| Phase | Scope | Duration | Rollback Trigger |
|-------|--------|----------|------------------|
| **Internal** | Darwin team; single serve in dev | 2 weeks | Critical bugs |
| **Beta** | 2–3 pilot teams; canary + blue-green | 4 weeks | Error rate > 2% during switch |
| **GA** | All FastAPI serves | 2 weeks | Same as beta |
| **Full** | Default canary for high-risk serves | Ongoing | N/A |

---

## 13. Appendix: Data Model (Reference)

- **AppLayerDeployment:** `deployment_strategy`, `deployment_params` (already exist; will be populated)
- **ActiveDeployment:** `deployment`, `previous_deployment`, `serve`, `environment` (already exist; used for rollback)
- **New/Extended:** May need `DeploymentLock` or `canary_in_progress` flag per serve/environment for locking.

---

*End of PRD*
