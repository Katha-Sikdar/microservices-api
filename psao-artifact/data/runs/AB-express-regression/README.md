# Controlled A/B: which dependency upgrade cost 35% of capacity

Three S5 ramps, identical parameters (50→1000 rps, 50 rps steps of 30 s), run
back to back within about 35 minutes on the same host, differing only in the
`service-a` dependency tree. Everything else — image base, handler code, mesh
posture, token pool, cluster — was held constant.

This exists because `npm audit fix` produced a service that collapsed, and the
obvious explanation (the `jws` HMAC security fix) turned out to be wrong.

| file | express | jsonwebtoken | jws | flat through | knee | held target to | dropped iterations |
|---|---|---|---|---|---|---|---|
| `s5-express-5.1.0-jwt-9.0.2.csv` | 5.1.0 | 9.0.2 | 3.2.2 | 650 rps | 800–900 | 950 rps | 12 997 |
| `s5-express-5.1.0-jwt-9.0.3.csv` | 5.1.0 | **9.0.3** | **4.0.1** | 650 rps | 750–850 | 950 rps | 10 604 |
| `s5-express-5.2.1-jwt-9.0.3.csv` | **5.2.1** | 9.0.3 | 4.0.1 | 550 rps | **collapse at 600** | 550 rps | **123 485** |

## What it establishes

**The security fix is free.** `jsonwebtoken` 9.0.3 pulls `jws` 4.0.1, which
carries the fix for *"auth0/node-jws Improperly Verifies HMAC Signature"*
(advisory range `<3.2.3`) — the advisory sitting directly on the HS256 path this
paper measures. Rows 1 and 2 differ only in that upgrade and are
indistinguishable: same flat region, same knee, both hold target to 950 rps, and
the dropped-iteration counts differ by less than the run-to-run noise on this
host.

**The express minor bump is not free.** Rows 2 and 3 differ *only* in express.
5.2.1 collapses S5 at 600 rps where 5.1.0 holds to 950 — a ~35% loss of peak
capacity, with an order of magnitude more dropped iterations, and no recovery at
any higher step (achieved rate falls to 212–360 rps for the rest of the ramp).

This is a direct isolation, not an inference by elimination: rows 2 and 3 share
the same `jsonwebtoken`, so express is the only variable between them.

## Consequence for the artifact

`express` is pinned to an exact `5.1.0` in both `service-a/package.json` and
`psao-artifact/package.json` — not a `^5.1.0` range, which would silently
re-acquire 5.2.1 on any fresh install and quietly cost a third of the measured
capacity. `jsonwebtoken` is kept at `^9.0.3` so the HMAC fix is in.

**Re-measure before widening that range.** A caret range on express in a
reproducibility artifact means the tree that produced the published numbers is
not the tree a reviewer gets.

## What this does NOT establish

No claim about *why* express 5.2.1 is slower here. That was not investigated —
it would need profiling of the express request path, and the finding stands
without it. It is also specific to this workload (a small JSON response behind
Edge TLS and mTLS on a single-threaded Node service) and this host; it is not a
general statement about express 5.2.1.

The first run of the three (`jwt-9.0.2`) was made after the host had picked up
background load from an editor and a browser, which is why its knee sits at
800–900 where the same image measured 750–850 earlier in the day. That drift is
the scale of host noise here, and it is far smaller than the effect being
reported.
