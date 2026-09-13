#!/usr/bin/env bash
# run_closedloop_scenario.sh — one closed-loop scenario run (S1..S9).
#
# Reproduces the manuscript's original load profile (100 VUs, 1 s think time)
# for a single scenario and a single repetition, with 1 s CPU sampling alongside
# so that the CPU columns belong to the same window as the throughput column.
# Run it once per repetition; analysis/stats_tests.py expects several runs per
# scenario and will say so if it gets fewer.
#
# The scenario's deployment state (which security layers are enabled, which
# service image is running) is NOT changed by this script. Bringing the cluster
# into the S<n> configuration is a deliberate manual step -- an automated
# "apply then measure" would make it far too easy to measure a configuration
# that had not finished rolling out. README.md lists the per-scenario setup.
#
# Output: data/runs/<ISO timestamp>-<scenario>-run<N>/
#   scenarios.csv, latency_samples.csv, k6_scenario.csv, k6_raw.csv,
#   pod_cpu_samples.csv, run_metadata.json
#
# Usage:
#   experiments/run_closedloop_scenario.sh --scenario S5 --run 1
#       [--environment local|eks] [--vus 100] [--warmup 20s] [--steady 1m]
#       [--rampdown 10s] [--sleep 1] [--base-url https://localhost]
#       [--token-file FILE|--token-pool FILE] [--no-auth]
#       [--namespace default] [--selector app=service-a]
#       [--metrics-url http://localhost:9464/metrics]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SCENARIO=""
RUN="1"
ENVIRONMENT="${PSAO_ENVIRONMENT:-local}"
VUS="${PSAO_VUS:-100}"
WARMUP="${PSAO_WARMUP:-20s}"
STEADY="${PSAO_STEADY:-1m}"
RAMPDOWN="${PSAO_RAMPDOWN:-10s}"
THINK="${PSAO_SLEEP:-1}"
BASE_URL="${PSAO_BASE_URL:-https://localhost}"
TOKEN_FILE="${PSAO_TOKEN_FILE:-}"
TOKEN_POOL="${PSAO_TOKEN_POOL:-}"
AUTH="${PSAO_AUTH:-true}"
NAMESPACE="${PSAO_NAMESPACE:-default}"
SELECTOR="${PSAO_SELECTOR:-app=service-a}"
APP_CONTAINER="${PSAO_APP_CONTAINER:-service-a}"
METRICS_URL="${PSAO_METRICS_URL:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --scenario) SCENARIO="$2"; shift 2 ;;
    --run) RUN="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --vus) VUS="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    --steady) STEADY="$2"; shift 2 ;;
    --rampdown) RAMPDOWN="$2"; shift 2 ;;
    --sleep) THINK="$2"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --token-file) TOKEN_FILE="$2"; shift 2 ;;
    --token-pool) TOKEN_POOL="$2"; shift 2 ;;
    --no-auth) AUTH="false"; shift ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --selector) SELECTOR="$2"; shift 2 ;;
    --metrics-url) METRICS_URL="$2"; shift 2 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

[ -n "$SCENARIO" ] || psao::die "--scenario is required (e.g. S5)"
psao::require k6 python3

# Absolute before anything else touches them; see psao::abspath.
TOKEN_FILE="$(psao::abspath "$TOKEN_FILE")"
TOKEN_POOL="$(psao::abspath "$TOKEN_POOL")"

# --- pre-flight ---------------------------------------------------------------
# See psao::verify_ingress.
PREFLIGHT_TOKEN=""
if [ "$AUTH" = "true" ]; then
  if [ -n "$TOKEN_FILE" ] && [ -r "$TOKEN_FILE" ]; then
    PREFLIGHT_TOKEN="$(head -n 1 "$TOKEN_FILE" | tr -d '\r\n')"
  elif [ -n "$TOKEN_POOL" ] && [ -r "$TOKEN_POOL" ]; then
    PREFLIGHT_TOKEN="$(head -n 1 "$TOKEN_POOL" | tr -d '\r\n')"
  else
    psao::die "auth is on but no readable token: pass --token-file or --token-pool"
  fi
fi
psao::verify_ingress "$BASE_URL" "${PSAO_PATH:-/products}" \
  "${PSAO_EXPECT_STATUS:-200}" "$PREFLIGHT_TOKEN"

RUN_DIR="$(psao::new_run_dir "${SCENARIO}-run${RUN}")"
psao::log "run directory: $RUN_DIR"

# The pod's CPU limit is a scenario property, not a measurement: it bounds what
# S9's extra workers can possibly deliver. Read it if the cluster is reachable.
CPU_LIMIT=""
if kubectl get pods -n "$NAMESPACE" -l "$SELECTOR" --request-timeout=5s >/dev/null 2>&1; then
  CPU_LIMIT="$(psao::try kubectl get pods -n "$NAMESPACE" -l "$SELECTOR" --request-timeout=5s \
    -o "jsonpath={.items[0].spec.containers[?(@.name=='$APP_CONTAINER')].resources.limits.cpu}" \
    | python3 -c '
import sys
raw = sys.stdin.read().strip()
if not raw:
    print("")
