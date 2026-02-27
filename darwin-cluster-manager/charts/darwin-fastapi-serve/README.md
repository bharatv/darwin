# darwin-fastapi-serve

Helm chart for deploying ML serving API workloads (FastAPI-based) with flexible deployment strategies.

## Features

- **Multiple deployment strategies**: Rolling updates, Recreate, Canary (progressive delivery), Blue/Green
- **Progressive delivery via Argo Rollouts**: Optional canary and blue/green deployments with ALB or NGINX traffic routing
- **Model caching**: Support for emptydir (per-pod) and PVC (shared) model caching strategies
- **Auto-scaling**: HPA support for both Kubernetes Deployments and Argo Rollouts
- **Observability**: Prometheus ServiceMonitor, PodDisruptionBudget

## Installing the Chart

Basic installation (default: Kubernetes Deployment with RollingUpdate):

```console
helm upgrade --install my-ml-serve ./darwin-fastapi-serve \
  --set name=my-ml-serve \
  --set image.repository=my-registry/ml-serve \
  --set image.tag=v1.0.0
```

## Deployment Strategies

### Kubernetes Mode (Default)

Standard Kubernetes Deployment with configurable rolling updates or recreate strategy.

**Example: Rolling Update (default)**
```yaml
deployment:
  strategy: kubernetes  # default
  kubernetes:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 10%
      maxUnavailable: 1
    progressDeadlineSeconds: 600
```

**Example: Recreate**
```yaml
deployment:
  strategy: kubernetes
  kubernetes:
    type: Recreate
```

### Progressive Delivery Mode (Argo Rollouts)

Requires [Argo Rollouts](https://argoproj.github.io/argo-rollouts/) controller installed in the cluster.

**Example: Canary with ALB**
```yaml
deployment:
  strategy: argo-rollouts
  rollouts:
    strategy: canary
    trafficRouting:
      provider: alb
      servicePort: 80
    canary:
      steps:
        - setWeight: 20
        - pause: {duration: 1m}
        - setWeight: 50
        - pause: {duration: 2m}
        - setWeight: 80
        - pause: {duration: 1m}
```

**Example: Canary with NGINX**
```yaml
deployment:
  strategy: argo-rollouts
  rollouts:
    strategy: canary
    trafficRouting:
      provider: nginx
      servicePort: 80
    canary:
      steps:
        - setWeight: 25
        - pause: {duration: 30s}
        - setWeight: 75
        - pause: {duration: 30s}
```

**Example: Blue/Green**
```yaml
deployment:
  strategy: argo-rollouts
  rollouts:
    strategy: blueGreen
    blueGreen:
      autoPromotionEnabled: false  # manual promotion
      previewIngress:
        enabled: true
```

## Configuration

Key parameters:

Parameter | Default | Description
--- | --- | ---
`deployment.strategy` | `kubernetes` | Deployment mode: `kubernetes` or `argo-rollouts`
`deployment.kubernetes.type` | `RollingUpdate` | K8s strategy: `RollingUpdate` or `Recreate`
`deployment.kubernetes.rollingUpdate.maxSurge` | `10%` | Max surge pods during rolling update
`deployment.kubernetes.rollingUpdate.maxUnavailable` | `1` | Max unavailable pods during rolling update
`deployment.rollouts.strategy` | `canary` | Rollouts strategy: `canary` or `blueGreen`
`deployment.rollouts.trafficRouting.provider` | `alb` | Traffic router: `alb` or `nginx`
`replicaCount` | `1` | Desired number of pods
`image.repository` | `localhost:5000/darwin` | Image repository
`image.tag` | `ml_serve_demo` | Image tag
`service.httpPort` | `8000` | Container HTTP port
`hpa.enabled` | `true` | Enable Horizontal Pod Autoscaler
`hpa.maxReplicas` | `3` | Maximum number of replicas
`ingressInt.enabled` | `true` | Enable internal ingress
`ingressInt.ingressClass` | `alb` | Ingress class (e.g., `alb`, `nginx`)
`modelCache.enabled` | `false` | Enable model caching
`modelCache.strategy` | `emptydir` | Model cache strategy: `emptydir` or `pvc`

See [values.yaml](values.yaml) for full configuration options.

## Cluster Prerequisites

### For Progressive Delivery (Argo Rollouts)

1. **Install Argo Rollouts controller and CRDs**:
   ```console
   kubectl create namespace argo-rollouts
   kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml
   ```

2. **For ALB traffic routing**:
   - **AWS Load Balancer Controller** must be installed and configured (v2.4.0 or later recommended)
   - **Ingress class**: Ensure your cluster has the `alb` ingress class configured
   - **Recommended**: Enable AWS target-group verification in Argo Rollouts controller by adding the `--aws-verify-target-group` flag to the controller deployment. This ensures target groups are fully registered before shifting traffic.
   - **IAM Permissions**: Argo Rollouts controller needs AWS IAM permissions to describe ALB resources:
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Effect": "Allow",
           "Action": [
             "elasticloadbalancing:DescribeTargetGroups",
             "elasticloadbalancing:DescribeLoadBalancers",
             "elasticloadbalancing:DescribeTargetHealth"
           ],
           "Resource": "*"
         }
       ]
     }
     ```
   - **Readiness gates** (for IP mode): Ensure AWS Load Balancer Controller is configured with readiness gate injection to prevent 502/503 errors during rollouts

3. **For NGINX traffic routing**:
   - **NGINX Ingress Controller** must be installed (v1.0.0 or later)
   - Argo Rollouts will automatically manage canary weights via NGINX ingress annotations

## Deprecation Notice

⚠️ **Flagger progressive delivery is deprecated** and not recommended for use with this chart. The existing `flagger.*` values are Istio-oriented and do not align with the chart's Ingress-based routing model.

**Migration**: If you previously used `flagger.enabled: true`, migrate to `deployment.strategy: argo-rollouts` for ALB/NGINX progressive delivery.

### Migration Steps from Flagger to Argo Rollouts

If you're currently using the deprecated Flagger integration (`flagger.enabled: true`), follow these steps to migrate to Argo Rollouts:

1. **Install Argo Rollouts** in your cluster (see [Cluster Prerequisites](#cluster-prerequisites))

2. **Update your values file**:
   ```yaml
   # OLD (deprecated):
   flagger:
     enabled: true
     maxWeight: 50
     stepWeight: 10
     interval: 1m
   
   # NEW (recommended):
   deployment:
     strategy: argo-rollouts
     rollouts:
       strategy: canary
       trafficRouting:
         provider: alb  # or nginx
         servicePort: 80
       canary:
         steps:
           - setWeight: 10
           - pause: {duration: 1m}
           - setWeight: 20
           - pause: {duration: 1m}
           - setWeight: 50
           - pause: {duration: 2m}
   ```

3. **Deploy the updated chart**:
   ```console
   helm upgrade my-ml-serve ./darwin-fastapi-serve -f my-values.yaml
   ```

4. **Verify the Rollout**:
   ```console
   kubectl argo rollouts status my-ml-serve -n <namespace>
   ```

**Note**: The migration requires a brief service restart. Plan accordingly and test in a staging environment first.

## Upgrading the Chart

When switching between deployment strategies (`kubernetes` ↔ `argo-rollouts`), a standard Helm upgrade will converge the resources appropriately. No manual cleanup is required.

## Release Playbook

### Progressive Delivery Operations

This section covers common operational tasks when using Argo Rollouts for progressive delivery.

#### Observing Rollout Progress

**Watch rollout status:**
```console
kubectl argo rollouts status <rollout-name> -n <namespace> --watch
```

**Get detailed rollout info:**
```console
kubectl argo rollouts get rollout <rollout-name> -n <namespace>
```

**View rollout history:**
```console
kubectl argo rollouts history <rollout-name> -n <namespace>
```

#### Promoting a Rollout (Canary/Blue-Green)

For manual canary promotions or blue/green promotions:

```console
# Promote to next step (canary)
kubectl argo rollouts promote <rollout-name> -n <namespace>

