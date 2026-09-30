# Response to the reviewer: changes by comment

Manuscript: "It Is Not the Signature: An Empirical Study of a Hidden Key-Parse
Cost in JSON Web Token Validation" (JSS).
Comment IDs follow `JSS_reviewer_report.md`. Section, table and figure numbers
refer to the revised `main.tex` / `submission-files/manuscript-preview.pdf`.

**Status key.** *done*: fully addressed in this revision. *partially*: addressed
with what could be run here; the rest is prepared and listed in
`TODO_EXPERIMENTS.md` (replication package). *needs-authors*: cannot be done
without the authors' hardware, testbed or a second person.

Every number added in this revision is a macro generated from a committed run
file (`analysis/make_review_macros.py` → `review_macros.tex`, with a provenance
map). No number was typed by hand.

## Major comments

| ID | Status | What changed | Where |
|---|---|---|---|
| M1 generalisation | partially | New npm library survey (result: across 64 JWT/JOSE packages ≥50k weekly downloads and 164 crypto/auth packages ≥500k, the only package using a failing parse as a type test is `jsonwebtoken` itself, in `verify()` and also in `sign()`): a stated frame (registry search queries, weekly-download threshold, capture date) and a parser-based detector for "failing parse used as a type test" run over every in-frame package's published tarball; hits adjudicated by hand. PyPI/Go/Maven frames and author confirmation of the adjudication are in TODO. | §3.3 (Library survey), §7.1, Table 1 note c, Table 10; `survey/libsurvey/` |
| M2 relevance | partially | Measured Ubuntu 24.04's packaged Node.js (v18.19.1, system OpenSSL 3.0.13) beside `node:18` and `node:26` on one machine: the OpenSSL 3.0 price persists on a current LTS distribution. Validation now also reported as a share of per-request application CPU. Debian 12 (mirror unreachable) and the in-situ A/B on supported images are prepared (Dockerfiles, commands) but not run. | Abstract, §1, §5.3 + Table 5, §6.2 + Table 6, Table 10 RQ2/RQ3 rows, §10; `experiments/distro/`, `testbed/service-a/Dockerfile.*` |
| M3 single-pair A/B | partially | "within 0.8%" removed everywhere; §6.2 now states the A/B is one pair of consecutive windows at different load with no interval; §10 corrected: CPU accounting excludes queueing but can be inflated by cache/SMT/frequency contention. Alternating, randomised-order A/B driver with k6 pinning and a bootstrap analysis written, not run (needs the Kubernetes testbed). | Abstract, §6.2, Table 6, §10, Table 10; `experiments/run_ab_alternating.sh`, `analysis/ab_alternating.py` |
| M4 jose | done | §7 rewritten: under OpenSSL 3.5.8 the absolute penalties of `jose` and `jsonwebtoken` are statistically indistinguishable (intervals given); the "11 times less" figure is scoped to OpenSSL 3.0; `jsonwebtoken`'s distinguishing property is a failing parse whose price changes by an order of magnitude with the OpenSSL release. Figure 7 caption, Table 10 RQ4 row, abstract and conclusion aligned. | §7, Fig. 7, Table 10, abstract, §11 |
| M5 host OpenSSL | partially | Explained from the run record: the host's Node 26.6.0 is the Homebrew build, which links Homebrew's OpenSSL dynamically (3.6.3 at run time), not the 3.5.x official Node 26 builds bundle; stated in §3.1 and Table 4's note. The version remains inferred, not recorded; the harness now records it on every row, and a re-run is in TODO. | §3.1, Table 4, §10 |
| M6 survey | partially | Counter-search arithmetic fixed (13 = 5 false positives + 1 unresolved + 7 genuine). Abstract now says "none of the 327 call sites in our sample" and §6.3 acknowledges the rare genuine uses. Downward bias from within-file tracing (93 untraced identifiers) discussed. Blinded 110-row stratified sheet + 13-row adjudication sheet, codebook and Cohen's κ script prepared; second rating not done. | Abstract, §6.3, §10; `survey/second_rater/` |
| M7 security, adversarial | done (microbenchmark) / needs-authors (in-service) | Rejected forged tokens timed under stock, narrow fix and pre-parsed key on four runtimes (Table 9): confirms from measurement that a non-HMAC header still reaches the parse under the narrow fix and that only a pre-parsed key avoids it. Behaviour under misconfiguration: stock and narrow fix compared on every combination of 9 kinds of key material (incl. PEM/JWK strings as the "secret"), 7 tokens and 4 algorithm options on four runtimes; no difference. No availability claim is made; in-service measurement in TODO. | §8.1, §8.4, Table 9, §10; `bench/forged-token.js`, `bench/keypath-equivalence.js`, `experiments/run_forged_tokens.sh` |

