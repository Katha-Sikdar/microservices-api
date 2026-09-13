# NOT A MEASUREMENT RUN

This is a coarse **probe** run, used only to locate the saturation point so the
real ramps could be given a sensible ceiling. Do not cite it, and do not point
`make analysis DATA=` at it.

* 200..2400 rps in 200 rps steps of **15 s** — steps far too coarse and too short
  to fit anything, chosen to sweep a wide range quickly.
* `dropped_iterations = 131998`. Every step from 1000 rps up failed to offer its
  nominal rate, so `target_rps` above 800 is not the load that was actually
  applied.
* The rows at 1600-2400 rps report `latency_mean_ms = 0.0000`. That is k6
  emitting no valid samples while the system was in collapse, not a measurement
  of zero latency.

## What it established

Read against the `pod_cpu_samples.csv` and a parallel `kubectl top` of the
ingress, taken during the same run:

| offered rps | service-a | service-a sidecar | nginx controller | nginx sidecar |
|---|---|---|---|---|
| 600  | 548m | 185m | 170m  | 265m |
| 800  | 795m | 328m | 296m  | 431m |
| 1000 | 963m | 467m | 708m  | 627m |
| 1200 | 525m | 702m | 1677m | 924m |

1. **The elbow is between 600 and 800 rps**, not below 400. Mean latency is flat
   at ~2.4-2.6 ms through 600 rps, then 8.4 ms at 800 rps and 159 ms at 1000 rps;
   event-loop p99 lag goes 3.4 ms -> 10.8 ms -> 110 ms across the same steps.

2. **service-a saturates first, which is what the experiment needs.** It is
   single-threaded and pins at ~960m — one core — by 1000 rps, while the
   multi-threaded nginx controller is still at 708m and nowhere near its own
   ceiling. The elbow being measured is therefore the application event loop,
   not the ingress.

3. **Above ~1000 rps nothing on this host is trustworthy.** The load generator,
   the ingress and the service share 10 cores; at 1200 rps the ingress alone
   takes 1.7 cores and service-a's CPU *falls* to 525m because it is starved.
   The defensible measurement window on this machine ends at about 1000 rps.

4. **The original 400 rps ceiling was too low for the whole study.** It produces
   a flat latency curve with no elbow, and — because the controller's
   `cpu_trigger_millicores` is 700 and its `sla_latency_ms` is 15 — a controller
   experiment that never crosses a threshold and never actuates. That run would
   have completed successfully and demonstrated nothing.

The real ramps therefore use **50 rps steps to 1000 rps** (20 steps x 30 s),
which brackets the elbow and stays inside the trustworthy window.
