#!/usr/bin/env bash
# common.sh — shared helpers for the experiment runners.
#
# Sourced, never executed. Provides:
#   psao::new_run_dir <label>     create data/runs/<ISO timestamp>-<label>/
#   psao::write_metadata <dir>    write run_metadata.json
#   psao::require <cmd>...        fail fast on missing tooling
#   psao::log <msg>               timestamped stderr logging
#
# Everything that cannot be determined is recorded as JSON null with an entry in
# the "unavailable" list. A run that could not read, say, the Istio version is a
# run whose metadata says so; it is never a run with a guessed version in it.

set -euo pipefail

PSAO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PSAO_ROOT

psao::log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

psao::die() {
  psao::log "ERROR: $*"
  exit 1
}

psao::require() {
  local missing=()
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    psao::die "missing required commands: ${missing[*]}"
  fi
}

# Run `$@`, returning its stdout, or the empty string if it fails. Used for
# every optional metadata probe so a missing cluster never aborts a local run.
psao::try() {
  "$@" 2>/dev/null || true
}

# Build the -e arguments k6 needs, into the K6_ENV_ARGS array.
#
# k6 v2 no longer copies the process environment into __ENV; only variables
# passed with -e (or --include-system-env-vars) are visible to the script. A
# runner that just exports PSAO_* and calls k6 silently gets script defaults --
# which for run_openloop_ramp.sh would mean ramping to the default 400 rps
# against the default URL no matter what you asked for. Passing them explicitly
# is version-independent and makes the k6 command line self-documenting.
psao::k6_env() {
  K6_ENV_ARGS=()
  local name value
  for name in "$@"; do
    eval "value=\${$name-}"
    if [ -n "$value" ]; then
      K6_ENV_ARGS+=(-e "$name=$value")
    fi
  done
}

# --- Prometheus port-forward -------------------------------------------------
#
# The controller and the metrics probes talk to Prometheus over
# PSAO_PROM_URL (default http://localhost:9090). In-cluster Prometheus is not
# reachable at that address without a port-forward, and a run that starts
# without one produces a trace of empty rows that looks like a run. So the
# runners open the forward themselves and close it on exit.
#
# psao::start_port_forward   idempotent; no-op if something already answers
# psao::stop_port_forward    kills only a forward WE started
PSAO_PROM_URL="${PSAO_PROM_URL:-http://localhost:9090}"
PSAO_PROM_NS="${PSAO_PROM_NS:-istio-system}"
PSAO_PROM_SVC="${PSAO_PROM_SVC:-svc/prometheus}"
PSAO_PROM_PORT="${PSAO_PROM_PORT:-9090}"
PSAO_PF_PID=""

psao::prom_ready() {
  curl -sf -m 3 "${PSAO_PROM_URL}/-/ready" >/dev/null 2>&1
}

psao::start_port_forward() {
  if psao::prom_ready; then
    psao::log "Prometheus already reachable at $PSAO_PROM_URL (not starting a port-forward)"
    return 0
  fi
  command -v kubectl >/dev/null 2>&1 || {
    psao::log "WARNING: kubectl not found; cannot port-forward to Prometheus"
    return 1
  }
  if ! kubectl -n "$PSAO_PROM_NS" get "$PSAO_PROM_SVC" --request-timeout=5s >/dev/null 2>&1; then
    psao::log "WARNING: $PSAO_PROM_SVC not found in namespace $PSAO_PROM_NS."
    psao::log "         Install it with:  kubectl apply -f <istio>/samples/addons/prometheus.yaml"
    return 1
  fi

  kubectl -n "$PSAO_PROM_NS" port-forward "$PSAO_PROM_SVC" \
    "${PSAO_PROM_PORT}:${PSAO_PROM_PORT}" >/dev/null 2>&1 &
  PSAO_PF_PID=$!

  local waited=0
  while [ "$waited" -lt 30 ]; do
    if psao::prom_ready; then
      psao::log "Prometheus port-forward up (pid $PSAO_PF_PID, $PSAO_PROM_URL)"
      return 0
    fi
    # If the forward died, stop waiting for it.
    kill -0 "$PSAO_PF_PID" 2>/dev/null || break
    sleep 1
    waited=$((waited + 1))
  done

  psao::log "WARNING: Prometheus did not become ready at $PSAO_PROM_URL within ${waited}s"
  psao::stop_port_forward
  return 1
}

psao::stop_port_forward() {
  if [ -n "$PSAO_PF_PID" ] && kill -0 "$PSAO_PF_PID" 2>/dev/null; then
    kill -TERM "$PSAO_PF_PID" 2>/dev/null || true
    wait "$PSAO_PF_PID" 2>/dev/null || true
    psao::log "Prometheus port-forward stopped (pid $PSAO_PF_PID)"
  fi
  PSAO_PF_PID=""
}

