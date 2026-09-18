# Sampling profiles at matched iteration counts

The first profiling pass ran the host at 200 000 iterations and the containers at
50 000, then reported the three self-time percentages as one series. Different
sampling durations give different attribution stability, so those figures were
not comparable with each other.

This run fixes the protocol: **50 000 iterations everywhere, three repeats per
environment**, same condition (`jwt_hs_string`), same harness. The paper reports
the median of three with the observed range, rather than a single number.

`cpuprof_matched.csv` is the summary; `raw/` holds the nine `.cpuprofile` files.

Self-time attributed to `createPublicKey`, median of three:

| environment | median | range |
|---|---|---|
| macOS host | 66.23% | 65.33--67.41 |
| node:18.20.8-alpine | 95.34% | 95.14--95.64 |
| node:26.6.0-alpine | 61.53% | 58.52--61.65 |

These supersede the single-run figures in
`../2026-09-17T08-42-17Z-keypath-mechanism/cpuprof_jwt_hs_string.csv` and
`../2026-09-17T08-57-13Z-keypath-runtime-matrix/cpuprof_node_*.csv`, which remain
in place as the record of what was first measured. The qualitative conclusion is
unchanged in both: the frame dominates the string-key path and is absent from
the top frames of the pre-parsed path.
