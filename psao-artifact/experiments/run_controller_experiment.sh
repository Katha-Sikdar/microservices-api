#!/usr/bin/env bash
# run_controller_experiment.sh — measure PSAO end to end.
#
# Starts psao_controller.py against the live cluster, then drives an open-loop
# ramp that deliberately crosses the trigger, so the run captures the whole
# story in one trace: load rising, rho crossing rho_trigger, the offload
# actuating, latency flattening afterwards, and load falling back through the
# revert band. fig_controller_trace.py plots exactly this file.
#
# The ramp is intentionally taken well past the trigger and then back down. A
# run that only goes up shows the offload but never demonstrates that the
# hysteresis and dwell logic prevents a flap on the way down, which is the first
# thing a reviewer will ask about.
#
# Output: data/runs/<ISO timestamp>-controller/
#   controller_trace.csv  the analysable result (see docs/DATA_SCHEMA.md)
#   controller.log        every decision, every suppressed flap
#   openloop_ramp.csv, k6_*.csv, pod_cpu_samples.csv, run_metadata.json
#
# Usage:
#   experiments/run_controller_experiment.sh [--scenario S5] [--dry-run]
#       [--config controller/config.yaml] [--max-rps 400] [--step-rps 20]
#       [--step-duration 30s] [--down-duration 3m] [--settle 30]
#       [--base-url URL] [--token-pool FILE]
#       [--namespace default] [--selector app=service-a]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SCENARIO="${PSAO_SCENARIO:-S5}"
ENVIRONMENT="${PSAO_ENVIRONMENT:-local}"
CONFIG="$PSAO_ROOT/controller/config.yaml"
DRY_RUN=""
MAX_RPS="${PSAO_MAX_RPS:-400}"
STEP_RPS="${PSAO_STEP_RPS:-20}"
STEP_DURATION="${PSAO_STEP_DURATION:-30s}"
BASE_URL="${PSAO_BASE_URL:-https://localhost}"
TOKEN_FILE="${PSAO_TOKEN_FILE:-}"
TOKEN_POOL="${PSAO_TOKEN_POOL:-}"
AUTH="${PSAO_AUTH:-true}"
NAMESPACE="${PSAO_NAMESPACE:-default}"
SELECTOR="${PSAO_SELECTOR:-app=service-a}"
APP_CONTAINER="${PSAO_APP_CONTAINER:-service-a}"
METRICS_URL="${PSAO_METRICS_URL:-}"
# How long to hold at the low rate afterwards. Must comfortably exceed
# control.hysteresis.min_dwell_s, or the run ends before a revert is even
# eligible and the hysteresis claim goes untested.
DOWN_DURATION="${PSAO_DOWN_DURATION:-3m}"
SETTLE_S="${PSAO_SETTLE_S:-30}"
PYTHON="${PSAO_PYTHON:-$PSAO_ROOT/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="python3"

while [ $# -gt 0 ]; do
  case "$1" in
    --scenario) SCENARIO="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    --max-rps) MAX_RPS="$2"; shift 2 ;;
    --step-rps) STEP_RPS="$2"; shift 2 ;;
    --step-duration) STEP_DURATION="$2"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --token-file) TOKEN_FILE="$2"; shift 2 ;;
    --token-pool) TOKEN_POOL="$2"; shift 2 ;;
    --no-auth) AUTH="false"; shift ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --selector) SELECTOR="$2"; shift 2 ;;
    --metrics-url) METRICS_URL="$2"; shift 2 ;;
    --down-duration) DOWN_DURATION="$2"; shift 2 ;;
    --settle) SETTLE_S="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

psao::require k6 python3

# Absolute before anything else touches them; see psao::abspath.
TOKEN_FILE="$(psao::abspath "$TOKEN_FILE")"
TOKEN_POOL="$(psao::abspath "$TOKEN_POOL")"

# --- pre-flight ---------------------------------------------------------------
# See psao::verify_ingress. A controller experiment is the longest run here and
# the one whose trace is hardest to sanity-check by eye, so measuring it through
# a degraded path is the most expensive mistake available.
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