# --- application metrics port-forward ----------------------------------------
#
# capture_pod_metrics.sh reads psao_eventloop_lag_p99_ms by curling
# PSAO_METRICS_URL from the HOST, once per second. The application's metrics
# listener (9464) is not reachable from the host without a forward, so without
# this the eventloop_lag_p99_ms column is silently left empty for the whole run.
# Forwarding to the pod (not the Service) keeps the samples tied to one replica,
# which is what a per-pod CPU sample is comparable against.
#
# Returns the URL in PSAO_METRICS_URL_RESOLVED rather than on stdout. Do NOT
# wrap the call in $( ): that forks a subshell, so PSAO_MF_PID would be set in
# the child and lost, leaving the port-forward orphaned after the run ends.
PSAO_METRICS_PORT="${PSAO_METRICS_PORT:-9464}"
PSAO_MF_PID=""
PSAO_METRICS_URL_RESOLVED=""

psao::start_metrics_port_forward() {
  local ns="${1:-default}" selector="${2:-app=service-a}"
  PSAO_METRICS_URL_RESOLVED=""
  if curl -sf -m 2 "http://localhost:${PSAO_METRICS_PORT}/metrics" >/dev/null 2>&1; then
    psao::log "app metrics already reachable on :${PSAO_METRICS_PORT}"
    PSAO_METRICS_URL_RESOLVED="http://localhost:${PSAO_METRICS_PORT}/metrics"
    return 0
  fi
  # Resolve the pod from the SERVICE ENDPOINT first, and only fall back to a
  # label query.
  #
  # This has now gone wrong twice, in two different disguises. Picking
  # `.items[0]` of a label query attached the tunnel to the old, TERMINATING pod
  # after a rollout (S3: 1 of 20 steps had a lag value). Filtering to
  # Running+Ready did not fix it, because a pod that is scaled down or
  # terminating stays Running AND Ready for a while -- so the S8 ramp picked the
  # scaled-down S5 pod and lost the lag column again.
  #
  # The endpoint is the only source that answers the question actually being
  # asked: which pod is the Service sending the load to. Everything else is a
  # proxy for it that is wrong precisely during a changeover.
  #
  # The failure is silent -- a dead tunnel just means every scrape fails, and
  # since a failed scrape can no longer kill the CPU sampler, the run completes
  # with an empty lag column. run_openloop_ramp.sh warns about that afterwards.
  local pod
  pod="$(kubectl get endpoints "${PSAO_SERVICE_NAME:-service-a}" -n "$ns" \
    --request-timeout=5s \
    -o jsonpath='{.subsets[0].addresses[0].targetRef.name}' 2>/dev/null || true)"
  if [ -n "$pod" ]; then
    psao::log "metrics target resolved from the service-a endpoint: $pod"
  else
    pod="$(kubectl get pods -n "$ns" -l "$selector" --request-timeout=5s \
      --field-selector=status.phase=Running \
      -o jsonpath='{range .items[*]}{.metadata.name}{" "}{range .status.conditions[?(@.type=="Ready")]}{.status}{end}{"\n"}{end}' \
      2>/dev/null | awk '$2=="True" {print $1; exit}')"
    [ -n "$pod" ] && psao::log "WARNING: no service endpoint; falling back to a label query ($pod)"
  fi
  if [ -z "$pod" ]; then
    psao::log "WARNING: no Ready pod matches '$selector' in '$ns'; eventloop lag will not be sampled"
    return 1
  fi

  kubectl -n "$ns" port-forward "pod/$pod" \
    "${PSAO_METRICS_PORT}:${PSAO_METRICS_PORT}" >/dev/null 2>&1 &
  PSAO_MF_PID=$!

  local waited=0
  while [ "$waited" -lt 20 ]; do
    if curl -sf -m 2 "http://localhost:${PSAO_METRICS_PORT}/metrics" >/dev/null 2>&1; then
      psao::log "app metrics port-forward up (pid $PSAO_MF_PID, pod $pod)"
      PSAO_METRICS_URL_RESOLVED="http://localhost:${PSAO_METRICS_PORT}/metrics"
      return 0
    fi
    kill -0 "$PSAO_MF_PID" 2>/dev/null || break
    sleep 1
    waited=$((waited + 1))
  done
  psao::log "WARNING: app metrics endpoint did not come up on :${PSAO_METRICS_PORT}"
  psao::stop_metrics_port_forward
  return 1
}

psao::stop_metrics_port_forward() {
  if [ -n "$PSAO_MF_PID" ] && kill -0 "$PSAO_MF_PID" 2>/dev/null; then
    kill -TERM "$PSAO_MF_PID" 2>/dev/null || true
    wait "$PSAO_MF_PID" 2>/dev/null || true
    psao::log "app metrics port-forward stopped (pid $PSAO_MF_PID)"
  fi
  PSAO_MF_PID=""
}

