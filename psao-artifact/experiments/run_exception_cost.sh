#!/usr/bin/env bash
# run_exception_cost.sh — V8 exception-cost baseline and the real probe, on
# several official Node.js runtimes (item: split parse from exception).
#
# bench/exception-cost.js runs ONE condition per process. For each round, every
# runtime runs every condition before the next round starts. Runtimes are the
# official release binaries fetched by experiments/fetch_node_runtimes.sh.
#
# Usage:
#   experiments/run_exception_cost.sh [--rounds 15] [--iterations 10000]
#        [--warmup 5000] [--runtimes "18.20.8 20.20.2 ..."] [--label x86_64-vm]
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ROUNDS=15; ITERATIONS=10000; WARMUP=5000; LABEL="${PSAO_ENV_LABEL:-host}"
RT="${PSAO_NODE_RUNTIMES:-/opt/node-rt}"
RUNTIMES="18.20.8 20.20.2 22.23.3 23.11.1 24.21.0 26.10.0"
CONDITIONS="exc_plain exc_node_like exc_node_like_nostack exc_node_internal probe_throws probe_throws_nostack timer_overhead"
while [ $# -gt 0 ]; do
  case "$1" in
    --rounds) ROUNDS="$2"; shift 2 ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    --runtimes) RUNTIMES="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done
case "$(uname -m)" in x86_64) ARCH=x64 ;; *) ARCH=arm64 ;; esac
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"

RUN_DIR="$(psao::new_run_dir "exception-cost")"
psao::log "run directory: $RUN_DIR"
echo "runtime,node_version,openssl_version,v8_version,arch" > "$RUN_DIR/environments.csv"
for r in $RUNTIMES; do
  n="$RT/node-v$r-$OS-$ARCH/bin/node"
  [ -x "$n" ] || psao::die "missing $n (experiments/fetch_node_runtimes.sh)"
  echo "node-$r,$("$n" -p '[process.version,process.versions.openssl,process.versions.v8,process.arch].join(",")')" >> "$RUN_DIR/environments.csv"
done
PSAO_NAMESPACE="${PSAO_NAMESPACE:-default}" psao::write_metadata "$RUN_DIR" \
  "experiment=exception-cost" "rounds=$ROUNDS" "iterations=$ITERATIONS" "warmup=$WARMUP" \
  "runtimes=$RUNTIMES" "conditions=$CONDITIONS" "environment_label=$LABEL" \
  "cpu_model=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)" \
  "nproc=$(nproc)" "arch=$(uname -m)" "needs_cluster=false" >/dev/null

OUT="$RUN_DIR/exception_cost.csv"
status=0
for round in $(seq 1 "$ROUNDS"); do
  psao::log "round $round/$ROUNDS"
  for r in $RUNTIMES; do
    for c in $CONDITIONS; do
      "$RT/node-v$r-$OS-$ARCH/bin/node" "$PSAO_ROOT/bench/exception-cost.js" \
        --condition "$c" --iterations "$ITERATIONS" --warmup "$WARMUP" \
        --invocation "$round" --environment "node-$r" --out "$OUT" \
        >> "$RUN_DIR/exception_cost.log" 2>&1 \
        || { psao::log "WARNING: node-$r $c round $round failed"; status=1; }
    done
  done
done
psao::finish_metadata "$RUN_DIR" "$status"
psao::log "done: $OUT"
exit "$status"
