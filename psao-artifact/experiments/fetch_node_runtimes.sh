#!/usr/bin/env bash
# fetch_node_runtimes.sh — download official Node.js release binaries for the
# exception-cost and cross-runtime experiments. Official binaries statically
# bundle their own OpenSSL, so each one pins a (V8, OpenSSL) pair.
#
# The default set contains two pairs chosen to separate engine from library:
#   18.20.8 (V8 10.2, OpenSSL 3.0.16)   20.20.2 (V8 11.3, OpenSSL 3.0.19)
#   22.23.3 (V8 12.4, OpenSSL 3.5.8)    23.11.1 (V8 12.9, OpenSSL 3.0.16)
#   24.21.0 (V8 13.6, OpenSSL 3.5.8)    26.10.0 (V8 14.6, OpenSSL 3.5.8)
# Node 23 carries a NEWER V8 than Node 22 and an OLDER OpenSSL.
#
# Usage: experiments/fetch_node_runtimes.sh [version ...]   (to $PSAO_NODE_RUNTIMES)
set -euo pipefail
DEST="${PSAO_NODE_RUNTIMES:-/opt/node-rt}"
VERSIONS=("$@")
[ ${#VERSIONS[@]} -gt 0 ] || VERSIONS=(18.20.8 20.20.2 22.23.3 23.11.1 24.21.0 26.10.0)
case "$(uname -m)" in x86_64) ARCH=x64 ;; aarch64|arm64) ARCH=arm64 ;; *) echo "unsupported arch"; exit 1 ;; esac
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
mkdir -p "$DEST"; cd "$DEST"
for v in "${VERSIONS[@]}"; do
  d="node-v$v-$OS-$ARCH"
  [ -x "$d/bin/node" ] || { curl -sSfL "https://nodejs.org/dist/v$v/$d.tar.xz" | tar xJ; }
  echo "$d $("$d/bin/node" -p 'process.versions.openssl+" "+process.versions.v8')"
done