# The controller is the only thing here that applies the offload policy, so it
# is the only run whose correctness depends on the offload trust boundary. If
# a client can forge x-psao-jwt-payload, the "offloaded" half of this trace is
# measuring an endpoint that anyone can walk into. Checked before any load.
PSAO_BASE_URL="$BASE_URL" PSAO_TOKEN_FILE="${TOKEN_FILE:-$PSAO_ROOT/tokens/hs256.token}" \
  "$PSAO_ROOT/experiments/verify_offload_safety.sh" \
  || psao::die "offload trust boundary is not safe; refusing to run the controller"

RUN_DIR="$(psao::new_run_dir "controller")"
TRACE="$RUN_DIR/controller_trace.csv"
psao::log "run directory: $RUN_DIR"
[ -n "$DRY_RUN" ] && psao::log "controller in DRY RUN: it will decide but not touch the cluster"

PSAO_NAMESPACE="$NAMESPACE" psao::write_metadata "$RUN_DIR" \
  "experiment=controller" \
  "scenario=$SCENARIO" \
  "environment=$ENVIRONMENT" \
  "controller_config=$CONFIG" \
  "controller_dry_run=$([ -n "$DRY_RUN" ] && echo true || echo false)" \
  "max_rps=$MAX_RPS" \
  "step_rps=$STEP_RPS" \
  "step_duration=$STEP_DURATION" >/dev/null
# The exact controller configuration in force is part of the result: thresholds
# and dwell times determine every decision in the trace.
cp "$CONFIG" "$RUN_DIR/controller_config.used.yaml"

# The controller cannot make a single observation without Prometheus, so the
# forward is opened before it starts and closed in cleanup() below.
psao::start_port_forward || psao::die "Prometheus is required for a controller experiment"

# The ramp runner opens this; the controller runner did not, so its
# pod_cpu_samples.csv had an empty eventloop_lag column while the ramps' did not.
# The controller's own decisions read lag from Prometheus and were unaffected,
# but the two run types should produce the same columns.
if [ -z "$METRICS_URL" ]; then
  psao::start_metrics_port_forward "$NAMESPACE" "$SELECTOR" || true
  METRICS_URL="${PSAO_METRICS_URL_RESOLVED:-}"
fi

CONTROLLER_PID=""
CAPTURE_PID=""

cleanup() {
  local status=$?
  # SIGTERM, not SIGKILL: the controller's own handler reverts the cluster to
  # the application-layer configuration on the way out. Killing it hard would
  # leave verification pinned in the sidecar.
  if [ -n "$CONTROLLER_PID" ] && kill -0 "$CONTROLLER_PID" 2>/dev/null; then
    psao::log "stopping controller (SIGTERM, so it reverts cleanly)"
    kill -TERM "$CONTROLLER_PID" 2>/dev/null || true
    wait "$CONTROLLER_PID" 2>/dev/null || true
  fi
  if [ -n "$CAPTURE_PID" ] && kill -0 "$CAPTURE_PID" 2>/dev/null; then
    kill -TERM "$CAPTURE_PID" 2>/dev/null || true
    wait "$CAPTURE_PID" 2>/dev/null || true
  fi
  psao::stop_metrics_port_forward
  psao::stop_port_forward
  psao::finish_metadata "$RUN_DIR" "$status"
  psao::log "controller trace: $TRACE"
}
trap cleanup EXIT INT TERM

psao::log "starting controller"
"$PYTHON" "$PSAO_ROOT/controller/psao_controller.py" \
  --config "$CONFIG" --out "$TRACE" $DRY_RUN --log-level INFO \
  > "$RUN_DIR/controller.log" 2>&1 &
CONTROLLER_PID=$!

# Give the controller one poll interval to establish a baseline before load
# starts, so the trace opens with the idle operating point rather than mid-ramp.
sleep 5
kill -0 "$CONTROLLER_PID" 2>/dev/null || {
  psao::log "controller exited immediately; its log follows"
  cat "$RUN_DIR/controller.log" >&2
  exit 1
}

