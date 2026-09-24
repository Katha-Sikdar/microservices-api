#!/usr/bin/env bash
# run_revision_suite.sh — every measurement added in the revision, run one
# experiment at a time so no two compete for the machine:
#
#   1. openssl-c-probe      the parse in plain C across OpenSSL versions
#   2. exception-cost       V8 exception baseline + the real probe, 6 runtimes
#   3. crosslib             7 JWT libraries in 4 languages
#   4. keypath-mechanism    Table 1, repeated on this machine
#   5. runtime matrix       Table 2, repeated on this machine (needs Docker)
#
# Set PSAO_ENV_LABEL to name the machine (it is written into every row).
# Prerequisites: experiments/build_openssl_versions.sh,
#                experiments/fetch_node_runtimes.sh, bench/ npm ci, Docker.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PSAO_ENV_LABEL="${PSAO_ENV_LABEL:-$(uname -m)-host}"
STEPS="${PSAO_STEPS:-1 2 3 4 5}"
for s in $STEPS; do
  case "$s" in
    1) "$HERE/run_openssl_c_probe.sh" ;;
    2) "$HERE/run_exception_cost.sh" ;;
    3) "$HERE/run_crosslib.sh" ;;
    4) "$HERE/run_keypath_mechanism.sh" ;;
    5) "$HERE/run_keypath_container.sh" \
         --images "node:18.20.8-alpine node:20-alpine node:26.6.0-alpine node:26.6.0-bookworm" ;;
  esac
done
