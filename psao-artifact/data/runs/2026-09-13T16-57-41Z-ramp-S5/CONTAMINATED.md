# CONTAMINATED — host, not workload

Correct image (`service-a:psao-5`: express 5.1.0, jsonwebtoken 9.0.3, jws 4.0.1,
verified inside the running container), correct posture, but **S5 collapses at
800 rps** here where the identical dependency set held target to 950 rps forty
minutes earlier (`../AB-express-regression/s5-express-5.1.0-jwt-9.0.3.csv`).

The difference was the host. `mds_stores` — Spotlight — was running at 41.8%
CPU, re-indexing the 3.8 GB of run output and the git objects that had just been
committed. Load average was 12.7 against 10 cores. k6, the ingress, the sidecars
and the service all share this machine, so that is not background noise, it is
part of the measurement.

Superseded by the re-run made after the host quiesced (load average 3.4,
`mds_stores` at 0%).

## What changed as a result

* `psao-artifact/data/` and `.git/` now carry `.metadata_never_index`, so writing
  run output no longer triggers a re-index.
* `run_metadata.json` records `host.uptime_at_run_start` and
  `host.top_cpu_at_run_start` for every run. This run was only diagnosable by
  re-running the same image on a quiet host; with the load recorded it would
  have been visible from the run directory alone.

That second change surfaced a bug of its own: `ps | head` under
`set -euo pipefail` gives `ps` a SIGPIPE, and the non-zero status aborted
`write_metadata` silently, producing no `run_metadata.json` at all — the same
failure shape as the unguarded lag scrape that killed the CPU sampler earlier.
Guarded now.
