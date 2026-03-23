#!/usr/bin/env sh
set -e

echo "Running post-deploy..."
echo "ODIN_APP_DIR: ${ODIN_APP_DIR}"
echo "ODIN_DEPLOYMENT_TYPE: ${ODIN_DEPLOYMENT_TYPE}"

# Add post-deployment tasks here (e.g., smoke tests, seed data)

echo "Post-deploy completed successfully"
