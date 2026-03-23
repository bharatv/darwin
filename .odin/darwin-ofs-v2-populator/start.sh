#!/usr/bin/env sh
set -e

echo "Starting darwin-ofs-v2-populator..."
echo "ODIN_APP_DIR: ${ODIN_APP_DIR}"
echo "ODIN_DEPLOYMENT_TYPE: ${ODIN_DEPLOYMENT_TYPE}"
echo "ODIN_SERVICE_NAME: ${ODIN_SERVICE_NAME}"
echo "ODIN_ARTIFACT_VERSION: ${ODIN_ARTIFACT_VERSION}"

cd "${ODIN_APP_DIR}" || exit

# ── Artifact resolution ──────────────────────────────────────────────

ARTIFACT="${ODIN_SERVICE_NAME}-${ODIN_ARTIFACT_VERSION}-fat.jar"


# ── JVM memory tuning (70% of available RAM for heap) ────────────────
if [ -f /sys/fs/cgroup/memory.max ]; then
  TOTAL_MEM_KB=$(awk '{printf "%.0f", $1/1024}' /sys/fs/cgroup/memory.max 2>/dev/null || true)
elif [ -f /sys/fs/cgroup/memory/memory.limit_in_bytes ]; then
  TOTAL_MEM_KB=$(awk '{printf "%.0f", $1/1024}' /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || true)
else
  TOTAL_MEM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || true)
fi

if [ -n "${TOTAL_MEM_KB}" ] && [ "${TOTAL_MEM_KB}" -gt 0 ] 2>/dev/null; then
  HEAP_MB=$(( TOTAL_MEM_KB * 70 / 100 / 1024 ))
  MEM_OPTS="-Xms${HEAP_MB}m -Xmx${HEAP_MB}m"
else
  MEM_OPTS="-Xms512m -Xmx512m"
fi

# ── JVM options ──────────────────────────────────────────────────────
JAVA_OPTS="${JAVA_OPTS:-}"
JAVA_OPTS="${JAVA_OPTS} ${MEM_OPTS}"
JAVA_OPTS="${JAVA_OPTS} -XX:+HeapDumpOnOutOfMemoryError"
JAVA_OPTS="${JAVA_OPTS} -XX:HeapDumpPath=/opt/logs/darwin-ofs-v2-populator-heapdump.hprof"
JAVA_OPTS="${JAVA_OPTS} -XX:+UseG1GC"

# JMX monitoring (enabled only on VMs)
case "${ODIN_DEPLOYMENT_TYPE}" in
  *container*|*k8s*) ;;
  *)
    JAVA_OPTS="${JAVA_OPTS} -Dcom.sun.management.jmxremote"
    JAVA_OPTS="${JAVA_OPTS} -Dcom.sun.management.jmxremote.port=9010"
    JAVA_OPTS="${JAVA_OPTS} -Dcom.sun.management.jmxremote.authenticate=false"
    JAVA_OPTS="${JAVA_OPTS} -Dcom.sun.management.jmxremote.ssl=false"
    ;;
esac

export JAVA_OPTS

# ── Launch ───────────────────────────────────────────────────────────
case "${ODIN_DEPLOYMENT_TYPE}" in
  *container*|*k8s*)
    exec java ${JAVA_OPTS} -jar "${ODIN_APP_DIR}/${ARTIFACT}"
    ;;
  *)
    nohup java ${JAVA_OPTS} -jar "${ODIN_APP_DIR}/${ARTIFACT}" > /opt/logs/darwin-ofs-v2-populator.log 2>&1 &
    echo $! > "${ODIN_APP_DIR}/.app.pid"
    ;;
esac
