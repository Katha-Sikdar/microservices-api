#!/usr/bin/env bash
# run_keypath_remote.sh — run the key-path matrix on a remote machine and bring
# the results back. Runs on the LAPTOP.
#
# WHY REMOTE AT ALL. Everything measured so far is one machine: Apple silicon,
# arm64, Docker Desktop. The finding -- that OpenSSL 3.0 makes a per-request
# createPublicKey() probe cost ~400 us where OpenSSL 3.5 costs ~20 us -- is
# either a property of that library or a property of that laptop, and only a
# second machine can tell the difference. An Oracle Cloud Always Free instance
# gives a different hypervisor (KVM rather than Apple Virtualization), a
# different OS, and on the AMD shapes a different instruction set.
#
# PROVENANCE. This deliberately does NOT call psao::write_metadata. That helper
# records the LOCAL cluster, Istio version and `node --version` -- and recording
# local state for a measurement taken elsewhere is exactly the mistake that put
# "Node.js is v26.6.0" in the manuscript for a service running v18.20.8. The
# authoritative provenance for a remote run is instance_env_before.json /
# instance_env_after.json, captured ON the instance.
#
# Usage:
#   experiments/run_keypath_remote.sh --host opc@1.2.3.4 --label oracle-a1 \
#       [--key ~/.ssh/oracle] [--bootstrap] [--mode both|native|container] \
#       [--rounds 10] [--iterations 20000] [--warmup 10000]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

HOST=""; LABEL=""; KEY=""; MODE="both"; BOOTSTRAP=0
ROUNDS=10; ITERATIONS=20000; WARMUP=10000
REMOTE_DIR="psao-bench"

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --key) KEY="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --bootstrap) BOOTSTRAP=1; shift ;;
    --rounds) ROUNDS="$2"; shift 2 ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --warmup) WARMUP="$2"; shift 2 ;;
    --remote-dir) REMOTE_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

[ -n "$HOST" ] || psao::die "--host is required (e.g. opc@193.122.0.1)"
[ -n "$LABEL" ] || psao::die "--label is required; it prefixes every environment name so rows from two machines never collide (e.g. oracle-a1, oracle-e2)"

psao::require ssh rsync

# common.sh defines no Python helper; prefer the artifact venv so the steal
# report uses the same interpreter the analysis does.
PSAO_PY="$PSAO_ROOT/.venv/bin/python"
[ -x "$PSAO_PY" ] || PSAO_PY="$(command -v python3 || true)"
[ -n "$PSAO_PY" ] || psao::die "no python3 available for the steal report"

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
[ -n "$KEY" ] && SSH_OPTS+=(-i "$KEY")
ssh_run() { ssh "${SSH_OPTS[@]}" "$HOST" "$@"; }

psao::log "checking $HOST is reachable"
ssh_run true || psao::die "cannot ssh to $HOST (key? security list? instance running?)"

RUN_DIR="$(psao::new_run_dir "keypath-remote-$LABEL")"
psao::log "local run directory: $RUN_DIR"

# --- ship --------------------------------------------------------------------
# bench/node_modules is pure JavaScript (jsonwebtoken -> jws -> jwa -> safe-buffer,
# no native addons), so shipping it verbatim to a different architecture is
# sound AND is the point: the remote machine must run byte-identical library
# code, or a difference in the result could be a difference in the dependency.
psao::log "shipping harness to $HOST:$REMOTE_DIR"
ssh_run "mkdir -p '$REMOTE_DIR'"
RSYNC_OPTS=(-az --delete --exclude '.keypath')
[ -n "$KEY" ] && RSYNC_OPTS+=(-e "ssh ${SSH_OPTS[*]}")
rsync "${RSYNC_OPTS[@]}" "$PSAO_ROOT/bench/" "$HOST:$REMOTE_DIR/"
rsync "${RSYNC_OPTS[@]}" "$PSAO_ROOT/experiments/oracle/" "$HOST:$REMOTE_DIR/oracle/"

