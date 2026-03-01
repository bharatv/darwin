## Operator runbook: deployment strategies

This runbook helps operators troubleshoot deployment-strategy rollouts (canary / blue-green / enhanced rolling).

### Quick triage checklist

- **Is a deployment awaiting approval?**
  - Check `GET /api/v1/deployment/{deployment_id}/status`
  - Look at `phase` and `requires_approval`
- **Is there a concurrent deployment block?**
  - ML Serve rejects concurrent rollouts for the same serve+env.
- **Is traffic routing correct?**
  - Verify the Kubernetes Service selector for the primary Service (Helm release name).
- **Are old/new pods present as expected?**
  - Confirm Deployments/Pods exist for primary and candidate roles (canary/green/rolling).

### Common issues

#### Deployment stuck in “awaiting approval”

**Symptom**: `requires_approval=true` and phase does not change.

**Action**:
- Approve: `POST /api/v1/deployment/{deployment_id}/approve`
- If validation fails, reject: `POST /api/v1/deployment/{deployment_id}/reject`

#### Approval fails with 409 / 400

**Likely causes**:
- Deployment is already terminal (`completed`, `failed`, `rejected`)
- Deployment does not require approval at the moment
- Deployment already ended

**Action**:
- Check status endpoint for terminal state
- Create a new deployment if you need to revert a completed rollout

#### Traffic not shifting after approval

**Likely causes**:
- Service selector patch didn’t apply (DCM error)
- Candidate pods missing expected role/version labels
- Candidate deployment scaled to 0 or not running

**Action**:
- Inspect Service selector:
  - `kubectl get svc <service-name> -n <ns> -o yaml | yq '.spec.selector'`
- Inspect pods + labels:
  - `kubectl get pods -n <ns> -l serve.darwin.io/name=<serve-name> --show-labels`
- Check DCM logs for the update-service call.

#### Rollback needed during rollout

**Action**:
- Use reject (records reason + rollback):
  - `POST /api/v1/deployment/{deployment_id}/reject`
- This should:
  - restore Service selector to primary-only
  - stop the candidate release (canary/green/rolling)
  - clear the ActiveDeployment candidate pointer

### Manual intervention (last resort)

If DB state and Kubernetes state diverge (e.g. manual kubectl edits), prefer bringing Kubernetes back to a safe routing:

1. Route Service to primary-only:
   - set selector to `{"serve.darwin.io/name": "<serve-name>", "deploy.darwin.io/role": "primary"}`
2. Ensure primary replicas are > 0
3. Stop candidate release if it is consuming resources unexpectedly

After manual intervention, create a new deployment rather than trying to “resume” a corrupted state.

