#!/usr/bin/env python3
"""merge_ramp.py -- join k6 per-step results with 1 s pod CPU samples.

Called by run_openloop_ramp.sh. Produces openloop_ramp.csv (see
docs/DATA_SCHEMA.md) from three inputs in the run directory:

  k6_steps.csv         per-step latency and throughput, written by k6's
                       handleSummary in experiments/k6/openloop-ramp.js
  k6_raw.csv           per-request samples; the `scenario` tag names the step,
                       so each step's true [t_start, t_end] window is read off
                       the observed request timestamps rather than assumed from
                       the nominal schedule
  pod_cpu_samples.csv  1 s CPU samples, written by capture_pod_metrics.sh

Anything not measured stays empty. In particular:
  * no CPU sampler running  -> cpu_* columns empty for every step
  * no /metrics endpoint    -> eventloop_lag_p99_ms empty for every step
  * a step with no samples inside its window -> that step's cell empty

eventloop_lag_p99_ms is the MEAN of the per-scrape p99 values observed during
the step. It is not a p99 over the step, and DATA_SCHEMA.md says so; averaging
quantiles is not a quantile, and pretending otherwise would be the sort of
derived-not-measured quantity this artifact exists to remove.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

RUN_DIR = Path(os.environ.get("PSAO_RUN_DIR", "."))
APP_CONTAINER = os.environ.get("PSAO_APP_CONTAINER", "service-a")
SIDECAR_CONTAINER = os.environ.get("PSAO_SIDECAR_CONTAINER", "istio-proxy")

OUT_COLUMNS = [
    "scenario", "environment", "target_rps", "achieved_rps",
    "latency_mean_ms", "latency_p99_ms",
    "cpu_app_millicores", "cpu_sidecar_millicores", "eventloop_lag_p99_ms",
]


def read_csv_skipping_comments(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        lines = [line for line in fh if not line.startswith("#")]
    return list(csv.DictReader(lines))


def step_windows(raw_path: Path) -> dict[str, tuple[float, float]]:
    """Map k6 scenario name (step_00120) -> (first_ts, last_ts) in unix seconds."""
    windows: dict[str, list[float]] = {}
    if not raw_path.exists():
        return {}
    with raw_path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("metric_name") != "http_req_duration":
                continue
            name = row.get("scenario") or ""
            if not name.startswith("step_"):
                continue
            try:
                ts = float(row["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            bounds = windows.setdefault(name, [ts, ts])
            bounds[0] = min(bounds[0], ts)
            bounds[1] = max(bounds[1], ts)
    return {k: (v[0], v[1]) for k, v in windows.items()}


def mean(values: list[float]) -> str:
    return f"{sum(values) / len(values):.3f}" if values else ""


def main() -> int:
    steps = read_csv_skipping_comments(RUN_DIR / "k6_steps.csv")
    if not steps:
        sys.stderr.write(f"merge_ramp: no k6_steps.csv in {RUN_DIR}; nothing to merge\n")
        return 1

    windows = step_windows(RUN_DIR / "k6_raw.csv")
    cpu_rows = read_csv_skipping_comments(RUN_DIR / "pod_cpu_samples.csv")

    samples = []
    for row in cpu_rows:
        try:
            ts = float(row["t_unix"])
        except (KeyError, TypeError, ValueError):
            continue
        def maybe(key):
            raw = (row.get(key) or "").strip()
            try:
                return float(raw)
            except ValueError:
                return None
        samples.append((ts, row.get("container", ""), maybe("cpu_millicores"),
                        maybe("eventloop_lag_p99_ms")))

    out_path = RUN_DIR / "openloop_ramp.csv"
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        for step in steps:
            target = step["target_rps"]
            key = f"step_{int(float(target)):05d}"
            window = windows.get(key)
            app_cpu, sidecar_cpu, lag = [], [], []
            if window is not None:
                t0, t1 = window
                for ts, container, cpu, lag_value in samples:
                    if not (t0 <= ts <= t1):
                        continue
                    if container == APP_CONTAINER:
                        if cpu is not None:
                            app_cpu.append(cpu)
                        if lag_value is not None:
                            lag.append(lag_value)
                    elif container == SIDECAR_CONTAINER and cpu is not None:
                        sidecar_cpu.append(cpu)
            writer.writerow({
                "scenario": step["scenario"],
                "environment": step["environment"],
                "target_rps": target,
                "achieved_rps": step["achieved_rps"],
                "latency_mean_ms": step["latency_mean_ms"],
                "latency_p99_ms": step["latency_p99_ms"],
                "cpu_app_millicores": mean(app_cpu),
                "cpu_sidecar_millicores": mean(sidecar_cpu),
                "eventloop_lag_p99_ms": mean(lag),
            })

    n_with_cpu = sum(1 for r in read_csv_skipping_comments(out_path) if r["cpu_app_millicores"])
    sys.stderr.write(
        f"merge_ramp: wrote {out_path} ({len(steps)} steps, "
        f"{n_with_cpu} with CPU attributed)\n"
    )
    if n_with_cpu == 0:
        sys.stderr.write(
            "merge_ramp: NO CPU was attributed to any step. elbow_fit.py will "
            "report the CPU at the elbow as a PLACEHOLDER rather than a number.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
