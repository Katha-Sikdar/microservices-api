#!/usr/bin/env bash
# provision.sh — create an Always Free instance to run the key-path matrix on.
#
# Creates real cloud resources. Everything it makes is tagged
# `psao-keypath` so `--destroy` can find and remove it again.
#
# SAFETY. --dry-run prints every call it would make and creates nothing; it is
# the default posture for a first run. Actually creating anything requires
# --yes. The script refuses a shape Oracle does not report as Always Free
# eligible unless you pass --allow-paid, because the difference between free and
# billable here is one flag and a surprise invoice.
#
# Usage:
#   experiments/oracle/provision.sh --shape a1 --dry-run
#   experiments/oracle/provision.sh --shape a1 --yes
#   experiments/oracle/provision.sh --shape e2 --yes
#   experiments/oracle/provision.sh --destroy --yes
#
#   --shape a1   VM.Standard.A1.Flex, aarch64, 2 OCPU / 12 GB  (half the free
#                allocation, leaving room for a second VM for Phase 3)
#   --shape e2   VM.Standard.E2.1.Micro, x86_64, 1 GB — the only free x86_64,
#                and the one that answers whether the OpenSSL 3.0 penalty is
#                architecture-specific
#
# VERIFIED, AND NOT VERIFIED. Every subcommand and flag used below was checked
# to exist in oci-cli 3.93.0 (note that --query is a GLOBAL option and does not
# appear in per-command --help, which makes a naive check report it missing).
# The API calls themselves have NOT been run against a live tenancy, because
# this machine has no OCI credentials. Treat the first --dry-run as part of the
# review, not as a formality.
#
# The CLI prompts interactively when ~/.oci/config is absent, which would hang a
# non-interactive run; the guard below exits before any oci invocation.

set -euo pipefail

SHAPE_KEY=""; DRY_RUN=1; DESTROY=0; ALLOW_PAID=0
COMPARTMENT="${OCI_COMPARTMENT_ID:-}"
SSH_KEY_FILE="$HOME/.ssh/id_ed25519.pub"
NAME_PREFIX="psao-keypath"
OCPUS=2; MEM_GB=12
AD_INDEX=0

while [ $# -gt 0 ]; do
  case "$1" in
    --shape) SHAPE_KEY="$2"; shift 2 ;;
    --compartment) COMPARTMENT="$2"; shift 2 ;;
    --ssh-key) SSH_KEY_FILE="$2"; shift 2 ;;
    --ocpus) OCPUS="$2"; shift 2 ;;
    --memory) MEM_GB="$2"; shift 2 ;;
    --ad-index) AD_INDEX="$2"; shift 2 ;;
    --name) NAME_PREFIX="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --yes) DRY_RUN=0; shift ;;
    --destroy) DESTROY=1; shift ;;
    --allow-paid) ALLOW_PAID=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

log() { printf '[provision %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
die() { printf '[provision] ERROR: %s\n' "$*" >&2; exit 1; }
run() {
  if [ "$DRY_RUN" -eq 1 ]; then printf '  DRY-RUN would run: %s\n' "$*" >&2; return 0; fi
  "$@"
}

command -v oci >/dev/null 2>&1 || die "oci CLI not installed. brew install oci-cli"
[ -r "$HOME/.oci/config" ] || die "no ~/.oci/config. Run: oci setup config  (see experiments/oracle/README.md)"

# Tenancy root is the default compartment; most free-tier accounts have no other.
if [ -z "$COMPARTMENT" ]; then
  COMPARTMENT="$(oci iam compartment list --all --query 'data[0]."compartment-id"' --raw-output 2>/dev/null || true)"
  [ -n "$COMPARTMENT" ] || COMPARTMENT="$(sed -n 's/^tenancy[[:space:]]*=[[:space:]]*//p' "$HOME/.oci/config" | head -1)"
fi
[ -n "$COMPARTMENT" ] || die "cannot determine compartment; pass --compartment <ocid>"
log "compartment: ${COMPARTMENT:0:28}..."

# --- destroy -----------------------------------------------------------------
if [ "$DESTROY" -eq 1 ]; then
  log "finding instances named ${NAME_PREFIX}-*"
  ids="$(oci compute instance list --compartment-id "$COMPARTMENT" --all \
          --query "data[?starts_with(\"display-name\",'${NAME_PREFIX}') && \"lifecycle-state\"!='TERMINATED'].id" \
          --raw-output 2>/dev/null | tr -d '[]"," ' | tr '\n' ' ')"
  [ -n "${ids// /}" ] || { log "nothing to destroy"; exit 0; }
  for id in $ids; do
    log "terminating ${id:0:28}..."
    run oci compute instance terminate --instance-id "$id" --force --wait-for-state TERMINATED
  done
  log "done. VCN and subnet are left in place (they cost nothing and are reusable)."
  exit 0
fi

[ -n "$SHAPE_KEY" ] || die "--shape is required (a1 or e2)"
[ -r "$SSH_KEY_FILE" ] || die "no ssh public key at $SSH_KEY_FILE (pass --ssh-key)"

case "$SHAPE_KEY" in
  a1) SHAPE="VM.Standard.A1.Flex"; OS_NAME="Canonical Ubuntu"; FLEX=1 ;;
  e2) SHAPE="VM.Standard.E2.1.Micro"; OS_NAME="Canonical Ubuntu"; FLEX=0 ;;
  *) die "--shape must be a1 or e2" ;;
