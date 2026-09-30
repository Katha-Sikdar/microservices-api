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
