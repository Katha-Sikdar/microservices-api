#!/usr/bin/env python3
"""merge_scenario.py -- assemble scenarios.csv and latency_samples.csv rows.

Called by run_closedloop_scenario.sh. Inputs, all in the run directory:

  k6_scenario.csv      steady-window and full-window rows from k6's
                       handleSummary (experiments/k6/closedloop.js)
  k6_raw.csv           per-request samples
  pod_cpu_samples.csv  1 s CPU samples from capture_pod_metrics.sh

Outputs:
  scenarios.csv        one row per throughput window, schema per docs/DATA_SCHEMA.md
  latency_samples.csv  per-request latencies, for the density figure

latency_stdev_ms is computed here from the per-request samples because k6 does
not report a standard deviation. CPU columns are means over the run's steady
window for the steady row and over the whole run for the full row -- the two are
different numbers and amortized_cpu.py depends on being able to tell them apart.
Every cell that was not measured is left empty.
"""
from __future__ import annotations

import csv
import os
import statistics
import sys
from pathlib import Path

RUN_DIR = Path(os.environ.get("PSAO_RUN_DIR", "."))
APP_CONTAINER = os.environ.get("PSAO_APP_CONTAINER", "service-a")
SIDECAR_CONTAINER = os.environ.get("PSAO_SIDECAR_CONTAINER", "istio-proxy")
INGRESS_CONTAINER = os.environ.get("PSAO_INGRESS_CONTAINER", "controller")
CPU_LIMIT = os.environ.get("PSAO_CPU_LIMIT_MILLICORES", "").strip()
# Cap on rows written to latency_samples.csv. A long run at high rate can
# produce millions of samples; the density figure does not need them all. When
# the cap bites we take an evenly spaced stride rather than the first N, so the
# retained sample still covers the whole run.
MAX_SAMPLES = int(os.environ.get("PSAO_MAX_LATENCY_SAMPLES", "200000"))

SCENARIO_COLUMNS = [
    "scenario", "environment", "run", "throughput_rps", "throughput_window",
    "latency_mean_ms", "latency_p50_ms", "latency_p90_ms", "latency_p95_ms",
    "latency_p99_ms", "latency_stdev_ms",
    "cpu_app_millicores", "cpu_sidecar_millicores", "cpu_ingress_millicores",
    "cpu_limit_millicores",
]


def read_csv_skipping_comments(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        lines = [line for line in fh if not line.startswith("#")]
    return list(csv.DictReader(lines))


def load_latency_samples(raw_path: Path):
    """Return (all_samples, steady_samples) as lists of (t_unix, latency_ms)."""
    every, steady = [], []
    if not raw_path.exists():
        return every, steady
    with raw_path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("metric_name") != "http_req_duration":
                continue
            try:
                ts = float(row["timestamp"])
                value = float(row["metric_value"])
            except (KeyError, TypeError, ValueError):
                continue
            every.append((ts, value))
            # closedloop.js tags each request with its phase; the tag may arrive
            # as its own column or inside extra_tags depending on k6 version.
            phase = row.get("phase") or ""
            if not phase:
                extra = row.get("extra_tags") or ""
                if "phase=steady" in extra:
                    phase = "steady"
            if phase == "steady":
                steady.append((ts, value))
    return every, steady


def cpu_means(samples, t0, t1):
    """Mean millicores per container role within [t0, t1]. Empty when unmeasured."""
    buckets = {"app": [], "sidecar": [], "ingress": []}
    for ts, container, cpu in samples:
        if cpu is None or not (t0 <= ts <= t1):
            continue
        if container == APP_CONTAINER:
            buckets["app"].append(cpu)
        elif container == SIDECAR_CONTAINER:
            buckets["sidecar"].append(cpu)
        elif container == INGRESS_CONTAINER:
            buckets["ingress"].append(cpu)
    return {k: (f"{sum(v) / len(v):.3f}" if v else "") for k, v in buckets.items()}


def main() -> int:
    rows = read_csv_skipping_comments(RUN_DIR / "k6_scenario.csv")
    if not rows:
        sys.stderr.write(f"merge_scenario: no k6_scenario.csv in {RUN_DIR}\n")
        return 1

    every, steady = load_latency_samples(RUN_DIR / "k6_raw.csv")

    cpu_samples = []
    for row in read_csv_skipping_comments(RUN_DIR / "pod_cpu_samples.csv"):
        try:
            ts = float(row["t_unix"])
        except (KeyError, TypeError, ValueError):
            continue
        raw = (row.get("cpu_millicores") or "").strip()
        try:
            cpu = float(raw)
        except ValueError:
            cpu = None
        cpu_samples.append((ts, row.get("container", ""), cpu))

    windows = {}
    if every:
        windows["full"] = (min(t for t, _ in every), max(t for t, _ in every))
    if steady:
        windows["steady"] = (min(t for t, _ in steady), max(t for t, _ in steady))

    stdevs = {}
    for name, series in (("full", every), ("steady", steady)):
        values = [v for _, v in series]
        stdevs[name] = f"{statistics.stdev(values):.4f}" if len(values) > 1 else ""

    out_path = RUN_DIR / "scenarios.csv"
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SCENARIO_COLUMNS)
        writer.writeheader()
        for row in rows:
            window = row["throughput_window"]
            cpu = {"app": "", "sidecar": "", "ingress": ""}
            if window in windows:
                cpu = cpu_means(cpu_samples, *windows[window])
            out = {k: row.get(k, "") for k in SCENARIO_COLUMNS}
            out["latency_stdev_ms"] = stdevs.get(window, "")
            out["cpu_app_millicores"] = cpu["app"]
            out["cpu_sidecar_millicores"] = cpu["sidecar"]
            out["cpu_ingress_millicores"] = cpu["ingress"]
            out["cpu_limit_millicores"] = CPU_LIMIT
            writer.writerow(out)

    # Per-request samples. Steady-window samples only: the density figure is
    # about the service's behaviour at load, and including the ramp-up would
    # blend two different operating points into one distribution.
    series = steady or every
    stride = max(1, len(series) // MAX_SAMPLES) if MAX_SAMPLES > 0 else 1
    scenario = rows[0]["scenario"]
    environment = rows[0]["environment"]
    run = rows[0]["run"]
    samples_path = RUN_DIR / "latency_samples.csv"
    with samples_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["scenario", "environment", "run", "latency_ms"])
        for _, value in series[::stride]:
            writer.writerow([scenario, environment, run, f"{value:.4f}"])

    sys.stderr.write(
        f"merge_scenario: wrote {out_path} ({len(rows)} windows) and "
        f"{samples_path} ({len(series[::stride])} samples"
        + (f", stride {stride}" if stride > 1 else "") + ")\n"
    )
    if not steady:
        sys.stderr.write(
            "merge_scenario: WARNING no phase:steady samples found; the steady "
            "window may be missing from k6_raw.csv tags\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