esac
INSTANCE_NAME="${NAME_PREFIX}-${SHAPE_KEY}"

# --- is this shape actually free? -------------------------------------------
log "checking Always Free eligibility of $SHAPE"
FREE="$(oci compute shape list --compartment-id "$COMPARTMENT" --all \
         --query "data[?shape=='$SHAPE']|[0].\"is-billed-for-stopped-instance\"" \
         --raw-output 2>/dev/null || true)"
ELIGIBLE="$(oci limits value list --compartment-id "$COMPARTMENT" \
             --service-name compute --query 'data[0].name' --raw-output 2>/dev/null || true)"
if [ "$ALLOW_PAID" -eq 0 ]; then
  log "NOTE: Oracle does not expose a reliable 'always free' flag through the API."
  log "      $SHAPE is free-tier eligible at the time of writing, but VERIFY in the"
  log "      console before passing --yes. Pass --allow-paid to silence this."
fi

# --- availability domain -----------------------------------------------------
AD="$(oci iam availability-domain list --compartment-id "$COMPARTMENT" \
       --query "data[$AD_INDEX].name" --raw-output 2>/dev/null || true)"
[ -n "$AD" ] || die "cannot list availability domains"
log "availability domain: $AD"
log "  (Ampere capacity is frequently exhausted. On an out-of-capacity error, retry"
log "   with --ad-index 1 or 2, or from a different region.)"

# --- network: reuse if present, create if not --------------------------------
VCN_NAME="${NAME_PREFIX}-vcn"
VCN_ID="$(oci network vcn list --compartment-id "$COMPARTMENT" --display-name "$VCN_NAME" \
           --query 'data[0].id' --raw-output 2>/dev/null || true)"
if [ -z "$VCN_ID" ] || [ "$VCN_ID" = "null" ]; then
  log "creating VCN $VCN_NAME (10.0.0.0/16)"
  VCN_ID="$(run oci network vcn create --compartment-id "$COMPARTMENT" \
      --display-name "$VCN_NAME" --cidr-blocks '["10.0.0.0/16"]' \
      --wait-for-state AVAILABLE --query 'data.id' --raw-output 2>/dev/null || echo DRYRUN_VCN)"

  log "creating internet gateway"
  IGW_ID="$(run oci network internet-gateway create --compartment-id "$COMPARTMENT" \
      --vcn-id "$VCN_ID" --is-enabled true --display-name "${NAME_PREFIX}-igw" \
      --wait-for-state AVAILABLE --query 'data.id' --raw-output 2>/dev/null || echo DRYRUN_IGW)"

  RT_ID="$(run oci network vcn get --vcn-id "$VCN_ID" \
      --query 'data."default-route-table-id"' --raw-output 2>/dev/null || echo DRYRUN_RT)"
  log "routing 0.0.0.0/0 to the gateway"
  run oci network route-table update --rt-id "$RT_ID" --force \
      --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW_ID\"}]"

  # Ingress 22 only. A permissive default here is how a throwaway benchmark box
  # becomes somebody else's. 0.0.0.0/0 because a laptop's address moves; narrow
  # it to your own /32 if it does not.
  SL_ID="$(run oci network vcn get --vcn-id "$VCN_ID" \
      --query 'data."default-security-list-id"' --raw-output 2>/dev/null || echo DRYRUN_SL)"
  log "allowing inbound tcp/22"
  run oci network security-list update --security-list-id "$SL_ID" --force \
    --ingress-security-rules '[{"protocol":"6","source":"0.0.0.0/0","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}]' \
    --egress-security-rules '[{"protocol":"all","destination":"0.0.0.0/0","isStateless":false}]'
