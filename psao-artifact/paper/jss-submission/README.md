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

## Second revision (items 1–9)

See `CHANGES.md` (bottom section) for every change with its evidence, and
`TODO_EXPERIMENTS.md` for what still needs the authors. Headline changes:

- A key-material fix (dispatch on the secret alone, not the token's declared
  algorithm) passes the library's full suite on 4 runtimes, behaves identically
  to the stock library in 364 cases per runtime, and removes the discarded parse
  for every token, forged ones included (§8.3–8.4, Tables 9–10, Fig. 9).
- `jwt.sign()` pays the same discarded parse (§7.1, Table 11).
- New Table 2 lists every machine; Tables 4, 5, 6 and 10 say absolute values are
  not comparable across machines.
- The RS256 rejection anomaly on node:26 is V8 stack-trace capture (§8.4).
- Ubuntu 24.04's nodejs support status verified (§5.3); Debian 12 could not be
  measured (archive blocked).

**Must complete before submission** (top of `TODO_EXPERIMENTS.md`): the
alternating A/B on the testbed, the host re-run with `process.versions`, and
the second rating. Also check DOIs (unreachable here) and the upstream status
(`TODO(minor 12)` in §8.5), merge `jss-revision` and mint a new Zenodo version.
The manuscript is 36 pages.

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
