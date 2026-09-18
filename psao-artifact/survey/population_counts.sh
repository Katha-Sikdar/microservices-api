#!/usr/bin/env bash
# population_counts.sh — record GitHub code-search totals to a CSV.
#
# `gh search code` returns [] for multi-term queries that the underlying
# search/code API answers normally, so these go through `gh api` directly.
# Counts are GitHub's own estimates and drift; the timestamp is part of the
# datum, not decoration.
set -uo pipefail
OUT="${1:-survey/data/population_counts.csv}"
mkdir -p "$(dirname "$OUT")"
echo "captured_at_utc,query,total_count" > "$OUT"
q() {
  n=$(gh api -X GET search/code -f q="$1" --jq '.total_count' 2>/dev/null)
  printf '%s,"%s",%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${n:-}" >> "$OUT"
  printf '  %-62s %s\n' "$1" "${n:-FAILED}"
  sleep 7
}
q "require('jsonwebtoken') language:javascript"
q "require('jsonwebtoken') createSecretKey language:javascript"
q "from 'jsonwebtoken' language:typescript"
q "from 'jsonwebtoken' createSecretKey language:typescript"
q "jwt.verify language:javascript"
q "jwt.verify createSecretKey language:javascript"
echo "wrote $OUT"