# Skip all remaining steps and promote fully
kubectl argo rollouts promote <rollout-name> -n <namespace> --full
```

#### Aborting a Rollout

If issues are detected during a rollout:

```console
kubectl argo rollouts abort <rollout-name> -n <namespace>
```

This immediately reverts traffic to the stable version and scales down the canary/preview.

#### Rollback to Previous Version

**Using Helm (recommended):**
```console
# Rollback to previous release
helm rollback <release-name> -n <namespace>

# Rollback to specific revision
helm rollback <release-name> <revision> -n <namespace>
```

**Using Argo Rollouts:**
```console
# Undo to previous revision
kubectl argo rollouts undo <rollout-name> -n <namespace>

# Undo to specific revision
kubectl argo rollouts undo <rollout-name> --to-revision=<revision> -n <namespace>
```

#### Restarting a Rollout

Force a new rollout (e.g., after config changes):

```console
kubectl argo rollouts restart <rollout-name> -n <namespace>
```

#### Pausing/Resuming Auto-Promotion

**Pause a rollout** (useful for extended manual testing):
```console
kubectl argo rollouts pause <rollout-name> -n <namespace>
```

**Resume a paused rollout**:
```console
kubectl argo rollouts resume <rollout-name> -n <namespace>
```

## Troubleshooting

### Progressive Delivery Issues

#### 502/503 Errors During Canary Promotion (ALB)

**Symptoms**: Intermittent 502 or 503 errors when traffic shifts to canary pods or during promotion.

**Causes & Solutions**:

1. **Target registration delays**:
   - **Cause**: ALB takes time to register new target IPs and mark them healthy
   - **Solution**: Enable AWS Load Balancer Controller readiness gates by setting `alb.ingress.kubernetes.io/target-type: ip` and ensuring the controller has readiness gate injection enabled
   - **Verification**: Check pod conditions - pods should have `target-health.alb.ingress.k8s.aws/...` condition

2. **Deregistration delay too short**:
   - **Cause**: Pods are terminated before ALB finishes draining connections
   - **Solution**: Increase deregistration delay (default: 120s is usually sufficient):
     ```yaml
     ingressInt:
       annotations:
         alb.ingress.kubernetes.io/target-group-attributes: deregistration_delay.timeout_seconds=120
     ```
   - Also ensure `terminationGracePeriodSeconds: 30` (or higher) in pod spec

3. **Target group verification disabled**:
   - **Cause**: Argo Rollouts shifts traffic before targets are fully healthy
   - **Solution**: Enable AWS target-group verification in Argo Rollouts controller by adding `--aws-verify-target-group` flag to the deployment

#### Canary Pods Not Receiving Traffic

**Symptoms**: Canary weight shows as set in Rollout status, but no traffic reaches canary pods.

**Diagnosis**:

1. **Verify Ingress backend service**:
   ```console
   kubectl get ingress <ingress-name> -n <namespace> -o yaml
   ```
   - For ALB canary: backend service name should be the **root** service
   - Backend port name must be `use-annotation` for ALB

2. **Check Ingress annotations**:
   ```console
   kubectl get ingress <ingress-name> -n <namespace> -o jsonpath='{.metadata.annotations}'
   ```
   - Look for `alb.ingress.kubernetes.io/actions.<service-name>` annotation with forward config showing weighted target groups

3. **Validate Rollout status**:
   ```console
   kubectl argo rollouts status <rollout-name> -n <namespace>
   kubectl argo rollouts get rollout <rollout-name> -n <namespace>
   ```
   - Check that canary ReplicaSet has ready pods
   - Verify traffic routing status shows correct weights

4. **Inspect Service selectors**:
   ```console
   kubectl get svc <stable-service> <canary-service> -n <namespace> -o wide
   ```
   - Ensure selectors match pod labels (Argo Rollouts manages this automatically)

#### HPA Not Scaling

**Symptoms**: HPA shows "unknown" metrics or doesn't scale the Rollout.

**Solutions**:

1. **Verify scaleTargetRef**:
   ```console
   kubectl get hpa <hpa-name> -n <namespace> -o yaml
   ```
   - For `deployment.strategy: argo-rollouts`, `scaleTargetRef.kind` must be `Rollout` (not `Deployment`)
   - This is handled automatically by the chart

2. **Check metrics-server**:
   ```console
   kubectl top pods -n <namespace>
   ```
   - If metrics aren't available, ensure metrics-server is running in the cluster

3. **Review HPA status**:
   ```console
   kubectl describe hpa <hpa-name> -n <namespace>
   ```
   - Look for errors in conditions or events

#### Rollout Stuck in Progressing State

**Symptoms**: Rollout doesn't progress through canary steps or promotion hangs.

**Diagnosis**:

1. **Check Rollout conditions**:
   ```console
   kubectl describe rollout <rollout-name> -n <namespace>
   ```
   - Look for error messages or failed health checks

2. **Review canary pod readiness**:
   ```console
   kubectl get pods -l app.kubernetes.io/name=<rollout-name> -n <namespace>
   ```
   - Ensure canary pods are Ready and passing health checks

3. **Inspect analysis runs** (if configured):
   ```console
   kubectl get analysisrun -n <namespace>
   kubectl describe analysisrun <run-name> -n <namespace>
   ```
   - Analysis failures will block promotion

4. **Manual intervention**:
   - If rollout is paused: `kubectl argo rollouts resume <rollout-name>`
   - If genuinely stuck: `kubectl argo rollouts abort <rollout-name>` and investigate

#### Readiness Gates Not Working

**Symptoms**: Pods become Ready before ALB target health checks pass, causing 502s.

**Solutions**:

1. **Verify AWS Load Balancer Controller configuration**:
   - Ensure controller has `--enable-pod-readiness-gate-inject=true` (default: true)
   - Check controller is watching the correct ingress class

2. **Check pod readiness gate injection**:
   ```console
   kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.readinessGates}'
   ```
   - Should show `target-health.alb.ingress.k8s.aws/<target-group-name>`

3. **Review target group health**:
   ```console
   aws elbv2 describe-target-health --target-group-arn <arn>
   ```

**Canary pods not receiving traffic**:
- Verify Ingress backend service name is set to the "root" service (for ALB) or stable service
- Check that Ingress port name is `use-annotation` (required for ALB action-based routing)
- Validate Rollout status: `kubectl argo rollouts status <rollout-name>`

**HPA not scaling**:
- Verify HPA `scaleTargetRef` points to the correct resource kind (`Deployment` for kubernetes mode, `Rollout` for argo-rollouts mode)
