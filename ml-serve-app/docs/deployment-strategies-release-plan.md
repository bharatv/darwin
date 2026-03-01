## Deployment plan (recommended order)

To roll out deployment strategies safely:

1. **Database migration first**
   - Apply DB migrations that add/extend `app_layer_deployments`, `deployment_phases`, and `active_deployments.candidate_deployment_id`.
2. **Helm chart update**
   - Deploy updated `darwin-fastapi-serve` chart that supports:
     - optional pod labels (`serve.darwin.io/name`, `deploy.darwin.io/*`)
     - optional `service.selector` override
3. **DCM update**
   - Deploy DCM with `POST /resource-instance/update-service` support.
4. **ml-serve-app update**
   - Deploy the new orchestrator + strategy logic.
5. **Staging validation**
   - Run canary and blue-green rollouts end-to-end.

## Rollback plan

### If ml-serve-app deploy fails

- Roll back ml-serve-app deployment; DB schema changes are backward compatible (nullable fields).
- Avoid rolling back DB unless required.

### If DCM deploy fails

- Roll back DCM; ml-serve-app strategy rollouts may fail to shift traffic (approval progression may error).
- Continue using legacy deploy (no strategy) until DCM is restored.

### If Helm chart deploy fails

- Roll back chart; strategy rollouts that rely on `service.selector` and pod labels will fail.
- Legacy deploy should still work if Service template remains compatible.

### Operational rollback of an in-progress deployment

Preferred:
- `POST /api/v1/deployment/{deployment_id}/reject` with a reason

Last resort (manual):
- Patch Service selector back to primary-only
- Scale primary up, scale candidate down
- Stop candidate Helm release

