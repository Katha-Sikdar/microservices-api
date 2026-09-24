# Revised manuscript — 2026-09-24

Build: `latexmk -pdf main.tex` (or `pdflatex main; bibtex main; pdflatex main; pdflatex main`).
Compiles cleanly with TeX Live 2023 and the bundled `sn-jnl.cls`.

| file | what |
|---|---|
| `main.tex` | **the revised manuscript** (base: your `main_1.tex`) |
| `main.pdf` | compiled |
| `main-diff.tex`, `main-diff.pdf` | `latexdiff main_1.tex main.tex` — every change marked |
| `main_1.tex` | your version, unchanged |
| `CHANGES.md` | every edit, why, and what is still for the authors |
| `UPSTREAM_STATUS.md` | auth0/node-jsonwebtoken #966 / #1046 / #1047 status and draft comment |
| `keypath_macros.tex` | original measurements (regenerated; additions only — see CHANGES.md) |
| `revision_macros.tex` | the new measurements (C probe, exception baseline, x86_64, cross-library) |
| `provenance/*.csv` | each macro → the run file it was read from |
| `discarded-exception.bib` | 60 scholarly references + 2 issue entries |
| `figures/codepath_excerpt.js` | verify.js lines 120–130 at v9.0.3 (sha256 prefix matches `\CodeExcerptHash`) |
| `figures/fig_decomposition.pdf`, `figures/fig_runtime_matrix.pdf` | **stand-ins** drawn from the committed data by `figures/make_revision_standin_figures.py`; replace with your originals if you have them |
| `figures/fig_insitu_rate.pdf` | from the repository |
| `sn-fallback.tex` | minimal stand-in, used only if `sn-jnl.cls` is absent |

The measurement code and every run directory are in the repository
(`psao-artifact/`), branch `claude/optimistic-goodall-i0e5zp`.