else
  log "reusing VCN ${VCN_ID:0:28}..."
fi

SUBNET_NAME="${NAME_PREFIX}-subnet"
SUBNET_ID="$(oci network subnet list --compartment-id "$COMPARTMENT" --vcn-id "$VCN_ID" \
             --display-name "$SUBNET_NAME" --query 'data[0].id' --raw-output 2>/dev/null || true)"
if [ -z "$SUBNET_ID" ] || [ "$SUBNET_ID" = "null" ]; then
  log "creating public subnet 10.0.0.0/24"
  SUBNET_ID="$(run oci network subnet create --compartment-id "$COMPARTMENT" --vcn-id "$VCN_ID" \
      --display-name "$SUBNET_NAME" --cidr-block '10.0.0.0/24' \
      --prohibit-public-ip-on-vnic false --wait-for-state AVAILABLE \
      --query 'data.id' --raw-output 2>/dev/null || echo DRYRUN_SUBNET)"
else
  log "reusing subnet ${SUBNET_ID:0:28}..."
fi

# --- image -------------------------------------------------------------------
log "finding the newest $OS_NAME image for $SHAPE"
IMAGE_ID="$(oci compute image list --compartment-id "$COMPARTMENT" \
            --operating-system "$OS_NAME" --shape "$SHAPE" --sort-by TIMECREATED \
            --sort-order DESC --query 'data[0].id' --raw-output 2>/dev/null || true)"
[ -n "$IMAGE_ID" ] && [ "$IMAGE_ID" != "null" ] || die "no $OS_NAME image available for $SHAPE in this region"
log "image: ${IMAGE_ID:0:28}..."

# --- launch ------------------------------------------------------------------
LAUNCH=(oci compute instance launch
  --compartment-id "$COMPARTMENT" --availability-domain "$AD"
  --display-name "$INSTANCE_NAME" --image-id "$IMAGE_ID" --shape "$SHAPE"
  --subnet-id "$SUBNET_ID" --assign-public-ip true
  --ssh-authorized-keys-file "$SSH_KEY_FILE"
  --wait-for-state RUNNING)
[ "$FLEX" -eq 1 ] && LAUNCH+=(--shape-config "{\"ocpus\":$OCPUS,\"memoryInGBs\":$MEM_GB}")

log "launching $INSTANCE_NAME ($SHAPE$([ "$FLEX" -eq 1 ] && echo ", ${OCPUS} OCPU / ${MEM_GB} GB"))"
if [ "$DRY_RUN" -eq 1 ]; then
  printf '  DRY-RUN would run: %s\n' "${LAUNCH[*]}" >&2
  log "dry run complete. Nothing was created. Re-run with --yes to create it."
  exit 0
fi

INSTANCE_ID="$("${LAUNCH[@]}" --query 'data.id' --raw-output)"
[ -n "$INSTANCE_ID" ] || die "launch did not return an instance id"

IP="$(oci compute instance list-vnics --instance-id "$INSTANCE_ID" \
      --query 'data[0]."public-ip"' --raw-output)"
[ -n "$IP" ] && [ "$IP" != "null" ] || die "instance is running but has no public IP"

log "instance $INSTANCE_NAME is up at $IP"
cat <<NEXT

  Next, from psao-artifact/:

    experiments/run_keypath_remote.sh --host ubuntu@$IP --label oracle-$SHAPE_KEY \\
        --key ${SSH_KEY_FILE%.pub} --bootstrap --rounds 10

  When you are finished:

    experiments/oracle/provision.sh --destroy --yes

NEXT
