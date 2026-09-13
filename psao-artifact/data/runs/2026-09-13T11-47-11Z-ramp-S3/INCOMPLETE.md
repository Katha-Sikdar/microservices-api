# INCOMPLETE RUN — latency and CPU are valid, event-loop lag is not

`openloop_ramp.csv` has 20 valid latency/throughput steps **with CPU attributed
to all 20**. Only `eventloop_lag_p99_ms` is affected: **1 of 20 steps** carries a
value. Superseded by the S3 re-run.

## What happened

`psao::start_metrics_port_forward` selected its target pod with
`-o jsonpath='{.items[0].metadata.name}'`, with no phase or readiness filter.
Every scenario here is preceded by a `PSAO_AUTH_MODE` rollout, and immediately
after a rollout that list is ordered with the **old, terminating** pod first. The
port-forward attached to a pod that was shutting down, the tunnel died within
seconds, and every subsequent scrape of `/metrics` failed.

This is the same `.items[0]` defect that made the first mTLS negative control
pass against a dying pod. It surfaced here and not in S1 or S5 (both 20/20)
because of rollout timing, not because those runs were structurally different.

It failed *silently* for a second reason. The preceding fix — guarding the
optional lag scrape so it could no longer kill the CPU sampler — was correct, but
it converted a loud failure into a quiet gap. Robustness that hides a missing
measurement is its own hazard.

## Fixed

* The metrics port-forward now selects a pod that is `status.phase=Running`
  **and** `Ready`, never `.items[0]` of an unfiltered list.
* `run_openloop_ramp.sh` now warns loudly when `eventloop_lag_p99_ms` is empty
  for an entire run, so a silent gap is reported at the time rather than
  discovered later while reading a figure.

## What this run is still good for

The latency and CPU columns are sound and were measured in a verified posture
(`STRICT` + `ISTIO_MUTUAL` + plaintext refused, recorded in `run_metadata.json`).
If you only need S3's latency-vs-rate or CPU-vs-rate curve, this run carries it.
