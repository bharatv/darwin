## Deployment strategies (API serves)

ML Serve supports approval-gated deployment strategies for **API serves**. Strategies are selected via
`POST /api/v1/serve/{serve_name}/deploy` and progressed via the deployment control APIs under `/api/v1/deployment`.

### Concepts

- **Primary (live)**: the currently active version serving production traffic.
- **Candidate**: the new version being rolled out (canary / green / rolling release).
- **Approval gate**: a manual action required to progress the rollout.
- **Traffic shifting**: implemented via **Kubernetes Service selector updates** (no service mesh required).

### Backward compatibility (legacy deploy)

If `api_serve_deployment_config.deployment_strategy` is **omitted** or **null**, ML Serve uses the legacy flow:
a standard Kubernetes rolling update of the single primary release.

### API: start a deployment

All strategies use the same entry point:

`POST /api/v1/serve/{serve_name}/deploy`

Body shape:

```json
{
  "env": "prod",
  "artifact_version": "v2.0.0",
  "api_serve_deployment_config": {
    "deployment_strategy": "canary|blue-green|rolling",
    "deployment_strategy_config": {},
    "environment_variables": {}
  }
}
```

Response includes at minimum:
- `deployment_id`
- `strategy`
- `phase`
- `requires_approval`

### Canary

**Goal**: shift traffic gradually in steps (approval between each step), then terminate the old version once traffic is 100%.

Start:

```json
{
  "env": "prod",
  "artifact_version": "v2.0.0",
  "api_serve_deployment_config": {
    "deployment_strategy": "canary",
    "deployment_strategy_config": { "steps": [20, 50, 100] }
  }
}
```

Progress:
- Approve each step:
  - `POST /api/v1/deployment/{deployment_id}/approve`
- On final approval (100%):
  - traffic is shifted to the new version
  - **old version is scaled down immediately**
  - the rollout converges back to a single “primary” release on the new version

### Blue-green

**Goal**: deploy “green” alongside “blue”, validate, then instantly switch traffic on approval.

Start:

```json
{
  "env": "prod",
  "artifact_version": "v2.0.0",
  "api_serve_deployment_config": {
    "deployment_strategy": "blue-green",
    "deployment_strategy_config": {}
  }
}
```

Progress:
- `POST /api/v1/deployment/{deployment_id}/approve`
- On approval:
  - Service selector switches to **green**
  - **old blue is scaled down immediately**
  - system converges back to a single primary release on the new version

### Enhanced rolling (approval checkpoints)

**Goal**: do a controlled rollout with approval checkpoints (e.g. 50% then 100%).

Start:

```json
{
  "env": "prod",
  "artifact_version": "v2.0.0",
  "api_serve_deployment_config": {
    "deployment_strategy": "rolling",
    "deployment_strategy_config": { "checkpoints": [50, 100] }
  }
}
```

Progress:
- `POST /api/v1/deployment/{deployment_id}/approve` at each checkpoint
- Final approval converges back to a single primary release on the new version

### Reject / rollback

- **Reject** (rollback + mark deployment rejected):

`POST /api/v1/deployment/{deployment_id}/reject`

```json
{ "rejection_reason": "High error rate observed", "notes": "Rollback requested" }
```

- **Rollback** (currently an alias of reject behavior):

`POST /api/v1/deployment/{deployment_id}/rollback`

```json
{ "notes": "Rollback requested" }
```

### Status / history

`GET /api/v1/deployment/{deployment_id}/status` returns:
- current `phase`
- `requires_approval`
- phase approval history (who approved/rejected and notes)

