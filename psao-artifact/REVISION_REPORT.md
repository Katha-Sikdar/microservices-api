# REVISION_REPORT — "It Is Not the Signature", EMSE revision

**Status: stopped at Part A, as the brief instructs.** A1 requires a macOS shell
I do not have, and — more importantly — the artifact contains a note that
invalidates A1's premise. A2 is **done** and yielded a stronger result than the
paper currently claims. Most of Part B needs hardware, builds or a package
registry that this environment cannot reach; none of it was substituted with a
weaker experiment.

---

# 1. Claims whose meaning changed

## 1.1 §6.4 can now make the *stronger* claim, not the weaker one

The A/B runs record `cpu_app_millicores` — CPU consumed by the application
container — not only client-side latency. That settles the wall-clock/CPU
question in favour of the original title.

| | enabled | disabled | difference |
|---|---|---|---|
| **app CPU (µs/request)** | **731.9** | **347.3** | **384.6 (52.6%)** |
| app CPU (millicores) | 146.377 | 69.454 | |
| mean latency (ms) | 2.0332 | 1.6802 | 0.3530 (17.4%) |
| p99 latency (ms) | 8.089 | 6.348 | |
| *control:* sidecar CPU (mc) | 49.132 | 53.401 | −4.269 |
| *control:* event-loop lag p99 (ms) | 3.159 | 3.137 | |
| *confound:* host load at start | 5.11 | 3.53 | ratio 1.45 |

200 req/s, 36,001 requests per arm, same images, same ingress.

A request that queues or is descheduled accrues wall clock but **no CPU**. A
384.6 µs/request CPU difference therefore cannot be queueing delay. §6.4 is
rewritten to say so, and the subsection title reverts to *"the cost is real
processor time"*.

The two controls hold: sidecar CPU moves 4.269 millicores *in the opposite
direction*, so the difference is in the application container and not the mesh;
event-loop lag is unchanged, so neither arm is near saturation.

## 1.2 A new, unplanned corroboration — and a partial answer to §6.1's gap

The deployed image is `node:18-alpine` (`service-a/Dockerfile`). Table 2 times
that runtime's discarded parse at **373.79 µs** in a single-process
microbenchmark. The A/B attributes **384.6 µs** of CPU per request to the
validation call in a live deployment over 36,001 requests.

Two instruments sharing no code and no arithmetic land **within 3%**.

§6.1 currently reports a 60–640 µs "unaccounted" gap between the in-situ means
and the sum of measured components. That gap is a *wall-clock* gap. On the CPU
axis there is essentially no gap. This should be stated — it is the strongest
single sentence available to §6 and it costs nothing to add.

## 1.3 A1's premise is wrong: re-running does not restore Table 1's provenance

`data/runs/HOST-OPENSSL-DRIFT-2026-09-17.md` records that on 2026-09-17 16:02
local, `brew install oci-cli` upgraded `openssl@3` from **3.6.3 → 3.6.4**.
Homebrew's Node links OpenSSL *dynamically*, so `node --version` still reports
v26.6.0 from the same binary while `process.versions.openssl` moved underneath
it.

Consequences the brief did not anticipate:

- Table 1 ran on **3.6.3**, inferred from run timestamps, because the per-row
  OpenSSL column *did not exist yet*. The note is explicit that the column was
  added **because of** this incident, not before it.
- The host is now on **3.6.4** and pinned. A re-run today produces 3.6.4 numbers
  that are **not poolable** with Phase 1. The note says so directly: label any
  new host run `host-openssl3.6.4` rather than appending to `host`.
- There is already a signal that the versions differ: the probe measured
  **18.04 µs on 3.6.3** (15 invocations, CI [17.83, 18.25]) against **17.60 µs
  on 3.6.4** (one informal run).

So A1 as written — "re-run with the version recorded, then delete §9's
paragraph" — is not a bookkeeping fix. It is a **re-measurement of the whole of
§4**, and every derived number moves with it. My recommendation, contrary to the
brief:

1. **Fill Table 2's host cell now** as `3.6.3`, explicitly labelled as inferred
   from run timestamps rather than recorded. That is honest and strictly better
   than `n/r`.
2. **Keep §9's paragraph**, sharpened to say the version is known by timestamp
   and why — and cite the drift note. It stops being an admission of sloppiness
   and becomes an instance of the paper's own thesis: the crypto library moved
   on an unchanged runtime as a side effect of installing an unrelated CLI.
3. Re-run §4 on 3.6.4 **only** if you are prepared to replace Table 1 wholesale.

This is the single most consequential finding in this report, and it argues for
*less* work than the brief assumed, not more.

## 1.4 B4 (source half): two sibling libraries do **not** have the defect

Verified by reading published source, not by benchmark:

- **`fast-jwt`** (`src/verifier.js`) dispatches on the detected algorithm family
  and calls exactly one constructor:
  `key = prepareKeyOrSecret(key, hsAlgorithms.includes(availableAlgorithms[0]))`
  → `return isSecret ? createSecretKey(key) : createPublicKey(key)`.
  No speculative parse, no try/catch around key parsing.