# Resolve a path to an absolute one, relative to the CALLER's cwd.
#
# k6's open() resolves a relative path against the directory of the SCRIPT that
# calls it -- experiments/k6/lib/ for auth.js -- not against the cwd of the
# process. So `--token-pool tokens/pool.txt`, typed from the artifact root, sends
# k6 looking for experiments/k6/lib/tokens/pool.txt and aborts the run at init.
# Making the path absolute here removes the ambiguity entirely.
psao::abspath() {
  local p="$1"
  [ -z "$p" ] && { printf '%s' ""; return 0; }
  case "$p" in
    /*) printf '%s' "$p" ;;
    *)  printf '%s' "$PWD/$p" ;;
  esac
}

# Strip server-populated fields from a `kubectl get -o yaml` dump so it can be
# re-applied later.
#
# An earlier version of the backup kept these, on the reasoning that they were
# "harmless on re-apply". They are not. `resourceVersion` carries optimistic
# concurrency: re-applying a manifest that still holds the version from BEFORE
# the teardown fails with
#
#   Operation cannot be fulfilled on ingresses.networking.k8s.io "my-ingress":
#   the object has been modified; please apply your changes to the latest
#   version and try again
#
# for any object that still exists (an Ingress that was patched, rather than a
# PeerAuthentication that was deleted and is being recreated). That turns the
# restore into a failure at exactly the moment the cluster most needs to go
# back, which is how the S1 restore first failed.
psao::sanitize_manifest() {
  python3 - "$1" <<'PYSAN'
import sys, yaml

STRIP_META = (
    "resourceVersion", "uid", "creationTimestamp", "generation",
    "managedFields", "selfLink",
)

def clean(obj):
    if not isinstance(obj, dict):
        return obj
    obj.pop("status", None)
    meta = obj.get("metadata")
    if isinstance(meta, dict):
        for key in STRIP_META:
            meta.pop(key, None)
        ann = meta.get("annotations")
        if isinstance(ann, dict):
            # Re-applying a stale last-applied-configuration makes kubectl
            # compute the diff against the PRE-teardown state.
            ann.pop("kubectl.kubernetes.io/last-applied-configuration", None)
            if not ann:
                meta.pop("annotations", None)
    return obj

path = sys.argv[1]
with open(path) as fh:
    docs = [d for d in yaml.safe_load_all(fh) if d]

for doc in docs:
    if doc.get("kind", "").endswith("List"):
        doc["items"] = [clean(i) for i in doc.get("items") or []]
        doc.pop("metadata", None)
    else:
        clean(doc)

with open(path, "w") as fh:
    yaml.safe_dump_all(docs, fh, default_flow_style=False, sort_keys=False)
PYSAN
}

# --- mesh posture change log -------------------------------------------------
#
# S1 is measured with mTLS and Edge TLS TORN DOWN, and every later scenario is
# measured with them restored. Which posture a given run was measured in is
# therefore not a property of the run's own parameters -- it is a property of
# what happened to the cluster before it started. An append-only log of the
# changes, echoed into every run_metadata.json, is what makes that visible after
# the fact instead of reconstructable only from shell history.
PSAO_POSTURE_LOG="${PSAO_POSTURE_LOG:-$PSAO_ROOT/data/runs/posture_events.jsonl}"

# psao::record_posture_event <event> <detail>
#   event  teardown_begin | teardown_complete | restore_begin |
#          restore_complete | verified | verification_failed
psao::record_posture_event() {
  local event="$1" detail="${2:-}"
  mkdir -p "$(dirname "$PSAO_POSTURE_LOG")"
  PSAO_PE_EVENT="$event" PSAO_PE_DETAIL="$detail" PSAO_PE_LOG="$PSAO_POSTURE_LOG" \
  python3 - <<'PYEV'
import datetime, json, os
row = {
    "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "event": os.environ["PSAO_PE_EVENT"],
    "detail": os.environ.get("PSAO_PE_DETAIL") or None,
}
with open(os.environ["PSAO_PE_LOG"], "a") as fh:
    fh.write(json.dumps(row) + "\n")
PYEV
  psao::log "posture event: $event${detail:+ ($detail)}"
}

# --- mTLS posture verification -----------------------------------------------
#
# A 200 from the ingress is NOT proof that mTLS is enforced. A 200 is exactly
# what you also get when STRICT mode is ABSENT -- the request simply travels in
# plaintext and everything appears to work. Any run bracketed by a teardown and
# a restore of the mesh posture (S1) therefore has to verify the control itself,
# not the happy path through it.
#
# Three checks, all of which must pass:
#   1. A namespace-wide PeerAuthentication with mtls.mode: STRICT exists.
#   2. A DestinationRule carries trafficPolicy.tls.mode: ISTIO_MUTUAL.
#   3. PAIRED CONTROLS on the same address: an in-mesh client must GET a
#      response, and a client with no sidecar must be REFUSED. Only this pair
#      tests behaviour rather than declared intent -- the objects can be present
#      and still not be in force (a narrower PeerAuthentication overriding them,
#      a sidecar that has not picked up the config, a workload never injected).
#      The positive half is not optional: a refusal on its own is equally
#      consistent with nothing listening at that address at all.
#
# psao::verify_mtls_posture [namespace]
PSAO_PROBE_NS="${PSAO_PROBE_NS:-psao-probe}"
PSAO_PROBE_POD="${PSAO_PROBE_POD:-psao-plaintext-probe}"
# Reuses an image already on the node so the probe never needs a registry pull;
# only its shell is used.
PSAO_PROBE_IMAGE="${PSAO_PROBE_IMAGE:-service-a:psao-1}"

psao::verify_mtls_posture() {
  local ns="${1:-default}" failed=0

  # --- 1. PeerAuthentication STRICT -------------------------------------------
  local pa_modes
  pa_modes="$(psao::try kubectl get peerauthentication -n "$ns" --request-timeout=10s \
    -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.spec.mtls.mode}{"\n"}{end}')"
  if printf '%s' "$pa_modes" | grep -q '=STRICT$'; then
    psao::log "posture 1/3 OK: PeerAuthentication STRICT in '$ns' ($(printf '%s' "$pa_modes" | tr '\n' ' '))"
  else
    psao::log "posture 1/3 FAILED: no PeerAuthentication with mtls.mode=STRICT in '$ns'"
    psao::log "  found: ${pa_modes:-<none>}"
    failed=1
  fi

  # --- 2. DestinationRule ISTIO_MUTUAL ----------------------------------------
  local dr_modes
  dr_modes="$(psao::try kubectl get destinationrule -n "$ns" --request-timeout=10s \
    -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.spec.trafficPolicy.tls.mode}{"\n"}{end}')"
  if printf '%s' "$dr_modes" | grep -q '=ISTIO_MUTUAL$'; then
    psao::log "posture 2/3 OK: DestinationRule ISTIO_MUTUAL in '$ns' ($(printf '%s' "$dr_modes" | tr '\n' ' '))"
  else
    psao::log "posture 2/3 FAILED: no DestinationRule with tls.mode=ISTIO_MUTUAL in '$ns'"
    psao::log "  found: ${dr_modes:-<none>}"
    failed=1
  fi

  # --- 3. paired controls: the same address, from inside and outside the mesh --
  #
  # A refusal on its own proves nothing. The first version of this check probed
  # a pod IP taken from `.items[0]`, which during a rollout is the OLD,
  # TERMINATING pod -- "Connection refused" came back and the check passed while
  # testing a dying process. A negative control needs a positive control pinned
  # to the SAME address, or it cannot tell "mTLS refused this" from "there is
  # nothing listening there".
  #
  # Both probes target the Service ClusterIP, not a pod IP. Istio has no
  # listener for a bare pod IP on the application port, so even an in-mesh
  # client is passed through in plaintext and would be refused too -- which
  # would make the positive control fail for a reason unrelated to posture.
  local svc_ip svc_port
  svc_ip="$(psao::try kubectl get svc "${PSAO_SERVICE_NAME:-service-a}" -n "$ns" \
    --request-timeout=10s -o jsonpath='{.spec.clusterIP}')"
  svc_port="$(psao::try kubectl get svc "${PSAO_SERVICE_NAME:-service-a}" -n "$ns" \
    --request-timeout=10s -o jsonpath='{.spec.ports[0].port}')"

  if [ -z "$svc_ip" ] || [ -z "$svc_port" ]; then
    psao::log "posture 3/3 FAILED: could not resolve ClusterIP for service '${PSAO_SERVICE_NAME:-service-a}' in '$ns'"
    failed=1
  else
    local target="http://${svc_ip}:${svc_port}/products"

    # --- 3a. POSITIVE control: an in-mesh client must get a response ----------
    # Any HTTP status will do, including 401/403. The question is whether the
    # address answers at all, not whether the application authorises us.
    local in_mesh_pod in_mesh_out
    in_mesh_pod="$(psao::try kubectl get pods -n "$ns" -l "${PSAO_INMESH_SELECTOR:-app=service-b}" \
      --field-selector=status.phase=Running --request-timeout=10s \
      -o jsonpath='{.items[0].metadata.name}')"
    if [ -z "$in_mesh_pod" ]; then
      psao::log "posture 3/3 FAILED: no Running in-mesh pod ('${PSAO_INMESH_SELECTOR:-app=service-b}') to run the positive control from"
      failed=1
    else
      in_mesh_out="$(kubectl exec -n "$ns" "$in_mesh_pod" -c "${PSAO_INMESH_CONTAINER:-service-b}" \
        --request-timeout=45s -- sh -c \
        "wget -q -S -T 5 -O /dev/null '$target' 2>&1; echo EXIT=\$?" 2>&1 || true)"
      psao::log "posture 3a probe (in-mesh, $in_mesh_pod): $(printf '%s' "$in_mesh_out" | tr '\n' ' ' | head -c 200)"
      if printf '%s' "$in_mesh_out" | grep -qE 'HTTP/1\.[01] [0-9]{3}|EXIT=0'; then
        psao::log "posture 3a OK: in-mesh client reached $target"
      else
        psao::log "posture 3a FAILED: an IN-MESH client could not reach $target."
        psao::log "  The negative control below cannot be interpreted, so this is not a pass."
        failed=1
      fi
    fi

    # --- 3b. NEGATIVE control: an out-of-mesh client must be refused ----------
    kubectl get namespace "$PSAO_PROBE_NS" --request-timeout=10s >/dev/null 2>&1 \
      || kubectl create namespace "$PSAO_PROBE_NS" --request-timeout=10s >/dev/null 2>&1 || true
    kubectl label namespace "$PSAO_PROBE_NS" istio-injection- --request-timeout=10s >/dev/null 2>&1 || true

    local injected
    injected="$(psao::try kubectl get namespace "$PSAO_PROBE_NS" --request-timeout=10s \
      -o jsonpath='{.metadata.labels.istio-injection}')"
    if [ -n "$injected" ]; then
      psao::log "posture 3b FAILED: probe namespace '$PSAO_PROBE_NS' is labelled istio-injection=$injected;"
      psao::log "  an injected probe would speak mTLS and pass regardless of posture"
      failed=1
    else
      kubectl -n "$PSAO_PROBE_NS" delete pod "$PSAO_PROBE_POD" \
        --ignore-not-found --request-timeout=30s >/dev/null 2>&1 || true

      local probe_out
      probe_out="$(kubectl -n "$PSAO_PROBE_NS" run "$PSAO_PROBE_POD" \
        --image="$PSAO_PROBE_IMAGE" --image-pull-policy=IfNotPresent \
        --restart=Never --rm -i --request-timeout=90s \
        --command -- sh -c \
        "wget -q -S -T 5 -O /dev/null '$target' 2>&1; echo EXIT=\$?" 2>&1 || true)"
      kubectl -n "$PSAO_PROBE_NS" delete pod "$PSAO_PROBE_POD" \
        --ignore-not-found --request-timeout=30s >/dev/null 2>&1 || true

      psao::log "posture 3b probe (out-of-mesh): $(printf '%s' "$probe_out" | tr '\n' ' ' | head -c 200)"
      if printf '%s' "$probe_out" | grep -qE 'HTTP/1\.[01] [0-9]{3}|EXIT=0'; then
        psao::log "posture 3b FAILED: a plaintext request from OUTSIDE the mesh got a response."
        psao::log "  mTLS is not being enforced on $target."
        failed=1
      elif printf '%s' "$probe_out" | grep -q 'EXIT='; then
        psao::log "posture 3b OK: out-of-mesh plaintext to $target was refused"
      else
        psao::log "posture 3b FAILED: the probe produced no verdict (could not run?)."
        psao::log "  Treating an unrunnable negative control as a failure, not a pass."
        failed=1
      fi
    fi
  fi

  if [ "$failed" -ne 0 ]; then
    psao::die "mTLS posture verification FAILED -- refusing to continue. A 200 from the ingress does not prove enforcement."
  fi
  psao::log "mTLS posture verified in namespace '$ns' (STRICT + ISTIO_MUTUAL + plaintext refused)"
  return 0
}

# --- ingress pre-flight ------------------------------------------------------
#
# Every runner calls this BEFORE it creates a run directory or generates load.
#
# The failure mode it exists for is not "the cluster is down" -- that is obvious.
# It is the degraded path that still answers fast: a 502 from NGINX because the
# ingress is dialling pod IPs past the mesh, or a 403 from an expired token pool.
# Both produce a full, smooth, entirely meaningless latency curve. A ramp is
# ~10 minutes and its output is indistinguishable from a good one without
# reading the status codes, so the check is worth the one request it costs.
#
# psao::verify_ingress <base_url> <path> <expected_status> [auth_header_or_empty]
psao::verify_ingress() {
  local base_url="$1" req_path="$2" expected="$3" auth="${4:-}"
  local url="${base_url}${req_path}"
  local -a curl_args=(-k -s -o /dev/null -m 10 -w '%{http_code}')
  [ -n "$auth" ] && curl_args+=(-H "Authorization: Bearer $auth")

  local code attempt=0
  # Three attempts: a single request can lose a race with a sidecar that is
  # still warming its endpoints. Three identical failures are not a race.
  while [ "$attempt" -lt 3 ]; do
    code="$(curl "${curl_args[@]}" "$url" 2>/dev/null || echo 000)"
    if [ "$code" = "$expected" ]; then
      psao::log "pre-flight OK: $url -> $code (expected $expected)"
      return 0
    fi
    attempt=$((attempt + 1))
    [ "$attempt" -lt 3 ] && sleep 2
  done

  psao::log "pre-flight FAILED: $url -> $code, expected $expected"
  case "$code" in
    000) psao::log "  nothing answered. Is the ingress controller up, and is \
the base URL right?" ;;
    502) psao::log "  NGINX could not reach the upstream. Under Istio STRICT \
mTLS this is usually the ingress dialling endpoint POD IPs instead of the \
Service VIP: kubectl -n default annotate ingress my-ingress \
nginx.ingress.kubernetes.io/service-upstream=true --overwrite" ;;
    401) psao::log "  the service wants a token and none was sent. Check \
--token-file / --token-pool, or pass --no-auth if this scenario is meant to be \
unauthenticated." ;;
    403) psao::log "  the service rejected the token. It has most likely \
EXPIRED: node experiments/mint_tokens.js --count 64 --ttl 24h" ;;
  esac
  psao::die "refusing to measure through a degraded path"
}

psao::new_run_dir() {
  local label="${1:-run}"
  # ISO 8601 UTC with ':' replaced by '-' so the directory name is portable.
  local stamp
  stamp="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
  local dir="${PSAO_RUN_DIR:-$PSAO_ROOT/data/runs/${stamp}-${label}}"
  mkdir -p "$dir"
  printf '%s\n' "$dir"
}

# psao::write_metadata <run_dir> [key=value ...]
#
# Captures everything a reader needs to know that two runs are comparable:
# cluster version, Istio version, node instance type, running image digests and
# the artifact's own git commit.
psao::write_metadata() {
  local dir="$1"; shift
  local ns="${PSAO_NAMESPACE:-default}"

  local git_commit git_dirty
  git_commit="$(psao::try git -C "$PSAO_ROOT" rev-parse HEAD)"
  if [ -n "$git_commit" ] && [ -n "$(psao::try git -C "$PSAO_ROOT" status --porcelain)" ]; then
    git_dirty="true"
  elif [ -n "$git_commit" ]; then
    git_dirty="false"
  else
    git_dirty=""
  fi

  local k8s_version istio_version node_type image_digests k6_version node_version
  # `kubectl version -o json` needs a reachable API server; --request-timeout
  # keeps a local run from hanging for a minute on a dead context.
  k8s_version="$(psao::try kubectl version -o json --request-timeout=5s)"
  istio_version="$(psao::try istioctl version -o json)"
  node_type="$(psao::try kubectl get nodes --request-timeout=5s \
    -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.metadata.labels.node\.kubernetes\.io/instance-type}{"\n"}{end}')"
  # imageID (not image) because it carries the digest actually running, which is
  # what makes a run reproducible; the image *tag* can be re-pushed.
  image_digests="$(psao::try kubectl get pods -n "$ns" --request-timeout=5s \
    -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{range .status.containerStatuses[*]}{.name}{"="}{.imageID}{" "}{end}{"\n"}{end}')"
  k6_version="$(psao::try k6 version)"
  node_version="$(psao::try node --version)"

  # The mesh posture AS OBSERVED at the moment this run started. Recorded for
  # every run, not just the ones that change it: the point is that a reader of
  # any run directory can see which posture its numbers were measured in without
  # trusting the scenario label.
  local pa_modes dr_modes posture_events
  pa_modes="$(psao::try kubectl get peerauthentication -n "$ns" --request-timeout=5s \
    -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.spec.mtls.mode}{"\n"}{end}')"
  dr_modes="$(psao::try kubectl get destinationrule -n "$ns" --request-timeout=5s \
    -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.spec.trafficPolicy.tls.mode}{"\n"}{end}')"
  posture_events="$([ -f "$PSAO_POSTURE_LOG" ] && cat "$PSAO_POSTURE_LOG" || true)"

  local extra_pairs=("$@")

  PSAO_MD_DIR="$dir" \
  PSAO_MD_NS="$ns" \
  PSAO_MD_GIT_COMMIT="$git_commit" \
  PSAO_MD_GIT_DIRTY="$git_dirty" \
  PSAO_MD_K8S="$k8s_version" \
  PSAO_MD_ISTIO="$istio_version" \
  PSAO_MD_NODETYPE="$node_type" \
  PSAO_MD_IMAGES="$image_digests" \
  PSAO_MD_K6="$k6_version" \
  PSAO_MD_NODE="$node_version" \
  PSAO_MD_PA="$pa_modes" \
  PSAO_MD_DR="$dr_modes" \
  PSAO_MD_POSTURE_EVENTS="$posture_events" \
  PSAO_MD_EXTRA="$(printf '%s\n' "${extra_pairs[@]+"${extra_pairs[@]}"}")" \
  python3 - <<'PYEOF'
import json, os, platform, subprocess, sys, datetime

def env(name):
    v = os.environ.get(name, "").strip()
    return v or None

unavailable = []

def note(name, value):
    if value is None:
        unavailable.append(name)
    return value

def parse_json(name, raw):
    if not raw:
        unavailable.append(name)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Keep the raw text rather than dropping it: a reader can still see what
        # the tool said, and we have not invented a parsed structure.
        return {"_unparsed": raw}

def parse_pairs(raw, sep="="):
    out = {}
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or sep not in line:
            continue
        k, _, v = line.partition(sep)
        out[k.strip()] = v.strip() or None
    return out or None

def parse_jsonl(raw):
    rows = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"_unparsed": line})
    return rows or None


def parse_images(raw):
    out = {}
    for line in (raw or "").splitlines():
        pod, _, rest = line.partition("|")
        pod = pod.strip()
        if not pod:
            continue
        out[pod] = parse_pairs(rest.replace(" ", "\n")) or {}
    return out or None

extra = {}
for line in (os.environ.get("PSAO_MD_EXTRA") or "").splitlines():
    if "=" in line:
        k, _, v = line.partition("=")
        extra[k.strip()] = v.strip()

# Configuration facts that are NOT derivable from the cluster dump above and
# that every reproduction of this testbed has to get right. Each one caused a
# silently or loudly broken measurement path at least once; they are recorded
# per-run so a run directory explains its own preconditions.
CLUSTER_CONFIGURATION_NOTES = [
    {
        "id": "ingress-nginx-namespace-injection",
        "requirement": (
            "The ingress-nginx namespace must carry istio-injection=enabled and "
            "the controller pod must be 2/2 (controller + istio-proxy)."
        ),
        "why": (
            "The paper's Section 3.1 specifies an injected NGINX pod, so edge "
            "traffic enters the mesh at the ingress. An un-injected controller "
            "was cluster drift, not the designed topology."
        ),
        "affects_measurement": (
            "Yes. Un-injected, the ingress hop is outside the mesh and the "
            "mTLS leg being measured does not exist."
        ),
    },
    {
        "id": "ingress-nginx-controller-api-hang",
        "requirement": (
            "The controller Deployment needs the pod annotation "
            "traffic.sidecar.istio.io/excludeOutboundIPRanges: \"10.96.0.1/32\"."
        ),
        "why": (
            "Under injection the controller crash-loops: its Kubernetes API "
            "client hangs behind the sidecar. holdApplicationUntilProxyStarts "
            "alone does not fix it. Excluding the API server VIP keeps "
            "control-plane traffic out of Envoy."
        ),
        "affects_measurement": (
            "No. 10.96.0.1/32 is the Kubernetes API server VIP only. All "
            "measured data-plane traffic -- client to ingress, and ingress to "
            "service-a -- is still intercepted by Envoy and still carries mTLS. "
            "The exclusion removes the controller's own watch/list calls from "
            "the proxy, and those are not on any measured path."
        ),
    },
    {
        "id": "ingress-service-upstream",
        "requirement": (
            "The Ingress needs the annotation "
            "nginx.ingress.kubernetes.io/service-upstream: \"true\"."
        ),
        "why": (
            "By default ingress-nginx load-balances to endpoint POD IPs "
            "(10.x.x.x:3000), bypassing the Service VIP. Istio has no listener "
            "for a bare pod IP on the application port, so the sidecar "
            "passthrough sends PLAINTEXT into service-a's STRICT mTLS inbound "
            "port, which resets the connection. NGINX reports 'upstream "
            "prematurely closed connection' and returns 502. Targeting the "
            "ClusterIP instead lets the sidecar match the service VIP, apply "
            "the DestinationRule, and originate mTLS."
        ),
        "affects_measurement": (
            "No. It changes which address NGINX dials, not what is on the wire: "
            "the request still traverses Edge TLS, the ingress sidecar, mTLS, "
            "and the service-a sidecar."
        ),
    },
    {
        "id": "offload-payload-header-guard",
        "requirement": (
            "controller/strip-untrusted-payload-header.yaml must be applied and "
            "stay applied: kubectl apply -f controller/strip-untrusted-payload-header.yaml"
        ),
        "why": (
            "service-a trusts x-psao-jwt-payload and skips signature "
            "verification when it is present -- that is what makes PSAO a "
            "relocation of verification rather than a duplication of it. Istio "
            "overwrites that header, but ONLY while a RequestAuthentication "
            "exists, and the controller applies one only transiently. In every "
            "other state, with no Authorization header at all, a hand-written "
            "payload header returned 200 and the protected body. This EnvoyFilter "
            "strips any client-supplied copy on entry to the pod."
        ),
        "affects_measurement": (
            "It adds a Lua filter to the sidecar's inbound chain on every "
            "request, so it is not free and it is present in every run made "
            "after 2026-09-13T12:1x. Runs made before it was applied (S1, S3, "
            "S5 here) did not carry it. Verify with "
            "experiments/verify_offload_safety.sh."
        ),
    },
    {
        "id": "token-pool-expiry",
        "requirement": (
            "Re-mint tokens/ before a measurement session: "
            "node experiments/mint_tokens.js --count 64 --ttl 24h"
        ),
        "why": (
            "An expired pool does not fail loudly. service-a answers 403 to "
            "every request, k6 records those 403s as fast responses, and the "
            "ramp yields a plausible latency curve for an error path."
        ),
        "affects_measurement": (
            "Yes, catastrophically, and silently. The runners' pre-flight check "
            "(psao::verify_ingress) exists to make this abort instead."
        ),
    },
]

meta = {
    "_note": (
        "Provenance for one experiment run. Fields listed under 'unavailable' "
        "could not be determined on this host and are null; they are never "
        "guessed."
    ),
    "run_dir": env("PSAO_MD_DIR"),
    "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "namespace": env("PSAO_MD_NS"),
    "git_commit": note("git_commit", env("PSAO_MD_GIT_COMMIT")),
    "git_working_tree_dirty": (
        None if env("PSAO_MD_GIT_DIRTY") is None else env("PSAO_MD_GIT_DIRTY") == "true"
    ),
    "kubernetes_version": parse_json("kubernetes_version", env("PSAO_MD_K8S")),
    "istio_version": parse_json("istio_version", env("PSAO_MD_ISTIO")),
    "node_instance_types": note("node_instance_types", parse_pairs(env("PSAO_MD_NODETYPE"))),
    "image_digests": note("image_digests", parse_images(env("PSAO_MD_IMAGES"))),
    "k6_version": note("k6_version", env("PSAO_MD_K6")),
    "node_version": note("node_version", env("PSAO_MD_NODE")),
    "host": {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    },
    "mesh_posture": {
        "_note": (
            "Observed at run start, not assumed from the scenario label. A 200 "
            "from the ingress does not prove mTLS is enforced -- it is also "
            "what an absent STRICT policy produces. 'peer_authentication' and "
            "'destination_rules' are declared intent; the negative control "
            "(plaintext from an un-injected pod being refused) is run by "
            "psao::verify_mtls_posture and logged in 'change_events'."
        ),
        "peer_authentication": parse_pairs(env("PSAO_MD_PA")),
        "destination_rules": parse_pairs(env("PSAO_MD_DR")),
        "change_events": parse_jsonl(env("PSAO_MD_POSTURE_EVENTS")),
    },
    "cluster_configuration_notes": CLUSTER_CONFIGURATION_NOTES,
    "run_parameters": extra,
    "unavailable": sorted(set(unavailable)),
}

path = os.path.join(meta["run_dir"], "run_metadata.json")
with open(path, "w") as fh:
    json.dump(meta, fh, indent=2, sort_keys=False)
    fh.write("\n")
print(path)
if meta["unavailable"]:
    sys.stderr.write(
        "[metadata] unavailable (recorded as null): "
        + ", ".join(meta["unavailable"]) + "\n"
    )
PYEOF
}

# Append a "finished_at_utc" and exit status to an existing run_metadata.json.
psao::finish_metadata() {
  local dir="$1"
  local status="${2:-0}"
  PSAO_MD_DIR="$dir" PSAO_MD_STATUS="$status" python3 - <<'PYEOF'
import datetime, json, os
path = os.path.join(os.environ["PSAO_MD_DIR"], "run_metadata.json")
try:
    with open(path) as fh:
        meta = json.load(fh)
except (OSError, json.JSONDecodeError):
    raise SystemExit(0)
meta["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
meta["exit_status"] = int(os.environ["PSAO_MD_STATUS"])
with open(path, "w") as fh:
    json.dump(meta, fh, indent=2)
    fh.write("\n")
PYEOF
}
