# It is OpenSSL 3.0, and it is not virtualisation

The manuscript reports that in-container validation costs ~16x the isolated host
microbenchmark and attributes the gap to deployment, leaving the magnitude
"unexplained under virtualisation" as future work. This run holds
containerisation constant and varies the runtime instead.

10 rounds x 10 conditions per image, one `docker run` per measurement, 20 000
timed calls after 10 000 warmup. Conditions interleaved within each round.
Bootstrap CIs over the 10 per-invocation medians. The macOS host row is the
Phase 1 run (`../2026-09-17T08-42-17Z-keypath-mechanism`, 15 rounds x 40 000).

## The matrix

| environment | Node | OpenSSL | V8 | libc | `probe_throws` us | `probe_succeeds` | `jwt_hs_preparsed` | `jwt_hs_string` |
|---|---|---|---|---|---|---|---|---|
| `node:18.20.8-alpine` **= the deployed service** | 18.20.8 | 3.0.16 | 10.2 | musl | **373.79** [371.5, 375.8] | 115.83 | 7.58 | 394.71 |
| `node:20-alpine` | 20.20.2 | 3.0.19 | 11.3 | musl | **420.62** [419.5, 422.6] | 142.38 | 7.25 | 437.40 |
| `node:26.6.0-alpine` | 26.6.0 | 3.5.7 | 14 | musl | **22.94** [22.8, 23.3] | 15.54 | 6.56 | 36.42 |
| `node:26.6.0-bookworm` | 26.6.0 | 3.5.7 | 14 | glibc | **16.58** [16.4, 17.9] | 12.12 | 6.04 | 27.96 |
| macOS host (Phase 1) | 26.6.0 | 3.6.3 | 14 | - | **18.04** [17.8, 18.3] | 13.83 | 6.04 | 29.92 |

## Three things this settles

**1. It is not virtualisation, and not containerisation.** Containerised Node 26
on glibc costs 16.58 us against 18.04 us on the macOS host: the container is
marginally *faster*. Whatever produced the 16x gap in the manuscript, it was not
the act of running in a container.

**2. It is OpenSSL, not Node or V8.** Node 18 (V8 10.2) and Node 20 (V8 11.3)
are two different V8 major versions that share the OpenSSL 3.0 series, and both
pay ~400 us. Node 26 ships OpenSSL 3.5.7 and pays ~20 us. In stock images Node
and OpenSSL versions co-vary, which would normally make this attribution
impossible to separate -- `node:20-alpine` separates them, because its V8 differs
from Node 18's while its OpenSSL does not.

**3. The effect is confined to key parsing.** Across all five environments:

    jwt_hs_preparsed   6.04 - 7.58 us    (1.26x spread)
    hmac_string        2.21 - 3.25 us    (1.47x)
    decode_only        1.29 - 2.19 us    (1.70x)
    probe_throws      16.58 - 420.62 us  (25.4x)
    probe_succeeds    12.12 - 142.38 us  (11.7x)

Everything that is not OpenSSL key parsing is within ~1.7x everywhere. The
failed probe spans 25x. `probe_succeeds` moves with it, so this is not specific
to the error path: OpenSSL 3.0's key parsing is slow in general, consistent with
its provider/decoder redesign. The failed probe is simply the case where an
application pays that cost on every request for nothing.

## Confirmed independently by the profiler

`--cpu-prof`, 50 000 iterations of `jwt_hs_string`, self-time attributed to
frames with no differencing on our part:

| environment | `createPublicKey` self-time |
|---|---|
| `node:18.20.8-alpine` | **94.66%** |
| `node:26.6.0-alpine` | 57.93% |
| macOS host | 67.87% |

## What this forces on the manuscript

**The runtime is misreported.** `service-a/Dockerfile` is `FROM node:18-alpine`
and runs Node v18.20.8 / OpenSSL 3.0.16 / musl. Every `run_metadata.json`
records `node_version: v26.6.0`, because `common.sh:559` runs `node --version`
on the **host**, not in the pod. Section 3.1 states "Node.js is v26.6.0" for the
system under test. It was not. Fix the capture to `kubectl exec` the pod, and
re-state the version.

**Section 4.2 does not survive as written.** "In-situ cost greatly exceeds
isolated cost" and the `\InsituVersusMicrobenchRatio{16.2}` compare a Node 26 /
OpenSSL 3.6 host benchmark against a Node 18 / OpenSSL 3.0 service. The gap is a
runtime difference between the two measurement setups, not an in-situ effect.
The "Measure in situ" implication rests on it and must be rewritten. The honest
replacement is stronger: **the cost of this defect varies 25x with the OpenSSL
version the base image pins, and `node:18-alpine` is a very common base image.**

**The rate-dependence result is untouched.** It was measured within a single
environment and the idle-gap experiment isolates it independently, so the
version confound does not reach it. It becomes the manuscript's most novel
surviving finding.

## Provenance and caveats

- **Host load.** Docker Desktop was restarted to clear a manual pause, which
  brought the Kubernetes cluster back up (19 containers, load average 5.63
  against 3.00 for the Phase 1 host run). A spot check of `probe_throws` on
  `node:26.6.0-bookworm` under the *heavier* load returned 16.46 us against the
  matrix's 16.58 [16.38, 17.88] -- inside the interval. Contention inflates
  durations, and these did not move, so the matrix values stand. Between-process
  CV is 0.5-2.3% on every condition carrying the finding.
- **`node:18.20.8-bullseye` was not obtained.** Two pull attempts exceeded the
  time allowed. That cell would separate libc *within* Node 18. It is missing,
  not null: the libc effect is characterised only at Node 26, where it is 1.38x
  (22.94 musl vs 16.58 glibc) against the 25x that OpenSSL contributes.
- **Five partial `node:20-alpine` rows** from a round interrupted mid-way were
  moved to `keypath_mechanism.partial-node20-interrupted.csv` and are not
  analysed. The cell was re-run from scratch.
- **One machine, arm64 only.** Everything here is Docker Desktop on Apple
  silicon. Whether the OpenSSL 3.0 penalty has the same magnitude on x86_64 is
  unmeasured -- that is what the Oracle Cloud instances are for.
- **RS256 conditions were not run in containers.** `jwt_rs_pem_string` and
  `jwt_rs_preparsed` are host-only so far.