## Minor comments

| # | Status | What changed | Where |
|---|---|---|---|
| 1 | done | Successful-parse column added to Table 4 (existing run file); the 11.74× span is now shown. | Table 4 |
| 2 | done | Explained: Node 22.22.2 is the x86 VM's own Node (repetition of the host decomposition, Fig. 9); 22.23.3 is the official release binary used for the exception baseline (Table 3). | §3.3 (Second architecture) |
| 3 | done | Plausible causes of the decline with rate and of the pass-to-pass gap listed; the magnitude claim explicitly rests on the CPU A/B instead. | §6.1 |
| 4 | done | Text and caption now say the three-way split is interpretable only for the OpenSSL 3.5 rows; the negative binding values are explained. | §4.1, Table 3 |
| 5 | done | Table 3 caption: "every column is a median of per-process medians over 15 processes". | Table 3 |
| 6 | done | Table 4 caption rewritten. | Table 4 |
| 7 | done | Figure 3(b) redrawn as separate bars, residual hatched and labelled, axis states "paired medians; not additive". | Fig. 3; `figures/make_revision_standin_figures.py` |
| 8 | done | "Two methods, one answer" replaced by both percentages (60% vs 66.2%) and why self-time share and differenced share differ. | §4.2 |
| 9 | done | Number of resamples (10,000, percentile) stated; BCa available via `analysis/keypath_stats.py --ci-method bca` (default output unchanged, verified byte-identical). | §3.2; `analysis/keypath_stats.py` |
| 10 | done | Table 1 gains a *Breadth* column in which most prior work is stronger than this paper; headers no longer stacked. | Table 1 |
| 11 | partially | New related-work paragraphs: exceptions as control flow, performance anti-patterns, npm ecosystem, benchmarking pitfalls and change detection, security–performance trade-offs, using only references already in the bibliography. New references could not be verified (no DOI resolver reachable); see "Candidate references" below. | §2 |
| 12 | partially | §8.5 updated with what could be checked on 30 Sept 2026 (PR unmerged, no release after 9.0.3, main branch unchanged since June 2026). Maintainer comments could not be read here: marked `TODO(minor 12)`. | §8.5 |
| 13 | done | Contribution 5 split: analysis (§8) and guidance (§9). | §1 |
| 14 | done | Code listing of the pre-parse change added. | §9, Fig. 10 |
| 15 | done | Threats state HS256, one 34-character secret, fixed token size; secret length measured (16 vs 256 characters) on four runtimes; PEM-prefixed secrets take the original path by design. | §10, §8.4 |
| 16 | done | Licence (MIT) and corpus reconstruction stated; new `survey/refetch_corpus.py` re-fetches every manifest file and checks its hash. | Data availability; `survey/refetch_corpus.py` |

## Language and typesetting

| Item | Status | Where |
|---|---|---|
| "local; In JavaScript" | done | §2 |
| "(Cito et al., 2017) and routinely ship" | done | §2 |
| Umlauts (Krüger, Mühlbauer) | done: the .bib already used `{\"u}`; the broken glyph came from OT1 encoding; `\usepackage[T1]{fontenc}` added | preamble |
| Space before full stop after "cryptography" | done | §1 |
| "Versionas cause" | done (Table 1 rebuilt with single-line headers) | Table 1 |
| Line-broken DOIs/URLs | done: DOIs and URLs typeset with `xurl` break only at safe points | references |
| Figure 1 text size | done: enlarged | Fig. 1 |
| Units, terminology | done: "discarded parse" used for the cost of the failed `createPublicKey()` call throughout; "attempt" only in prose | throughout |
| Highlights | done | `submission-files/highlights.txt` / `.docx` |

