#!/usr/bin/env sh
set -e

echo "Starting darwin-workflow-app_layer..."
echo "ODIN_APP_DIR: ${ODIN_APP_DIR}"
echo "ODIN_DEPLOYMENT_TYPE: ${ODIN_DEPLOYMENT_TYPE}"
echo "ODIN_SERVICE_NAME: ${ODIN_SERVICE_NAME}"

cd "${ODIN_APP_DIR}" || exit

# ── Python runtime defaults ──────────────────────────────────────────
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# ── Launch ───────────────────────────────────────────────────────────
case "${ODIN_DEPLOYMENT_TYPE}" in
  *container*|*k8s*)
    exec uvicorn workflow_app_layer.main:app --host 0.0.0.0 --port 8080
    ;;
  *)
    nohup uvicorn workflow_app_layer.main:app --host 0.0.0.0 --port 8080 > /opt/logs/darwin-workflow-app_layer.log 2>&1 &
    echo $! > "${ODIN_APP_DIR}/.app.pid"
    ;;
esac
