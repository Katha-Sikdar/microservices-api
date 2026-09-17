#!/usr/bin/env bash
# run_keypath_container.sh — the same key-path measurement, across runtimes.
#
# WHY THIS EXISTS. The manuscript compares an isolated host microbenchmark
# against in-container measurements and attributes the gap to deployment. Those
# two environments differ in more than deployment:
#
#     host       Node v26.6.0, OpenSSL 3.6.3, macOS/arm64
#     container  Node v18.20.8, OpenSSL 3.0.16, Alpine musl/aarch64
#
# (service-a/Dockerfile is FROM node:18-alpine; run_metadata.json's
# `node_version` is `node --version` on the HOST -- common.sh:559 -- so every
# in-situ run recorded 26.6.0 for a service that was running 18.20.8.)
#
# Two Node majors and two OpenSSL majors is a confound at least the size of the
# one being reported. This runner holds containerisation constant and varies
# Node version and libc independently, so the effects can be separated instead
# of summed.
#
# Usage:
#   experiments/run_keypath_container.sh [--rounds 10] [--iterations 20000]
#       [--warmup 10000] [--images "a b c"] [--conditions "x y"] [--run-dir DIR]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ROUNDS=10
ITERATIONS=20000
WARMUP=10000
RUN_DIR_ARG=""
# node:18.20.8-alpine is the deployed service's runtime, exactly. The other
# three complete a 2x2 of (Node major) x (libc), so neither can be mistaken for
# the other.
IMAGES="node:18.20.8-alpine node:18.20.8-bookworm node:26.6.0-alpine node:26.6.0-bookworm"
CONDITIONS="jwt_hs_string jwt_hs_preparsed jwt_hs_string_safe probe_throws probe_succeeds create_secret_key hmac_string hmac_keyobject decode_only timer_overhead"

while [ $# -gt 0 ]; do
  case "$1" in
    --rounds) ROUNDS="$2"; shift 2 ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    --images) IMAGES="$2"; shift 2 ;;
    --conditions) CONDITIONS="$2"; shift 2 ;;
    --run-dir) RUN_DIR_ARG="$2"; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

psao::require docker

docker info >/dev/null 2>&1 || psao::die "docker is not responding (paused?)"

if [ -n "$RUN_DIR_ARG" ]; then
  RUN_DIR="$RUN_DIR_ARG"; mkdir -p "$RUN_DIR"
else
  RUN_DIR="$(psao::new_run_dir "keypath-runtime-matrix")"
fi
psao::log "run directory: $RUN_DIR"

OUT="$RUN_DIR/keypath_mechanism.csv"

# bench/ is mounted read-WRITE because keypath-patch.js materialises the patched
# library under bench/node_modules/.keypath/, and it must live there: a copy
# anywhere else would resolve require('jws') to a different tree, or to nothing.
# --user keeps those files owned by the invoking user rather than by root.
DOCKER_UID="$(id -u):$(id -g)"

# Record what each image actually is, rather than trusting its tag. APPENDED,
# never truncated: this runner is designed to be re-invoked against an existing
# --run-dir to add a cell, and truncating here would erase the record of every
# image already measured while leaving their rows in keypath_mechanism.csv.
if [ ! -s "$RUN_DIR/environments.csv" ]; then
  echo "image,node_version,openssl_version,libc,arch,image_source,image_id" > "$RUN_DIR/environments.csv"
fi

status=0
for image in $IMAGES; do
  psao::log "pulling $image"
  # Fall back to a local copy when the registry is briefly unreachable: a
  # transient hiccup should not silently remove a cell from the matrix.
  if docker pull -q "$image" >/dev/null 2>&1; then
    img_src=registry
  elif docker image inspect "$image" >/dev/null 2>&1; then
    img_src=local-cache
    psao::log "  NOTE: registry unreachable for $image; using the local copy"
  else
    psao::log "WARNING: $image is neither pullable nor local, skipping"; status=1; continue
  fi
  img_id="$(docker image inspect "$image" --format '{{.Id}}' 2>/dev/null)"

  probe="$(docker run --rm --user "$DOCKER_UID" "$image" node -e '
    const os = require("os");
    let libc = "unknown";
    try {
      libc = require("fs").existsSync("/lib/ld-musl-aarch64.so.1")
          || require("fs").existsSync("/lib/ld-musl-x86_64.so.1") ? "musl" : "glibc";
    } catch (_) {}
    console.log([process.version, process.versions.openssl, libc, process.arch].join(","));
  ' 2>/dev/null)" || { psao::log "WARNING: $image will not run node, skipping"; status=1; continue; }
  echo "$image,$probe,$img_src,$img_id" >> "$RUN_DIR/environments.csv"
  psao::log "  $image -> $probe"

  # One `docker run` per (condition, round), mirroring the host runner: one
  # process per measurement, conditions interleaved within each round.
  for round in $(seq 1 "$ROUNDS"); do
    for condition in $CONDITIONS; do
      docker run --rm --user "$DOCKER_UID" \
        -v "$PSAO_ROOT/bench:/bench" -v "$RUN_DIR:/out" \
        -w /bench "$image" \
        node /bench/keypath-mechanism.js \
          --condition "$condition" --iterations "$ITERATIONS" \
          --warmup "$WARMUP" --invocation "$round" \
          --environment "$image" --out "/out/$(basename "$OUT")" \
        >> "$RUN_DIR/keypath_container.log" 2>&1 \
        || { psao::log "WARNING: $image $condition round $round failed"; status=1; }
    done
    psao::log "  $image round $round/$ROUNDS"
  done
done

if [ -z "$RUN_DIR_ARG" ]; then
  PSAO_NAMESPACE="${PSAO_NAMESPACE:-default}" psao::write_metadata "$RUN_DIR" \
    "experiment=keypath-runtime-matrix" \
    "rounds=$ROUNDS" "iterations=$ITERATIONS" "warmup=$WARMUP" \
    "images=$IMAGES" "conditions=$CONDITIONS" \
    "docker_server_version=$(docker info --format '{{.ServerVersion}}')" \
    "docker_cpus=$(docker info --format '{{.NCPU}}')" \
    "needs_cluster=false" >/dev/null
  psao::finish_metadata "$RUN_DIR" "$status"
fi

psao::log "done: $OUT"
exit "$status"
