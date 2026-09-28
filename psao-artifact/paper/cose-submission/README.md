# Computers & Security submission package

## Import into Overleaf

1. New Project → Upload Project → choose this zip.
2. Menu → Compiler: **pdfLaTeX**. Main document: **main.tex**.
3. Recompile. The `elsarticle` class and the `elsarticle-harv` style are built into Overleaf.

A local build uses `latexmk -pdf main.tex`. It compiles cleanly with TeX Live 2023.

## Files

| File | What it is | Upload in Editorial Manager as |
|---|---|---|
| `main.tex` + `references.bib` + `*_macros.tex` + `figures/` | the manuscript source (Elsevier `elsarticle`, author–year, line-numbered) | Manuscript (upload the PDF, or the LaTeX source files if asked) |
| `submission-files/manuscript-preview.pdf` | the compiled manuscript | Manuscript PDF |
| `submission-files/highlights.docx` (and `.txt`) | 5 highlights, each ≤ 85 characters | Highlights |
| `submission-files/cover_letter.tex` / `.pdf` | cover letter | Cover Letter |
| `figures/*.pdf`, `figures/fig_verify_order.tex`, `figures/fig_workflow.tex` | figures (vector) | Figures, if asked separately |

Article type: **Full Length Article**.

## What changed from the Springer version

**Format**
- Converted from `sn-jnl` to Elsevier `elsarticle` (preprint, 12 pt, line numbers, author–year references).
- Added an Elsevier front matter and keywords.
- Added the Elsevier declaration sections: CRediT, competing interest, funding, data availability, ethics and responsible disclosure, and generative AI.

**Security reframing**
- **Title and abstract:** these now lead with the security result.
- **Keywords:** now include *authentication*, *key confusion* and *cryptographic API*.
- **Introduction:** new paragraph on the security significance, a new research question (RQ5), and a rewritten security contribution in position 2.
- **Section 2 (related work):** the key-confusion paragraph now covers the library's history: CVE-2015-9235, and CVE-2022-23539/23540/23541 fixed in 9.0.0.
- **Section 8** is now *"RQ5: The cost as a security property"*. It keeps the original fix, constraint and upstream text, and adds these parts:
  - 8.1 Threat model.
  - 8.2 The attempt precedes authentication. This adds a **new Figure 7**, the order of operations in `verify()` with line numbers.
  - 8.3 The attempt arrived with a key-confusion fix. This comes from comparing `verify.js` in 8.5.1, 9.0.0 and 9.0.3.
  - 8.5 What the narrow fix leaves reachable. This adds a **new Table 10**.
- **Section 9 (implications):** adds a paragraph for security reviewers, and clarifies that pinning the algorithm does not remove the cost.
- **Section 10, now "Threats to validity and future work":** the 14 existing threats, with their text unchanged, are grouped under Measurement, Deployment measurement, Survey of public code and Scope. There is a new threat: the security analysis is from source code, not attack traffic. A new **10.5 Future work** covers security, cause, generality and deployment; it is drawn only from limitations the paper already states.
- **Section 11 (conclusion):** adds a security paragraph.
- **New Table 1 (Section 2.1):** positions the paper against the closest lines of work. Each cell records only what Section 2 itself says about the cited work.
- **New Figure 1 (Section 3):** the study workflow: research questions → instruments → the tables and figures each produces. Its numbers are live references, so they update automatically.
- **New Figure 5:** the C-probe cost across the 8 OpenSSL releases. It is generated from `revision_macros.tex` by `figures/make_fig_openssl_releases.py`, so no value is typed by hand.
- **New references:** `auth0bulletin2022` and `ghsa2015jsonwebtoken`.

No measured value was changed. Every number still comes from the macro files.

## Check before submitting (authors only)

1. **Upstream status.** Section 8.6 says that neither issue #1046 nor the PR has a maintainer response. Update it if that has changed. Also confirm who authored PR #1047 (opened by `Hashim1999164`). The paper does not call it "our" PR.
2. **New security statements.** Sections 8.2, 8.3 and 8.5 and Table 10 come from reading `verify.js` (8.5.1 / 9.0.0 / 9.0.3) and the patch in `upstream/verify.js.patch`. They were not measured. Check that you agree with them.
3. **Generative AI declaration.** It names Claude (Anthropic) for restructuring and drafting. Edit it to match how you actually used AI tools.
4. **Originality statement in the cover letter.** Confirm it. The earlier, withdrawn manuscript (*"It Is Not the Cryptography…"*) must not be under consideration anywhere else.
5. **Replication package DOI (recommended).** Archive the GitHub repository on Zenodo and cite the DOI in `artifact2026` and in the Data availability section.
6. **Suggested reviewers (optional).** Editorial Manager may ask for 3–5 reviewers with no conflict of interest. Choose them from JWT/JOSE security, crypto-API misuse, or performance engineering.
7. **Table 1 cells.** Each ✓ / ○ / – restates what Section 2 already says about the cited work. Check each against the cited paper.
8. **Journal limits.** Check the current Guide for Authors for Computers & Security, especially abstract length. The abstract is about 240 words; there are 7 keywords and 5 highlights of at most 85 characters each.
