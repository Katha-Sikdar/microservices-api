#!/usr/bin/env bash
# verify_rate_sweep.sh — in-situ cost of jwt.verify() as a function of arrival rate.
#
# WHAT THIS MEASURES, AND WHY IT IS TRUSTWORTHY WHERE THE RAMPS ARE NOT
# --------------------------------------------------------------------
# psao_verify_duration_seconds times the verification call itself, inside the
# server, with process.hrtime.bigint(). It is a DURATION DISTRIBUTION of a
# CPU-bound call, not a throughput measurement, and that difference matters:
#
#   * A throughput ramp asks "how many requests can this host carry", which is
#     exactly the quantity host contention destroys. Those runs were invalidated
#     twice in one day here.
#   * This asks "how long does one call take". Contention can only make that
#     number BIGGER. So a measured cost is an upper bound, and the finding --
#     that in-situ cost far exceeds the isolated benchmark -- is conservative
#     under contention rather than produced by it.
#
# Host load is recorded per point anyway, so the claim can be checked.
#
# SEPARATING RATE FROM WARMTH
# ---------------------------
# Running 5, 10, ... 400 rps in that order on one process confounds arrival rate
# with accumulated JIT warmth: the 400 rps point would have had the benefit of
# every earlier point's compilation. So the sweep runs ASCENDING and then
# DESCENDING on the same process:
#
#   * If cost tracks rate in both directions, it is rate-dependent.
#   * If the descending pass is uniformly fast, the effect was warmth, and the
#     ascending curve was measuring process age.
#
# That comparison is the actual experiment; a single ascending pass cannot
# distinguish the two.
#
# Usage:
#   experiments/verify_rate_sweep.sh --label hs256 --token-pool tokens/pool.txt
#       [--rates "5 10 25 50 100 200 400"] [--duration 3m] [--no-descend]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

LABEL="sweep"
TOKEN_POOL=""
RATES="5 10 25 50 100 200 400"
DURATION="3m"
DESCEND=1
NAMESPACE="${PSAO_NAMESPACE:-default}"
BASE_URL="${PSAO_BASE_URL:-https://localhost}"

while [ $# -gt 0 ]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    --token-pool) TOKEN_POOL="$2"; shift 2 ;;
    --rates) RATES="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --no-descend) DESCEND=0; shift ;;
    -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

[ -n "$TOKEN_POOL" ] || psao::die "--token-pool is required"
TOKEN_POOL="$(psao::abspath "$TOKEN_POOL")"
psao::require kubectl k6 curl python3

PREFLIGHT_TOKEN="$(head -n 1 "$TOKEN_POOL" | tr -d '\r\n')"
psao::verify_ingress "$BASE_URL" "${PSAO_PATH:-/products}" 200 "$PREFLIGHT_TOKEN"

RUN_DIR="$(psao::new_run_dir "verifyrate-$LABEL")"
psao::log "run directory: $RUN_DIR"
PSAO_NAMESPACE="$NAMESPACE" psao::write_metadata "$RUN_DIR" \
  "experiment=verify_rate_sweep" "label=$LABEL" \
  "rates=$RATES" "duration_per_point=$DURATION" "descend=$DESCEND" >/dev/null

POD="$(kubectl -n "$NAMESPACE" get endpoints service-a \
  --request-timeout=10s -o jsonpath='{.subsets[0].addresses[0].targetRef.name}')"
[ -n "$POD" ] || psao::die "could not resolve the pod behind the service-a Service"
psao::log "measuring pod: $POD"
echo "$POD" > "$RUN_DIR/pod.txt"

kubectl -n "$NAMESPACE" port-forward "pod/$POD" 9466:9464 >/dev/null 2>&1 &
PF_PID=$!
cleanup() { kill "$PF_PID" 2>/dev/null || true; }
trap cleanup EXIT
sleep 5
curl -sf -m 5 http://localhost:9466/metrics >/dev/null || psao::die "metrics endpoint unreachable"

scrape() { curl -sf -m 10 http://localhost:9466/metrics > "$1"; }

# One point: snapshot, load, snapshot. The delta between the two scrapes is the
# histogram for exactly this rate and nothing else -- the histograms are
# cumulative, so a delta isolates the window without needing a pod restart.
measure() {
  local rate="$1" pass="$2"
  local tag="${pass}-$(printf '%04d' "$rate")"
  psao::log "point: $rate rps ($pass pass), $DURATION"
  uptime > "$RUN_DIR/host-$tag.txt"
  scrape "$RUN_DIR/before-$tag.prom"
  # k6's handleSummary writes into OUT_DIR and will not create it; without this
  # every point logs a summary-write failure and exits non-zero. The scrape pair
  # is what this experiment actually reads, so it was cosmetic -- but a runner
  # that always exits non-zero trains you to ignore its exit status.
  mkdir -p "$RUN_DIR/k6-$tag"
  k6 run --quiet \
    -e "PSAO_BASE_URL=$BASE_URL" -e "PSAO_TOKEN_POOL=$TOKEN_POOL" \
    -e "PSAO_SCENARIO=$LABEL" -e "PSAO_MAX_RPS=$rate" -e "PSAO_STEP_RPS=$rate" \
    -e "PSAO_STEP_DURATION=$DURATION" -e "PSAO_OUT_DIR=$RUN_DIR/k6-$tag" \
    "$PSAO_ROOT/experiments/k6/openloop-ramp.js" \
    > "$RUN_DIR/k6-$tag.log" 2>&1 || psao::log "  WARNING: k6 exited non-zero"
  scrape "$RUN_DIR/after-$tag.prom"
  uptime >> "$RUN_DIR/host-$tag.txt"
}

# Warm the process before the first point so that "5 rps" is not also "the first
# 900 requests this process ever served". Without it the lowest rate carries all
# the cold-start cost and the curve is guaranteed to slope downward whatever the
# truth is.
psao::log "warming the process before the first point"
k6 run --quiet -e "PSAO_BASE_URL=$BASE_URL" -e "PSAO_TOKEN_POOL=$TOKEN_POOL" \
  -e "PSAO_MAX_RPS=200" -e "PSAO_STEP_RPS=200" -e "PSAO_STEP_DURATION=60s" \
  -e "PSAO_OUT_DIR=$RUN_DIR/k6-warmup" \
  "$PSAO_ROOT/experiments/k6/openloop-ramp.js" > "$RUN_DIR/k6-warmup.log" 2>&1 || true

for r in $RATES; do measure "$r" "asc"; done

if [ "$DESCEND" -eq 1 ]; then
  psao::log "descending pass (same process) to separate rate from JIT warmth"
  rev=""
  for r in $RATES; do rev="$r $rev"; done
  for r in $rev; do measure "$r" "desc"; done
fi

psao::finish_metadata "$RUN_DIR" 0
psao::log "done: $RUN_DIR"