elif raw.endswith("m"):
    print(raw[:-1])
else:
    try:
        print(int(float(raw) * 1000))
    except ValueError:
        print("")
')"
fi
[ -n "$CPU_LIMIT" ] && psao::log "pod CPU limit: ${CPU_LIMIT}m" || psao::log "pod CPU limit: not readable (column left empty)"

PSAO_NAMESPACE="$NAMESPACE" psao::write_metadata "$RUN_DIR" \
  "experiment=closedloop_scenario" \
  "scenario=$SCENARIO" \
  "run=$RUN" \
  "environment=$ENVIRONMENT" \
  "vus=$VUS" \
  "warmup=$WARMUP" \
  "steady=$STEADY" \
  "rampdown=$RAMPDOWN" \
  "think_seconds=$THINK" \
  "base_url=$BASE_URL" \
  "auth=$AUTH" \
  "cpu_limit_millicores=${CPU_LIMIT:-unavailable}" >/dev/null

psao::start_port_forward || psao::log "WARNING: continuing without Prometheus; metrics-derived columns will be empty"

if [ -z "$METRICS_URL" ]; then
  psao::start_metrics_port_forward "$NAMESPACE" "$SELECTOR" || true
  METRICS_URL="${PSAO_METRICS_URL_RESOLVED:-}"
fi

CAPTURE_PID=""
if kubectl get pods -n "$NAMESPACE" -l "$SELECTOR" --request-timeout=5s >/dev/null 2>&1; then
  PSAO_NAMESPACE="$NAMESPACE" PSAO_SELECTOR="$SELECTOR" \
  PSAO_APP_CONTAINER="$APP_CONTAINER" PSAO_METRICS_URL="$METRICS_URL" \
    "$PSAO_ROOT/experiments/capture_pod_metrics.sh" --out "$RUN_DIR" --interval 1 &
  CAPTURE_PID=$!
else
  psao::log "WARNING: no pods match '$SELECTOR' in namespace '$NAMESPACE'; CPU columns will be empty"
fi

cleanup() {
  local status=$?
  if [ -n "$CAPTURE_PID" ] && kill -0 "$CAPTURE_PID" 2>/dev/null; then
    kill -TERM "$CAPTURE_PID" 2>/dev/null || true
    wait "$CAPTURE_PID" 2>/dev/null || true
  fi
  psao::stop_metrics_port_forward
  psao::stop_port_forward
  psao::finish_metadata "$RUN_DIR" "$status"
}
trap cleanup EXIT

psao::log "starting k6 closed-loop: $SCENARIO run $RUN, $VUS VUs, think ${THINK}s"
export PSAO_SCENARIO="$SCENARIO" PSAO_ENVIRONMENT="$ENVIRONMENT" PSAO_RUN="$RUN" \
       PSAO_VUS="$VUS" PSAO_WARMUP="$WARMUP" PSAO_STEADY="$STEADY" \
       PSAO_RAMPDOWN="$RAMPDOWN" PSAO_SLEEP="$THINK" PSAO_BASE_URL="$BASE_URL" \
       PSAO_TOKEN_FILE="$TOKEN_FILE" PSAO_TOKEN_POOL="$TOKEN_POOL" \
       PSAO_AUTH="$AUTH" PSAO_OUT_DIR="$RUN_DIR"
psao::k6_env PSAO_SCENARIO PSAO_ENVIRONMENT PSAO_RUN PSAO_VUS PSAO_WARMUP \
             PSAO_STEADY PSAO_RAMPDOWN PSAO_SLEEP PSAO_BASE_URL PSAO_TOKEN_FILE \
             PSAO_TOKEN_POOL PSAO_AUTH PSAO_OUT_DIR

set +e
k6 run ${K6_ENV_ARGS[@]+"${K6_ENV_ARGS[@]}"} \
  --out "csv=$RUN_DIR/k6_raw.csv" "$PSAO_ROOT/experiments/k6/closedloop.js" \
  2>&1 | tee "$RUN_DIR/k6.log"
K6_STATUS=${PIPESTATUS[0]}
set -e
[ "$K6_STATUS" -eq 0 ] || psao::log "WARNING: k6 exited $K6_STATUS"

if [ -n "$CAPTURE_PID" ] && kill -0 "$CAPTURE_PID" 2>/dev/null; then
  kill -TERM "$CAPTURE_PID" 2>/dev/null || true
  wait "$CAPTURE_PID" 2>/dev/null || true
  CAPTURE_PID=""
fi

psao::log "merging k6 summary, per-request samples and CPU"
PSAO_RUN_DIR="$RUN_DIR" \
PSAO_APP_CONTAINER="$APP_CONTAINER" \
PSAO_CPU_LIMIT_MILLICORES="$CPU_LIMIT" \
  python3 "$PSAO_ROOT/experiments/merge_scenario.py"

psao::log "done: $RUN_DIR/scenarios.csv"
psao::log "combine runs with:  cat data/runs/*/scenarios.csv | awk 'NR==1 || !/^scenario,/' > data/measured/scenarios.csv"
