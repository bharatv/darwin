#!/usr/bin/env sh
set -e

echo "Running pre-deploy..."
echo "ODIN_APP_DIR: ${ODIN_APP_DIR}"
echo "ODIN_DEPLOYMENT_TYPE: ${ODIN_DEPLOYMENT_TYPE}"

# Add pre-deployment tasks here (e.g., database migrations)

echo "Pre-deploy completed successfully"
