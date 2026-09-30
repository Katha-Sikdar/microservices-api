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

## Trimmed to 39 pages

The manuscript is now 39 pages (it was 57), references included. Nothing was deleted from the study. Secondary material moved to a separate **Supplementary Material** document (`supplementary.tex`, 26 pages), which the paper cites as Supplementary Sections S1 to S7:

| Supplement | Contents moved out of the paper |
|---|---|
| S1 | Full related-work discussion, and the three gaps we searched for |
| S2 | Protocol details, full C-probe, exception and in-situ method text, the three prevalence frames, host-state note |
| S3 | Residual of the decomposition and the profiler confirmation |
| S4 | Runtime-matrix limitations and the x86_64 table (Table S1) |
| S5 | In-situ values (Table S2), drift between passes, host load, full prevalence counts |
| S6 | Full threats to validity |
| S7 | Design note on relocating validation to the service mesh |

The paper keeps a short summary in each place. The introduction, related work, implications, future work and conclusion were condensed, and the references are set in a smaller font.

**Overleaf:** `supplementary.tex` reads cross-references from `main.aux`. The simplest route is to upload the ready-made `submission-files/supplementary-material.pdf`. To rebuild it, compile `main.tex` first, then set `supplementary.tex` as the main document and compile.

## Upload

| File | Item type |
|---|---|
| `submission-files/manuscript-preview.pdf` (or your Overleaf PDF) | Manuscript |
| `submission-files/supplementary-material.pdf` | Supplementary material |
| `submission-files/cover_letter.pdf` | Cover letter |
| `submission-files/highlights.docx` | Highlights |
| `submission-files/declaration_of_interest.docx` | Declaration of interest (only if the menu offers it) |

Article type: **Research paper** (full-length article).

## Before submitting

1. Check the current JSS Guide for Authors for the abstract limit and keyword count.
2. Recompile the cover letter on the day you submit, so `\today` shows that date.
3. Dr. Liew, the corresponding author, should agree to the new title and to the JSS submission.
