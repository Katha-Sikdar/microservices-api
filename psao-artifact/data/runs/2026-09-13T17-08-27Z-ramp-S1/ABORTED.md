# ABORTED — no result

Killed mid-ramp. There is no `openloop_ramp.csv`: the run never reached the merge
step, so `k6_raw.csv` and `pod_cpu_samples.csv` were never joined.

It was stopped deliberately. The sweep it belonged to was measuring a host that
`mds_stores` (Spotlight) was re-indexing at 41.8% CPU, which had already moved
the preceding S5 collapse point from 950 rps to 800. Continuing would have
produced five more runs that looked complete and measured the indexer.

Because S1 is the scenario that tears the mesh posture down, the kill landed
mid-teardown. The EXIT trap restored `PeerAuthentication` and the
`DestinationRule`, but was interrupted before resetting `PSAO_AUTH_MODE`, which
was left on `none`. Both were corrected and re-verified — mTLS posture and the
offload trust boundary — before the sweep was restarted. See
`posture_events.jsonl` for the timestamped record.

Superseded by `2026-09-13T17-23-54Z-ramp-S1`.
