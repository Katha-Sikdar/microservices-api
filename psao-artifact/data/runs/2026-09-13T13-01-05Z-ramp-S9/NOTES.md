# S9 — read the CPU budget before reading the numbers

**Usable range: 50–700 rps. Everything above 750 rps is collapse, not measurement.**
`dropped_iterations = 104026`; at target 850 the generator achieved 17 rps. Those
rows describe a service that has fallen over, and the `achieved_rps` column says
so. `eventloop_lag_p99_ms` is present for 17 of 20 steps — the three gaps are all
inside the collapsed region.

## The configuration this measures

4 workers (`WORKERS=4`) inside a pod capped at **1000m — one core**, which is the
same budget S5 and S8 are confined to by being single-threaded. That choice is
what the run is about, and it is deliberate: see the header comment in
`scenarios/deploy/s9-deployment.yaml`. Uncapped on this 10-core node, S9 would
simply take more CPU and report more throughput, which answers a question nobody
asked.

## What it shows

Forking **does not help within a fixed CPU budget here — it hurts.**

| rps | S5 mean | S9 mean | S5 app CPU | S9 app CPU |
|---|---|---|---|---|
| 50  | 3.49 ms | 3.06 ms | 83 m  | 109 m |
| 200 | 2.18 ms | 2.10 ms | 169 m | 199 m |
| 500 | 2.27 ms | 28.99 ms| 369 m | 516 m |
| 650 | 2.78 ms | 52.32 ms| 490 m | 755 m |
| 700 | 2.91 ms | 93.44 ms| 525 m | 837 m |

S5 was still flat at 700 rps and did not reach its knee until ~750–850. S9 is
already at 93 ms mean and 837m — it saturates *earlier* and costs *more* CPU at
every rate. Four event loops, four metric registries and the cluster module's
IPC are overhead that a single process does not pay, and four processes sharing
one core add CFS throttling on top.

Note also the two isolated excursions at 250 and 500 rps (43.5 ms and 29.0 ms
mean, with matching lag spikes of 23.2 ms and 19.2 ms) surrounded by normal
steps. Uneven work distribution across workers is the obvious candidate — the
kernel's connection distribution is not perfectly even, and this run reports a
single aggregated lag rather than per-worker lag. Confirming that would need the
per-worker series `scenarios/s9-cluster-mode.js` already labels.

## What it does NOT show

It does not show that `node:cluster` is useless. It shows that **4 workers in a
1-core budget** is worse than 1 worker in the same budget. The other experiment —
N workers given N cores — is a different question with a different answer, and
any S9 number quoted without its CPU budget attached is not interpretable.