if [ "$BOOTSTRAP" -eq 1 ]; then
  psao::log "bootstrapping the instance (docker + node 18/20/26; several minutes)"
  ssh_run "bash '$REMOTE_DIR/oracle/bootstrap.sh'" 2>&1 | tee "$RUN_DIR/bootstrap.log"
  psao::log "bootstrap done; reconnecting so docker group membership takes effect"
fi

# --- run ---------------------------------------------------------------------
REMOTE_OUT="$REMOTE_DIR/out-$(date -u +%Y%m%dT%H%M%SZ)"
psao::log "running the matrix on $HOST (mode=$MODE, $ROUNDS rounds)"
set +e
ssh_run "bash '$REMOTE_DIR/oracle/run_matrix_remote.sh' \
          --out '$REMOTE_OUT' --label '$LABEL' --mode '$MODE' \
          --rounds '$ROUNDS' --iterations '$ITERATIONS' --warmup '$WARMUP' \
          --bench '$REMOTE_DIR'" 2>&1 | tee "$RUN_DIR/remote.log"
remote_status=${PIPESTATUS[0]}
set -e
[ "$remote_status" -eq 0 ] || psao::log "WARNING: remote runner exited $remote_status (partial results are still retrieved below)"

# --- retrieve ----------------------------------------------------------------
psao::log "retrieving results"
rsync "${RSYNC_OPTS[@]}" --no-delete "$HOST:$REMOTE_OUT/" "$RUN_DIR/" 2>/dev/null \
  || rsync -az ${KEY:+-e "ssh ${SSH_OPTS[*]}"} "$HOST:$REMOTE_OUT/" "$RUN_DIR/"

[ -s "$RUN_DIR/keypath_mechanism.csv" ] || psao::die "no measurements came back from $HOST"

# --- provenance, from the instance rather than from here ---------------------
cat > "$RUN_DIR/run_metadata.json" <<JSON
{
  "_note": "Remote run. The authoritative machine description is instance_env_before.json / instance_env_after.json, captured ON the instance. Local cluster/Node fields are deliberately ABSENT: recording them here would describe the wrong machine, which is the error that put the host's Node version in the manuscript for a containerised service.",
  "experiment": "keypath-remote",
  "label": $(printf '"%s"' "$LABEL"),
  "remote_host": $(printf '"%s"' "${HOST%%@*}@<redacted>"),
  "remote_out_dir": $(printf '"%s"' "$REMOTE_OUT"),
  "mode": $(printf '"%s"' "$MODE"),
  "rounds": $ROUNDS,
  "iterations": $ITERATIONS,
  "warmup": $WARMUP,
  "remote_exit_status": $remote_status,
  "artifact_git_commit": $(printf '"%s"' "$(git -C "$PSAO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"),
  "artifact_git_dirty": $(git -C "$PSAO_ROOT" diff --quiet 2>/dev/null && echo false || echo true),
  "started_at_utc": $(printf '"%s"' "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
}
JSON

# --- steal check -------------------------------------------------------------
# Reported, and loudly, because a cloud run with high steal is an upper bound
# rather than a measurement, and nothing downstream can tell that from the CSV.
"$PSAO_PY" - "$RUN_DIR" <<'PYEOF' 2>/dev/null || true
import json, sys, pathlib
d = pathlib.Path(sys.argv[1])
for name in ("instance_env_before.json", "instance_env_after.json"):
    p = d / name
    if not p.exists():
        print(f"  {name}: MISSING"); continue
    try:
        s = json.loads(p.read_text())["steal"]["percent"]
    except Exception:
        print(f"  {name}: unreadable"); continue
    if s is None:
        print(f"  {name}: steal not measured")
    else:
        flag = "  <-- ABOVE 1%: treat absolute figures as upper bounds" if s > 1 else ""
        print(f"  {name}: steal {s}%{flag}")
PYEOF

psao::log "done: $RUN_DIR/keypath_mechanism.csv"
psao::log "analyse with: python3 -m analysis.keypath_stats --run $RUN_DIR"
exit "$remote_status"
