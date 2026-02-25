#!/bin/bash
# Configure metrics for Flagger canary analysis
# This script sets up MetricTemplates for standard HTTP metrics

set -e

echo "=== Configuring Metrics for Flagger ==="

# Check kubectl connection
if ! kubectl cluster-info &> /dev/null; then
    echo "Error: kubectl not connected to a cluster"
    exit 1
fi

# Create monitoring namespace if it doesn't exist
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

echo "Creating standard MetricTemplates for HTTP services..."

# Create request-success-rate MetricTemplate
cat <<EOF | kubectl apply -f -
apiVersion: flagger.app/v1beta1
kind: MetricTemplate
metadata:
  name: request-success-rate
  namespace: monitoring
spec:
  provider:
    type: prometheus
    address: http://prometheus.monitoring:9090
  query: |
    sum(
      rate(
        istio_requests_total{
          reporter="source",
          destination_workload_namespace="{{ namespace }}",
          destination_workload=~"{{ target }}.*",
          response_code!~"5.*"
        }[{{ interval }}]
      )
    )
    /
    sum(
      rate(
        istio_requests_total{
          reporter="source",
          destination_workload_namespace="{{ namespace }}",
          destination_workload=~"{{ target }}.*"
        }[{{ interval }}]
      )
    )
    * 100
EOF

# Create request-duration MetricTemplate
cat <<EOF | kubectl apply -f -
apiVersion: flagger.app/v1beta1
kind: MetricTemplate
metadata:
  name: request-duration
  namespace: monitoring
spec:
  provider:
    type: prometheus
    address: http://prometheus.monitoring:9090
  query: |
    histogram_quantile(
      0.99,
      sum(
        rate(
          istio_request_duration_milliseconds_bucket{
            reporter="source",
            destination_workload_namespace="{{ namespace }}",
            destination_workload=~"{{ target }}.*"
          }[{{ interval }}]
        )
      ) by (le)
    )
EOF

# Create error-rate MetricTemplate
cat <<EOF | kubectl apply -f -
apiVersion: flagger.app/v1beta1
kind: MetricTemplate
metadata:
  name: error-rate
  namespace: monitoring
spec:
  provider:
    type: prometheus
    address: http://prometheus.monitoring:9090
  query: |
    sum(
      rate(
        istio_requests_total{
          reporter="source",
          destination_workload_namespace="{{ namespace }}",
          destination_workload=~"{{ target }}.*",
          response_code=~"5.*"
        }[{{ interval }}]
      )
    )
    /
    sum(
      rate(
        istio_requests_total{
          reporter="source",
          destination_workload_namespace="{{ namespace }}",
          destination_workload=~"{{ target }}.*"
        }[{{ interval }}]
      )
    )
    * 100
EOF

echo "✅ MetricTemplates configured successfully!"
echo ""
echo "Available metrics for canary analysis:"
echo "  - request-success-rate (target: >99%)"
echo "  - request-duration (target: <500ms)"
echo "  - error-rate (target: <1%)"
echo ""
echo "Example canary metrics configuration:"
echo "  metrics:"
echo "  - name: request-success-rate"
echo "    templateRef:"
echo "      name: request-success-rate"
echo "      namespace: monitoring"
echo "    thresholdRange:"
echo "      min: 99"
echo "    interval: 1m"
