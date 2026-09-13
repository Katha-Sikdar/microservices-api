# Run index

Every directory under `data/runs/`, what it is, and whether the paper rests on
it. **Five runs are canonical.** Everything else is here for provenance and is
marked in place with its own `SUPERSEDED.md`, `INCOMPLETE.md`, `SUSPECT.md`,
`FAILED.md` or `NOTES.md`.

All measurements were taken on 2026-09-13 on the host documented in
`../../README.md` ("The machine these measurements came from").

## Canonical — these back the paper

| Directory | Scenario | Steps | Dropped | Lag | Notes |
|---|---|---|---|---|---|
| `2026-09-13T11-36-08Z-ramp-S1` | S1 — plain HTTP, no mTLS, no app JWT | 20 | 424 | 20/20 | Mesh posture torn down and restored; both logged in `posture_events.jsonl`. No elbow within 1000 rps. |
| `2026-09-13T11-59-03Z-ramp-S3` | S3 — Edge TLS + STRICT mTLS, no app JWT | 20 | 0 | 20/20 | Cleanest run in the set: every step on target. No elbow within 1000 rps. |
| `2026-09-13T11-09-18Z-ramp-S5` | S5 — Edge TLS + mTLS + app JWT (HS256) | 20 | 669 | 20/20 | **The elbow run.** Flat to ~350 rps, knee at 750–850, saturated by 950. |
| `2026-09-13T12-49-53Z-ramp-S8` | S8 — S5 + LRU token cache | 20 | 180 | 20/20 | Sustains 1000 rps where S5 saturates. |
| `2026-09-13T13-01-05Z-ramp-S9` | S9 — S5 under `node:cluster`, 4 workers, capped 1000m | 20 | 104026 | 17/20 | **Usable range 50–700 rps only.** Read `NOTES.md` first — the CPU budget is what the run is about. |

Ramps are open-loop, 50→1000 rps in 50 rps steps of 30 s. "Dropped" is
`dropped_iterations`; "Lag" is steps carrying `eventloop_lag_p99_ms`. Each
directory holds its own `run_metadata.json` with the mesh posture **observed at
run start**, not assumed from the scenario label.

## Derived and supporting

| Directory | What it is |
|---|---|
| `COMBINED-2026-09-13` | Concatenation of the five canonical `openloop_ramp.csv` plus today's microbench, so the analysis can put them on one axis. **This is what `make analysis` and `make figures` were run against.** No values changed; no `run_metadata.json` of its own, because five runs do not share one provenance record. Has its own README listing the caveats that survive the merge. |
| `2026-09-13T13-25-31-340Z` | Microbenchmark, 200 000 iterations, HS256 and RS256 at 0.5/2/4 kB. Its `microbench.csv` is the copy used in `COMBINED-2026-09-13`. |
| `posture_events.jsonl` | Append-only, timestamped log of every mesh-posture teardown, restore and verification — including one **retracted** verification (see below). |
| `cluster-backup-2026-09-13T11-20-02Z`, `…T11-35-52Z` | Posture backups taken before each S1 teardown. `raw/` holds the unmodified `kubectl get -o yaml`; the top-level files are sanitised so they can actually be re-applied. |
| `cluster-backup-2026-09-07` | Pre-injection manifests from an earlier session. |

## Set aside — kept as the record, not for citation

