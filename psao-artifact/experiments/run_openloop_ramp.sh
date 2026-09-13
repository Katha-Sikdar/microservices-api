#!/usr/bin/env bash
# run_openloop_ramp.sh — the run that produces the paper's missing elbow figure.
#
# Drives k6 in open-loop constant-arrival-rate mode, stepping the offered rate,
# while capture_pod_metrics.sh samples pod CPU at 1 s resolution. Because the
# CPU sampler and the load generator share a wall clock, each ramp step can be
# matched to the CPU consumed DURING that step. That is the difference between
# reporting CPU **at** the elbow (a measurement) and CPU *derived* from a
# scenario-average utilisation (what the manuscript currently does).
#
# Defaults: up to 400 rps, 20 rps steps, 30 s per step -> 20 steps, ~10 minutes.
#
# Output: data/runs/<ISO timestamp>-ramp-<scenario>/
#   openloop_ramp.csv     the analysable result (see docs/DATA_SCHEMA.md)
#   k6_steps.csv          per-step latency/throughput straight from k6
#   k6_raw.csv            per-request samples (source of the step time windows)
#   pod_cpu_samples.csv   1 s CPU samples
#   run_metadata.json     provenance
#
# Usage:
#   experiments/run_openloop_ramp.sh --scenario S5 [--environment local|eks]
#       [--max-rps 400] [--step-rps 20] [--step-duration 30s]
#       [--base-url https://localhost] [--token-file FILE|--token-pool FILE]
#       [--no-auth] [--namespace default] [--selector app=service-a]
#       [--metrics-url http://localhost:9464/metrics]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SCENARIO=""
ENVIRONMENT="${PSAO_ENVIRONMENT:-local}"
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
SIDECAR_CONTAINER="${PSAO_SIDECAR_CONTAINER:-istio-proxy}"
METRICS_URL="${PSAO_METRICS_URL:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --scenario) SCENARIO="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
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
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

[ -n "$SCENARIO" ] || psao::die "--scenario is required (e.g. S5)"
psao::require k6 python3

# Absolute before anything else touches them; see psao::abspath.
TOKEN_FILE="$(psao::abspath "$TOKEN_FILE")"
TOKEN_POOL="$(psao::abspath "$TOKEN_POOL")"

# --- pre-flight ---------------------------------------------------------------
# One request through the exact path the ramp will hammer, before anything is
# created or measured. See psao::verify_ingress for why.
#
# PSAO_EXPECT_STATUS overrides the expected code for a scenario whose designed
# response is not 200 -- but if you find yourself setting it, be sure the status
# you are accepting is the one the scenario is supposed to produce, not the one
# the cluster happens to be producing.
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

RUN_DIR="$(psao::new_run_dir "ramp-$SCENARIO")"
psao::log "run directory: $RUN_DIR"

PSAO_NAMESPACE="$NAMESPACE" psao::write_metadata "$RUN_DIR" \
  "experiment=openloop_ramp" \
  "scenario=$SCENARIO" \
  "environment=$ENVIRONMENT" \
  "max_rps=$MAX_RPS" \
  "step_rps=$STEP_RPS" \
  "step_duration=$STEP_DURATION" \
  "base_url=$BASE_URL" \
  "auth=$AUTH" \
  "selector=$SELECTOR" >/dev/null

# --- Prometheus port-forward --------------------------------------------------
# Opened here, torn down in cleanup() below, so a ramp never runs blind because
# somebody forgot to open a tunnel in another terminal.
psao::start_port_forward || psao::log "WARNING: continuing without Prometheus; metrics-derived columns will be empty"

# Per-second event-loop lag alongside the per-second CPU samples. Without this
# the eventloop_lag_p99_ms column is empty for the whole run.
if [ -z "$METRICS_URL" ]; then
  psao::start_metrics_port_forward "$NAMESPACE" "$SELECTOR" || true
  METRICS_URL="${PSAO_METRICS_URL_RESOLVED:-}"
fi

# --- CPU sampler --------------------------------------------------------------
CAPTURE_PID=""
if kubectl get pods -n "$NAMESPACE" -l "$SELECTOR" --request-timeout=5s >/dev/null 2>&1; then
  PSAO_NAMESPACE="$NAMESPACE" PSAO_SELECTOR="$SELECTOR" \
  PSAO_APP_CONTAINER="$APP_CONTAINER" PSAO_METRICS_URL="$METRICS_URL" \
    "$PSAO_ROOT/experiments/capture_pod_metrics.sh" --out "$RUN_DIR" --interval 1 &
  CAPTURE_PID=$!
  psao::log "CPU sampler running (pid $CAPTURE_PID)"
