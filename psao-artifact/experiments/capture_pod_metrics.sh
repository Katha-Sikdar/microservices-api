#!/usr/bin/env bash
# capture_pod_metrics.sh — sample pod CPU (and event-loop lag) at 1-second
# resolution for the duration of an experiment.
#
# WHY NOT `kubectl top`
# --------------------
# `kubectl top pod` reads metrics-server, which aggregates over a ~15 s window
# and only refreshes on its own schedule. Polling it every second returns the
# same stale number about fifteen times. The manuscript's CPU figures came from
# that path, which is why the paper can only report CPU *derived* from a
# scenario average and cannot report CPU **at** the elbow: 15 s is longer than a
# whole ramp step, so no `kubectl top` sample belongs to a single arrival rate.
#
# Two backends give genuine 1 s resolution instead:
#
#   cgroup      (default) reads /sys/fs/cgroup/cpu.stat inside each container and
#               differences the monotonic usage_usec counter. This is the
#               kernel's own accounting, sampled by us, so the averaging window
#               is exactly the interval between two reads.
#   prometheus  queries container_cpu_usage_seconds_total via rate(). Requires a
#               Prometheus scraping cAdvisor. NOTE that rate() over a 15 s scrape
#               interval has the same resolution problem as metrics-server, so
#               the window is configurable and is written into the CSV header.
#
# Output: <out>/pod_cpu_samples.csv
#   t_unix,pod,container,cpu_millicores,eventloop_lag_p99_ms
# eventloop_lag_p99_ms is populated only for the application container and only
# when PSAO_METRICS_URL is reachable; otherwise the field is EMPTY, never zero.
# An empty field means "not measured"; a zero would be a measurement.
#
# Written for bash 3.2 (the macOS system bash): no associative arrays.
#
# Usage:
#   experiments/capture_pod_metrics.sh --out DIR [--duration SECONDS]
#                                      [--interval SECONDS] [--selector SEL]
#                                      [--namespace NS] [--backend cgroup|prometheus]
#                                      [--metrics-url URL]
# Stop early with SIGINT/SIGTERM; the CSV is flushed line by line.

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

OUT_DIR=""
DURATION=0                       # 0 = until killed
INTERVAL="${PSAO_SAMPLE_INTERVAL:-1}"
SELECTOR="${PSAO_SELECTOR:-app=service-a}"
NAMESPACE="${PSAO_NAMESPACE:-default}"
BACKEND="${PSAO_CPU_BACKEND:-cgroup}"
APP_CONTAINER="${PSAO_APP_CONTAINER:-service-a}"
METRICS_URL="${PSAO_METRICS_URL:-}"
PROM_URL="${PSAO_PROMETHEUS_URL:-http://localhost:9090}"
PROM_WINDOW="${PSAO_PROM_RATE_WINDOW:-15s}"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT_DIR="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --selector) SELECTOR="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --backend) BACKEND="$2"; shift 2 ;;
    --metrics-url) METRICS_URL="$2"; shift 2 ;;
    -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

[ -n "$OUT_DIR" ] || psao::die "--out is required"
mkdir -p "$OUT_DIR"
CSV="$OUT_DIR/pod_cpu_samples.csv"
STATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/psao-cpu.XXXXXX")"
trap 'rm -rf "$STATE_DIR"' EXIT

psao::require kubectl python3

{
  printf '# pod CPU samples, backend=%s interval=%ss selector=%s namespace=%s\n' \
    "$BACKEND" "$INTERVAL" "$SELECTOR" "$NAMESPACE"
  if [ "$BACKEND" = "prometheus" ]; then
    printf '# prometheus rate() window = %s -- this, not the sample interval, is the true resolution\n' "$PROM_WINDOW"
  fi
  printf 't_unix,pod,container,cpu_millicores,eventloop_lag_p99_ms\n'
} > "$CSV"

RUNNING=1
trap 'RUNNING=0' INT TERM

now_unix() { python3 -c 'import time; print(repr(time.time()))'; }

# --- event-loop lag -----------------------------------------------------------
# Scraped from the application's own /metrics endpoint
# (instrumentation/eventloop-metrics.js). Empty when unreachable.
# MUST NOT be able to fail. This runs under `set -euo pipefail` (inherited from
# common.sh), so an unguarded failing pipeline here does not merely lose one lag
# reading -- it terminates the sampler. It is called once per iteration BEFORE
# the per-pod loop, so a single transient scrape failure on the first iteration
# leaves pod_cpu_samples.csv containing nothing but its header, for the whole
# run, with no error anywhere. That is exactly what happened to the first S1
# ramp: ten minutes of load, zero CPU samples, and a merge that could only say
# "0 with CPU attributed" afterwards.
#
# The lag column is optional enrichment. The CPU samples are the measurement.
# Nothing optional is allowed to take the measurement down with it.
read_eventloop_lag() {
  [ -n "$METRICS_URL" ] || return 0
  { curl -fsS --max-time 1 "$METRICS_URL" 2>/dev/null \
      | awk '/^psao_eventloop_lag_p99_ms([{ ])/ { print $NF; exit }'; } || true
}

