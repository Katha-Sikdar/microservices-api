# Revised manuscript — 2026-09-24

Build: `latexmk -pdf main.tex` (or `pdflatex main; bibtex main; pdflatex main; pdflatex main`).
Compiles cleanly with TeX Live 2023 and the bundled `sn-jnl.cls`.

| file | what |
|---|---|
| `main.tex` | **the revised manuscript** (base: your `main_1.tex`) |
| `main.pdf` | compiled |
| `main-diff.pdf` | every change against your original `main_1.tex` |
| `main-diff-round3.pdf` | only the latest round's changes (page layout, float placement, RQ list, captions) |
| `main_1.tex` | your version, unchanged |
| `CHANGES.md` | every edit, why, and what is still for the authors |
| `UPSTREAM_STATUS.md` | auth0/node-jsonwebtoken #966 / #1046 / #1047 status and draft comment |
| `keypath_macros.tex` | original measurements (regenerated; additions only — see CHANGES.md) |
| `revision_macros.tex` | the new measurements (C probe, exception baseline, x86_64, cross-library) |
| `provenance/*.csv` | each macro → the run file it was read from |
| `discarded-exception.bib` | 60 scholarly references (the upstream issues are linked directly in the text) |
| `figures/codepath_excerpt.js` | verify.js lines 120–130 at v9.0.3 (sha256 prefix matches `\CodeExcerptHash`) |
| `figures/fig_decomposition.pdf`, `figures/fig_runtime_matrix.pdf`, `figures/fig_insitu_rate.pdf` | generated from the committed data by `figures/make_revision_standin_figures.py` |
| `sn-fallback.tex` | minimal stand-in, used only if `sn-jnl.cls` is absent |

The measurement code and every run directory are in the repository
(`psao-artifact/`), branch `claude/optimistic-goodall-i0e5zp`.
