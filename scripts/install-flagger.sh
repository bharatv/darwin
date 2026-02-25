#!/bin/bash
# Install Flagger for progressive delivery
# This script installs Flagger controller to enable canary and blue-green deployments

set -e

echo "=== Installing Flagger for Darwin Platform ==="

# Check if helm is installed
if ! command -v helm &> /dev/null; then
    echo "Error: helm not found. Please install it first."
    exit 1
fi

# Check kubectl connection
if ! kubectl cluster-info &> /dev/null; then
    echo "Error: kubectl not connected to a cluster"
    exit 1
fi

# Get cluster context
CONTEXT=$(kubectl config current-context)
echo "Installing Flagger on cluster: $CONTEXT"

# Add Flagger Helm repository
echo "Adding Flagger Helm repository..."
helm repo add flagger https://flagger.app
helm repo update

# Install Flagger with Istio provider
echo "Installing Flagger controller..."
helm upgrade --install flagger flagger/flagger \
    --namespace flagger-system \
    --create-namespace \
    --set meshProvider=istio \
    --set metricsServer=http://prometheus.monitoring:9090 \
    --wait

# Wait for Flagger to be ready
echo "Waiting for Flagger pods to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=flagger -n flagger-system --timeout=300s

# Install Flagger's Grafana dashboard (optional)
echo "Installing Flagger Grafana dashboard..."
helm upgrade --install flagger-grafana flagger/grafana \
    --namespace flagger-system \
    --set url=http://prometheus.monitoring:9090 \
    --wait || echo "Warning: Grafana dashboard installation failed (optional)"

echo "✅ Flagger installation complete!"
echo ""
echo "Flagger is now monitoring Canary resources in the cluster."
echo ""
echo "Next steps:"
echo "  1. Configure metrics: ./scripts/configure-metrics.sh"
echo "  2. Update Environment records in database to set flagger_enabled=true"
echo "  3. Deploy a serve with canary or blue-green strategy to test"
