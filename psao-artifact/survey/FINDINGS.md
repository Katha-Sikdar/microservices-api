# How real code hands a key to `jwt.verify()`

The upstream finding is that passing anything other than a `KeyObject` makes
`jsonwebtoken` attempt `createPublicKey()` on every call. Whether that matters
is a question about the population, not about our testbed. Three measurements,
each with a different failure mode, so they can check each other.

## 1. Population counts (GitHub code search)

| query | files |
|---|---|
| `require('jsonwebtoken')` language:javascript | 792,576 |
| ... **and** `createSecretKey` | **29** |
| `from 'jsonwebtoken'` language:typescript | 319,488 |
| ... **and** `createSecretKey` | **101** |

**130 of 1,112,064 files — about 1 in 8,500 (0.012%)** mention the API at all.
Counts were stable across repeated queries (46 twice for a third variant).

## 2. Broad sample of call sites

315 `jwt.verify()` call sites across **235 distinct repositories**, one file per
repository so no project can dominate. Second argument classified by tracing
within the file; anything undecidable recorded as `unknown` rather than assigned.

| bucket | call sites | repos |
|---|---|---|
| `env_string` (`process.env.X`) | 176 | 121 |
| `unknown` (untraced identifier or member) | 85 | 73 |
| `string_literal` | 49 | 39 |
| `file_contents` (`readFileSync`) | 3 | 3 |
| `buffer` (`Buffer.from`) | 2 | 1 |
| **`keyobject`** | **0** | **0** |

No file in this corpus contains `createSecretKey`, `createPublicKey`, `jwks` or
`getKey` at all, so the zero is the pattern's absence and not a classifier that
cannot see it.

**299 of 315 call sites (95%) pass no `algorithms` option.** Not the question
this survey set out to answer, but it bears directly on the upstream report:
pinning `algorithms` is an independent defence against key-type confusion, and
almost nothing does it.

## 3. Targeted counter-search, hand-verified

A sample can only show the good pattern is rare if it could have found it. So
every file co-occurring `jsonwebtoken` with `createSecretKey` was fetched
directly: **191 distinct files, of which 120 contain a `verify()` call.**

An automated pass flagged 13 as passing a `KeyObject`. **All 13 were then read by hand: 5 are false positives, 1 is unresolved, and 7
are genuine.** The false positives define their own helper *named*
`createSecretKey` (one returns a string via `crypto.randomBytes`), or the matched
call passes `config.tokenKey`, `process.env.JWT_SECRET`, `'shhhh'` or `null`. The
unresolved case binds its identifier outside the file. Per-case verdicts and
evidence are in `survey/data/hand_adjudication.csv`.

Verified genuine: **7 call sites across 6 distinct projects.**

| project | key argument resolves to |
|---|---|
| graduate-project-sut/engineering-curriculum-system (2 files) | `createSecretKey(Buffer.from(SECRET_KEY, "base64"))` |
| felipe-software/feridinha.com | `createSecretKey(env.JWT_SECRET, "utf-8")` |
| tuatui/xe-ai | `c.createSecretKey(...)` |
| patilprashant48/sakhalas-admin | `createSecretKey(Buffer.from(rawSecret))` |
| emilebilodeau/survey-creation-2 | `createSecretKey(...)` **constructed inline, per call** |
| Kirill-Bokov/I-ll-give-you-the-stone | `createSecretKey("6688...")` |

Two further files use a `KeyObject` correctly but are not application code: a
library benchmark harness that deliberately exercises both forms, and a
vulnerability demonstration (`algorithms: ["none", "RS256", "HS256"]`).

## What this supports, and what it does not

**Supports:** passing a pre-parsed `KeyObject` to `jwt.verify()` is vanishingly
rare in public JavaScript and TypeScript. Three independent measurements agree:
~0.01% of files mention the API; 0 of 315 sampled call sites use it; and of 120
files that demonstrably know the API exists and call `verify()`, 7 call sites
across 6 projects actually pass one.

**Does not support** an unqualified population proportion, for four reasons.

1. **Cross-file pre-parsing is invisible to this method.** A project could build
   the `KeyObject` in `config.js` and verify in `auth.js`; file-level analysis
   would miss it. This is the strongest threat to the result. The within-file
   tracing in the sample found no such case, but that is weak evidence against it.
2. GitHub code search counts are approximate, cover public repositories only,
   and include forks, vendored `node_modules`, tutorials and dead code. The
   numerator is inflated the same way as the denominator, but the ratio is not a
   clean proportion.
3. Public code skews toward tutorials and hobby projects. The six genuine users
   found are all small projects, which is itself informative but not
   representative of production systems behind closed repositories.
4. Search is relevance-ranked, not random. Query selection shapes the sample; an
   earlier pass included a `process.env` term and biased the result toward
   exactly the bucket under investigation. That query was removed.

## Corrections made during this survey

Recorded because both were silent failures that would have produced a wrong
number.

- **`gh search code` returns `[]` for multi-term queries** that the underlying
  `search/code` API answers normally. The first counter-search arm returned
  nothing and was indistinguishable from "the pattern does not exist". Caught by
  checking that the counter-search queries appeared in the hit distribution at
  all; they did not. All counter-searches now go through `gh api search/code`.
- **The automated `KeyObject` detector over-counted by ~2x**, matching
  user-defined functions named `createSecretKey`. With only 13 candidates, hand
  verification was feasible and is what the table above reports. The automated
  figure (13) is not used.
