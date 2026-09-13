# FAILED RUN — do not use for any reported number

The controller experiment did not complete. It is kept because what it shows is
worth knowing, but **no quantity in it is citable**: there is no confirmed
actuation, no offloaded steady state, and no revert.

## What happened, in order

1. **The control logic worked.** At t≈118s the CPU signal crossed the trigger
   (`cpu=723m > 700m`). Hysteresis suppressed two would-be offloads
   (`consecutive(1/3)`, `consecutive(2/3)`) and committed on the third. That part
   of the policy behaved exactly as designed and is visible in
   `controller_trace.csv`.

2. **Actuation failed twice, then succeeded on the third attempt.** The
   controller applied both Istio objects, then failed confirmation twice with
   `OFFLOAD FAILED: probe:timed out after 30s` (recorded actuation latencies
   31237 ms and 30429 ms — both are the 30 s timeout, not a measurement of
   anything). The confirmation probe is an HTTPS request with a 2 s timeout sent
   to the same endpoint the ramp is saturating, so near saturation it returns
   "no evidence" rather than "confirmed" — **the confirmation mechanism is least
   reliable exactly when actuation matters most.**

   The third attempt confirmed, at **t_rel = 184.4 s with
   `actuation_latency_ms = 8537.872`**. That 8.54 s is a genuine measurement:
   decision to two-sided probe confirmation, including the observation lag of
   the 1 m Prometheus rate window. The trace shows `mode=sidecar` for the
   following 46 rows.

   An earlier note in this file said actuation was never confirmed. That was
   wrong and is corrected here.

3. **Prometheus went unreachable.** Under full load the port-forward stopped
   answering within the 5 s query timeout. After 3 consecutive failed polls the
   controller stopped itself, as designed.

4. **The revert failed, and this is the serious part.** On exit the controller
   tried to remove the policy and could not reach the Kubernetes API server at
   all — `SSLEOFError`, `RemoteDisconnected`, connection refused on 127.0.0.1:6443.
   The control plane of this single-node Docker Desktop cluster had been starved
   by the load test. `REVERT ON EXIT FAILED`.

   **The offload policy was therefore left applied on the cluster** after the run
   ended. It was found still present 11 minutes later and removed by hand; the
   mesh posture and the offload trust boundary were then re-verified clean. The
   final trace rows show `mode=sidecar` with every metric empty — the controller
   knew it had actuated and could no longer observe anything.

## The before/after comparison this run CANNOT support

Offered load was still rising throughout — it is a ramp, not a hold — so the
CPU either side of the transition is confounded by load, not a controlled
comparison:

| window | app CPU | sidecar CPU |
|---|---|---|
| before offload (t_rel 60-118) | 454.0 m (n=29) | 197.4 m (n=29) |
| during attempts (t_rel 118-184) | 516.8 m (n=6) | 808.5 m (n=6) |
| after offload (t_rel 190-260) | 541.8 m (n=16) | 753.8 m (n=15) |

Application CPU did **not** fall after the offload (454 m -> 542 m) and sidecar
CPU rose sharply (197 m -> 754 m). The sidecar rise is the expected direction —
it is now doing the JWT verification — but **no claim about PSAO's CPU benefit
can be drawn from these numbers**, because the arrival rate increased across the
same interval. Demonstrating the benefit needs load held constant across the
transition, which this run design does not do.

The observations themselves are also degraded: `lambda_rps` reads 114.7 at
t_rel=184 while the generator was offering roughly 600 rps, and
`eventloop_lag_p99_ms` reads 1459.6 ms. Prometheus was already failing to answer
within its 5 s timeout by then.

## What this run does establish

* The trigger, the hysteresis counter and the flap suppression work against a
  live cluster and a real load.
* `max rho = 1.33` — the ramp comfortably crossed the operating point the policy
  is written around.
* The failure modes above are properties of **this host**, not of the policy.

## What has to change before it is re-run

* **Ceiling.** Drive to roughly 700-800 rps, not 1000. The elbow is at 750-850,
  so the trigger is crossed well before the point where k6, the ingress, the
  sidecars, Prometheus and the API server start fighting for the same 10 cores.
* **Confirmation.** The probe needs a longer timeout and should not share the
  saturated path, or actuation should be confirmed from Envoy's own config dump
  rather than a data-plane request.
* **Revert.** A revert that cannot reach the API server must retry with backoff
  past the end of the load, and the runner must verify the policy is gone before
  it exits. A failed revert currently leaves the cluster in a state no artifact
  file describes.
* **Prometheus.** A port-forward is not a dependable metrics path under load.

None of these are policy defects. All of them are reasons this particular run
produced no usable measurement.
