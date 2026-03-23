#!/usr/bin/env sh
set -e

echo "Starting chronos-consumer..."
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
    exec python -m src.start_consumer
    ;;
  *)
    nohup python -m src.start_consumer > /opt/logs/chronos-consumer.log 2>&1 &
    echo $! > "${ODIN_APP_DIR}/.app.pid"
    ;;
esac
