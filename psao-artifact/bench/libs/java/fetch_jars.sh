#!/usr/bin/env bash
# Fetch the pinned Java dependencies from Maven Central into lib/ (retrying on
# 429, which Central returns under load).
set -euo pipefail
cd "$(dirname "$0")"; mkdir -p lib
M=https://repo1.maven.org/maven2; J=2.18.2
for p in com/nimbusds/nimbus-jose-jwt/10.10/nimbus-jose-jwt-10.10.jar \
         io/jsonwebtoken/jjwt-api/0.13.0/jjwt-api-0.13.0.jar \
         io/jsonwebtoken/jjwt-impl/0.13.0/jjwt-impl-0.13.0.jar \
         io/jsonwebtoken/jjwt-jackson/0.13.0/jjwt-jackson-0.13.0.jar \
         com/fasterxml/jackson/core/jackson-databind/$J/jackson-databind-$J.jar \
         com/fasterxml/jackson/core/jackson-core/$J/jackson-core-$J.jar \
         com/fasterxml/jackson/core/jackson-annotations/$J/jackson-annotations-$J.jar; do
  f="lib/$(basename "$p")"; [ -s "$f" ] && continue
  for t in 1 2 3 4 5; do curl -sSfL "$M/$p" -o "$f" && break; rm -f "$f"; sleep $((t * 4)); done
  [ -s "$f" ] || { echo "could not fetch $p" >&2; exit 1; }
done
