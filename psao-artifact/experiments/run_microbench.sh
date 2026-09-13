#!/usr/bin/env bash
# run_microbench.sh — the JWT stage microbenchmark, with provenance.
#
# `node bench/jwt-path-microbench.js` on its own writes a CSV and nothing else.
# That CSV then sits in data/runs/ looking exactly like a ramp's output while
# carrying none of its provenance: no Node version, no host state, no timer
# overhead, no git commit. The decomposition it produces is the artifact's
# strongest claim about where JWT cost actually goes, so it is the last thing
# that should be unattributable.
#
# This wrapper gives it the same treatment every other runner gets: a timestamped
# run directory, run_metadata.json (including host load -- this benchmark is a
# single CPU-bound process sharing a laptop with whatever else is running), and
# the full console output kept alongside the CSV because the timer overhead is
# reported there and nowhere else.
#
# Needs no cluster. The cluster-dependent fields in run_metadata.json will simply
# be recorded as unavailable, which is correct: they did not apply.
#
# Usage:
#   experiments/run_microbench.sh [--iterations 200000] [--repeat 1]
#
# --repeat runs the benchmark N times into the same directory as
# microbench.run<N>.csv, with microbench.csv left pointing at the first. Use it
# when a stage is near timer resolution and you want to see the spread rather
# than trust one sample -- the sub-3 us stages (HS256 primitive_*, and RS256
# primitive_* at 4 kB) are where that matters.

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ITERATIONS="${PSAO_ITERATIONS:-200000}"
REPEAT=1

while [ $# -gt 0 ]; do
  case "$1" in
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --repeat) REPEAT="$2"; shift 2 ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

psao::require node python3

RUN_DIR="$(psao::new_run_dir "microbench")"
psao::log "run directory: $RUN_DIR"

PSAO_NAMESPACE="${PSAO_NAMESPACE:-default}" psao::write_metadata "$RUN_DIR" \
  "experiment=microbench" \
  "iterations=$ITERATIONS" \
  "repeat=$REPEAT" \
  "needs_cluster=false" >/dev/null

status=0
for i in $(seq 1 "$REPEAT"); do
  out="$RUN_DIR/microbench.run${i}.csv"
  psao::log "microbench pass $i/$REPEAT ($ITERATIONS iterations)"
  # Console output carries the Node version and the measured timer overhead,
  # which appear in no other artifact. Keep it.
  node "$PSAO_ROOT/bench/jwt-path-microbench.js" \
    --iterations "$ITERATIONS" --out "$out" 2>&1 | tee "$RUN_DIR/microbench.run${i}.log"
  rc=${PIPESTATUS[0]}
  [ "$rc" -eq 0 ] || { psao::log "WARNING: pass $i exited $rc"; status=$rc; }
done

# microbench.csv is what the analysis reads; point it at the first pass.
if [ -f "$RUN_DIR/microbench.run1.csv" ]; then
  cp "$RUN_DIR/microbench.run1.csv" "$RUN_DIR/microbench.csv"
else
  psao::die "no microbench output produced"
fi

# With more than one pass, report the spread so a stage sitting near timer
# resolution is visible rather than implied.
if [ "$REPEAT" -gt 1 ]; then
  psao::log "per-stage spread across $REPEAT passes:"
  PSAO_RUN_DIR="$RUN_DIR" python3 - <<'PYEOF'
import csv, glob, os, statistics
d = os.environ["PSAO_RUN_DIR"]
runs = sorted(glob.glob(os.path.join(d, "microbench.run*.csv")))
acc = {}
for f in runs:
    for r in csv.DictReader(open(f)):
        acc.setdefault((r["algorithm"], r["stage"], r["payload_kb"]), []).append(float(r["mean_us"]))
rows = []
for k, v in acc.items():
    if len(v) < 2:
        continue
    spread = 100.0 * (max(v) - min(v)) / statistics.mean(v)
    rows.append((spread, k, v))
rows.sort(reverse=True)
for spread, k, v in rows:
    flag = "  <-- near timer resolution, treat with care" if spread > 10 else ""
    print("    %-6s %-20s %3s kB  mean=%s  spread=%.1f%%%s"
          % (k[0], k[1], k[2], "/".join("%.3f" % x for x in v), spread, flag))
with open(os.path.join(d, "microbench.spread.txt"), "w") as fh:
    for spread, k, v in rows:
        fh.write("%s,%s,%s,%s,%.2f\n" % (k[0], k[1], k[2],
                 "|".join("%.6f" % x for x in v), spread))
PYEOF
fi

psao::finish_metadata "$RUN_DIR" "$status"
psao::log "done: $RUN_DIR/microbench.csv"
exit "$status"