else
  # No cluster: the ramp still measures latency and throughput, and the CPU
  # columns stay empty. An empty column is an honest "not measured".
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

# --- load ---------------------------------------------------------------------
psao::log "starting k6 open-loop ramp: ${STEP_RPS}..${MAX_RPS} rps in ${STEP_RPS} rps steps of $STEP_DURATION"
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
  2>&1 | tee "$RUN_DIR/k6.log"
K6_STATUS=${PIPESTATUS[0]}
set -e
[ "$K6_STATUS" -eq 0 ] || psao::log "WARNING: k6 exited $K6_STATUS; the merge below uses whatever it produced"

# k6 exits non-zero for a failed threshold too, and those runs ARE usable, which
# is why the status alone is not fatal. No k6_steps.csv is a different thing:
# the script aborted during init (a bad token path, an unreachable URL) and the
# run produced no measurements at all. Failing here stops a directory that
# contains only metadata from sitting in data/runs/ looking like a result.
if [ ! -s "$RUN_DIR/k6_steps.csv" ]; then
  psao::die "k6 wrote no k6_steps.csv (exit $K6_STATUS): this run measured nothing. See $RUN_DIR/k6.log"
fi

if [ -n "$CAPTURE_PID" ] && kill -0 "$CAPTURE_PID" 2>/dev/null; then
  kill -TERM "$CAPTURE_PID" 2>/dev/null || true
  wait "$CAPTURE_PID" 2>/dev/null || true
  CAPTURE_PID=""
fi

# --- the CPU sampler either measured, or the run is incomplete ----------------
# "No CPU column" is an honest absence only when there was no cluster to sample.
# When the sampler WAS started, an empty column means it died -- and a ramp
# without CPU cannot produce CPU-at-the-elbow, which is the measurement this
# whole experiment exists to replace a derived number with. Failing here stops
# that run from being quietly analysed as though the column were legitimately
# unavailable.
if [ -n "$CAPTURE_PID" ]; then
  CPU_ROWS="$(grep -vc '^#' "$RUN_DIR/pod_cpu_samples.csv" 2>/dev/null || echo 0)"
  # Header row counts as one non-comment line, so >1 means real samples.
  if [ "${CPU_ROWS:-0}" -le 1 ]; then
    psao::log "the CPU sampler was started but wrote no samples to $RUN_DIR/pod_cpu_samples.csv"
    psao::die "ramp has latency but no CPU: refusing to present it as a complete run"
  fi
  psao::log "CPU sampler wrote $((CPU_ROWS - 1)) sample rows"

  # Event-loop lag is the signal the saturation story is told with, so a run
  # that quietly lost it should say so. It is enrichment rather than the
  # measurement, so this warns instead of failing -- but loudly enough that it
  # is not discovered weeks later while reading a figure.
  LAG_ROWS="$(awk -F, 'NR>2 && $5 != "" {n++} END {print n+0}' \
    "$RUN_DIR/pod_cpu_samples.csv" 2>/dev/null || echo 0)"
  if [ "${LAG_ROWS:-0}" -eq 0 ]; then
    psao::log "WARNING: eventloop_lag_p99_ms is EMPTY for this entire run."
    psao::log "         The app metrics endpoint was never scraped successfully;"
    psao::log "         check the :$PSAO_METRICS_PORT port-forward. CPU and latency are unaffected."
  else
    psao::log "eventloop lag captured in $LAG_ROWS sample rows"
  fi
fi

# --- merge --------------------------------------------------------------------
# Step time windows come from the k6 per-request CSV (the `scenario` tag names
# the step), so CPU is attributed using the real request timestamps rather than
# an assumed schedule. Startup skew, a slow first connection, or a step that
# overran therefore cannot silently shift the CPU attribution by a step.
psao::log "merging k6 steps with CPU samples"
PSAO_RUN_DIR="$RUN_DIR" \
PSAO_APP_CONTAINER="$APP_CONTAINER" \
PSAO_SIDECAR_CONTAINER="$SIDECAR_CONTAINER" \
  python3 "$PSAO_ROOT/experiments/merge_ramp.py"

psao::log "done: $RUN_DIR/openloop_ramp.csv"
