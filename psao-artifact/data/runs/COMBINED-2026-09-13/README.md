# Combined ramp data — S1, S3, S5, S8, S9

`openloop_ramp.csv` here is a straight concatenation of the canonical
`openloop_ramp.csv` from five separate runs, so the analysis and the elbow figure
can put them on one axis. No values were changed. Provenance:

| Scenario | Source run |
|---|---|
| S1 | `2026-09-13T11-36-08Z-ramp-S1` |
| S3 | `2026-09-13T11-59-03Z-ramp-S3` |
| S5 | `2026-09-13T11-09-18Z-ramp-S5` |
| S8 | `2026-09-13T12-49-53Z-ramp-S8` |
| S9 | `2026-09-13T13-01-05Z-ramp-S9` |

Each source directory holds its own `run_metadata.json`, including the mesh
posture observed at run start. **This directory deliberately has none** — five
runs do not share one provenance record, and inventing a merged one would be a
fabrication. Read the sources.

## Caveats that survive the merge

* **S9's rows above 750 rps are collapse, not measurement** (achieved 17 rps
  against a target of 850). See `NOTES.md` in its source run. Any fit over S9
  must be restricted to the steps where `achieved_rps` tracks `target_rps`.
* **S1, S3 and S5 ran on `service-a:psao-2`; S8 and S9 on
  `psao-scenarios:psao-2`.** Same base image and dependency ranges, different
  builds. S8/S9 also ran after
  `controller/strip-untrusted-payload-header.yaml` was applied, which adds a Lua
  filter to the sidecar's inbound path on every request; S1/S3/S5 did not carry
  it. That is a real, unquantified difference in the sidecar column between the
  two groups.
* S1 and S3 do **not** reach an elbow within 1000 rps. Any elbow reported for
  them would be an extrapolation.
