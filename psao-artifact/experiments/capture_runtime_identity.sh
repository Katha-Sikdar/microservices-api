#!/usr/bin/env bash
# capture_runtime_identity.sh — what does each measured image actually contain?
#
# The matrix attributes cost to the bundled OpenSSL rather than to V8. That
# attribution rests on two runtimes sharing an OpenSSL series while differing in
# V8 major version -- so the V8 version is load-bearing evidence and must be a
# recorded datum, not a claim in prose. The original run recorded node and
# openssl per row but not v8; this captures all three, plus the image digest, so
# the identity is pinned to the bytes that ran.
#
# Identity is a property of the image, not of a timing run, so this does not
# require re-measuring. It DOES require that the image still resolves to the
# same digest; the digest column is what lets a reviewer check that.
set -uo pipefail
OUT="${1:-data/runs/runtime_identity.csv}"
IMAGES="${2:-node:18.20.8-alpine node:20-alpine node:26.6.0-alpine node:26.6.0-bookworm}"
mkdir -p "$(dirname "$OUT")"
echo "image,node_version,openssl_version,v8_version,v8_major,libc,arch,image_id,captured_at_utc" > "$OUT"
for img in $IMAGES; do
  docker image inspect "$img" >/dev/null 2>&1 || docker pull -q "$img" >/dev/null 2>&1 || {
    echo "  WARNING: $img unavailable, skipping" >&2; continue; }
  id="$(docker image inspect "$img" --format '{{.Id}}' 2>/dev/null)"
  probe="$(docker run --rm "$img" node -e '
    const fs = require("fs");
    const musl = ["/lib/ld-musl-aarch64.so.1","/lib/ld-musl-x86_64.so.1"].some(p => fs.existsSync(p));
    const v8 = process.versions.v8;
    console.log([process.version, process.versions.openssl, v8, v8.split(".")[0],
                 musl ? "musl" : "glibc", process.arch].join(","));
  ' 2>/dev/null)" || { echo "  WARNING: $img will not run node" >&2; continue; }
  echo "$img,$probe,$id,$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT"
  echo "  $img -> $probe"
done
echo "wrote $OUT"
