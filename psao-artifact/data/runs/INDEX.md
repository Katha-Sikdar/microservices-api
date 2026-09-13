# Run index

Every directory under `data/runs/`, and whether anything rests on it.

**Read this first: the microbenchmark is the only result here that survived
verification. Every cluster measurement taken on 2026-09-13 is in doubt, for a
reason documented below.** That is an unsatisfying state to hand a reviewer, but
it is the honest one.

Host details are in `../../README.md` ("The machine these measurements came
from").

---

## The one defensible result: the JWT stage decomposition

`2026-09-13T20-34-41Z-microbench` — three passes, 200 000 iterations each,
Node v26.6.0, host load average 1.92. Supersedes `2026-09-13T13-25-31-340Z`
(same numbers, no provenance recorded).

| alg | full_verify | crypto primitive | parsing | residual | crypto share |
|---|---|---|---|---|---|
| HS256 @ 0.5 kB | 25.98 us | ~1.4 us | 0.90 us | ~23.7 us | **roughly 5-6%** |
| RS256 @ 0.5 kB | 28.69 us | 11.15 us | 0.92 us | 16.62 us | **~39%** |

For HS256, cryptography is single-digit percent of `jwt.verify()`; about 91% is
`jsonwebtoken` library dispatch, key handling and allocation.

### Why this one is defensible when the cluster runs are not

It was measured twice, **four hours apart, under opposite host conditions** — once
at 13:25 UTC before the day's contamination, once at 20:34 UTC on a verified-quiet
host (load 1.92, Spotlight idle) — and then a third and fourth time as repeat
passes. Observed spread:

| stage | spread across passes | quotable? |
|---|---|---|
| `RS256 full_verify` 4 kB | **0.4%** | yes |
| `HS256 full_verify` 2 kB | 0.6% | yes |
| `RS256 full_verify` 0.5 kB | 1.1% | yes |
| `HS256 full_verify` 0.5 kB | 2.4% | yes |
| `RS256 primitive_preparsed` 4 kB | 4.1% | yes |
| `HS256 primitive_preparsed` 0.5 kB | 7.2% | **round to 1 significant figure** |
| `HS256 primitive_preparsed` 2 kB | 11.4% | **treat as approximate** |
| `HS256 decode_only` 0.5 kB | 12.6% | **treat as approximate** |

Full per-stage spread in `2026-09-13T20-34-41Z-microbench/microbench.spread.txt`.

**Do not quote "5.1%".** That third digit is timer noise on a sub-2 us quantity
(1.484 / 1.440 / 1.381 us across passes). "Roughly 5-6%", or "single digits", is
what the data supports. The denominator is solid: every `full_verify` reproduced
within 2.7%.

The benchmark is a single CPU-bound process, which is why it tolerated a host
that invalidated everything measured through the cluster.

---

## Cluster runs: why they are all in doubt

Two incompatible regimes were measured on the same day, on the same code:

| | morning (10:36-13:01 UTC) | evening (17:13-18:18 UTC) |
|---|---|---|
| host load at run start | **not recorded** | 2.6 - 5.8 |
| S5 elbow | ~905 rps, rho=0.906 | **no elbow within 1000 rps** |
| S5 app CPU @1000 rps | 913 m | 388 m |
| S1 app CPU @1000 rps | 297 m | 113 m |
| S8 app CPU @1000 rps | 551 m | 122 m |
| controller | triggered at cpu=723m | **never triggered, max rho 0.326** |

The evening runs are mechanically cleaner in every respect — 100% of checks
passed, 0% HTTP failures, 20/20 steps with CPU and lag attributed, dropped
iterations at 0-530 against the morning's 0-104 026. They are also unusable,
because nothing saturates: event-loop lag sits at 1.8-2.8 ms at 1000 rps and the
controller had nothing to react to.

**The likely reading is that the morning's elbow was a host-contention artifact,
not the service's capacity.** Host load was not recorded for those runs — the
capture did not exist yet — so this cannot be settled from the data on disk. It
needs a re-probe for the real saturation point on a quiet host, then a re-run of
the matrix at a ceiling derived from it.

Consequently **the 126 measured macros in `paper/generated_macros.tex` are
provisional**, along with every elbow, every rho, and `fig_elbow.pdf`.

---

## Directory listing

### Evening sweep — clean, but no saturation reached

| Directory | Scenario | Dropped | Lag | Peak held |
|---|---|---|---|---|
| `2026-09-13T17-13-26Z-ramp-S5` | S5 | 530 | 20/20 | 1000 rps |
| `2026-09-13T17-23-54Z-ramp-S1` | S1 | 0 | 20/20 | 1000 rps |
| `2026-09-13T17-34-37Z-ramp-S3` | S3 | 2 | 20/20 | 1000 rps |
| `2026-09-13T17-45-29Z-ramp-S8` | S8 | 4 | 20/20 | 1000 rps |
| `2026-09-13T17-56-18Z-ramp-S9` | S9 | 0 | 20/20 | 1000 rps |
| `2026-09-13T18-06-33Z-controller` | controller | 0 | - | never triggered |

All on `service-a:psao-5` / `psao-scenarios:psao-5` with matched dependency
trees. The controller ran with its three post-mortem fixes in place (probe
timeout 10 s, revert retry budget 180 s, runner-side leftover-policy check) and
logged *"confirmed: no offload policy left on the cluster"* — the failure that
left a policy applied on 2026-09-13T12:21 did not recur.

**The S5 run additionally has an unexplained internal inconsistency:** app CPU
*falls* from 653 m at 700 rps to 346 m at 750 rps while latency improves, and at
1000 rps it draws less CPU (388 m) than at 550 rps (402 m). Work per request
halved mid-run. One stable pod throughout, no restarts, continuous samples — so
the attribution is sound and the effect is real but unaccounted for. Do not use
that curve.

### Morning runs — superseded, and now in doubt

| Directory | Scenario | Note |
|---|---|---|
| `2026-09-13T11-36-08Z-ramp-S1` | S1 | Was canonical. Host load unrecorded. |
| `2026-09-13T11-59-03Z-ramp-S3` | S3 | Was canonical. 0 dropped. Host load unrecorded. |
| `2026-09-13T11-09-18Z-ramp-S5` | S5 | Was canonical; the source of the 905 rps elbow. Host load unrecorded. |
| `2026-09-13T12-49-53Z-ramp-S8` | S8 | Was canonical. Host load unrecorded. |
| `2026-09-13T13-01-05Z-ramp-S9` | S9 | Was canonical. Read its `NOTES.md`: usable range 50-700 rps only. |

### The dependency regression A/B — a result that stands

`AB-express-regression/` — three S5 ramps, ~35 minutes apart, same host, differing
only in the `service-a` dependency tree. Has its own README.

**express 5.1.0 -> 5.2.1 costs ~35% of peak capacity** (collapse at 600 rps vs
target held to 950; 123 485 dropped iterations vs 10 604). **The `jws` HMAC
security fix is free** — `jsonwebtoken` 9.0.3 / `jws` 4.0.1 is indistinguishable
from 9.0.2 / 3.2.2. Rows 2 and 3 share the same `jsonwebtoken`, so this is a
direct isolation, not inference by elimination.

`express` is consequently pinned to an exact `5.1.0` in both `service-a` and
`psao-artifact`, with the reason recorded in each `package.json`. Supporting
runs: `AB-psao2-S5/`, `AB-variantB-S5/`.

### Failed, contaminated and aborted — kept as the record

| Directory | Marker | Why |
|---|---|---|
| `2026-09-13T10-36-36Z-ramp-S5` | `SUPERSEDED.md` | 400 rps ceiling, no elbow; different image from S1/S3. |
| `2026-09-13T11-20-18Z-ramp-S1` | `INCOMPLETE.md` | Zero CPU samples — sampler died on its first iteration. |
| `2026-09-13T11-47-11Z-ramp-S3` | `INCOMPLETE.md` | Lag on 1 of 20 steps — port-forward attached to a terminating pod. |
| `2026-09-13T12-21-47Z-controller` | `FAILED.md` | Confirmed actuation at 8537.9 ms, then Prometheus and the API server went away and the revert failed, leaving the policy applied. |
| `2026-09-13T12-37-17Z-ramp-S8-SUSPECT` | `SUSPECT.md` | Lost lag column; contaminated by the cluster still recovering from the above. |
| `2026-09-13T16-23-03Z-ramp-S5` | - | `psao-4` (express 5.2.1). The run that exposed the express regression. |
| `2026-09-13T16-57-41Z-ramp-S5` | `CONTAMINATED.md` | Correct image, but Spotlight re-indexing at 41.8% CPU moved the collapse point from 950 to 800 rps. |
| `2026-09-13T17-08-27Z-ramp-S1` | `ABORTED.md` | Killed mid-ramp to stop the contaminated sweep; no merged output. |

These are kept deliberately. Every one of them produced a directory that looked
finished. That is the failure mode this artifact is most exposed to, and the
markers record what went wrong and what changed so it cannot recur silently.

### Supporting

| Directory | What it is |
|---|---|
| `COMBINED-2026-09-13` | Concatenation of the morning canonical runs + microbench, used for `make analysis` / `make figures`. **Inherits the doubt above.** |
| `posture_events.jsonl` | Timestamped log of every posture teardown, restore and verification — including one retracted verification and the sweep abort. |
| `cluster-backup-*` | Posture backups taken before each S1 teardown. `raw/` holds the unmodified dump; top-level files are sanitised to be re-appliable. |
| `PROBE-2026-09-13-find-saturation` | Coarse probe used to pick the original ceiling. Not a measurement. |
| `2026-09-06T15-05-38-189Z`, `2026-09-07T06-09-46-232Z`, `2026-09-13T13-25-31-340Z`, `controller/` | Stale, superseded. |

---

## On `k6_raw.csv.gz`

Archival, ~51x smaller than the raw dump. `merge_ramp.py` consumes the
*uncompressed* file during a run; nothing reads it afterwards. `make analysis`
and `make figures` work from `openloop_ramp.csv`, already merged and committed,
so a reviewer who never gunzips anything can still reproduce every figure.

## Image lineage

| Tag | Digest | Deps | Used by |
|---|---|---|---|
| `service-a:psao-1` | `ac502eec` | - | superseded |
| `service-a:psao-2` | `068793d4` | express 5.1.0, jwt 9.0.2 | morning S1/S3/S5 |
| `service-a:psao-3` | `e89c4fc4` | + sidecar-trust offload path | morning controller |
| `service-a:psao-4` | `82d6db7b` | express **5.2.1**, jwt 9.0.3 | the regression run only |
| `service-a:psao-5` | `1c74d9a6` | express **5.1.0** pinned, jwt 9.0.3 | evening sweep |
| `psao-scenarios:psao-5` | `bacd5526` | matched to psao-5 | evening S8/S9 |
