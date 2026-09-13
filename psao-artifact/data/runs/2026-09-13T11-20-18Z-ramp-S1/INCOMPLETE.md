# INCOMPLETE RUN — latency only, no CPU

`openloop_ramp.csv` here has 20 valid latency/throughput steps and **zero CPU
samples**. Do not use it for anything CPU-related, and do not use it as the S1
arm of the elbow figure, which needs CPU at the elbow.

## What happened

`capture_pod_metrics.sh` runs under `set -euo pipefail`. Its
`read_eventloop_lag()` helper was an unguarded pipeline, called once per
iteration *before* the per-pod sampling loop. One failed scrape of the
application's `/metrics` endpoint therefore returned non-zero and terminated the
sampler — on its first iteration, in this run. `pod_cpu_samples.csv` contains
its header and nothing else. The ramp itself continued for the full ten minutes
and produced a normal-looking `openloop_ramp.csv` with an empty CPU column.

Nothing reported an error at the time. `merge_ramp.py` printed
"0 with CPU attributed" at the end, which is the only reason it was noticed.

## Fixed

* `read_eventloop_lag()` is now guarded — the optional lag column can no longer
  take the CPU measurement down with it.
* A failed sampling iteration logs a warning and continues instead of exiting.
* `run_openloop_ramp.sh` now **fails the run** if the sampler was started but
  wrote no samples, rather than emitting a ramp with a silently empty column.

This run is kept as the record of the failure. It is superseded by the S1 re-run.
