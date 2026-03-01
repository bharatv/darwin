# darwin-cluster-manager

Cluster Manager Component of the Compute Service in ML-Platform. 

## APIs

### Update Kubernetes Service selector

This endpoint patches a live Kubernetes `Service.spec.selector` for a Helm-managed release. It is used by **ml-serve-app**
deployment strategies (canary / blue-green / rolling) to shift traffic without a service mesh.

- **Route**: `POST /resource-instance/update-service`
- **Body**:

```json
{
  "resource_id": "prod-my-serve",
  "kube_cluster": "kind",
  "kube_namespace": "serve",
  "service_selector": {
    "serve.darwin.io/name": "my-serve",
    "deploy.darwin.io/role": "canary"
  }
}
```

- **Success response** (shape):

```json
{
  "status": "SUCCESS",
  "message": "Service selector updated",
  "data": {
    "resource_id": "prod-my-serve",
    "service_name": "prod-my-serve",
    "before_selector": { "app.kubernetes.io/name": "prod-my-serve" },
    "after_selector": { "serve.darwin.io/name": "my-serve", "deploy.darwin.io/role": "canary" },
    "idempotent": false
  }
}
```

**Notes**
- The update is **idempotent**: if the selector already matches the requested selector, the API returns `SUCCESS` with `idempotent: true`.
- `resource_id` is expected to be the **Service name** (for `darwin-fastapi-serve`, this is the Helm release name).

## APIs

### Update Kubernetes Service selector

This endpoint patches a live Kubernetes `Service.spec.selector` for a Helm-managed release. It is used by **ml-serve-app**
deployment strategies (canary / blue-green / rolling) to shift traffic without a service mesh.

- **Route**: `POST /resource-instance/update-service`
- **Body**:

```json
{
  "resource_id": "prod-my-serve",
  "kube_cluster": "kind",
  "kube_namespace": "serve",
  "service_selector": {
    "serve.darwin.io/name": "my-serve",
    "deploy.darwin.io/role": "canary"
  }
}
```

- **Success response** (shape):

```json
{
  "status": "SUCCESS",
  "message": "Service selector updated",
  "data": {
    "resource_id": "prod-my-serve",
    "service_name": "prod-my-serve",
    "before_selector": { "app.kubernetes.io/name": "prod-my-serve" },
    "after_selector": { "serve.darwin.io/name": "my-serve", "deploy.darwin.io/role": "canary" },
    "idempotent": false
  }
}
```

**Notes**
- The update is **idempotent**: if the selector already matches the requested selector, the API returns `SUCCESS` with `idempotent: true`.
- `resource_id` is expected to be the **Service name** (for `darwin-fastapi-serve`, this is the Helm release name).
