#!/usr/bin/env bash
# run_matrix_remote.sh — the key-path matrix, run ON a remote instance.
#
# Deliberately self-contained: it does not source experiments/common.sh, because
# that expects a repository checkout and a Kubernetes cluster. All this needs is
# bench/ and, optionally, docker and nvm. The laptop-side orchestrator
# (experiments/run_keypath_remote.sh) supplies the provenance wrapper.
#
# Runs two families:
#
#   native     nvm-installed Node, no container. The Linux row the laptop cannot
#              provide -- macOS is the only non-containerised environment we had,
#              and it differs from the containers in OS as well as in Node.
#   container  the SAME image tags the laptop used. Identical userland on a
#              different machine, hypervisor and (for x86_64 shapes) ISA, which
#              is what makes this a replication rather than a new experiment.
#
# Every environment label is prefixed with --label so rows from two machines can
# be concatenated without colliding.
#
# Usage:
#   ./run_matrix_remote.sh --out /tmp/psao-out --label oracle-a1 [--mode both]
#       [--rounds 10] [--iterations 20000] [--warmup 10000]

set -uo pipefail

OUT=""; LABEL=""; MODE="both"
ROUNDS=10; ITERATIONS=20000; WARMUP=10000
BENCH="${BENCH_DIR:-$HOME/psao-bench}"
IMAGES="node:18.20.8-alpine node:20-alpine node:26.6.0-alpine node:26.6.0-bookworm"
NODE_VERSIONS="18.20.8 20.20.2 26.6.0"
CONDITIONS="jwt_hs_string jwt_hs_preparsed jwt_hs_string_safe jwt_rs_pem_string jwt_rs_preparsed probe_throws probe_succeeds create_secret_key hmac_string hmac_keyobject decode_only timer_overhead"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --rounds) ROUNDS="$2"; shift 2 ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    --images) IMAGES="$2"; shift 2 ;;
    --node-versions) NODE_VERSIONS="$2"; shift 2 ;;
    --conditions) CONDITIONS="$2"; shift 2 ;;
    --bench) BENCH="$2"; shift 2 ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ -n "$OUT" ] || { echo "--out is required" >&2; exit 2; }
[ -n "$LABEL" ] || { echo "--label is required (e.g. oracle-a1)" >&2; exit 2; }
[ -f "$BENCH/keypath-mechanism.js" ] || { echo "no harness at $BENCH" >&2; exit 2; }

mkdir -p "$OUT"
CSV="$OUT/keypath_mechanism.csv"
LOG="$OUT/run_matrix_remote.log"
ENVCSV="$OUT/environments.csv"
[ -s "$ENVCSV" ] || echo "environment,node_version,openssl_version,libc,arch,kind,image_source,image_id" > "$ENVCSV"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*" | tee -a "$LOG"; }
status=0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Steal before and after. A run bracketed by low steal is usable; one bracketed
# by high steal is an upper bound and must be reported as one.
log "capturing environment (60s steal window -- this is measurement, not waiting)"
bash "$HERE/capture_env.sh" --steal-window 60 > "$OUT/instance_env_before.json" 2>/dev/null || \
  log "WARNING: capture_env.sh failed before the run"

# --- the security precondition, same as the laptop runner --------------------
# The safe patch's timing is only worth having if the patch is still sound on
# this runtime. OpenSSL differs here, and the defence depends on OpenSSL's
# behaviour, so this is a real check rather than a formality.
if command -v node >/dev/null 2>&1; then
  if node "$BENCH/keypath-security-check.js" > "$OUT/security_check.csv" 2>"$OUT/security_check.log"; then
    log "algorithm-confusion check passed on the native runtime"
  else
    log "ERROR: algorithm-confusion expectations violated on this runtime -- see security_check.csv"
    exit 1
  fi
else
  log "WARNING: no native node; skipping the security precondition"
fi