## Candidate references (unverified; not cited)

The revision environment could not reach doi.org, Crossref or publisher sites,
so these were **not** added to the manuscript. The authors should verify each
and add it to §2 where marked:

- C. U. Smith, L. G. Williams. Software performance antipatterns. WOSP 2000. doi:10.1145/350391.350420 (performance anti-patterns)
- A. Decan, T. Mens, P. Grosjean. An empirical comparison of dependency network evolution in seven software packaging ecosystems. Empirical Software Engineering 24(1), 2019. doi:10.1007/s10664-017-9589-y (npm ecosystem)
- M. Zimmermann, C.-A. Staicu, C. Tenny, M. Pradel. Small world with high risks: a study of security threats in the npm ecosystem. USENIX Security 2019 (npm security)
- D. Daly et al. The use of change point detection to identify software performance regressions in a continuous integration system. ICPE 2020. doi:10.1145/3358960.3375791 (change detection)

## Remaining `\todo` / TODO markers in the LaTeX

- §8.5: `TODO(minor 12)`: confirm maintainer responses on the upstream issue and pull request.

Everything else that needs the authors is in `TODO_EXPERIMENTS.md`.

---

# Second revision request (items 1–9)

Every number added in this round is a macro in `review_macros.tex`, generated
by `analysis/make_review_macros.py` from the run directories named below
(replication repository, branch `jss-revision`).

**Table renumbering.** The new machines table is Table 2, so the tables the
request calls 3, 5, 8, 9 and 10 are now Tables 4, 6, 9, 10 and 11. Old numbers
are given in parentheses below.

