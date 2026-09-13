#!/usr/bin/env bash
# verify_offload_safety.sh — regression test for the PSAO offload trust boundary.
#
# service-a trusts x-psao-jwt-payload and skips signature verification when it is
# present. That is what makes PSAO a relocation of verification rather than a
# duplication of it -- and it means the security of the service now depends on a
# client being unable to set that header.
#
# This was a real bypass, not a theoretical one. Before
# controller/strip-untrusted-payload-header.yaml existed, with no offload policy
# applied and no Authorization header at all:
#
#   curl -H "x-psao-jwt-payload: eyJzdWIiOiAiYXR0YWNrZXIifQ" https://localhost/products
#   -> 200, with the protected payload
#
# Run this after any change to the handler, the policy template, the EnvoyFilter,
# or the mesh posture. It exits non-zero on the first failure.
#
# Usage: experiments/verify_offload_safety.sh [--base-url https://localhost]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

BASE_URL="${PSAO_BASE_URL:-https://localhost}"
REQ_PATH="${PSAO_PATH:-/products}"
NAMESPACE="${PSAO_NAMESPACE:-default}"
TOKEN_FILE="${PSAO_TOKEN_FILE:-$PSAO_ROOT/tokens/hs256.token}"

while [ $# -gt 0 ]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    --token-file) TOKEN_FILE="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

psao::require curl kubectl python3

URL="${BASE_URL}${REQ_PATH}"
FORGED="$(python3 -c 'import base64,json; print(base64.urlsafe_b64encode(json.dumps({"sub":"attacker","name":"not authenticated"}).encode()).decode().rstrip("="))')"
FAILED=0

status() {
  curl -k -s -o /dev/null -m 10 -w '%{http_code}' "$@" "$URL" 2>/dev/null || echo 000
}

check() {
  local label="$1" want="$2" got="$3"
  if [ "$got" = "$want" ]; then
    psao::log "  OK   $label -> $got"
  else
    psao::log "  FAIL $label -> $got (expected $want)"
    FAILED=1
  fi
}

# --- the guard must exist ------------------------------------------------------
if kubectl get envoyfilter psao-strip-untrusted-payload-header -n "$NAMESPACE" \
     --request-timeout=10s >/dev/null 2>&1; then
  psao::log "  OK   EnvoyFilter psao-strip-untrusted-payload-header is present"
else
  psao::log "  FAIL EnvoyFilter psao-strip-untrusted-payload-header is MISSING in '$NAMESPACE'"
  psao::log "       kubectl apply -f controller/strip-untrusted-payload-header.yaml"
  FAILED=1
fi

psao::log "offload trust-boundary checks against $URL"

# --- the bypass itself ---------------------------------------------------------
# No Authorization header, only a forged payload header. Must NOT be served.
# 401 (no offload policy) and 403 (offload policy applied, RBAC rejects) are both
# correct refusals; 200 is the bypass.
FORGED_ONLY="$(status -H "x-psao-jwt-payload: $FORGED")"
if [ "$FORGED_ONLY" = "401" ] || [ "$FORGED_ONLY" = "403" ]; then
  psao::log "  OK   forged payload header alone -> $FORGED_ONLY (refused)"
else
  psao::log "  FAIL forged payload header alone -> $FORGED_ONLY"
  psao::log "       AUTHENTICATION BYPASS: a client set the trusted header and was served."
  FAILED=1
fi

# --- the normal paths must still work -----------------------------------------
if [ -r "$TOKEN_FILE" ]; then
  TOKEN="$(head -n 1 "$TOKEN_FILE" | tr -d '\r\n')"
  check "valid token" 200 "$(status -H "Authorization: Bearer $TOKEN")"
  # A deliberately malformed forged header alongside a valid token. If the
  # client's value were reaching the handler, its JSON.parse would fail closed
  # with 500; 200 means the header was stripped or overwritten before arrival.
  check "valid token + malformed forged header" 200 \
    "$(status -H "Authorization: Bearer $TOKEN" -H 'x-psao-jwt-payload: !!!not-base64-json!!!')"
else
  psao::log "  SKIP token checks: $TOKEN_FILE not readable"
fi

check "no credentials at all" 401 "$(status)"

if [ "$FAILED" -ne 0 ]; then
  psao::die "offload trust-boundary verification FAILED"
fi
psao::log "offload trust boundary verified"
