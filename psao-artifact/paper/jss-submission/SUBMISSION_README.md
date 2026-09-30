# JSS submission copy

**Manuscript:** "It Is Not the Signature: An Empirical Study of a Hidden
Key-Parse Cost in JSON Web Token Validation" (36 pages, Elsevier preprint
format, line numbers). Article type: **Research paper**.

## Upload these (from `submission-files/`)

| File | Item type in the JSS system |
|---|---|
| `manuscript-preview.pdf` | Manuscript |
| `cover_letter.pdf` | Cover letter |
| `highlights.docx` | Highlights |
| `declaration_of_interest.docx` | Declaration of interest (only if asked) |

The LaTeX source (`main.tex`, `references.bib`, `*_macros.tex`, `figures/`) is
here for Overleaf or if the journal asks for source files. In Overleaf: new
project from this zip, compiler pdfLaTeX, main document `main.tex`.

## Before you press submit

1. **Replication package (important).** The paper describes scripts and runs
   that are on the `jss-revision` branch of the replication repository, not yet
   on `main` or in Zenodo record 10.5281/zenodo.23011153. Merge `jss-revision`
   into `main`, create a new GitHub release so Zenodo mints a new version, and
   if the new version has its own DOI, replace `10.5281/zenodo.23011153` in
   `references.bib` (entry `artifact2026`), in the Data availability section
   and in the cover letter, then recompile.
2. **Upstream status.** Check auth0/node-jsonwebtoken issues 966 and 1046 and
   the pull request; if the maintainers have replied, update the sentence at
   the end of Section 8.5 (marked `STATUS-AT-SUBMISSION` in `main.tex`).
3. **Recompile the cover letter** on the day you submit so the date is current.
4. **Co-authors and corresponding author** (Dr. Liew) approve this version.
5. **DOIs.** The DOIs in `references.bib` could not be checked from the
   environment used to prepare this copy; open a few in a browser or run the
   check script in the replication repository's `TODO_EXPERIMENTS.md`.
