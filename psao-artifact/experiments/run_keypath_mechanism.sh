#!/usr/bin/env bash
# run_keypath_mechanism.sh — why a string key costs what it costs, with the
# repetition discipline a single process cannot provide.
#
# bench/keypath-mechanism.js measures one condition per process. This runner
# invokes it ROUNDS times per condition, cycling condition-by-condition WITHIN
# each round rather than finishing one condition before starting the next. The
# ordering matters: a thermal drift or a background process during a block-
# ordered run lands entirely on whichever condition was running, and is
# indistinguishable from an effect. Interleaved, it is spread across all of
# them and shows up as between-round variance, which the analysis reports.
#
# Needs no cluster. Cluster fields in run_metadata.json record as unavailable.
#
# Usage:
#   experiments/run_keypath_mechanism.sh [--rounds 15] [--iterations 40000]
#                                        [--warmup 20000]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ROUNDS=15
ITERATIONS=40000
WARMUP=20000

while [ $# -gt 0 ]; do
  case "$1" in
    --rounds) ROUNDS="$2"; shift 2 ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

psao::require node python3

CONDITIONS=(
  jwt_hs_string jwt_hs_preparsed jwt_hs_string_safe
  jwt_rs_pem_string jwt_rs_preparsed
  probe_throws probe_succeeds create_secret_key
  hmac_string hmac_keyobject decode_only timer_overhead
)

RUN_DIR="$(psao::new_run_dir "keypath-mechanism")"
psao::log "run directory: $RUN_DIR"

PSAO_NAMESPACE="${PSAO_NAMESPACE:-default}" psao::write_metadata "$RUN_DIR" \
  "experiment=keypath-mechanism" \
  "rounds=$ROUNDS" \
  "iterations=$ITERATIONS" \
  "warmup=$WARMUP" \
  "conditions=${CONDITIONS[*]}" \
  "jsonwebtoken_version=$(node -e "console.log(require('$PSAO_ROOT/bench/node_modules/jsonwebtoken/package.json').version)")" \
  "needs_cluster=false" >/dev/null

# The security result is a precondition for reporting the patched timing at all:
# if the safe patch does not hold the line against algorithm confusion, its
# latency is not a result worth having. Run it first and stop if it fails.
psao::log "algorithm-confusion check (stock / naive / safe)"
if node "$PSAO_ROOT/bench/keypath-security-check.js" \
     > "$RUN_DIR/security_check.csv" 2> "$RUN_DIR/security_check.log"; then
  psao::log "  all expectations held"
else
  cat "$RUN_DIR/security_check.log" >&2
  psao::finish_metadata "$RUN_DIR" 1
  psao::die "algorithm-confusion expectations violated; see $RUN_DIR/security_check.csv"
fi

OUT="$RUN_DIR/keypath_mechanism.csv"
status=0
for round in $(seq 1 "$ROUNDS"); do
  psao::log "round $round/$ROUNDS"
  for condition in "${CONDITIONS[@]}"; do
    node "$PSAO_ROOT/bench/keypath-mechanism.js" \
      --condition "$condition" --iterations "$ITERATIONS" \
      --warmup "$WARMUP" --invocation "$round" --out "$OUT" \
      >> "$RUN_DIR/keypath_mechanism.log" 2>&1 \
      || { psao::log "WARNING: $condition round $round exited $?"; status=1; }
  done
done

psao::finish_metadata "$RUN_DIR" "$status"
psao::log "done: $OUT"
exit "$status"
