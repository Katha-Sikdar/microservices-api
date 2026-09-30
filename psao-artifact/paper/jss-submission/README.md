# Journal of Systems and Software (JSS) submission package

This is the JISA manuscript reframed for a software-engineering journal. JISA and Computers & Security both desk-rejected it as out of scope. All numbers still come from the macro files, and the new charts read their values from the same macros.

## Overleaf

Upload the zip as a new project, set the compiler to **pdfLaTeX** and the main document to **main.tex**, then **Recompile from scratch**. The new charts use `pgfplots`, which Overleaf includes.

## What changed from the JISA version

**Framing**
- **Title:** *It Is Not the Signature: An Empirical Study of a Hidden Key-Parse Cost in JSON Web Token Validation*.
- **Abstract:** now leads with performance attribution, root cause and the transitive dependency. The security coupling is presented as the reason the obvious optimisation is unsafe. It is 232 words.
- **Keywords (6):** Empirical study, performance analysis, software libraries, root-cause analysis, JSON Web Token, OpenSSL.
- **Introduction:** opens with performance misattribution and prior empirical studies of performance bugs. A new paragraph explains why the case matters for software engineering. Contributions are reordered so that the security constraint comes last, and a guidance contribution and an organisation paragraph are added.
- **RQ5 and Section 8:** retitled *Removing the cost safely*.

**New figures and table**
- **Figure 7:** where the secret passed to the validator comes from, across 327 call sites (RQ3 survey).
- **Figure 8:** the raw-secret to pre-parsed cost ratio across seven libraries, on a log scale (RQ4).
- **Figure 10:** stock library vs narrow fix vs pre-parsed key, on both machines (RQ5).
- **Table 11:** summary of findings, evidence and implications, by RQ and by who acts (Implications section).

**Submission files**
- The cover letter is addressed to JSS and fits on one page.
- There are 5 new highlights, each at most 85 characters.
- The declaration shows the new journal and title.

## Revised after the reviewer report (JSS_reviewer_report.md)

This version answers the reviewer's M1–M7, minors 1–16 and language items. See
`CHANGES.md` for the response table (one row per comment, with status and
location) and `TODO_EXPERIMENTS.md` for what still needs the authors' Mac,
Kubernetes testbed or a second rater. The manuscript is 34 pages (was 26),
because the new analyses the reviewer asked for were added:

- Section 5.3 and Table 5: Ubuntu 24.04's packaged Node.js (system OpenSSL 3.0) still pays the slow price (M2).
- Section 7.1: an npm survey of 228 popular packages; only `jsonwebtoken` uses a failing parse as a type test (M1).
- Section 8.4 and Table 9: measured cost of rejected forged tokens; the narrow fix behaves identically to the stock library on 252 cases x 4 runtimes (M7).
- Corrected: the jose comparison (M4), the host OpenSSL source (M5), the survey counts (M6), the A/B wording (M3), and all minor items.

Every new number comes from `review_macros.tex`, generated from run files in
the replication repository (branch `jss-revision`).

**Before submitting:** check the upstream issue for maintainer comments and
update the sentence marked `TODO(minor 12)` in Section 8.5; confirm the two
survey adjudications; and, to cite the new scripts, merge the `jss-revision`
branch and publish a new Zenodo version, then use its DOI in the paper's
reference and Data availability section if it differs.

## Upload

| File | Item type |
|---|---|
| `submission-files/manuscript-preview.pdf` (or your Overleaf PDF) | Manuscript |
| `submission-files/cover_letter.pdf` | Cover letter |
| `submission-files/highlights.docx` | Highlights |
| `CHANGES.md` (as PDF or pasted) | Response to reviewers, if the journal asks for one |
| `submission-files/declaration_of_interest.docx` | Declaration of interest (only if the menu offers it) |

Article type: **Research paper** (full-length article).

## Before submitting

1. Check the current JSS Guide for Authors for the abstract limit and keyword count.
2. Recompile the cover letter on the day you submit, so `\today` shows that date.
3. Dr. Liew, the corresponding author, should agree to the new title and to the JSS submission.
