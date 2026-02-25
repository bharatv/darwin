# Istio Setup for Advanced Deployment Strategies

Blue-green and canary deployments require Istio for traffic management.

## Installation

**Darwin does not install Istio.** The platform team should install Istio cluster-wide.

- **Recommended:** Istio 1.20+ (latest stable)
- **Scope:** Cluster-wide (single control plane for all namespaces)

## Configuration

Set these environment variables for ml-serve-app:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_ISTIO` | `false` | Set to `true` to enable blue-green and canary |
| `ISTIO_SERVICE_NAME` | `istio-ingressgateway` | Istio ingress gateway service |
| `ISTIO_NAMESPACE` | `istio-system` | Istio control plane namespace |

## RBAC Requirements

ml-serve-app needs Kubernetes API access to manage Istio resources. Add to the ml-serve-app ServiceAccount:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: darwin-ml-serve-app-istio
rules:
  - apiGroups: ["networking.istio.io"]
    resources: ["virtualservices", "destinationrules"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["nodes", "pods"]
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
    namespace: <ml-serve-app-namespace>
```

## When ENABLE_ISTIO=false

- Rolling deployments work without Istio
- Blue-green and canary return 400 with "Istio is required"
