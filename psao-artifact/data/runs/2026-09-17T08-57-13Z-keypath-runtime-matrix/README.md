# Provenance notes for this run directory

`run_metadata.json` was written by the FIRST invocation of
`experiments/run_keypath_container.sh` and its `run_parameters.images` field
lists what that invocation was *asked* to run, not what ran:

- `node:18.20.8-bookworm` is listed but **does not exist** on Docker Hub and was
  skipped (the runner warned and exited non-zero rather than dropping it
  silently). `node:18.20.8-bullseye` was substituted as the Node 18 glibc cell,
  but two pull attempts exceeded the time allowed, so **that cell is missing**.
- `node:20-alpine` ran but is absent from that field, because it was added by a
  later invocation against `--run-dir`, which by design does not rewrite
  metadata.

**`environments.csv` is the authoritative record of what ran.** It was rebuilt
from the `node_version` / `openssl_version` / `platform` columns that
`keypath_mechanism.csv` carries on every row, after a bug in the runner
truncated it on each re-invocation. That bug is fixed (the file is now
append-only); this directory is the one it affected. No measurement was lost —
only the summary of which images produced them, which the measurements
themselves could reconstruct.

`keypath_mechanism.partial-node20-interrupted.csv` holds 5 rows from a
`node:20-alpine` round interrupted part-way. They are excluded from analysis and
the cell was re-run from scratch.
