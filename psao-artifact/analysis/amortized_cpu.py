"""amortized_cpu.py -- CPU per request, computed both ways.

THE AMBIGUITY THIS RESOLVES
---------------------------
The manuscript reports an amortised CPU cost per request. A closed-loop run with
a ramp-up, a steady phase and a ramp-down has two defensible throughputs:

  steady  requests completed during the steady phase, divided by the steady
          phase's duration. Describes the system AT the tested concurrency.
  full    requests completed over the whole profile, divided by the whole
          profile's duration. Lower, because the ramps contribute time at less
          than full load.

Dividing the same CPU figure by these two throughputs gives two different
amortised costs -- routinely differing by 20-40% for a 20 s ramp-up against a
60 s steady phase. The paper does not say which it used, so a reader cannot
reproduce the number, and the choice is large enough to matter to the
comparison between scenarios.

Both are computed here, reported side by side, with their ratio. The ratio is
the point: if it is near 1 the ambiguity was harmless, and if it is not, the
paper must state its choice.

WHAT "CPU" MEANS HERE
---------------------
Three components are measured separately and reported separately, because PSAO's
whole claim is that it MOVES cost rather than removing it:

  app       the Node.js container
  sidecar   the Envoy sidecar (where PSAO relocates verification to)
  ingress   the edge proxy

An application-only figure would make PSAO look free. The `total` column is the
honest one for a cost claim, and `app` is the honest one for a claim about the
event loop.

Units: millicores divided by requests-per-second yields millicore-seconds per
request. One millicore-second is 1 ms of a core's time, so the numbers are
directly comparable with the per-request service times measured by
bench/jwt-path-microbench.js.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import io as psao_io

COMPONENTS = {
    "app": "cpu_app_millicores",
    "sidecar": "cpu_sidecar_millicores",
    "ingress": "cpu_ingress_millicores",
}


def _per_request(cpu_millicores: float, throughput_rps: float):
    """millicore-seconds per request == milliseconds of a core per request."""
    if not np.isfinite(cpu_millicores) or not np.isfinite(throughput_rps) or throughput_rps <= 0:
        return None
    return float(cpu_millicores / throughput_rps)


def _window_stats(frame: pd.DataFrame) -> dict:
    """Aggregate one scenario's runs within one throughput window.

    Aggregation is across RUNS: each run contributes one CPU figure and one
    throughput, the per-request cost is formed per run, and the runs are then
    averaged. Averaging CPU and throughput separately and dividing the averages
    would be a ratio of means rather than a mean of ratios, which is a different
    (and, with unequal run lengths, biased) quantity.
    """
    if frame.empty:
        return {"n_runs": 0}

    out = {"n_runs": int(len(frame))}
    throughput = frame["throughput_rps"].to_numpy(float)
    out["throughput_rps_mean"] = float(np.nanmean(throughput)) if len(throughput) else None

    per_run_total = []
    for component, column in COMPONENTS.items():
        values = frame[column].to_numpy(float)
        per_run = [_per_request(c, t) for c, t in zip(values, throughput)]
        measured = [v for v in per_run if v is not None]
        out[component] = {
            "cpu_millicores_mean": (float(np.nanmean(values))
                                    if np.isfinite(values).any() else None),
            "per_request_mcore_s_mean": (float(np.mean(measured)) if measured else None),
            "per_request_mcore_s_sd": (float(np.std(measured, ddof=1))
                                       if len(measured) > 1 else None),
            "n_runs_measured": len(measured),
        }

    # Total is formed per run so a run missing one component is excluded from the
    # total rather than silently contributing a partial sum.
    complete = frame.dropna(subset=list(COMPONENTS.values()))
    if not complete.empty:
        totals = complete[list(COMPONENTS.values())].sum(axis=1).to_numpy(float)
        tput = complete["throughput_rps"].to_numpy(float)
        per_run_total = [v for v in (_per_request(c, t) for c, t in zip(totals, tput))
                         if v is not None]
    out["total"] = {
        "cpu_millicores_mean": (float(np.mean(complete[list(COMPONENTS.values())]
                                              .sum(axis=1))) if not complete.empty else None),
        "per_request_mcore_s_mean": (float(np.mean(per_run_total)) if per_run_total else None),
        "per_request_mcore_s_sd": (float(np.std(per_run_total, ddof=1))
                                   if len(per_run_total) > 1 else None),
        "n_runs_measured": len(per_run_total),
        "note": ("runs missing any of app/sidecar/ingress CPU are excluded from the "
                 "total rather than summed partially"),
    }
    return out


def analyse(bundle: psao_io.DataBundle) -> dict:
    scenarios = bundle.scenarios
    if scenarios is None or scenarios.empty:
        return {"available": False, "reason": "scenarios.csv absent"}

    out = {
        "available": True,
        "synthetic": bundle.synthetic,
        "units": "millicore-seconds per request (equivalently, ms of one core per request)",
        "scenarios": {},
    }
    for scenario in psao_io.scenarios_present(scenarios):
        frame = scenarios[scenarios["scenario"] == scenario]
        entry = {
            "description": psao_io.SCENARIO_DESCRIPTIONS.get(scenario, ""),
            "steady": _window_stats(frame[frame["throughput_window"] == "steady"]),
            "full": _window_stats(frame[frame["throughput_window"] == "full"]),
        }
        steady_total = entry["steady"].get("total", {}).get("per_request_mcore_s_mean")
        full_total = entry["full"].get("total", {}).get("per_request_mcore_s_mean")
        if steady_total and full_total:
            entry["steady_over_full_ratio"] = float(steady_total / full_total)
            entry["ambiguity_percent"] = float(abs(steady_total - full_total)
                                               / full_total * 100.0)
        else:
            entry["steady_over_full_ratio"] = None
            entry["ambiguity_percent"] = None
        out["scenarios"][scenario] = entry
    return out


def format_text(results: dict) -> str:
    if not results.get("available"):
        return f"AMORTIZED CPU: unavailable -- {results.get('reason')}\n"
    lines = ["AMORTIZED CPU PER REQUEST", "=" * 78]
    if results.get("synthetic"):
        lines.append("*** SYNTHETIC EXAMPLE DATA -- these numbers are not measurements ***")
    lines.append(f"units: {results['units']}")
    lines.append("")
    lines.append("Both normalisations are reported because the manuscript does not say")
    lines.append("which it used. 'ambiguity' is how much the choice changes the answer.")
    lines.append("")
    header = (f"{'scen':<5} {'window':<7} {'rps':>8} {'app':>9} {'sidecar':>9} "
              f"{'ingress':>9} {'total':>9}")
    lines.append(header)
    lines.append("-" * len(header))
    for scenario, entry in results["scenarios"].items():
        for window in ("steady", "full"):
            stats = entry[window]
            if not stats.get("n_runs"):
                lines.append(f"{scenario:<5} {window:<7} {'no runs':>8}")
                continue

            def cell(key):
                value = stats[key]["per_request_mcore_s_mean"]
                return "n/a" if value is None else f"{value:.4f}"

            rps = stats.get("throughput_rps_mean")
            lines.append(f"{scenario:<5} {window:<7} "
                         f"{'n/a' if rps is None else f'{rps:.1f}':>8} "
                         f"{cell('app'):>9} {cell('sidecar'):>9} "
                         f"{cell('ingress'):>9} {cell('total'):>9}")
        ratio = entry["steady_over_full_ratio"]
        if ratio is not None:
            lines.append(f"      ambiguity: steady/full = {ratio:.3f} "
                         f"({entry['ambiguity_percent']:.1f}% difference in the "
                         f"published number depending on the choice)")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example")
    parser.add_argument("--json")
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    results = analyse(bundle)
    print(format_text(results))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