| Directory | Status | Why it was set aside |
|---|---|---|
| `2026-09-13T10-36-36Z-ramp-S5` | superseded | Sound data (0 dropped, 20/20 lag) but ramps only to **400 rps**, entirely on the flat part of the curve, so it shows no elbow. Also ran on `service-a:psao-1`, a different image from S1/S3, which would put a build difference inside the comparison the elbow figure makes. |
| `2026-09-13T11-20-18Z-ramp-S1` | incomplete | 20 latency steps but **zero CPU samples**. The CPU sampler died on its first iteration: its optional event-loop-lag scrape was an unguarded pipeline under `set -euo pipefail`, so one failed `/metrics` scrape killed it. The ramp then ran its full ten minutes and wrote a normal-looking CSV with an empty CPU column. |
| `2026-09-13T11-47-11Z-ramp-S3` | incomplete | Latency and CPU are sound; `eventloop_lag_p99_ms` is present for **1 of 20 steps**. The metrics port-forward attached to a pod that was terminating after the `PSAO_AUTH_MODE` rollout, so every later scrape failed — silently, because by then a failed scrape could no longer kill the sampler. |
| `2026-09-13T12-37-17Z-ramp-S8-SUSPECT` | suspect | Same lost-lag failure (1/20), **and** 59 406 dropped iterations with a non-monotonic latency curve. It started seven minutes after the controller run starved the cluster badly enough that the Kubernetes API server became unreachable. No conclusion about the token cache should be drawn from it in either direction. |
| `2026-09-13T12-21-47Z-controller` | failed | Trigger and hysteresis worked (two suppressed flaps, then commit at `cpu=723m`), and the third actuation attempt confirmed at **8537.9 ms**. But Prometheus then the API server became unreachable, the revert failed, and the offload policy was left applied on the cluster. 211 712 dropped iterations. No before/after CPU comparison is possible — offered load was rising across the transition. |
| `PROBE-2026-09-13-find-saturation` | not a measurement | Coarse 200→2400 rps sweep in 15 s steps, used only to locate the saturation point so the real ramps could be given a sensible ceiling. Steps far too short to fit anything; rows above 1600 rps report `latency_mean_ms = 0.0000`, which is k6 emitting no valid samples during collapse. |
| `2026-09-06T15-05-38-189Z`, `2026-09-07T06-09-46-232Z` | stale | Microbenchmark output from earlier sessions, superseded by `2026-09-13T13-25-31-340Z`. |
| `controller/` | stale | Leftover trace from an early dry-run; not a cluster measurement. |

### One retracted verification

`posture_events.jsonl` contains a `verification_retracted` entry. The mTLS
verification logged at `2026-09-13T11:08:03Z` is **not sound**: its negative
control probed `.items[0]` of the service-a pod list, which during that rollout
was the old, terminating pod. `Connection refused` from a dying process proves
nothing about mTLS. It is superseded by the `11:09:09Z` verification, which pairs
the out-of-mesh refusal with an in-mesh positive control on the same ClusterIP.

## On `k6_raw.csv.gz`

Each ramp directory ships `k6_raw.csv.gz` — the per-request sample dump, ~51×
smaller compressed (3824 MB → 75 MB across the set). **It is archival.**
`merge_ramp.py` consumes the *uncompressed* file during a run, to derive each
step's time window from real request timestamps; nothing reads it afterwards.
`make analysis` and `make figures` work from `openloop_ramp.csv`, which is
already merged and committed. So a reviewer who never gunzips anything can still
reproduce every figure and macro — the gzip is there to make the merge itself
auditable, not because the pipeline needs it.

## The image lineage

| Tag | Digest prefix | What changed |
|---|---|---|
| `service-a:psao-1` | `ac502eec` | JWT validation hard-coded. Cannot serve S1 or S3. |
| `service-a:psao-2` | `068793d4` | `PSAO_AUTH_MODE` selects the handler at startup, so S1/S3/S5 share one image and one digest. |
| `service-a:psao-3` | `e89c4fc4` | Adds the PSAO offload path: when Istio supplies verified claims in `x-psao-jwt-payload`, the handler reads them instead of re-verifying. |
| `psao-scenarios:psao-2` | `e1640692` | S8 and S9 services; same `node:18-alpine` base and dependency ranges as `service-a`. |

S1, S3 and S5 ran on `psao-2`; S8 and S9 on `psao-scenarios:psao-2`; the
controller on `psao-3`. S8 and S9 also ran **after**
`controller/strip-untrusted-payload-header.yaml` was applied, which adds a Lua
filter to the sidecar's inbound path on every request. S1/S3/S5 did not carry it.
That is a real, unquantified difference in the sidecar CPU column between the two
groups, and it is why `psao-3`'s S5 path should be re-measured before the
controller trace is placed on the same axis as the elbow figure.
