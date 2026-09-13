#!/usr/bin/env bash
# set_mesh_posture.sh — tear the mesh posture down for S1, and put it back.
#
# S1 is defined as the plain-HTTP baseline: no PeerAuthentication, no
# DestinationRule, no TLS on the ingress. Every other scenario here is measured
# with all three in force. That makes the posture a property of the CLUSTER at
# the time of a run rather than of the run's own parameters, which is precisely
# the kind of state that gets mislabelled later.
#
# Two rules this script exists to enforce:
#
#   1. The teardown backs up what it removes, to data/runs/cluster-backup-<ts>/,
#      and the restore re-applies those exact objects. It does not reconstruct
#      them from the manifests in microservices-api/, because what was running
#      is not necessarily what is in a file.
#
#   2. The restore does NOT accept a 200 from the ingress as proof. A 200 is
#      also what you get when STRICT is absent and everything travels in
#      plaintext. It runs psao::verify_mtls_posture, whose third check is a
#      negative control: a plaintext request from a pod with no sidecar must be
#      REFUSED. If any check fails the script exits non-zero, and the caller is
#      expected to abort the remaining runs rather than continue on a 200.
#
# NOTE ON WHAT S1 IS AND IS NOT: this removes the mTLS policy and the edge TLS,
# but it does NOT remove the sidecars. In S1 a request still traverses the
# ingress Envoy and the service-a Envoy, in plaintext. So S3 minus S1 isolates
# the cost of mTLS *crypto and policy*, not the cost of the proxy hop, which is
# present in both. That is arguably the cleaner decomposition, but it is not the
# same claim as "S1 is a mesh-free baseline" and must not be written up as one.
#
# Usage:
#   experiments/set_mesh_posture.sh --posture s1     # tear down
#   experiments/set_mesh_posture.sh --posture full   # restore + verify
#   experiments/set_mesh_posture.sh --verify         # verify only, change nothing

set -euo pipefail
# shellcheck source=common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

POSTURE=""
VERIFY_ONLY=""
NAMESPACE="${PSAO_NAMESPACE:-default}"
INGRESS_NAME="${PSAO_INGRESS_NAME:-my-ingress}"
BASE_URL_HTTPS="${PSAO_BASE_URL:-https://localhost}"
BACKUP_DIR="${PSAO_BACKUP_DIR:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --posture) POSTURE="$2"; shift 2 ;;
    --verify) VERIFY_ONLY="1"; shift ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) psao::die "unknown argument: $1" ;;
  esac
done

psao::require kubectl curl python3

# The most recent backup, so a restore can find what a teardown saved.
PSAO_POSTURE_STATE="$PSAO_ROOT/data/runs/.last_posture_backup"

if [ -n "$VERIFY_ONLY" ]; then
  psao::verify_mtls_posture "$NAMESPACE"
  psao::record_posture_event "verified" "namespace=$NAMESPACE (verify-only)"
  exit 0
fi

[ -n "$POSTURE" ] || psao::die "--posture is required (s1 | full), or pass --verify"

case "$POSTURE" in
# ---------------------------------------------------------------------------
s1)
  psao::record_posture_event "teardown_begin" "namespace=$NAMESPACE target=S1-plain-http"

  if [ -z "$BACKUP_DIR" ]; then
    BACKUP_DIR="$PSAO_ROOT/data/runs/cluster-backup-$(date -u +%Y-%m-%dT%H-%M-%SZ)"
  fi
  mkdir -p "$BACKUP_DIR"
  psao::log "backing up current posture to $BACKUP_DIR"

  # Backed up as-running, then sanitized. `kubectl get -o yaml` carries
  # resourceVersion, generation, status and a stale last-applied-configuration.
  # Those are NOT harmless on re-apply: resourceVersion is an optimistic
  # concurrency token, so re-applying a manifest holding the pre-teardown
  # version fails with "the object has been modified" for any object that still
  # exists. The raw dump is kept alongside, unmodified, as the record of what
  # was actually in force.
  kubectl get peerauthentication -n "$NAMESPACE" -o yaml --request-timeout=15s \
    > "$BACKUP_DIR/peerauthentication.yaml"
  kubectl get destinationrule -n "$NAMESPACE" -o yaml --request-timeout=15s \
    > "$BACKUP_DIR/destinationrule.yaml"
  kubectl get ingress "$INGRESS_NAME" -n "$NAMESPACE" -o yaml --request-timeout=15s \
    > "$BACKUP_DIR/ingress.yaml"

  mkdir -p "$BACKUP_DIR/raw"
  for f in peerauthentication destinationrule ingress; do
    cp "$BACKUP_DIR/$f.yaml" "$BACKUP_DIR/raw/$f.yaml"
    psao::sanitize_manifest "$BACKUP_DIR/$f.yaml"
  done
  printf '%s\n' "$BACKUP_DIR" > "$PSAO_POSTURE_STATE"

  # Prove the backup is restorable BEFORE destroying the live objects. A backup
  # that turns out to be unapplyable after the teardown is not a backup.
  # Dry-run through the SAME path the restore will use. A dry run that exercises
  # client-side apply proves nothing about a restore that uses server-side apply.
  for f in peerauthentication destinationrule ingress; do
    kubectl apply --server-side --force-conflicts --dry-run=server \
      -f "$BACKUP_DIR/$f.yaml" --request-timeout=30s >/dev/null \
      || psao::die "backup $BACKUP_DIR/$f.yaml does not apply cleanly; refusing to tear anything down"
  done
  psao::log "backup verified restorable (server-side dry run)"

  psao::log "removing PeerAuthentication and DestinationRule from '$NAMESPACE'"
  kubectl delete peerauthentication --all -n "$NAMESPACE" --request-timeout=60s || true
  kubectl delete destinationrule --all -n "$NAMESPACE" --request-timeout=60s || true

  psao::log "removing TLS from ingress/$INGRESS_NAME"
  # Removing spec.tls also removes ingress-nginx's automatic 308 redirect to
  # https, which is what makes plain http://localhost/products reachable.
  kubectl patch ingress "$INGRESS_NAME" -n "$NAMESPACE" --type=json --request-timeout=30s \
    -p '[{"op":"remove","path":"/spec/tls"}]' 2>/dev/null \
    || psao::log "ingress had no spec.tls to remove"

  psao::log "waiting for the sidecars to pick up the new configuration"
  sleep 15

  # Positive check for the S1 posture: plaintext must now WORK end to end. This
  # is the mirror image of the restore's negative control.
  psao::log "confirming the plain-HTTP path is live"
  code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' http://localhost/products || echo 000)"
  psao::log "  http://localhost/products -> $code"

  psao::record_posture_event "teardown_complete" \
    "namespace=$NAMESPACE posture=S1-plain-http backup=$BACKUP_DIR http_status=$code"
  psao::log "posture is now S1 (plain HTTP). Restore with: $0 --posture full"
  ;;

