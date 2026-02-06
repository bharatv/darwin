# Darwin Ray Operator

A Kubernetes operator that manages `DarwinRayCluster` custom resources, providing a production-ready wrapper around the KubeRay operator's `RayCluster` CRD.

## Overview

The Darwin Ray Operator is part of the compute layer re-architecture that:

1. **Introduces DarwinRayCluster CRD** - A wrapper over `RayCluster` with Darwin-specific features
2. **Provides real-time status updates** - Uses K8s watches instead of polling
3. **Manages cluster lifecycle** - Handles create, update, delete, suspend/resume operations
4. **Implements state machine** - Tracks cluster phases (Creating → HeadNodeUp → JupyterUp → Active)

## Architecture

```
                    ┌──────────────────────────────┐
                    │  darwin-compute (centralized)│
                    │        (FastAPI API)         │
                    └──────────┬───────────────────┘
                               │ Creates DarwinRayCluster CRs
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
      ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
      │ K8s Cluster A  │ │ K8s Cluster B  │ │ K8s Cluster C  │
      │                │ │                │ │                │
      │ ┌────────────┐ │ │ ┌────────────┐ │ │ ┌────────────┐ │
      │ │ darwin-ray-│ │ │ │ darwin-ray-│ │ │ │ darwin-ray-│ │
      │ │ operator   │ │ │ │ operator   │ │ │ │ operator   │ │
      │ └──────┬─────┘ │ │ └──────┬─────┘ │ │ └──────┬─────┘ │
      │        │       │ │        │       │ │        │       │
      │ ┌──────▼─────┐ │ │ ┌──────▼─────┐ │ │ ┌──────▼─────┐ │
      │ │ KubeRay    │ │ │ │ KubeRay    │ │ │ │ KubeRay    │ │
      │ │ Operator   │ │ │ │ Operator   │ │ │ │ Operator   │ │
      │ └────────────┘ │ │ └────────────┘ │ │ └────────────┘ │
      └────────────────┘ └────────────────┘ └────────────────┘
```

## Installation

### Prerequisites

- Kubernetes 1.26+
- KubeRay Operator v1.1.0+ installed
- Helm 3.x

### Deploy via Helm

```bash
# Add the CRD
kubectl apply -f config/crd/bases/compute.darwin.io_darwinrayclusters.yaml

# Install the operator
helm install darwin-ray-operator ./helm/darwin-ray-operator \
  --namespace darwin-system \
  --create-namespace \
  --set rayNamespace=ray
```

### Build from Source

```bash
# Generate code
make generate

# Build
make build

# Build Docker image
make docker-build IMG=darwin-ray-operator:latest

# Push Docker image
make docker-push IMG=darwin-ray-operator:latest
```

## DarwinRayCluster CRD

### Example

```yaml
apiVersion: compute.darwin.io/v1alpha1
kind: DarwinRayCluster
metadata:
  name: my-cluster
  namespace: ray
spec:
  name: My ML Cluster
  user: john@example.com
  runtime: "2.37.0"
  cloudEnv: prod
  labels:
    team: ml-platform
    project: fraud-detection
  tags:
    - training
    - gpu
  headNode:
    resources:
      cpu: "4"
      memoryGB: 16
    enableJupyter: true
  workerGroups:
    - name: default
      replicas: 2
      resources:
        cpu: "8"
        memoryGB: 32
  autoTermination:
    enabled: true
    idleTimeoutMinutes: 60
```

### Status

The operator maintains status in real-time:

```yaml
status:
  phase: Active
  activePods: 3
  availableMemoryGB: 80
  headPodIP: 10.0.1.5
  jupyterURL: http://10.0.1.5:8888
  rayDashboardURL: http://10.0.1.5:8265
  readyWorkers: 2
  desiredWorkers: 2
  conditions:
    - type: Ready
      status: "True"
      reason: Ready
      message: Cluster is ready
```

### Phases

| Phase | Description |
|-------|-------------|
| Inactive | Cluster is not running |
| Creating | Cluster resources being created |
| HeadNodeUp | Head node is running |
| JupyterUp | Jupyter is accessible |
| Active | All workers ready |
| Failed | Cluster has failed |
| Terminating | Cluster being deleted |

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `RAY_NAMESPACE` | Namespace where Ray clusters are created | `ray` |
| `LEADER_ELECTION` | Enable leader election for HA | `true` |
| `METRICS_PORT` | Metrics server port | `8080` |
| `HEALTH_PORT` | Health check port | `8081` |

### Helm Values

See `helm/darwin-ray-operator/values.yaml` for all configuration options.

## Operations

### Start/Stop a Cluster

```bash
# Stop (suspend)
kubectl patch drc my-cluster --type=merge -p '{"spec":{"suspend":true}}'

# Start (resume)
kubectl patch drc my-cluster --type=merge -p '{"spec":{"suspend":false}}'
```

### Scale Workers

```bash
kubectl patch drc my-cluster --type=merge -p '{"spec":{"workerGroups":[{"name":"default","replicas":4}]}}'
```

### View Status

```bash
kubectl get drc my-cluster -o yaml

# Or use short output
kubectl get drc
NAME         PHASE    USER              RUNTIME   PODS   AGE
my-cluster   Active   john@example.com  2.37.0    3      1h
```

## Development

### Run Locally

```bash
# Run against current kubeconfig
make run

# With specific namespace
go run main.go --ray-namespace=ray-dev
```

### Run Tests

```bash
make test
```

### Generate CRD Manifests

```bash
make manifests
```

## Migration from DCM

This operator replaces darwin-cluster-manager for cluster lifecycle management:

| DCM Function | Operator Equivalent |
|--------------|---------------------|
| Create cluster | Create DarwinRayCluster CR |
| Start cluster | Set `suspend: false` |
| Stop cluster | Set `suspend: true` |
| Delete cluster | Delete DarwinRayCluster CR |
| Get status | Read CR status |

See `darwin-compute/core/src/compute_core/service/cluster_manager.py` for the migration adapter.

## License

Apache 2.0
