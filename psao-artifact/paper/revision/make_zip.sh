#!/usr/bin/env bash
# make_zip.sh -- assemble the revised manuscript as a self-contained archive
# that compiles with `latexmk -pdf main.tex` (or pdflatex/bibtex/pdflatex x2).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; P="$HERE/.."; A="$P/.."
OUT="${1:-$HERE/revised-manuscript-2026-09-24.zip}"
T="$(mktemp -d)/revised-manuscript"; mkdir -p "$T/figures" "$T/provenance"
cp "$HERE/main.tex" "$HERE/main_1.tex" "$HERE/CHANGES.md" "$HERE/sn-fallback.tex" "$T/"
[ -f "$HERE/main.pdf" ] && cp "$HERE/main.pdf" "$T/"
[ -f "$HERE/main-diff.tex" ] && cp "$HERE/main-diff.tex" "$T/"
[ -f "$HERE/main-diff.pdf" ] && cp "$HERE/main-diff.pdf" "$T/"
cp "$P/keypath_macros.tex" "$P/revision_macros.tex" "$P/discarded-exception.bib" \
   "$P/sn-jnl.cls" "$P/sn-basic.bst" "$T/"
cp "$P/keypath_macros_provenance.csv" "$P/revision_macros_provenance.csv" "$T/provenance/"
cp "$HERE/codepath_excerpt.js" "$HERE/figures/"*.pdf "$T/figures/"
cp "$P/fig_insitu_rate.pdf" "$T/figures/"
cp "$A/upstream/STATUS.md" "$T/UPSTREAM_STATUS.md"
cp "$HERE/ZIP_README.md" "$T/README.md"
(cd "$(dirname "$T")" && rm -f "$OUT" && zip -qr "$OUT" "$(basename "$T")")
echo "$OUT"