| Item | Status | What changed | Where | Evidence (run files) |
|---|---|---|---|---|
| 1 Narrow-fix design | done | Implemented the key-material-only variant (`keyonly` in `bench/keypath-patch.js`; diff in `upstream/verify-keyonly.js.patch`). **It passes:** the library's full suite at v9.0.3 gives 511 passing / 0 failing (515 / 0 with the four key-path tests) on all 4 runtimes, identical to stock and to the declared-algorithm narrow fix; the naive variant fails the same 2 key-confusion tests on every runtime. Equivalence extended to 13 kinds of key material (364 cases per runtime) with 0 differences for either fix on 4 runtimes. Forged-token timings re-run with the variant: RS256-header tokens no longer reach the parse. §8.3 now presents both fixes and explains that the key-material restriction, not the declared algorithm, is what the defence needs; §8.4, Table 9 (old 8; new row), Table 10 (old 9; new columns), Figure 9 (new bars and a VM B group) updated; abstract, contributions, Table 10, §9, §8.5 and conclusion follow. | §8.3–8.4, Tables 9–11 (old 8–10), Fig. 9, abstract, §1, §9, §11 | `2026-09-30T09-07-54Z-upstream-suite-variants/summary.csv`; `2026-09-30T09-45-00Z-forged-tokens/` (equivalence_*.csv, forged_tokens.csv); `2026-09-30T09-13-02Z-keypath-mechanism` |
| 2 sign() timing | done | `jwt.sign()` with a string secret vs a pre-parsed key timed on the Table 5 runtimes; §7.1 now reports it (replaces "we did not time it"); Table 10 RQ4 row. | §7.1, Table 11 (old 10) | `2026-09-30T09-16-09Z-keypath-runtime-matrix` (conditions `jwt_sign_*`) |
| 3 Machines | done / not feasible (part) | New Table (machines) in §3.1 listing every machine with CPU, CPUs, OS and the tables/figures it produced; captions of Tables 4, 6 and 10 (old 3, 5, 9), and of the arm64 matrix Table 5, state that absolute values are not comparable across machines. Re-running Tables 5 and 9 on the Table 3 VM (VM A) was **not feasible**: VM A was a per-session cloud VM no longer available; this is stated in §3.1. | §3.1, Table 2 (new), Tables 4, 5, 6, 10 | `MACHINE-vm-b-2026-09-30/machine.txt`; run_metadata.json of each run |
| 4 RS256 rejection on OpenSSL 3.5 | done | Explained by measurement: on `node:26.6.0-alpine` the extra cost of an RS256-header rejection is V8's stack-trace capture for the "invalid algorithm" error; with `--stack-trace-limit=0` it falls to below the HS256 case. On the other three runtimes RS256 is cheaper with or without stack capture. Two sentences in §8.4. Measured: 58.0 → 6.6 µs (RS256, node:26) vs 23.3 → 12.7 µs (HS256). | §8.4 | `2026-09-30T09-14-12Z-rejection-breakdown/rejection_breakdown.csv`; exploratory `--cpu-prof` profiles not committed |
| 5 Debian 12; Ubuntu support status | partially | Ubuntu 24.04 `nodejs` status verified from the archive and Ubuntu's policy page (universe component; security coverage via ESM/Ubuntu Pro; no newer version in the archive) and stated in §5.3. Debian 12 could **not** be added: every Debian mirror was blocked by the revision environment's network policy; commands in TODO_EXPERIMENTS.md; §5.3 says so. | §5.3 | `2026-09-30-ubuntu-nodejs-support/` |
| 6 Failed node:18 process | done | Table 6 (old 5) re-run in full with the new conditions: 0 of 240 invocations failed; the count is generated from the run and shown in the caption. The earlier failure left no output (`docker run` exited non-zero before the harness wrote anything) and is recorded in `data/runs/INDEX.md`. | Table 6 (old 5) caption | `2026-09-30T09-16-09Z-keypath-runtime-matrix` (0 failed invocations of 240) |
| 7 Wording | done | "with 0 and 0 failures" → "without parse failures in either frame". CRediT spacing checked: the PDF text layer and rendering both read "Tasmia Tahmid Prova" (the earlier gap came from OT1 encoding, fixed by `\usepackage[T1]{fontenc}` in the previous round). | §7.1, CRediT | — |
| 8 Author scripts | done (dry-run) / needs-authors (results) | Alternating A/B (`--dry-run` end to end: 5 randomised pairs, bootstrap over pairs, flagged `dummy_data`), host re-run (`run_keypath_mechanism.sh` now records `process.versions`, labels rows `host-openssl<ver>`; run end to end on VM B), and κ (`make_dummy_ratings.py` + `kappa.py --sheets`) all run end to end on dummy data. Listed at the top of TODO_EXPERIMENTS.md under "MUST COMPLETE BEFORE SUBMISSION". The paper keeps the "prepared but not run" wording because the results do not exist yet; TODO lists exactly which sentences change. | TODO_EXPERIMENTS.md | dry-run outputs are not committed (synthetic) |
| 9 DOIs; highlights; cover letter | partially | doi.org and Crossref were still unreachable, so no DOI could be re-checked here (a verification script is in TODO_EXPERIMENTS.md); no new reference was added. Highlights and cover letter regenerated. | submission-files | — |

**Machine note for item 1 and 4 runs.** The forged-token re-run was split into
three invocations filling one run directory (host + node:26, node:18, Ubuntu),
because the revision environment stops background jobs after 30 minutes; the
first attempt was stopped mid-run and discarded. Protocol, machine and
conditions are identical across the three invocations.

---

# Submission copy (first submission, not a response)

Prepared as a fresh submission to JSS, so the manuscript contains no
revision-process language. No number changed.

| Change | Where |
|---|---|
| "prepared but not run", "pending experiments", "the second rating has not yet been done", "first revision" and the TODO comment removed; the same facts stated as limitations (single A/B pair, inferred host OpenSSL, single rater, key-material fix timed on VM B only). | §3.1, §6.2, Fig. 9 caption, §8.5, §10, Data availability |
| Debian 12 sentence rewritten as scope ("were not measured"). | §5.3 |
| Upstream-status sentence dated "at the time of writing"; `STATUS-AT-SUBMISSION` comment left in the source for the authors. | §8.5 |
| Abstract tightened (under 250 words). Cover letter no longer mentions testbed experiments. | abstract, cover letter |
| `jss-submission-copy.zip` contains only the LaTeX source and the upload files, plus `SUBMISSION_README.md`; CHANGES.md and TODO_EXPERIMENTS.md stay in the repositories. | package |
