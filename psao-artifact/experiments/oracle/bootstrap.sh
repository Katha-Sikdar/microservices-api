#!/usr/bin/env bash
# bootstrap.sh — prepare a fresh Oracle Cloud instance to run the key-path
# measurement. Runs ON the instance. Idempotent: safe to re-run.
#
# Installs Docker (for the container matrix, using the SAME image tags the
# laptop used, which is what makes the two machines comparable) and nvm with
# three Node versions (for the NATIVE rows, which is the comparison the laptop
# cannot provide for Linux).
#
# Oracle Linux and Ubuntu are both handled because the Always Free images offer
# both, and which one you picked should not change the measurement.
#
# Usage:  ./bootstrap.sh [--skip-docker] [--skip-node]

set -euo pipefail

SKIP_DOCKER=0
SKIP_NODE=0
for a in "$@"; do
  case "$a" in
    --skip-docker) SKIP_DOCKER=1 ;;
    --skip-node) SKIP_NODE=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done

log() { printf '[bootstrap %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

# These are the versions the mechanism result turns on: two OpenSSL 3.0 runtimes
# with different V8 majors, and one OpenSSL 3.5 runtime. Changing this list
# changes what the matrix can attribute.
NODE_VERSIONS="18.20.8 20.20.2 26.6.0"

if [ -r /etc/os-release ]; then . /etc/os-release; else echo "cannot identify OS" >&2; exit 1; fi
log "os: ${PRETTY_NAME:-$ID}  arch: $(uname -m)"

# --- Docker ------------------------------------------------------------------
if [ "$SKIP_DOCKER" -eq 0 ]; then
  if command -v docker >/dev/null 2>&1; then
    log "docker already present: $(docker --version)"
  else
    case "$ID" in
      ol|rhel|centos|almalinux|rocky)
        log "installing docker via dnf"
        sudo dnf install -y dnf-utils
        sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        sudo dnf install -y docker-ce docker-ce-cli containerd.io
        ;;
      ubuntu|debian)
        log "installing docker via apt"
        sudo apt-get update -y
        sudo apt-get install -y ca-certificates curl gnupg
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL "https://download.docker.com/linux/$ID/gpg" \
          | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$ID $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
          | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
        sudo apt-get update -y
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io
        ;;
      *) echo "unsupported distro for automatic docker install: $ID" >&2; exit 1 ;;
    esac
    sudo systemctl enable --now docker
    sudo usermod -aG docker "$USER"
    log "added $USER to the docker group -- you must reconnect for it to take effect"
  fi
fi

# --- Node, natively, at three versions ---------------------------------------
if [ "$SKIP_NODE" -eq 0 ]; then
  export NVM_DIR="$HOME/.nvm"
  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    log "installing nvm"
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  fi
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
  for v in $NODE_VERSIONS; do
    if [ -d "$NVM_DIR/versions/node/v$v" ]; then
      log "node v$v already installed"
    else
      log "installing node v$v"
      nvm install "$v" >/dev/null
    fi
    printf '  v%-9s openssl %s\n' "$v" \
      "$("$NVM_DIR/versions/node/v$v/bin/node" -p 'process.versions.openssl')"
  done
fi

# --- tuning that affects measurement, reported rather than silently applied ---
GOV="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo 'n/a')"
log "cpu governor: $GOV  (n/a is normal on a cloud guest -- frequency is the host's business)"

log "done. Verify with: experiments/oracle/capture_env.sh --steal-window 30"