# --- native ------------------------------------------------------------------
if [ "$MODE" = "both" ] || [ "$MODE" = "native" ]; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  for v in $NODE_VERSIONS; do
    BIN="$NVM_DIR/versions/node/v$v/bin/node"
    if [ ! -x "$BIN" ]; then
      log "WARNING: node v$v not installed natively, skipping (run bootstrap.sh)"
      status=1; continue
    fi
    env_label="$LABEL:native-v$v"
    probe="$("$BIN" -e 'console.log([process.version,process.versions.openssl,process.arch].join(","))')"
    echo "$env_label,$(printf '%s' "$probe" | cut -d, -f1),$(printf '%s' "$probe" | cut -d, -f2),native,$(printf '%s' "$probe" | cut -d, -f3),native,nvm,$BIN" >> "$ENVCSV"
    log "native v$v -> $probe"
    for round in $(seq 1 "$ROUNDS"); do
      for c in $CONDITIONS; do
        "$BIN" "$BENCH/keypath-mechanism.js" --condition "$c" \
          --iterations "$ITERATIONS" --warmup "$WARMUP" --invocation "$round" \
          --environment "$env_label" --out "$CSV" >>"$LOG" 2>&1 \
          || { log "WARNING: native v$v $c round $round failed"; status=1; }
      done
      log "  native v$v round $round/$ROUNDS"
    done
  done
fi

# --- container ---------------------------------------------------------------
if [ "$MODE" = "both" ] || [ "$MODE" = "container" ]; then
  if ! docker info >/dev/null 2>&1; then
    log "WARNING: docker unavailable (not installed, or you have not reconnected since bootstrap added you to the docker group); skipping container family"
    status=1
  else
    for image in $IMAGES; do
      # Prefer the registry, but fall back to a local copy. A transient registry
      # hiccup dropping an entire matrix cell is a silent hole in the design, and
      # it happened once during development. The digest recorded below is what
      # removes any ambiguity about which bytes actually ran.
      if docker pull -q "$image" >/dev/null 2>&1; then
        src=registry
      elif docker image inspect "$image" >/dev/null 2>&1; then
        src=local-cache
        log "NOTE: could not reach the registry for $image; using the local copy"
      else
        log "WARNING: $image is neither pullable nor local, skipping"; status=1; continue
      fi
      digest="$(docker image inspect "$image" --format '{{.Id}}' 2>/dev/null)"
      probe="$(docker run --rm --user "$(id -u):$(id -g)" "$image" node -e '
        const fs = require("fs");
        const musl = ["/lib/ld-musl-aarch64.so.1","/lib/ld-musl-x86_64.so.1"].some(p => fs.existsSync(p));
        console.log([process.version, process.versions.openssl, musl ? "musl" : "glibc", process.arch].join(","));
      ' 2>/dev/null)" || { log "WARNING: $image will not run node, skipping"; status=1; continue; }
      env_label="$LABEL:$image"
      echo "$env_label,$probe,container,$src,$digest" >> "$ENVCSV"
      log "container $image -> $probe ($src ${digest:0:19})"
      for round in $(seq 1 "$ROUNDS"); do
        for c in $CONDITIONS; do
          docker run --rm --user "$(id -u):$(id -g)" \
            -v "$BENCH:/bench" -v "$OUT:/out" -w /bench "$image" \
            node /bench/keypath-mechanism.js --condition "$c" \
              --iterations "$ITERATIONS" --warmup "$WARMUP" --invocation "$round" \
              --environment "$env_label" --out "/out/$(basename "$CSV")" \
            >>"$LOG" 2>&1 \
            || { log "WARNING: $image $c round $round failed"; status=1; }
        done
        log "  $image round $round/$ROUNDS"
      done
    done
  fi
fi

log "capturing environment again (60s steal window)"
bash "$HERE/capture_env.sh" --steal-window 60 > "$OUT/instance_env_after.json" 2>/dev/null || \
  log "WARNING: capture_env.sh failed after the run"

log "done (exit $status): $CSV"
exit "$status"
