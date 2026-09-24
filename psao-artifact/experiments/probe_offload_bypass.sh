#!/usr/bin/env bash
# probe_offload_bypass.sh — measure the offload trust-boundary bypass, both ways.
#
# verify_offload_safety.sh asserts the guard WORKS. It cannot show what the guard
# is for, because it never runs without it. This runs the same four probes in
# both configurations and writes a CSV, so the bypass is a recorded measurement
# rather than a remembered observation:
#
#   guarded    EnvoyFilter psao-strip-untrusted-payload-header APPLIED
#   unguarded  the same filter REMOVED  <-- the vulnerable configuration
#
# The negative control is the guarded row for probe `forged_header_only`: it must
# REFUSE. If guarded and unguarded do not differ on that probe, this script has
# measured nothing and says so.
#
# It re-applies the guard on exit, including on failure or interrupt.
#
# NOT `set -e`: a probe returning a failure status is DATA, not an error, and
# three runs in this study were silently truncated by an early exit. Every probe
# records a row even when curl fails; the row carries 000.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

URL="${PSAO_BASE_URL:-https://localhost}"
NS="${PSAO_NAMESPACE:-default}"
FILTER="psao-strip-untrusted-payload-header"
MANIFEST="$PSAO_ROOT/controller/strip-untrusted-payload-header.yaml"
TOKEN_FILE="${PSAO_TOKEN_FILE:-$PSAO_ROOT/tokens/pool.txt}"

RUN_DIR="$(psao::new_run_dir "offload-bypass-probe")"
OUT="$RUN_DIR/offload_probe.csv"
psao::log "run directory: $RUN_DIR"

restore() {
  kubectl get envoyfilter "$FILTER" -n "$NS" >/dev/null 2>&1 || {
    psao::log "restoring guard EnvoyFilter"
    kubectl apply -f "$MANIFEST" >/dev/null 2>&1 && psao::log "  restored" || psao::log "  RESTORE FAILED -- apply $MANIFEST by hand"
  }
}
trap restore EXIT INT TERM

TOKEN="$(head -1 "$TOKEN_FILE" 2>/dev/null)"
[ -n "$TOKEN" ] || psao::die "no token in $TOKEN_FILE (run: make tokens)"
FORGED="$(python3 -c 'import base64,json; print(base64.urlsafe_b64encode(json.dumps({"sub":"attacker","name":"not authenticated"}).encode()).decode().rstrip("="))')"

status() { curl -k -s -o /dev/null -m 10 -w '%{http_code}' "$@" "$URL/products" 2>/dev/null || echo 000; }

echo "configuration,probe,expected,observed,verdict,meaning" > "$OUT"
row() { # config probe expected observed meaning
  local v=PASS; [ "$4" = "$3" ] || v=DIFFERS
  printf '%s,%s,%s,%s,%s,"%s"\n' "$1" "$2" "$3" "$4" "$v" "$5" >> "$OUT"
  printf '    %-10s %-28s expect=%-3s got=%-3s %s\n' "$1" "$2" "$3" "$4" "$v"
}

probe_all() { # configuration expected_for_forged
  local cfg="$1" want_forged="$2"
  psao::log "  probing: $cfg"
  row "$cfg" forged_header_only          "$want_forged" "$(status -H "x-psao-jwt-payload: $FORGED")" \
      "no Authorization at all, only a hand-written claims header. 200 here is a complete authentication bypass"
  row "$cfg" valid_token                 200 "$(status -H "Authorization: Bearer $TOKEN")" \
      "the normal path must keep working"
  row "$cfg" valid_token_plus_forged     200 "$(status -H "Authorization: Bearer $TOKEN" -H "x-psao-jwt-payload: !!!not-base64-json!!!")" \
      "handler fails closed on a malformed header, so 200 proves the client value never reached it"
  row "$cfg" no_credentials              401 "$(status)" \
      "baseline refusal"
}

psao::log "offload trust-boundary probe against $URL"
kubectl get envoyfilter "$FILTER" -n "$NS" >/dev/null 2>&1 || kubectl apply -f "$MANIFEST" >/dev/null 2>&1
sleep 3
probe_all guarded 401

# Envoy applies a config change asynchronously. A fixed sleep here recorded a
# guarded response as an unguarded one on the first attempt of this experiment --
# a complete-looking CSV carrying a wrong value, which is the failure mode this
# study keeps hitting. Poll until the observable behaviour CHANGES from the
# guarded baseline, with a timeout, and record how long it took. Waiting for a
# change rather than for an expected value keeps this non-circular: whatever it
# settles to is what gets recorded.
BASELINE="$(awk -F, '$1=="guarded"&&$2=="forged_header_only"{print $4}' "$OUT")"
psao::log "  REMOVING the guard -- entering the vulnerable configuration"
kubectl delete envoyfilter "$FILTER" -n "$NS" >/dev/null 2>&1
SETTLE=""
for i in $(seq 1 12); do
  sleep 5
  now="$(status -H "x-psao-jwt-payload: $FORGED")"
  if [ "$now" != "$BASELINE" ]; then SETTLE=$((i*5)); break; fi
done
if [ -n "$SETTLE" ]; then
  psao::log "  configuration settled after ${SETTLE}s (response changed from $BASELINE)"
else
  psao::log "  WARNING: response never changed from $BASELINE in 60s; recording anyway"
  SETTLE="not_observed"
fi
probe_all unguarded 200

psao::log "  re-applying the guard"
kubectl apply -f "$MANIFEST" >/dev/null 2>&1
for i in $(seq 1 12); do
  sleep 5
  [ "$(status -H "x-psao-jwt-payload: $FORGED")" = "$BASELINE" ] && { psao::log "  guard back in effect after $((i*5))s"; break; }
done

G="$(awk -F, '$1=="guarded"&&$2=="forged_header_only"{print $4}' "$OUT")"
U="$(awk -F, '$1=="unguarded"&&$2=="forged_header_only"{print $4}' "$OUT")"
psao::log "negative control: guarded=$G unguarded=$U (settle ${SETTLE}s)"
echo "settle_seconds,$SETTLE" >> "$RUN_DIR/probe_timing.csv"
if [ "$G" = "$U" ]; then
  psao::log "  INCONCLUSIVE: the two configurations did not differ; this measured nothing"
else
  psao::log "  the guard is what distinguishes them"
fi

PSAO_NAMESPACE="$NS" psao::write_metadata "$RUN_DIR" \
  "experiment=offload-bypass-probe" "base_url=$URL" "needs_cluster=true" >/dev/null
psao::finish_metadata "$RUN_DIR" 0
psao::log "done: $OUT"
