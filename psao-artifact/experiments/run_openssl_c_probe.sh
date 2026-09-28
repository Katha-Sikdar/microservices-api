#!/usr/bin/env bash
# run_openssl_c_probe.sh — the discarded asymmetric parse in plain C, against
# several OpenSSL versions built identically (item: is it OpenSSL or V8?).
#
# bench/c/openssl-probe.c is compiled once per OpenSSL version, with the same
# compiler and flags, and linked against that version only (rpath, no system
# libcrypto). Each (version, condition) runs as its own process; conditions and
# versions are interleaved WITHIN each round so drift spreads across all of
# them. Each binary reports the OpenSSL version it actually loaded, and the
# analysis refuses rows whose loaded version differs from the one requested.
#
# Usage:
#   experiments/run_openssl_c_probe.sh [--rounds 15] [--iterations 5000]
#        [--warmup 2500] [--versions "3.0.16 3.5.8 ..."] [--label x86_64-vm]
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ROUNDS=15; ITERATIONS=5000; WARMUP=2500; LABEL="${PSAO_ENV_LABEL:-host}"
PREFIX="${PSAO_OPENSSL_PREFIX:-/opt/ossl}"
VERSIONS="3.0.16 3.0.19 3.1.8 3.2.6 3.3.5 3.4.3 3.5.8 3.6.1"
CONDITIONS="full public_tries private_parse error_strings spki_ok timer_overhead"
while [ $# -gt 0 ]; do
  case "$1" in
    --rounds) ROUNDS="$2"; shift 2 ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    --versions) VERSIONS="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done
psao::require gcc python3

RUN_DIR="$(psao::new_run_dir "openssl-c-probe")"
psao::log "run directory: $RUN_DIR"
mkdir -p "$RUN_DIR/bin"
CFLAGS="-O2 -Wall"
echo "openssl_requested,binary,cc,cflags" > "$RUN_DIR/builds.csv"
for v in $VERSIONS; do
  [ -f "$PREFIX/$v/lib/libcrypto.so" ] || psao::die "OpenSSL $v not built under $PREFIX (experiments/build_openssl_versions.sh)"
  gcc $CFLAGS -I"$PREFIX/$v/include" -o "$RUN_DIR/bin/probe-$v" "$PSAO_ROOT/bench/c/openssl-probe.c" \
      -L"$PREFIX/$v/lib" -Wl,-rpath,"$PREFIX/$v/lib" -lcrypto
  echo "$v,bin/probe-$v,\"$(gcc --version | head -1)\",$CFLAGS" >> "$RUN_DIR/builds.csv"
done

PSAO_NAMESPACE="${PSAO_NAMESPACE:-default}" psao::write_metadata "$RUN_DIR" \
  "experiment=openssl-c-probe" "rounds=$ROUNDS" "iterations=$ITERATIONS" "warmup=$WARMUP" \
  "versions=$VERSIONS" "conditions=$CONDITIONS" "environment_label=$LABEL" \
  "cpu_model=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)" \
  "nproc=$(nproc)" "arch=$(uname -m)" "needs_cluster=false" >/dev/null

OUT="$RUN_DIR/openssl_c_probe.csv"
status=0
for round in $(seq 1 "$ROUNDS"); do
  psao::log "round $round/$ROUNDS"
  for v in $VERSIONS; do
    for c in $CONDITIONS; do
      [ -s "$OUT" ] || "$RUN_DIR/bin/probe-$v" --header | sed 's/$/,openssl_requested/' > "$OUT"
      if row="$("$RUN_DIR/bin/probe-$v" "$c" "$ITERATIONS" "$WARMUP" "$round" "$LABEL" 2>>"$RUN_DIR/probe.log")"; then
        echo "$row,$v" >> "$OUT"
      else
        psao::log "WARNING: $v $c round $round failed"; status=1
      fi
    done
  done
done
psao::finish_metadata "$RUN_DIR" "$status"
psao::log "done: $OUT"
exit "$status"
