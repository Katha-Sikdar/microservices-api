# The 687 us was key conversion, not cryptography

Three in-situ rate sweeps, each 7 rate points x 3 minutes, ascending then
descending on one process, measured with `psao_verify_duration_seconds` inside
the running service. The only differences between them are the algorithm and how
the key is handed to `jwt.verify()`.

| run | algorithm | key form |
|---|---|---|
| `2026-09-14T05-57-22Z-verifyrate-hs256` | HS256 | string secret (as the submitted paper's code) |
| `2026-09-14T15-01-36Z-verifyrate-hs256-preparsed` | HS256 | pre-parsed `KeyObject` |
| `2026-09-14T06-41-56Z-verifyrate-rs256` | RS256 | pre-parsed `KeyObject` |

## Mean in-situ cost per call (us), ascending pass

| rps | HS256 string | HS256 pre-parsed | RS256 pre-parsed |
|---|---|---|---|
| 5 | 928.24 | 221.42 | 351.05 |
| 10 | 976.28 | 235.01 | 338.89 |
| 25 | 918.54 | 168.44 | 270.77 |
| 50 | 758.57 | 127.19 | 203.19 |
| 100 | 571.59 | 79.70 | 120.42 |
| 200 | 494.91 | 71.68 | 73.92 |
| 400 | 452.82 | 39.38 | 59.11 |

Isolated host microbenchmark, for reference: HS256 25.98 us, RS256 28.69 us.

## How much of the cost is key conversion

| rps | saved by pre-parsing | ratio |
|---|---|---|
| 5 | 706.8 us | 4.2x |
| 25 | 750.1 us | 5.5x |
| 100 | 491.9 us | 7.2x |
| 400 | 413.4 us | 11.5x |

**At 5 rps — the regime the submitted paper measured — 706.8 us of the 928.24 us
is key conversion. That is 76%.** At 400 rps it is 91%.

The remaining 221 us at 5 rps is the idle-gap effect (below), not cryptography:
the HMAC itself is ~1.3-2 us.

## Two independent, multiplicative effects

Measured in-container, one warm process, both key forms at each gap:

| gap | equiv rps | string | pre-parsed | ratio |
|---|---|---|---|---|
| 0 (tight loop) | - | 415.43 | 9.63 | 43.1x |
| 2 ms | 500 | 637.32 | 87.73 | 7.3x |
| 10 ms | 100 | 747.82 | 111.49 | 6.7x |
| 50 ms | 20 | 1037.51 | 157.01 | 6.6x |
| 200 ms | 5 | 1125.88 | 233.25 | 4.8x |

1. **Key conversion.** `jsonwebtoken` converts a string key to a key object on
   every call. 43x at tight loop, ~5x at 5 rps. Dominant at high rates.
2. **Inter-arrival gap.** Cache and branch-predictor eviction plus CPU
   idle-state exit between calls. 2.7x across the range with a string key, but
   **24x** with a pre-parsed key (9.63 -> 233.25 us) once conversion stops
   masking it. Dominant at low rates.

The rate dependence is **not** JIT warmth: the descending pass, which had served
every higher rate first, reproduces the ascending curve within ~7% at every
point. It is not GC either: GC time *rises* 12x with rate while per-call cost
falls, and is 1-5% of verify time throughout.

## HS256 vs RS256, like for like

Both pre-parsed, so the only difference is the signature algorithm:

| rps | HS256 | RS256 | RS256 / HS256 |
|---|---|---|---|
| 5 | 221.42 | 351.05 | 1.59x |
| 50 | 127.19 | 203.19 | 1.60x |
| 100 | 79.70 | 120.42 | 1.51x |
| 200 | 71.68 | 73.92 | 1.03x |
| 400 | 39.38 | 59.11 | 1.50x |

**In situ, RS256 costs about 1.5x HS256** — not the 2.1x the isolated
microbenchmark's crypto primitives suggest (11.15 vs 1.32 us, 8.4x on the
primitive alone), because in the deployed environment the fixed per-call
overhead dominates both.

The earlier RS256-vs-HS256 comparison in
`../INSITU-2026-09-14-verify-cost/FINDINGS.md` is void: it compared a pre-parsed
RS256 against a string-keyed HS256 and so appeared to show RS256 as *cheaper*.
Two variables changed at once. This table is the corrected comparison.

## What the submitted paper measured

`git show ef2c9dd:service-a/index.js`:

```js
const JWT_SECRET = 'your-super-secret-key-that-is-long';   // line 27
jwt.verify(token, JWT_SECRET, (err, user) => {             // line 45
```

A string, re-parsed on every request, at roughly 83 rps closed-loop. **The 687 us
attributed to "signature verification" was about three-quarters key conversion
and nearly all of the remainder fixed per-call overhead. Under 1% was
cryptography.**

A one-line change removes most of it:

```js
const key = crypto.createSecretKey(Buffer.from(JWT_SECRET));  // once, at startup
jwt.verify(token, key, { algorithms: ['HS256'] });            // per request
```

`PSAO_JWT_KEYFORM=string|preparsed` on `service-a` keeps both paths measurable.

## Consequence for PSAO

The motivation weakens sharply. The cost PSAO proposes to relocate into Envoy is
mostly an avoidable application defect, and fixing it in place is cheaper, safer
and does not move the trust boundary. Offloading still removes the residual
39-221 us, but "JWT validation costs 687 us per request" is not a defensible
premise once the key is pre-parsed.

The 2776 us RS256 figure remains **unverified**: it was never measured in situ
with the paper's own code, and the service was HS256-only until this work.
