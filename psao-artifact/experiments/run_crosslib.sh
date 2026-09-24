#!/usr/bin/env bash
# run_crosslib.sh — HS256 verification across JWT libraries and languages,
# string secret vs pre-parsed key (item: is this one bug or a class?).
#
# Libraries (versions pinned in each harness's manifest):
#   JavaScript  jsonwebtoken, fast-jwt, jose   bench/libs/node/crosslib.js
#               -- run under TWO Node runtimes: one bundling OpenSSL 3.0.x and
#                  one bundling 3.5.x, since the jsonwebtoken penalty depends on it
#   Python      PyJWT                          bench/libs/python/crosslib.py
#   Go          golang-jwt/jwt/v5              bench/libs/go
#   Java        nimbus-jose-jwt, jjwt          bench/libs/java/CrossLib.java
# ONE condition per process; every (environment, condition) is run once per
# round before the next round starts.
#
# Usage: experiments/run_crosslib.sh [--rounds 15] [--iterations 20000]
#        [--warmup 10000] [--node-runtimes "20.20.2 26.10.0"] [--label x86_64-vm]
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ROUNDS=15; ITERATIONS=20000; WARMUP=10000; LABEL="${PSAO_ENV_LABEL:-host}"
RT="${PSAO_NODE_RUNTIMES:-/opt/node-rt}"
NODE_RUNTIMES="20.20.2 26.10.0"
while [ $# -gt 0 ]; do
  case "$1" in
    --rounds) ROUNDS="$2"; shift 2 ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    --node-runtimes) NODE_RUNTIMES="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done
psao::require go java javac python3
case "$(uname -m)" in x86_64) ARCH=x64 ;; *) ARCH=arm64 ;; esac
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
L="$PSAO_ROOT/bench/libs"

# --- build / install, outside every timed region ------------------------------
( cd "$L/node" && npm ci --no-audit --no-fund >/dev/null 2>&1 || npm install --no-audit --no-fund >/dev/null )
( cd "$L/python" && { [ -x .venv/bin/python ] || python3 -m venv .venv; } && .venv/bin/pip install -q -r requirements.txt )
( cd "$L/go" && go build -o crosslib-go . )
( cd "$L/java" && ./fetch_jars.sh && javac -cp 'lib/*' -d . CrossLib.java )

RUN_DIR="$(psao::new_run_dir "crosslib")"
psao::log "run directory: $RUN_DIR"
PSAO_NAMESPACE="${PSAO_NAMESPACE:-default}" psao::write_metadata "$RUN_DIR" \
  "experiment=crosslib" "rounds=$ROUNDS" "iterations=$ITERATIONS" "warmup=$WARMUP" \
  "node_runtimes=$NODE_RUNTIMES" "environment_label=$LABEL" \
  "go_version=$(go version)" "java_version=$(java -version 2>&1 | grep -m1 version)" \
  "python_version=$("$L/python/.venv/bin/python" --version)" \
  "cpu_model=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)" \
  "nproc=$(nproc)" "arch=$(uname -m)" "needs_cluster=false" >/dev/null

OUT="$RUN_DIR/crosslib.csv"
LOG="$RUN_DIR/crosslib.log"
status=0
run() { "$@" >>"$LOG" 2>&1 || { psao::log "WARNING: failed: $*"; status=1; }; }
for round in $(seq 1 "$ROUNDS"); do
  psao::log "round $round/$ROUNDS"
  for r in $NODE_RUNTIMES; do
    for c in jsonwebtoken_string jsonwebtoken_preparsed fastjwt_string fastjwt_preparsed jose_string jose_preparsed; do
      run "$RT/node-v$r-$OS-$ARCH/bin/node" "$L/node/crosslib.js" --condition "$c" \
        --iterations "$ITERATIONS" --warmup "$WARMUP" --invocation "$round" \
        --environment "$LABEL" --out "$OUT"
    done
  done
  for c in pyjwt_string pyjwt_preparsed; do
    run "$L/python/.venv/bin/python" "$L/python/crosslib.py" --condition "$c" \
      --iterations "$ITERATIONS" --warmup "$WARMUP" --invocation "$round" --environment "$LABEL" --out "$OUT"
  done
  for c in golangjwt_string golangjwt_preparsed; do
    run "$L/go/crosslib-go" -condition "$c" -iterations "$ITERATIONS" -warmup "$WARMUP" \
      -invocation "$round" -environment "$LABEL" -out "$OUT"
  done
  for c in nimbus_string nimbus_preparsed jjwt_string jjwt_preparsed; do
    # JIT warm-up in HotSpot needs more calls than V8's; a 2x warmup is used.
    run java -cp "$L/java/lib/*:$L/java" CrossLib "$c" "$ITERATIONS" "$((WARMUP * 2))" "$round" "$OUT" "$LABEL"
  done
done
psao::finish_metadata "$RUN_DIR" "$status"
psao::log "done: $OUT"
exit "$status"