# --- cgroup backend -----------------------------------------------------------
# cpu.stat's usage_usec is a monotonic counter of CPU microseconds consumed.
# Differencing successive reads over a known wall interval gives millicores:
#   millicores = (delta_usec / (delta_wall_s * 1e6)) * 1000
# State is kept in files rather than an associative array so this runs under the
# bash 3.2 that ships with macOS.
sample_cgroup() {
  local pods pod containers container now usec statefile prev mc lag
  pods="$(kubectl get pods -n "$NAMESPACE" -l "$SELECTOR" \
    --field-selector=status.phase=Running -o name --request-timeout=3s 2>/dev/null \
    | sed 's|pod/||')"
  [ -n "$pods" ] || return 0
  lag="$(read_eventloop_lag || true)"

  for pod in $pods; do
    containers="$(kubectl get pod "$pod" -n "$NAMESPACE" \
      -o jsonpath='{range .spec.containers[*]}{.name}{"\n"}{end}' \
      --request-timeout=3s 2>/dev/null)"
    for container in $containers; do
      # cgroup v2 first, then v1. A container without a shell (distroless)
      # simply yields no sample rather than a fabricated one.
      usec="$(kubectl exec -n "$NAMESPACE" "$pod" -c "$container" --request-timeout=3s -- \
        sh -c 'awk "/^usage_usec/ {print \$2}" /sys/fs/cgroup/cpu.stat 2>/dev/null ||
               awk "{printf \"%d\", \$1/1000}" /sys/fs/cgroup/cpuacct/cpuacct.usage 2>/dev/null' \
        2>/dev/null | tr -dc '0-9')"
      [ -n "$usec" ] || continue
      now="$(now_unix)"
      statefile="$STATE_DIR/$(printf '%s' "$pod-$container" | tr -c 'A-Za-z0-9' '_')"
      prev=""
      [ -f "$statefile" ] && prev="$(cat "$statefile")"
      printf '%s %s\n' "$usec" "$now" > "$statefile"
      # The first read of a container only establishes a baseline. There is no
      # rate to report yet, and we do not report one.
      [ -n "$prev" ] || continue
      mc="$(printf '%s %s %s\n' "$prev" "$usec" "$now" | python3 -c '
import sys
prev_usec, prev_t, usec, now = sys.stdin.read().split()
dt = float(now) - float(prev_t)
du = int(usec) - int(prev_usec)
print("%.3f" % ((du / 1e6) / dt * 1000.0) if dt > 0 and du >= 0 else "")
')"
      [ -n "$mc" ] || continue
      if [ "$container" = "$APP_CONTAINER" ]; then
        printf '%s,%s,%s,%s,%s\n' "$now" "$pod" "$container" "$mc" "$lag" >> "$CSV"
      else
        printf '%s,%s,%s,%s,\n' "$now" "$pod" "$container" "$mc" >> "$CSV"
      fi
    done
  done
}

# --- prometheus backend -------------------------------------------------------
sample_prometheus() {
  local now query response lag
  now="$(now_unix)"
  lag="$(read_eventloop_lag)"
  query="sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace=\"${NAMESPACE}\",container!=\"\",container!=\"POD\"}[${PROM_WINDOW}])) * 1000"
  response="$(curl -fsS --max-time 3 --get "$PROM_URL/api/v1/query" \
    --data-urlencode "query=$query" 2>/dev/null)" || return 0
  printf '%s' "$response" \
    | PSAO_NOW="$now" PSAO_LAG="$lag" PSAO_APP="$APP_CONTAINER" python3 -c '
import json, os, sys
try:
    doc = json.load(sys.stdin)
except json.JSONDecodeError:
    raise SystemExit(0)
if doc.get("status") != "success":
    raise SystemExit(0)
now = os.environ["PSAO_NOW"]
lag = os.environ["PSAO_LAG"]
app = os.environ["PSAO_APP"]
for series in doc["data"]["result"]:
    labels = series["metric"]
    pod = labels.get("pod", "")
    container = labels.get("container", "")
    value = series["value"][1]
    print(",".join([now, pod, container, value, lag if container == app else ""]))
' >> "$CSV"
}

psao::log "sampling pod CPU into $CSV (backend=$BACKEND, interval=${INTERVAL}s, duration=${DURATION}s)"
[ -n "$METRICS_URL" ] || psao::log "PSAO_METRICS_URL unset: eventloop_lag_p99_ms will be left empty"

START="$(now_unix)"
while [ "$RUNNING" -eq 1 ]; do
  # A failed iteration is a lost second, not a lost run. Without this, any
  # non-zero exit anywhere inside the sampler (a kubectl exec that times out
  # while the node is saturated -- which is precisely when the samples matter
  # most) would kill the sampler under `set -e` and silently truncate the
  # dataset at that point.
  case "$BACKEND" in
    cgroup) sample_cgroup || psao::log "WARNING: CPU sample iteration failed; continuing" ;;
    prometheus) sample_prometheus || psao::log "WARNING: CPU sample iteration failed; continuing" ;;
    *) psao::die "unknown backend: $BACKEND" ;;
  esac
  if [ "$DURATION" != "0" ]; then
    if [ "$(python3 -c "import time; print(1 if time.time() - $START >= $DURATION else 0)")" = "1" ]; then
      break
    fi
  fi
  sleep "$INTERVAL"
done

psao::log "wrote $(($(wc -l < "$CSV") - 2)) CPU sample lines to $CSV"