if kubectl get pods -n "$NAMESPACE" -l "$SELECTOR" --request-timeout=5s >/dev/null 2>&1; then
  PSAO_NAMESPACE="$NAMESPACE" PSAO_SELECTOR="$SELECTOR" \
  PSAO_APP_CONTAINER="$APP_CONTAINER" PSAO_METRICS_URL="$METRICS_URL" \
    "$PSAO_ROOT/experiments/capture_pod_metrics.sh" --out "$RUN_DIR" --interval 1 &
  CAPTURE_PID=$!
fi

psao::log "ramping up to $MAX_RPS rps"
export PSAO_SCENARIO="$SCENARIO" PSAO_ENVIRONMENT="$ENVIRONMENT" \
       PSAO_MAX_RPS="$MAX_RPS" PSAO_STEP_RPS="$STEP_RPS" \
       PSAO_STEP_DURATION="$STEP_DURATION" PSAO_BASE_URL="$BASE_URL" \
       PSAO_TOKEN_FILE="$TOKEN_FILE" PSAO_TOKEN_POOL="$TOKEN_POOL" \
       PSAO_AUTH="$AUTH" PSAO_OUT_DIR="$RUN_DIR"
psao::k6_env PSAO_SCENARIO PSAO_ENVIRONMENT PSAO_MAX_RPS PSAO_STEP_RPS \
             PSAO_STEP_DURATION PSAO_BASE_URL PSAO_TOKEN_FILE PSAO_TOKEN_POOL \
             PSAO_AUTH PSAO_OUT_DIR

set +e
k6 run ${K6_ENV_ARGS[@]+"${K6_ENV_ARGS[@]}"} \
  --out "csv=$RUN_DIR/k6_raw.csv" "$PSAO_ROOT/experiments/k6/openloop-ramp.js" \
  2>&1 | tee "$RUN_DIR/k6_up.log"
K6_STATUS=${PIPESTATUS[0]}
set -e

# k6 exits non-zero for a failed threshold too, and those runs ARE usable, which
# is why the status alone is not fatal. No k6_steps.csv is a different thing:
# the script aborted during init (a bad token path, an unreachable URL) and the
# run produced no measurements at all. Failing here stops a directory that
# contains only metadata from sitting in data/runs/ looking like a result.
if [ ! -s "$RUN_DIR/k6_steps.csv" ]; then
  psao::die "k6 wrote no k6_steps.csv (exit $K6_STATUS): this run measured nothing. See $RUN_DIR/k6_up.log"
fi

# Descending half: hold at a low rate so the revert band is actually entered and
# the dwell timer is exercised. Without this the trace never shows a revert and
# the hysteresis claim is untested.
psao::log "descending: holding at ${STEP_RPS} rps for $DOWN_DURATION to exercise the revert path"
export PSAO_MAX_RPS="$STEP_RPS" PSAO_STEP_DURATION="$DOWN_DURATION" PSAO_OUT_DIR="$RUN_DIR/down"
mkdir -p "$RUN_DIR/down"
psao::k6_env PSAO_SCENARIO PSAO_ENVIRONMENT PSAO_MAX_RPS PSAO_STEP_RPS \
             PSAO_STEP_DURATION PSAO_BASE_URL PSAO_TOKEN_FILE PSAO_TOKEN_POOL \
             PSAO_AUTH PSAO_OUT_DIR

set +e
k6 run ${K6_ENV_ARGS[@]+"${K6_ENV_ARGS[@]}"} \
  "$PSAO_ROOT/experiments/k6/openloop-ramp.js" 2>&1 | tee "$RUN_DIR/k6_down.log"
set -e

psao::log "load finished; letting the controller observe the quiet period"
sleep "$SETTLE_S"

psao::log "decisions recorded:"
awk -F, 'NR>1 && $9 != "hold" { print "  " $2 "s  " $9 "  actuation=" $10 "ms  " $11 }' \
  "$TRACE" 2>/dev/null | head -40 || true
psao::log "suppressed flaps:"
grep -c "SUPPRESSED FLAP" "$RUN_DIR/controller.log" 2>/dev/null || echo "  0"
