# SUSPECT RUN — do not cite; superseded by the S8 re-run

Two independent reasons not to trust this one.

## 1. The lag column is missing (1 of 20 steps)

Same silent failure as the first S3 ramp, in a new disguise. The metrics
port-forward resolved its target with a label query filtered to
`status.phase=Running` **and** `Ready` — and the scaled-down S5 pod was still
both. The tunnel attached to a pod that was on its way out, died, and every
subsequent scrape failed silently.

Fixed by resolving the target from the **Service endpoint's `targetRef`**, which
is the only source that answers the question actually being asked: which pod is
the Service sending load to. The same fix was applied to the scenario identity
check in `run_scenario_service.sh`.

## 2. The latency numbers are not plausible as S8

S8 is S5 plus an LRU cache of verified tokens. It should be **faster** than S5,
or at worst equal. Measured here it is dramatically worse, and erratically so:

| rps | S5 mean | S8 mean (this run) |
|---|---|---|
| 200 | 2.18 ms | 15.76 ms |
| 300 | 1.98 ms | 3.84 ms |
| 600 | 2.92 ms | 20.67 ms |
| 650 | 2.78 ms | 130.07 ms |
| 900 | 28.34 ms | 3221.64 ms |

`dropped_iterations = 59406`. The curve is not monotonic — it spikes at 150-200,
recovers at 300, spikes again at 650, recovers at 750, then collapses. A service
that is genuinely slower degrades monotonically; this looks like the host, not
the workload.

**The likely cause is contamination.** This ramp started at 12:37:17, seven
minutes after the controller experiment starved this single-node cluster badly
enough that the Kubernetes API server became unreachable
(`2026-09-13T12-21-47Z-controller/FAILED.md`). etcd and the API server were
plausibly still recovering. A scaled-down S5 pod was also still terminating
alongside the S8 pod for part of the run, and the CPU sampler selects on
`app=service-a`, which matches both.

No conclusion about the token cache should be drawn from this run in either
direction. It is kept as the record of the failure.
