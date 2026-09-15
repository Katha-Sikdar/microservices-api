> ## RETRACTION — 2026-09-14, later the same day
>
> **Sections 3 and 4 below attribute the in-situ cost to "jsonwebtoken library
> overhead amplified by the virtualised environment". That attribution is WRONG.**
> It is not retracted because the measurements were bad — they reproduce — but
> because the cause I inferred from them was not the cause.
>
> The real driver is that `jsonwebtoken` converts the key from a **string** into a
> key object on **every single call**. The service passed `JWT_SECRET`, a string,
> exactly as the submitted paper's code did. Measured in the same container,
> identical cryptography, identical token, the only change being how the key is
> handed to `jwt.verify()`:
>
> | key form | mean |
> |---|---|
> | string secret (what the service and the paper did) | **422.48 us** |
> | pre-parsed `KeyObject` | **8.31 us** |
> | **ratio** | **50.8x** |
>
> So the "8.9x virtualisation penalty on the library" in section 4 is really a
> per-call key-conversion cost that happens to be far more expensive under the
> Docker Desktop Linux VM than on the host. Same measurements, different and
> correct explanation.
>
> **What I got right:** the in-situ cost is real (section 1), it is real CPU and
> not scheduling (section 2), the environment matters and the host benchmark is
> not comparable to the container (section 3's core observation), and GC is not
> the cause. The rate dependence is also real and survives the correction.
>
> **What I got wrong:** calling the residual "library dispatch, key handling and
> allocation" as though it were irreducible. It is one specific, avoidable
> operation. A one-line change — pre-parse the key at startup — removes about 98%
> of it.
>
> **How I found the error:** adding RS256 in situ, where I pre-parsed the public
> key because handing `jwt.verify()` a PEM string would have put PEM parsing
> inside the measured RS256 cost. RS256 then measured *cheaper* than HS256, which
> is backwards. Chasing that asymmetry surfaced the key-form effect. The RS256
> figures in the sweep of 2026-09-14T06-41-56Z are therefore NOT comparable to
> the HS256 figures of 2026-09-14T05-57-22Z: I changed two variables at once.
>
> Corrected analysis, with both algorithms on pre-parsed keys, is in
> `../KEYFORM-2026-09-14/FINDINGS.md`.

# Resolving the 26x gap: in-situ verification cost

**Question.** The microbenchmark says `jwt.verify()` costs ~26 us (HS256). The
submitted paper attributes 687 us per request to validation. Both cannot be right.

**Answer: (a). Verification in the running service costs far more than in
isolation — about 16x — and the paper's magnitude is plausible. But the reason is
not what either account assumed, and it makes the cryptographic share *smaller*,
not larger.**

## 1. In-situ histogram vs microbenchmark

`psao_verify_duration_seconds`, delta over a 3-minute 200 rps run,
36 002 observations against k6's 36 001 iterations (1:1):

| | mean | p50 | p90 | p99 |
|---|---|---|---|---|
| in situ, 200 rps | **421.21 us** | 434.97 | 585.18 | 1111.91 |
| microbench (host) | 25.98 us | 24.83 | - | 35.92 |
| **ratio** | **16.2x** | | | |

No observation fell below 150 us. The tight loop's 26 us is not attainable in the
server at any percentile. Reproduced independently on a second pod: 19.651 s over
48 003 calls = 409.4 us mean.

## 2. It is real CPU, not scheduling

Matched A/B, both pods warmed, 200 rps, identical bytes on the wire — only the
`jwt.verify()` call removed via `PSAO_AUTH_MODE`:

| mode | app CPU | client latency |
|---|---|---|
| `none` | 69.454 m | 1.6802 ms |
| `jwt` | 146.377 m | 2.0332 ms |
| delta | **76.923 m** | 0.353 ms |

76.923 m / 200 rps = **384.6 us of CPU per request**, corroborating the 421 us
wall-clock histogram. Validation really does burn that CPU.

## 3. Where the 16x actually comes from — and it is NOT interleaving

The obvious hypothesis (server interleaving evicts caches; a tight loop is
unrealistically hot) is **wrong**. A tight loop run *inside the running
container* gives **218.94 us**, not 26 us.

| | HS256 `full_verify` |
|---|---|
| tight loop, host (native macOS/arm64) | 25.98 us |
| tight loop, **inside the container** (Linux VM) | **218.94 us** |
| in situ, inside the container | 409-421 us |

So the gap decomposes as **~8.4x from the execution environment** and only
**~1.9x from in-situ interleaving on top of that**.

`make microbench` runs on the host. The service runs in Docker Desktop's Linux
VM. **They are not the same machine**, and the artifact compares their numbers
directly. That is a methodological defect in the artifact, not in the paper.

## 4. The environment penalty falls entirely on the library, not the crypto

Same decomposition, run inside the container:

| stage | host | container | ratio |
|---|---|---|---|
| `decode_only` | 0.898 us | 1.032 us | 1.1x |
| `primitive_preparsed` (HMAC) | 1.324 us | 2.031 us | 1.5x |
| `full_verify` | 25.976 us | 215.565 us | 8.3x |
| **residual (library)** | **23.75 us** | **212.50 us** | **8.9x** |

Cryptography and parsing are essentially unchanged. The entire penalty is in the
`jsonwebtoken` wrapper around them.

**In the deployed environment the cryptographic share of `jwt.verify()` is 0.9%,
not 5-6%.** The artifact's headline finding survives and strengthens: what
offloading removes is Node library overhead, not cryptography. Envoy would do the
HMAC in single-digit microseconds and skip the wrapper entirely.

*Why* the wrapper costs 8.9x more under virtualisation is **not established**.
GC is ruled out: 0.435 s of GC against 19.651 s of verify on the same pod, 2.2%.
Establishing the cause needs a `--prof` run inside the container, which was not
done.

## 5. How much of the reported latency is client-side

Same run, 200 rps:

| | mean |
|---|---|
| k6 client-side | 1944 us |
| server-side handler (`psao_request_duration_seconds`) | 549 us |
| in-situ verify | 421 us |

**Only 28% of client-observed latency is the application.** The other 72%
(~1.4 ms) is TLS, NGINX, two Envoy hops, and k6 itself competing for the same
host. Any latency-based attribution of per-request cost inherits that.

## 6. Client-side work differs between the paper's scenarios

`load-tests/test.js` (baseline) vs `test-jwt.js`: the baseline requests
**`http://`** while the JWT test requests **`https://`**. Any S1-based comparison
therefore includes the whole TLS cost on both sides, not just validation.

For the paper's actual S5 - S3 the confound is minor — both are HTTPS closed-loop,
differing only by an `Authorization` header and a per-iteration params object.
So client-side work does **not** explain the 687 us.

## 7. What this means for the paper

- The **mechanism holds**: validation is expensive per request in the deployed
  environment, and 687 us is the right order. The paper's 5 rps-equivalent
  regime (100 VUs with `sleep(1)`) is *colder* than this test, and colder
  measured slower here — 942.60 us at ~5 rps versus 421.21 us at 200 rps — so
  687 us sits inside the measured range.
- The **attribution must change**: it is not "signature verification" and not
  cryptography. Under 1% of it is. It is `jsonwebtoken` library overhead,
  amplified roughly ninefold by the virtualised environment.
- **RS256 was not measured in situ.** The service is HS256-only, so the paper's
  2776 us RS256 figure remains unverified by this work.
- The microbenchmark should be run **inside the target container** before any of
  its absolute numbers are cited against in-cluster measurements.