- **`jose`** does not accept a plain string for HS\* at all; the secret must be a
  `Uint8Array`/`CryptoKey`/`KeyObject`. The ambiguity is removed at the API
  boundary.

This **strengthens §7**: the fix the paper proposes is not speculative, it is the
design two maintained siblings already ship, by two different routes (dispatch,
and refusing the ambiguous input). It also narrows §9's "One library at one
version" from "we don't know" to "we checked two others at source level and
neither reproduces it; we did not time them."

---

# 2. Item-by-item

| Item | Status | Where | Note |
|---|---|---|---|
| **A1** host OpenSSL | **not done — premise changed** | §1.3 above | No macOS shell reachable; and a re-run replaces Table 1 rather than annotating it. Two edits recommended instead. |
| **A2** §6.4 A/B numbers | **done** | `analysis/make_ab_macros.py`, `paper/ab_macros.tex`, `paper/section64_ab.tex` | 22 macros, each carrying its source file. Stronger claim now supported. |
| **A3** placeholders | **partial** | below | Test titles and the verify.js digest not obtainable here; both are recoverable on your machine. |
| **B1** OpenSSL vs V8 | **not done** | — | Needs Node built `--shared-openssl` against two OpenSSL trees, on the measurement machine. Hours of compilation; cannot be done from here. |
| **B2** exception bound | **not done** | — | Must run on the Table 2 runtimes and the host. The harness is trivial; the *placement* is the constraint. |
| **B3** x86_64 | **not done** | — | This container is x86_64 but a 2-vCPU shared ephemeral cloud VM with npm blocked. Running Table 1 here and calling it the second-architecture replication is exactly the substitution the brief forbids — and Laaber et al. (already cited in §2) is the reason. |
| **B4** second library | **partial — source done, timing not** | §1.4 above | Classification verified from published source. Timing needs npm. |
| **B5** second rater | **not done, by design** | `survey/` | Your `survey/classify.py`, `survey/data/` and `survey/counterexamples.py` hold what the sheet needs. I did not rate. |
| **B6** related work | **done** | §3 below | Both references verified against Crossref, not memory. |
| **B7** upstream issue | **already done by you** | `upstream/jsonwebtoken-issue.md`; issue #1046 | Moot. See §4.2. |
| **C1–C4** writing | **not done, deliberately** | — | All four depend on whether §4 is re-run. Editing prose before the numbers settle means doing it twice. |

## A3 detail

| Placeholder | Status |
|---|---|
| Fig. 1 sha256 | **Partial.** Full digest of the *excerpt* is `4c4781826f49fa9006cb8e42be400c46953870c7d46f4219ec342330ba8ced71`. The digest of the pinned `verify.js` could not be computed: `raw.githubusercontent.com` is 403 to this container's egress, and WebFetch returns rendered text, not bytes. **You have the file** — `shasum -a 256 node_modules/jsonwebtoken/verify.js`. Until then the caption must say "sha256 prefix" or use the excerpt digest and say so. |
| §7 test titles | **Not done.** npm is 403-blocked here, so the suite cannot be run. But `upstream/verify.js.patch` and `upstream/verify-keypath.tests.js` are in your tree: apply the unrestricted variant at v9.0.3 and run `npx mocha test/wrong_alg.tests.js --reporter spec`. The file is confirmed — commit `1bb584b` adds `describe("signing with pub key as symmetric")` → `it("should not verify")`. |
| Ref [4] inline note | **Ready.** Delete the `note = {...AUTHORS: mint the DOI...}` field; replace with `% TODO(authors): DOI` above the entry. |
| Anonymity switch | **Ready, not applied** — see §3.2. |
| Red text | **Diagnosis.** In the build I hold, red comes from the `\TODO`/`\AUTHORNOTE` macros, not hyperref. `\showauthornotesfalse` removes it. If red persists on "version 9.0.3", it is hyperref link colour: add `hidelinks` to the `hyperref` options or `\hypersetup{colorlinks=false}`. |

---

# 3. Ready-to-paste additions

## 3.1 B6 — verified BibTeX

Both confirmed against Crossref (DOI, authors, pages, venue):

```bibtex
@inproceedings{selakovic2016performance,
  author    = {Selakovic, Marija and Pradel, Michael},
  title     = {Performance issues and optimizations in {J}ava{S}cript: an empirical study},
  booktitle = {Proceedings of the 38th International Conference on Software Engineering (ICSE '16)},
  pages     = {61--72},
  publisher = {ACM},
  year      = {2016},
  doi       = {10.1145/2884781.2884829}
}

@inproceedings{jin2012understanding,
  author    = {Jin, Guoliang and Song, Linhai and Shi, Xiaoming and Scherpelz, Joel and Lu, Shan},
  title     = {Understanding and detecting real-world performance bugs},
  booktitle = {Proceedings of the 33rd ACM SIGPLAN Conference on Programming Language Design and Implementation (PLDI '12)},
  pages     = {77--88},
  publisher = {ACM},
  year      = {2012},
  doi       = {10.1145/2254064.2254075}
}
```

