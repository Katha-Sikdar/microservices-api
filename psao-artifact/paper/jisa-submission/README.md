# Journal of Information Security and Applications (JISA) submission package

Same manuscript as the Computers & Security package (`../cose-submission/`), retargeted to JISA.
The only changes are the journal name in `main.tex` (`\journal{...}`) and the cover letter's
"why this journal" paragraph. All numbers still come from the macro files.

## Upload

| File | Item type |
|---|---|
| `submission-files/manuscript-preview.pdf` (or your Overleaf PDF) | Manuscript |
| `submission-files/cover_letter.pdf` | Cover letter |
| `submission-files/highlights.docx` | Highlights |
| `submission-files/declaration_of_interest.docx` | Declaration of interest (only if the menu offers it) |

Overleaf: upload the zip as a new project, compiler **pdfLaTeX**, main document **main.tex**,
then **Recompile from scratch**.

## Before submitting

1. Check JISA's current Guide for Authors for the abstract word limit. The abstract is 252 words; if the
   limit is 250, drop its last sentence ("The defect has been reported upstream.").
2. If the form asks whether the paper was submitted elsewhere before, answer honestly: it was
   desk-rejected by Computers & Security on 29 September 2026 without review.
3. Recompile the cover letter on the day you submit (`\today`).
