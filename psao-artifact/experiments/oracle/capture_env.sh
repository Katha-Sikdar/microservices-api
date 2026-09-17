#!/usr/bin/env bash
# capture_env.sh — what machine is this, really? Runs ON the instance.
#
# A free-tier cloud VM is shared tenancy. The number that decides whether a
# timing measurement taken on one is usable is CPU STEAL: time the hypervisor
# gave to somebody else while our vCPU was runnable. Steal inflates every
# duration we record and is invisible in the process's own clock, so it has to
# come from /proc/stat and be reported alongside the result.
#
# Emits JSON on stdout. Fields that cannot be determined are null, never guessed,
# so this is also safe to run on a laptop (most fields will simply read null).
#
# Usage:
#   experiments/oracle/capture_env.sh
#   experiments/oracle/capture_env.sh --steal-window 60

set -uo pipefail

STEAL_WINDOW=0
[ "${1:-}" = "--steal-window" ] && STEAL_WINDOW="${2:-60}"

# JSON string: quoted, or bare null when empty.
jstr() {
  local v="${1:-}"
  if [ -z "$v" ]; then printf 'null'; else
    printf '"%s"' "$(printf '%s' "$v" | tr -d '"\\' | tr '\n' ' ' | sed 's/  *$//')"
  fi
}
# JSON number: bare, or null when empty / non-numeric.
jnum() {
  local v="${1:-}"
  case "$v" in
    ''|*[!0-9.]*) printf 'null' ;;
    *) printf '%s' "$v" ;;
  esac
}

# --- Oracle instance metadata service ---------------------------------------
# Absent on a non-OCI host; these fields then read null, which is correct.
MD="$(curl -s -m 3 -H 'Authorization: Bearer Oracle' \
      'http://169.254.169.254/opc/v2/instance/' 2>/dev/null || true)"
mdfield() {
  [ -n "$MD" ] || return 0
  printf '%s' "$MD" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" | head -1
}
mdnum() {
  [ -n "$MD" ] || return 0
  printf '%s' "$MD" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\([0-9][0-9.]*\).*/\1/p" | head -1
}

OCI_SHAPE="$(mdfield shape)"
OCI_REGION="$(mdfield region)"
OCI_AD="$(mdfield availabilityDomain)"
OCI_OCPUS="$(mdnum ocpus)"
OCI_MEM="$(mdnum memoryInGBs)"
IMDS_OK=false; [ -n "$MD" ] && IMDS_OK=true

# --- machine ----------------------------------------------------------------
CPU_MODEL="$(sed -n 's/^model name[[:space:]]*:[[:space:]]*//p' /proc/cpuinfo 2>/dev/null | head -1)"
[ -n "$CPU_MODEL" ] || CPU_MODEL="$(sed -n 's/^Model[[:space:]]*:[[:space:]]*//p' /proc/cpuinfo 2>/dev/null | head -1)"
[ -n "$CPU_MODEL" ] || CPU_MODEL="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)"
CPU_ARCH="$(uname -m 2>/dev/null)"
CPU_ONLINE="$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null) | head -1 )"
HYPERVISOR="$(systemd-detect-virt 2>/dev/null || echo unknown)"
KERNEL="$(uname -sr 2>/dev/null)"
OSNAME="$( (. /etc/os-release 2>/dev/null && printf '%s' "$PRETTY_NAME") || sw_vers -productVersion 2>/dev/null || true )"
LOADAVG="$( (cut -d' ' -f1-3 /proc/loadavg 2>/dev/null) || (uptime | sed 's/.*averages*: *//') || true )"
DOCKER_V="$(docker info --format '{{.ServerVersion}}' 2>/dev/null || true)"
NODE_V="$(node --version 2>/dev/null || true)"

# --- steal ------------------------------------------------------------------
# /proc/stat cpu: user nice system idle iowait irq softirq steal guest guest_nice
read_cpu() { awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8+$9, $9}' /proc/stat 2>/dev/null; }
STEAL_PCT=""
STEAL_NOTE="not measured (pass --steal-window N)"
if [ "$STEAL_WINDOW" -gt 0 ] 2>/dev/null; then
  before="$(read_cpu)"
  if [ -n "$before" ]; then
    sleep "$STEAL_WINDOW"
    after="$(read_cpu)"
    STEAL_PCT="$(awk -v b="$before" -v a="$after" 'BEGIN{
      split(b,B," "); split(a,A," ");
      dt = A[1]-B[1]; ds = A[2]-B[2];
      if (dt > 0) printf "%.4f", 100*ds/dt;
    }')"
    STEAL_NOTE="measured over ${STEAL_WINDOW}s of wall clock, all CPUs"
  else
    STEAL_NOTE="/proc/stat unavailable on this platform"
  fi
fi

cat <<JSON
{
  "_note": "Captured on the instance by experiments/oracle/capture_env.sh. Nulls are undetermined, never guessed.",
  "captured_at_utc": $(jstr "$(date -u +%Y-%m-%dT%H:%M:%SZ)"),
  "oracle": {
    "shape": $(jstr "$OCI_SHAPE"),
    "region": $(jstr "$OCI_REGION"),
    "availability_domain": $(jstr "$OCI_AD"),
    "ocpus": $(jnum "$OCI_OCPUS"),
    "memory_gb": $(jnum "$OCI_MEM"),
    "imds_reachable": $IMDS_OK
  },
  "cpu": {
    "model": $(jstr "$CPU_MODEL"),
    "arch": $(jstr "$CPU_ARCH"),
    "online": $(jnum "$CPU_ONLINE"),
    "hypervisor": $(jstr "$HYPERVISOR")
  },
  "kernel": $(jstr "$KERNEL"),
  "os": $(jstr "$OSNAME"),
  "loadavg": $(jstr "$LOADAVG"),
  "steal": {
    "percent": $(jnum "$STEAL_PCT"),
    "how": $(jstr "$STEAL_NOTE"),
    "why": "Shared-tenancy vCPU time given to other tenants. It inflates every duration measured here and is invisible to the process's own clock. Above ~1%, treat absolute figures as upper bounds and say so explicitly."
  },
  "docker": $(jstr "$DOCKER_V"),
  "node_native": $(jstr "$NODE_V")
}
JSON
