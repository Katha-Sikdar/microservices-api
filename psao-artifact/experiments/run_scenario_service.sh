#!/usr/bin/env bash
# run_scenario_service.sh — swap which implementation sits behind the service-a
# Service, then ramp it.
#
# S8 (token cache) and S9 (node:cluster) are defined as "S5 with a different
# service". Keeping the Service, the Ingress, the edge TLS and the mTLS leg
# identical, and changing ONLY the pod behind them, is what puts their numbers
# on the same axis as S5's.
#
# Three Deployments carry the label app=service-a:
#   service-a-deployment       S5 (and S1/S3 via PSAO_AUTH_MODE)
#   service-a-s8-deployment    S8
#   service-a-s9-deployment    S9
#
# The Service selects on app=service-a alone, so if two of them are up at once
# it load-balances across two different implementations and the ramp measures a
# blend. This script therefore scales the others to zero FIRST, waits for their
# endpoints to actually disappear, and refuses to start the ramp unless exactly
# one pod is backing the Service.
#
# Usage:
#   experiments/run_scenario_service.sh --scenario S8 [--max-rps 1000]
#       [--step-rps 50] [--step-duration 30s] [--no-ramp]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SCENARIO=""
MAX_RPS="${PSAO_MAX_RPS:-1000}"
STEP_RPS="${PSAO_STEP_RPS:-50}"
STEP_DURATION="${PSAO_STEP_DURATION:-30s}"
NAMESPACE="${PSAO_NAMESPACE:-default}"
NO_RAMP=""

while [ $# -gt 0 ]; do
  case "$1" in
    --scenario) SCENARIO="$2"; shift 2 ;;
    --max-rps) MAX_RPS="$2"; shift 2 ;;
    --step-rps) STEP_RPS="$2"; shift 2 ;;
    --step-duration) STEP_DURATION="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --no-ramp) NO_RAMP="1"; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

[ -n "$SCENARIO" ] || psao::die "--scenario is required (S5 | S8 | S9)"
psao::require kubectl k6 python3

ALL_DEPLOYMENTS=(service-a-deployment service-a-s8-deployment service-a-s9-deployment)

case "$(printf '%s' "$SCENARIO" | tr '[:upper:]' '[:lower:]')" in
  s5) WANT="service-a-deployment" ;;
  s8) WANT="service-a-s8-deployment" ;;
  s9) WANT="service-a-s9-deployment" ;;
  *)  psao::die "this script handles S5, S8 and S9; got '$SCENARIO'" ;;
esac

restore_s5() {
  local status=$?
  if [ "$WANT" != "service-a-deployment" ]; then
    psao::log "restoring S5 as the service behind service-a"
    kubectl -n "$NAMESPACE" scale "deploy/$WANT" --replicas=0 --request-timeout=60s >/dev/null || true
    kubectl -n "$NAMESPACE" scale deploy/service-a-deployment --replicas=1 --request-timeout=60s >/dev/null || true
    kubectl -n "$NAMESPACE" rollout status deploy/service-a-deployment --timeout=180s || true
  fi
  return $status
}
trap restore_s5 EXIT

# --- scale everything else down ----------------------------------------------
for d in "${ALL_DEPLOYMENTS[@]}"; do
  [ "$d" = "$WANT" ] && continue
  if kubectl -n "$NAMESPACE" get "deploy/$d" --request-timeout=10s >/dev/null 2>&1; then
    psao::log "scaling down $d"
    kubectl -n "$NAMESPACE" scale "deploy/$d" --replicas=0 --request-timeout=60s >/dev/null
  fi
done

psao::log "scaling up $WANT"
kubectl -n "$NAMESPACE" scale "deploy/$WANT" --replicas=1 --request-timeout=60s >/dev/null
kubectl -n "$NAMESPACE" rollout status "deploy/$WANT" --timeout=240s