Suggested §2 paragraph:

> **Performance defects as a class.** Jin et al. \cite{jin2012understanding}
> characterise real-world performance bugs and find that most arise from a small
> number of recurring patterns rather than from algorithmic complexity, and that
> the fix is usually local. Selakovic and Pradel \cite{selakovic2016performance}
> classify performance issues in JavaScript specifically and report that
> inefficient use of an API — calling it in a way that is correct but costly —
> is among the most common. The defect reported here is an instance of that
> class with a narrower cause: not an inefficient call, but a correct call made
> in the wrong *order*, where the first of two attempts is guaranteed to fail for
> the input the interface most invites. Neither line of work measures a
> cryptographic interface, and neither treats key resolution as a cost site.

## 3.2 A3 — anonymity switch

```latex
\newif\ifanonymous
\anonymousfalse          % \anonymoustrue for a double-blind submission
```

Wrap the author block:

```latex
\ifanonymous
  \author[1]{\fnm{Anonymous} \sur{Author}}
  \affil[1]{\orgname{Affiliation withheld for review}}
\else
  ...existing five \author and five \affil lines...
\fi
```

and in the bibliography, swap the artifact entry under the same switch —
`howpublished = {Archived dataset; DOI and repository withheld for review}`.

**EMSE is single-blind**, so the default `\anonymousfalse` is correct for that
venue and the GitHub link is an asset, not a liability. Confirm before
submitting elsewhere.

---

# 4. Two things found that the brief did not ask about

## 4.1 The public repository is the *wrong artifact*

`github.com/Katha-Sikdar/microservices-api` — cited as reference [4] and named in
the Data Availability statement — contains the **earlier, desk-rejected**
manuscript's artifact: `kubernetes/`, `load-tests/`, `results/` for five
TLS/mTLS/JWT scenarios, and a README describing *"Quantifying the Performance
Cost of API Security in Cloud-Native Microservices."*

This paper's artifact lives only at
`~/Desktop/EliteLabIndividual_Research/testbedForFinApiZTA/microservices-api/psao-artifact/`
on the measurement machine. It is not published anywhere.

The Data Availability statement therefore asserts something not yet true:
*"openly available in the archived replication package … Every number is
generated from a file under the run or survey directories."* A referee following
the link finds a different study. **This is a submission blocker in its own
right**, and arguably more serious than the `??` placeholders, because it reads
as a citation to work that does not support the claims.

Fix: publish `psao-artifact/` (or the JWT-relevant subtree) to Zenodo, mint the
DOI, and point reference [4] at the DOI rather than the old repo.

## 4.2 B7 is already done

`upstream/` contains `jsonwebtoken-issue.md`, `repro.js`, `verify.js.patch`,
`verify-keypath.tests.js` and `NEGATIVE-CONTROL.md`, and issue **#1046** is filed
publicly (17 Sep 2026). PR **#1047** exists, opened 18 Sep by account
`Hashim1999164`.

Two consequences: B7 needs no draft, and **§7 should say the report was made** —
a performance defect reported upstream is a contribution; one that is not is an
observation. The authorship of #1047 still needs settling.

---

# 5. Needs the authors

| | Why |
|---|---|
| Funding statement | Not mine to write (ground rule 5). |
| Author contributions | Not mine to write. Note §9 says there was no second rater — do not assign Validation to someone who did not re-rate. |
| Zenodo DOI | Not mine to mint. See §4.1: the artifact must actually be published. |
| Second rater + Cohen's κ | Ground rule: I must not rate. Data is in `survey/`. |
| Anonymity decision | Follows the venue. EMSE is single-blind. |
| A1 decision | Re-run §4 on OpenSSL 3.6.4 and replace Table 1, or adopt the two edits in §1.3. |
| B1, B2, B3 | Need Node builds, the Table 2 runtimes, and a real x86_64 machine. |
| B4 timing half | Needs a working npm. |
| §7 test titles | Needs the patched suite run locally. |
| Authorship of PR #1047 | Whether `Hashim1999164` is a collaborator. |

---

# 6. Files written

In `psao-artifact/`:

- `analysis/make_ab_macros.py` — derives the A/B values from the two committed
  run directories; every macro carries its source path.
- `paper/ab_macros.tex` — 22 generated macros.
- `paper/section64_ab.tex` — §6.4 replacement, table and prose, no typed digits.
- `REVISION_REPORT.md` — this file.

Nothing was committed to git and no existing file was modified. `latexdiff` was
not produced: it is only meaningful once the paper is actually edited, and
editing was deliberately deferred pending the A1 decision.

**Authoritative source note.** The live manuscript is
`psao-artifact/paper/discarded-exception.tex` with
`psao-artifact/paper/keypath_macros.tex` (257 macros, each carrying provenance).
The `_build-*.tex` files are generated variants. Apply §6.4 there, adding
`\input{ab_macros}` beside the existing `\input{keypath_macros}`.
