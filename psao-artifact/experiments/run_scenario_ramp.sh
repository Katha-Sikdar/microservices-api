#!/usr/bin/env bash
# run_scenario_ramp.sh — bring the cluster into a scenario's configuration, ramp
# it, and put the cluster back.
#
# run_openloop_ramp.sh deliberately does not touch the cluster: an automated
# "apply then measure" makes it far too easy to measure a configuration that had
# not finished rolling out. But S1 and S3 are not the configuration the cluster
# sits in, and doing those transitions by hand is how a run ends up mislabelled.
# This script does exactly the transitions, waits for each to land, VERIFIES it,
# and restores afterwards.
#
#   S1   plain HTTP, no mTLS, no edge TLS, no application JWT
#   S3   edge TLS + STRICT mTLS, no application JWT
#   S5   edge TLS + STRICT mTLS + application JWT   (the resting configuration)
#
# The application JWT is switched with PSAO_AUTH_MODE on the deployment rather
# than by swapping images, so every scenario is measured on one digest. See the
# comment block at the top of microservices-api/service-a/index.js.
#
# THE RESTORE IS NOT OPTIONAL AND NOT ASSUMED. After an S1 run this script puts
# the mesh posture back and then proves it: PeerAuthentication STRICT, an
# ISTIO_MUTUAL DestinationRule, and paired probes on one ClusterIP -- in-mesh
# must get a response, out-of-mesh must be refused. If that fails the script
# exits non-zero and says so, because every later run would otherwise be
# measured, and labelled, in the wrong posture.
#
# Usage:
#   experiments/run_scenario_ramp.sh --scenario S1 [--max-rps 1000]
#       [--step-rps 50] [--step-duration 30s] [--keep-posture]

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SCENARIO=""
MAX_RPS="${PSAO_MAX_RPS:-1000}"
STEP_RPS="${PSAO_STEP_RPS:-50}"
STEP_DURATION="${PSAO_STEP_DURATION:-30s}"
NAMESPACE="${PSAO_NAMESPACE:-default}"
DEPLOYMENT="${PSAO_DEPLOYMENT:-service-a-deployment}"
KEEP_POSTURE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --scenario) SCENARIO="$2"; shift 2 ;;
    --max-rps) MAX_RPS="$2"; shift 2 ;;
    --step-rps) STEP_RPS="$2"; shift 2 ;;
    --step-duration) STEP_DURATION="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --keep-posture) KEEP_POSTURE="1"; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

[ -n "$SCENARIO" ] || psao::die "--scenario is required (S1 | S3 | S5)"
psao::require kubectl k6 python3

case "$SCENARIO" in
  S1) AUTH_MODE="none"; POSTURE="s1";   BASE_URL="http://localhost";  RAMP_AUTH="--no-auth" ;;
  S3) AUTH_MODE="none"; POSTURE="full"; BASE_URL="https://localhost"; RAMP_AUTH="--no-auth" ;;
  S5) AUTH_MODE="jwt";  POSTURE="full"; BASE_URL="https://localhost"; RAMP_AUTH="" ;;
  *)  psao::die "this script handles S1, S3 and S5; got '$SCENARIO'" ;;
esac

TORE_DOWN=""

restore_posture() {
  local status=$?
  if [ -n "$TORE_DOWN" ] && [ -z "$KEEP_POSTURE" ]; then
    psao::log "restoring mesh posture after $SCENARIO"
    if ! "$PSAO_ROOT/experiments/set_mesh_posture.sh" --posture full; then
      psao::log ""
      psao::log "############################################################"
      psao::log "# RESTORE FAILED. The cluster is NOT in the full Zero Trust"
      psao::log "# posture. Do not run anything else against it until this is"
      psao::log "# resolved -- later runs would be measured, and labelled, in"
      psao::log "# the wrong posture."
      psao::log "############################################################"
      exit 1
    fi
  fi
  # Leave the application in the configuration the other scenarios expect.
  if [ -z "$KEEP_POSTURE" ] && [ "$AUTH_MODE" != "jwt" ]; then
    psao::log "returning $DEPLOYMENT to PSAO_AUTH_MODE=jwt"
    kubectl -n "$NAMESPACE" set env "deploy/$DEPLOYMENT" PSAO_AUTH_MODE=jwt \
      --request-timeout=60s >/dev/null
    kubectl -n "$NAMESPACE" rollout status "deploy/$DEPLOYMENT" --timeout=180s
  fi
  return $status
}
trap restore_posture EXIT

# --- application layer --------------------------------------------------------
psao::log "setting PSAO_AUTH_MODE=$AUTH_MODE for $SCENARIO"
kubectl -n "$NAMESPACE" set env "deploy/$DEPLOYMENT" "PSAO_AUTH_MODE=$AUTH_MODE" \
  --request-timeout=60s >/dev/null
# Waiting for the rollout is the difference between measuring this scenario and
# measuring whatever mixture of old and new pods happened to be serving.
kubectl -n "$NAMESPACE" rollout status "deploy/$DEPLOYMENT" --timeout=180s

# --- mesh layer ---------------------------------------------------------------
if [ "$POSTURE" = "s1" ]; then
  "$PSAO_ROOT/experiments/set_mesh_posture.sh" --posture s1
  TORE_DOWN="1"
else
  # Not merely assumed: S3 and S5 are defined by mTLS being ON, so prove it is.
  "$PSAO_ROOT/experiments/set_mesh_posture.sh" --verify
fi

# --- ramp ---------------------------------------------------------------------
psao::log "ramping $SCENARIO: ${STEP_RPS}..${MAX_RPS} rps, ${STEP_DURATION} steps, base=$BASE_URL"
RAMP_ARGS=(--scenario "$SCENARIO" --environment local
           --max-rps "$MAX_RPS" --step-rps "$STEP_RPS"
           --step-duration "$STEP_DURATION" --base-url "$BASE_URL")
if [ -n "$RAMP_AUTH" ]; then
  RAMP_ARGS+=("$RAMP_AUTH")
else
  RAMP_ARGS+=(--token-pool "$PSAO_ROOT/tokens/pool.txt")
fi

"$PSAO_ROOT/experiments/run_openloop_ramp.sh" "${RAMP_ARGS[@]}"

psao::log "$SCENARIO ramp complete"