# --- refuse to measure a blend ------------------------------------------------
# Endpoints, not pods: what matters is what the Service is actually sending
# traffic to. A terminating pod can linger in the pod list long after it has
# left the endpoint set, and a new one can be in the pod list before it joins.
psao::log "waiting for exactly one endpoint behind the service-a Service"
waited=0
while [ "$waited" -lt 120 ]; do
  eps="$(psao::try kubectl get endpoints service-a -n "$NAMESPACE" --request-timeout=10s \
    -o jsonpath='{range .subsets[*].addresses[*]}{.ip}{" "}{end}')"
  count="$(printf '%s' "$eps" | tr ' ' '\n' | grep -c . || true)"
  if [ "$count" = "1" ]; then
    psao::log "service-a endpoints: $eps (1 pod, as required)"
    break
  fi
  sleep 2
  waited=$((waited + 2))
done
[ "${count:-0}" = "1" ] || psao::die "service-a has ${count:-0} endpoints ($eps); refusing to ramp a blend of implementations"

# Confirm which implementation is actually answering. Derived from the
# ENDPOINT's targetRef, not from `.items[0]` of a label query: a scaled-down
# Deployment's pod stays in the pod list, and Running, for a while after it has
# left the endpoint set, so `.items[0]` reports the wrong implementation exactly
# during the window this check exists to cover. The endpoint is what the Service
# actually routes to, which is the thing being asserted.
serving_pod="$(psao::try kubectl get endpoints service-a -n "$NAMESPACE" \
  --request-timeout=10s \
  -o jsonpath='{.subsets[0].addresses[0].targetRef.name}')"
[ -n "$serving_pod" ] || psao::die "could not resolve the pod behind the service-a Service"
serving_scenario="$(psao::try kubectl get pod "$serving_pod" -n "$NAMESPACE" \
  --request-timeout=10s -o jsonpath='{.metadata.labels.psao-scenario}')"
psao::log "serving pod: $serving_pod (psao-scenario=${serving_scenario:-s5})"

# And assert it is the one asked for, rather than merely reporting it.
want_scenario="$(printf '%s' "$SCENARIO" | tr '[:upper:]' '[:lower:]')"
if [ "$want_scenario" != "s5" ] && [ "${serving_scenario:-s5}" != "$want_scenario" ]; then
  psao::die "asked for $SCENARIO but the Service is routing to psao-scenario=${serving_scenario:-s5}"
fi

# The CPU sampler selects on app=service-a, which also matches the pod of the
# Deployment just scaled to zero until it finishes terminating. Both pods run a
# container named service-a, so an overlap would attribute the old pod's CPU to
# this scenario's early steps. It is idle, so the error is small -- but waiting
# removes it rather than arguing about its size.
psao::log "waiting for any scaled-down service-a pods to finish terminating"
waited=0
while [ "$waited" -lt 120 ]; do
  others="$(psao::try kubectl get pods -n "$NAMESPACE" -l app=service-a \
    --request-timeout=10s -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
    | grep -c . || true)"
  [ "${others:-0}" -le 1 ] && break
  sleep 3
  waited=$((waited + 3))
done
psao::log "service-a pods present: ${others:-unknown}"

if [ -n "$NO_RAMP" ]; then
  psao::log "--no-ramp given; leaving $WANT up and stopping here"
  trap - EXIT
  exit 0
fi

# --- posture + ramp -----------------------------------------------------------
# S8 and S9 are "S5 with a different service", so the mesh posture must be the
# full one. Proven, not assumed.
"$PSAO_ROOT/experiments/set_mesh_posture.sh" --verify

"$PSAO_ROOT/experiments/run_openloop_ramp.sh" \
  --scenario "$SCENARIO" --environment local \
  --max-rps "$MAX_RPS" --step-rps "$STEP_RPS" --step-duration "$STEP_DURATION" \
  --base-url "https://localhost" --token-pool "$PSAO_ROOT/tokens/pool.txt"

psao::log "$SCENARIO ramp complete"
