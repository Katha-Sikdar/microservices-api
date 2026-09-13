# SUPERSEDED — valid, but not the canonical S5

This is a complete, sound S5 ramp: 20 steps, 0 dropped iterations, CPU attributed
to all 20, measured in a verified full Zero Trust posture.

It is superseded for two reasons, neither of which is a defect in the data:

1. **Ceiling too low.** It ramps only to 400 rps. The elbow is between 750 and
   850 rps on this host (see `PROBE-2026-09-13-find-saturation/README.md`), so
   this run is entirely on the flat part of the curve and shows no elbow.

2. **Different image.** It ran on `service-a:psao-1`
   (`sha256:ac502eec...`), which hard-codes JWT validation. S1 and S3 require a
   build without application-layer JWT, so all three scenarios were re-measured
   on `service-a:psao-2` (`sha256:068793d4...`), which selects the handler at
   startup from `PSAO_AUTH_MODE`. Comparing S1/S3/S5 across different images
   would put build differences inside the comparison the elbow figure makes.

The canonical S5 for the elbow figure is `2026-09-13T11-09-18Z-ramp-S5`
(50..1000 rps on psao-2). This run remains usable as an independent check that
the two images agree on the flat part of the curve.
