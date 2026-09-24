#!/usr/bin/env bash
# build_openssl_versions.sh — build several OpenSSL releases from source with
# ONE compiler and ONE set of flags, so that bench/c/openssl-probe.c can be
# linked against each and the versions compared with nothing else varying.
#
# Tarballs come from the OpenSSL GitHub releases. Builds go to
# $PSAO_OPENSSL_PREFIX/<version> (default /opt/ossl). Libraries only: no tests,
# no docs, no apps are needed by the probe.
#
# Usage: experiments/build_openssl_versions.sh [version ...]
set -euo pipefail
PREFIX="${PSAO_OPENSSL_PREFIX:-/opt/ossl}"
SRC="${PSAO_OPENSSL_SRC:-/opt/ossl-src}"
VERSIONS=("$@")
[ ${#VERSIONS[@]} -gt 0 ] || VERSIONS=(3.0.16 3.0.19 3.1.8 3.2.6 3.3.5 3.4.3 3.5.8 3.6.1)
mkdir -p "$SRC" "$PREFIX"
cd "$SRC"
for v in "${VERSIONS[@]}"; do
  [ -f "$PREFIX/$v/lib/libcrypto.so" ] && { echo "have $v"; continue; }
  [ -f "openssl-$v.tar.gz" ] || curl -sSfLO "https://github.com/openssl/openssl/releases/download/openssl-$v/openssl-$v.tar.gz"
  rm -rf "openssl-$v"; tar xzf "openssl-$v.tar.gz"
  ( cd "openssl-$v"
    CC=gcc ./Configure linux-"$(uname -m)" --prefix="$PREFIX/$v" --libdir=lib shared no-tests no-docs -O2 >"../cfg-$v.log" 2>&1 \
      || CC=gcc ./Configure linux-"$(uname -m)" --prefix="$PREFIX/$v" --libdir=lib shared no-tests -O2 >"../cfg-$v.log" 2>&1
    make -j"$(nproc)" build_libs >"../build-$v.log" 2>&1
    make install_dev >>"../build-$v.log" 2>&1 )
  rm -rf "openssl-$v"
  echo "built $v -> $PREFIX/$v"
done