# ---------------------------------------------------------------------------
full)
  psao::record_posture_event "restore_begin" "namespace=$NAMESPACE target=full-zero-trust"

  if [ -z "$BACKUP_DIR" ]; then
    [ -f "$PSAO_POSTURE_STATE" ] \
      || psao::die "no backup recorded in $PSAO_POSTURE_STATE; pass --backup-dir explicitly"
    BACKUP_DIR="$(cat "$PSAO_POSTURE_STATE")"
  fi
  [ -d "$BACKUP_DIR" ] || psao::die "backup directory does not exist: $BACKUP_DIR"
  psao::log "restoring posture from $BACKUP_DIR"

  # Server-side apply. Client-side `kubectl apply` needs either a matching
  # resourceVersion or an intact last-applied-configuration annotation to work
  # out what to change, and the sanitized backup deliberately has neither -- it
  # fails with "metadata.resourceVersion: must be specified for an update" on an
  # object that still exists. Server-side apply reconciles from the desired
  # state alone, so the same file both creates a deleted object and updates a
  # surviving one. --force-conflicts takes ownership of fields last written by
  # the teardown's patch.
  for f in peerauthentication destinationrule ingress; do
    kubectl apply --server-side --force-conflicts \
      -f "$BACKUP_DIR/$f.yaml" --request-timeout=60s
  done

  psao::log "waiting for the sidecars to pick up the restored configuration"
  sleep 20

  # --- the part that matters -------------------------------------------------
  # Declared intent, then the negative control. Exits non-zero on any failure.
  if ! psao::verify_mtls_posture "$NAMESPACE"; then
    psao::record_posture_event "verification_failed" "namespace=$NAMESPACE backup=$BACKUP_DIR"
    exit 1
  fi

  # Edge TLS is part of the posture too, and it has its own misleading success:
  # with no spec.tls for the host, ingress-nginx still answers https on its OWN
  # default self-signed certificate, so https://localhost/products returns 200
  # while the configured certificate is not in use at all.
  ing_tls="$(psao::try kubectl get ingress "$INGRESS_NAME" -n "$NAMESPACE" \
    --request-timeout=10s -o jsonpath='{.spec.tls[0].secretName}')"
  if [ -n "$ing_tls" ]; then
    psao::log "edge TLS OK: ingress/$INGRESS_NAME terminates with secret '$ing_tls'"
  else
    psao::log "edge TLS FAILED: ingress/$INGRESS_NAME has no spec.tls."
    psao::log "  https would still answer 200 on nginx's default certificate, so a"
    psao::log "  200 is not evidence here."
    psao::record_posture_event "verification_failed" "namespace=$NAMESPACE reason=ingress-has-no-spec.tls"
    exit 1
  fi

  # Only after the posture is proven is the happy path worth checking at all.
  token_file="$PSAO_ROOT/tokens/hs256.token"
  if [ -r "$token_file" ]; then
    psao::verify_ingress "$BASE_URL_HTTPS" "/products" "200" \
      "$(head -n 1 "$token_file" | tr -d '\r\n')"
  else
    psao::log "WARNING: $token_file not readable; skipping the 200 check"
  fi

  psao::record_posture_event "restore_complete" \
    "namespace=$NAMESPACE posture=full-zero-trust backup=$BACKUP_DIR verified=STRICT+ISTIO_MUTUAL+plaintext-refused"
  psao::log "posture restored and verified."
  ;;

*)
  psao::die "unknown posture '$POSTURE' (expected s1 or full)"
  ;;
esac
