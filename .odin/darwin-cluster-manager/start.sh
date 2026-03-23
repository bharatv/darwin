#!/usr/bin/env sh
set -e

echo "Starting darwin-cluster-manager..."
echo "ODIN_APP_DIR: ${ODIN_APP_DIR}"
echo "ODIN_DEPLOYMENT_TYPE: ${ODIN_DEPLOYMENT_TYPE}"
echo "ODIN_SERVICE_NAME: ${ODIN_SERVICE_NAME}"

cd "${ODIN_APP_DIR}" || exit

# ── Go runtime defaults ─────────────────────────────────────────────
NPROC=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 0)
if [ "${NPROC}" -gt 0 ] 2>/dev/null; then
  export GOMAXPROCS="${GOMAXPROCS:-${NPROC}}"
fi

# GOMEMLIMIT: 80% of available memory (Go 1.19+)
if [ -f /sys/fs/cgroup/memory.max ]; then
  TOTAL_MEM=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || true)
elif [ -f /sys/fs/cgroup/memory/memory.limit_in_bytes ]; then
  TOTAL_MEM=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || true)
else
  TOTAL_MEM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || true)
  if [ -n "${TOTAL_MEM_KB}" ]; then
    TOTAL_MEM=$(( TOTAL_MEM_KB * 1024 ))
  fi
fi

if [ -n "${TOTAL_MEM}" ] && [ "${TOTAL_MEM}" -gt 0 ] 2>/dev/null; then
  GOMEMLIMIT_BYTES=$(( TOTAL_MEM * 80 / 100 ))
  export GOMEMLIMIT="${GOMEMLIMIT:-${GOMEMLIMIT_BYTES}}"
fi

BINARY="${ODIN_APP_DIR}/${ODIN_SERVICE_NAME}"

# ── Launch ───────────────────────────────────────────────────────────
case "${ODIN_DEPLOYMENT_TYPE}" in
  *container*|*k8s*)
    exec "${BINARY}"
    ;;
  *)
    nohup "${BINARY}" > /opt/logs/darwin-cluster-manager.log 2>&1 &
    echo $! > "${ODIN_APP_DIR}/.app.pid"
    ;;
esac
