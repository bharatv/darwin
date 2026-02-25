#!/bin/bash
# Install Istio service mesh for Darwin platform
# This script installs Istio in the Kubernetes cluster to enable advanced deployment strategies

set -e

echo "=== Installing Istio for Darwin Platform ==="

# Check if istioctl is installed
if ! command -v istioctl &> /dev/null; then
    echo "Error: istioctl not found. Please install it first:"
    echo "  curl -L https://istio.io/downloadIstio | sh -"
    echo "  export PATH=\$PATH:\$HOME/.istioctl/bin"
    exit 1
fi

# Check kubectl connection
if ! kubectl cluster-info &> /dev/null; then
    echo "Error: kubectl not connected to a cluster"
    exit 1
fi

# Get cluster context
CONTEXT=$(kubectl config current-context)
echo "Installing Istio on cluster: $CONTEXT"

# Install Istio with default profile
echo "Installing Istio operator..."
istioctl install --set profile=default -y

# Wait for Istio to be ready
echo "Waiting for Istio pods to be ready..."
kubectl wait --for=condition=ready pod -l app=istiod -n istio-system --timeout=300s
kubectl wait --for=condition=ready pod -l app=istio-ingressgateway -n istio-system --timeout=300s

# Enable Istio injection for serve namespace
SERVE_NAMESPACE=${SERVE_NAMESPACE:-"serve"}
echo "Enabling Istio sidecar injection for namespace: $SERVE_NAMESPACE"

# Create namespace if it doesn't exist
kubectl create namespace $SERVE_NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Label namespace for injection
kubectl label namespace $SERVE_NAMESPACE istio-injection=enabled --overwrite

echo "✅ Istio installation complete!"
echo ""
echo "Next steps:"
echo "  1. Install Flagger: ./scripts/install-flagger.sh"
echo "  2. Configure metrics: ./scripts/configure-metrics.sh"
echo "  3. Update Environment records in database to set istio_enabled=true"
