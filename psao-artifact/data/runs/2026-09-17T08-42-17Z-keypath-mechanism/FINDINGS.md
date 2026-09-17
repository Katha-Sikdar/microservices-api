# The cost is a failed asymmetric-key probe, not key conversion

15 rounds x 12 conditions, **one `node` process per measurement** (181 rows),
40 000 timed calls after 20 000 warmup in each. Conditions are cycled inside
each round rather than run in blocks, so drift lands on all of them and shows up
as between-round variance instead of as an effect. Intervals are percentile
bootstraps (10 000 resamples) over the 15 per-invocation medians — they cover
between-process variation, which a single-process benchmark cannot see.

Host: macOS 26.5.2, arm64, Node v26.6.0, `jsonwebtoken` 9.0.3.
Load average at run start: 3.00. Timer overhead 0.042 us, reported, not subtracted.

## What the numbers say

| condition | median us | 95% CI | CV% across processes |
|---|---|---|---|
| `jwt_rs_pem_string` | 52.583 | [52.416, 52.708] | 0.4 |
| `jwt_hs_string` | 29.917 | [29.750, 30.125] | 1.2 |
| `jwt_rs_preparsed` | 25.334 | [25.291, 25.500] | 0.8 |
| **`probe_throws`** | **18.042** | [17.834, 18.250] | 1.5 |
| `probe_succeeds` | 13.833 | [13.625, 13.916] | 1.1 |
| `jwt_hs_string_safe` | 7.208 | [7.125, 7.334] | 1.7 |
| `jwt_hs_preparsed` | 6.042 | [5.958, 6.125] | 1.8 |
| `hmac_string` | 2.208 | [2.208, 2.250] | 1.2 |
| `hmac_keyobject` | 2.166 | [2.125, 2.167] | 2.0 |
| `decode_only` | 1.292 | [1.250, 1.292] | 1.9 |
| **`create_secret_key`** | **0.583** | [0.542, 0.583] | 3.5 |
| `timer_overhead` | 0.042 | [0.042, 0.042] | 0.0 |

**The conversion the cost has been attributed to takes 0.583 us.** The failed
probe that precedes it takes 18.042 us — 31x the conversion it is a fallback
for, and 60% of the entire string-key verification.

`jsonwebtoken/verify.js:120-127` resolves any non-`KeyObject` secret by calling
`createPublicKey()` first and falling back to `createSecretKey()` in the catch.
For an HMAC string secret the first call cannot succeed, so every verification
constructs and discards an OpenSSL parse failure.

## Decomposition, paired by round

    observed penalty (string - preparsed)   23.917 us [23.583, 24.000]
    probe_throws + create_secret_key        18.624 us [18.417, 18.833]
    residual                                 5.292 us [ 4.916,  5.501]
    explained                                  77.9%

The residual's interval excludes zero, so the two measured parts are **not** the
whole story: roughly 5.3 us is `jsonwebtoken`'s own type and claim checking on
the non-`KeyObject` path. Reported rather than absorbed.

## Independent confirmation, no differencing involved

The table above reaches its conclusion by subtracting conditions — the same
inference style this project criticises elsewhere. V8's sampling profiler
attributes self-time to frames directly (`--cpu-prof`, 200 000 iterations):

| path | top frame | self |
|---|---|---|
| `jwt_hs_string` | **`createPublicKey` (node:internal/crypto/keys)** | **67.87%** |
| `jwt_hs_preparsed` | `Hmac` (node:internal/crypto/hash) | 19.30% |

`createPublicKey` does not appear anywhere in the pre-parsed path's top frames.
Two methods, one answer.

## The obvious fix is an authentication bypass

`bench/keypath-security-check.js`, run as a precondition of every timing run.

The attack: a service configured with an RSA **public** key; the attacker sends
`alg:HS256` HMAC'd with that public key, which is public.

| variant | confusion attack | legitimate HS256 | legitimate RS256 |
|---|---|---|---|
| `stock` | reject | accept | accept |
| `naive` (skip probe whenever alg is HS*) | **ACCEPT** | accept | accept |
| `safe` (skip only for non-PEM, non-JWK string secrets) | reject | accept | accept |

Stock `jsonwebtoken` survives algorithm confusion **by accident of the probe
order**: `createPublicKey(pem)` succeeds, yields a `KeyObject` of type `public`,
and the guard at `verify.js:148` rejects `HS*` against a non-secret key. Removing
the probe naively removes that defence with it. The wasted work is load-bearing.

The bypass lands only when the caller omits the `algorithms` option. The service
in the earlier study (`git show ef2c9dd:service-a/index.js`) called
`jwt.verify(token, JWT_SECRET, cb)` with no `algorithms` — the vulnerable
configuration.

## What the safe patch buys, with no change to caller code

    jwt_hs_string        29.917 us
    jwt_hs_string_safe    7.208 us     saving 22.709 us [22.542, 22.876], 4.15x
    jwt_hs_preparsed      6.042 us     residual 1.208 us [1.084, 1.251]

The library-side fix recovers all but 1.2 us of what pre-parsing recovers,
without the application changing a line.

## Three corrections this forces on the manuscript

1. **"Key material re-converted from a string on every call" is the wrong
   mechanism.** The conversion is 0.583 us. The cost is a discarded exception.
   The headline finding survives — it is still not cryptography — but the
   attribution must change, which is the same class of error the paper corrects
   in others.

2. **The Table 2 explanation is backwards.** The paper explains RS256-with-PEM
   being cheaper than HS256-with-string as "converting a string secret into a
   keyed-hash key is more expensive here than parsing a PEM." On this host PEM
   parsing (`probe_succeeds`, 13.833 us) is 24x more expensive than secret
   conversion (0.583 us). The real asymmetry is that RS256's probe **succeeds**,
   so its cost is useful parsing; HS256's **fails**, so its cost is waste.

3. **A concrete, testable prediction for the container anomaly.** Host penalty
   23.9 us; container penalty (435.72 - 8.26) 427.5 us. The pre-parsed path is
   nearly identical across host and container (6.04 vs 8.26 us), so whatever
   costs 18x more in the container is confined to the probe. Run `probe_throws`
   in the container: the prediction is ~400 us. If it holds, the "unexplained
   virtualisation penalty" is an exception-construction cost and is reportable
   rather than open.

## What this does NOT establish

- **One host, one OS, one architecture.** macOS arm64 only. The container and
  cross-architecture replication is Phase 2 and is not done.
- **One library at one version.** `jsonwebtoken` 9.0.3. Whether other JWT
  libraries or other runtimes probe in the same order is unmeasured. The patch
  is verified against 9.0.3's source text and refuses to apply to anything else.
- **The safe patch is not upstream.** It is verified against five cases here,
  which is not the same as being reviewed by the maintainers.
- **Prevalence is unmeasured.** That a string secret is the common configuration
  is still asserted, not counted. Phase 4.
