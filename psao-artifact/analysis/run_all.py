"""run_all.py -- run every analysis, write JSON, a readable summary, and the
LaTeX macros the manuscript cites.

THE MACRO FILE IS THE POINT
---------------------------
paper/generated_macros.tex defines one \\newcommand for every number the
manuscript quotes. The manuscript then cites \\PsaoSFiveLatencyMean rather than
typing "8.4". Two consequences, both deliberate:

  * A number in the paper cannot drift away from the analysis that produced it.
    Re-run the analysis and the paper's numbers change with it.
  * A number that was NOT measured cannot be typed in by accident. Missing
    quantities are emitted as \\PLACEHOLDER{key}, which renders in red as
    [MISSING: key] and is impossible to miss in a proof. There is no code path
    in this artifact that turns a missing measurement into a plausible one.

When the data is synthetic, every value is additionally wrapped in \\SYNTHVAL,
which renders it in red with a dagger. Example data can therefore be run all the
way through to a compiled PDF without any chance of the result being mistaken
for a measurement.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from . import amortized_cpu, elbow_fit, io as psao_io, stats_tests

MACRO_PREFIX = "Psao"


# ---------------------------------------------------------------------------
# Summaries of the two inputs that have no module of their own
# ---------------------------------------------------------------------------

def summarise_controller(trace: Optional[pd.DataFrame]) -> dict:
    """Decisions, actuation latency and mode occupancy from controller_trace.csv."""
    if trace is None or trace.empty:
        return {"available": False,
                "reason": "controller_trace.csv absent; run experiments/run_controller_experiment.sh"}

    decisions = trace["decision"].value_counts().to_dict()
    actuation = trace["actuation_latency_ms"].dropna().to_numpy(float)
    # A suppressed flap is recorded as decision=hold with a trigger_reason that
    # begins 'suppressed:'. Counting them from the trace (rather than from the
    # log) keeps the count reproducible from the shipped data alone.
    reasons = trace["trigger_reason"].fillna("").astype(str)
    suppressed = reasons.str.startswith("suppressed:")
    suppressed_by_dwell = reasons.str.contains(":dwell(", regex=False)
    suppressed_by_consecutive = reasons.str.contains(":consecutive(", regex=False)

    duration = float(trace["t_rel_s"].max() - trace["t_rel_s"].min()) if len(trace) > 1 else 0.0
    mode_counts = trace["mode"].value_counts().to_dict()
    total_rows = len(trace)

    out = {
        "available": True,
        "rows": int(total_rows),
        "duration_s": duration,
        "decisions": {str(k): int(v) for k, v in decisions.items()},
        "transitions": int(sum(v for k, v in decisions.items() if k in ("offload", "revert"))),
        "offloads": int(decisions.get("offload", 0)),
        "reverts": int(decisions.get("revert", 0)),
        "suppressed_flaps": int(suppressed.sum()),
        "suppressed_by_dwell": int((suppressed & suppressed_by_dwell).sum()),
        "suppressed_by_consecutive": int((suppressed & suppressed_by_consecutive).sum()),
        "mode_sample_fraction": {str(k): float(v / total_rows) for k, v in mode_counts.items()},
        "actuation_latency_ms": {
            "n": int(len(actuation)),
            "mean": float(np.mean(actuation)) if len(actuation) else None,
            "median": float(np.median(actuation)) if len(actuation) else None,
            "min": float(np.min(actuation)) if len(actuation) else None,
            "max": float(np.max(actuation)) if len(actuation) else None,
        },
    }
    for column in ("lambda_rps", "rho", "mu_eff_rps", "latency_mean_ms",
                   "eventloop_lag_p99_ms"):
        values = trace[column].replace([np.inf, -np.inf], np.nan).dropna().to_numpy(float)
        out[column] = {
            "min": float(values.min()) if len(values) else None,
            "max": float(values.max()) if len(values) else None,
            "mean": float(values.mean()) if len(values) else None,
        }

    first_offload = trace[trace["decision"] == "offload"]
    if not first_offload.empty:
        row = first_offload.iloc[0]
        out["first_offload"] = {
            "t_rel_s": float(row["t_rel_s"]),
            "lambda_rps": (None if pd.isna(row["lambda_rps"]) else float(row["lambda_rps"])),
            "rho": (None if pd.isna(row["rho"]) else float(row["rho"])),
            "actuation_latency_ms": (None if pd.isna(row["actuation_latency_ms"])
                                     else float(row["actuation_latency_ms"])),
            "trigger_reason": str(row["trigger_reason"]),
        }
    return out


def summarise_microbench(bench: Optional[pd.DataFrame]) -> dict:
    """Stage decomposition, and the share of jwt.verify() that is not cryptography."""
    if bench is None or bench.empty:
        return {"available": False,
                "reason": "microbench.csv absent; run `make microbench`"}

    out = {"available": True, "stages": {}, "decomposition": {}}
    grouped = bench.groupby(["algorithm", "stage", "payload_kb"], dropna=False)
    for (algorithm, stage, payload), frame in grouped:
        out["stages"].setdefault(str(algorithm), {}).setdefault(str(stage), {})[str(payload)] = {
            "mean_us": float(frame["mean_us"].mean()),
            "p50_us": float(frame["p50_us"].mean()),
            "p99_us": float(frame["p99_us"].mean()),
            "iterations": int(frame["iterations"].sum()),
        }

    # The headline decomposition: how much of a full jwt.verify() is parsing
    # rather than the cryptographic primitive. If this is large, relocating
    # verification to the sidecar does not remove the cost, it relocates it --
    # the sidecar parses too.
    for algorithm, by_stage in out["stages"].items():
        for payload in sorted({p for stage in by_stage.values() for p in stage}):
            def mean_us(stage):
                return by_stage.get(stage, {}).get(payload, {}).get("mean_us")

            full = mean_us("full_verify")
            decode = mean_us("decode_only")
            preparsed = mean_us("primitive_preparsed")
            raw = mean_us("primitive_raw")
            if full is None:
                continue
            entry = {
                "full_verify_us": full,
                "decode_only_us": decode,
                "primitive_preparsed_us": preparsed,
                "primitive_raw_us": raw,
            }
            if decode is not None and preparsed is not None:
                residual = full - decode - preparsed
                entry["library_overhead_us"] = residual
                entry["parsing_share_percent"] = 100.0 * decode / full
                entry["crypto_share_percent"] = 100.0 * preparsed / full
                entry["residual_share_percent"] = 100.0 * residual / full
                if residual < 0:
                    entry["note"] = (
                        "negative residual: decode_only + primitive_preparsed exceeds "
                        "full_verify. The stages overlap in what they attribute (both "
                        "touch the same buffers, and the JIT specialises the isolated "
                        "loops more aggressively than the combined one). Reported as "
                        "measured; not clamped.")
            if preparsed is not None and raw is not None:
                entry["signing_input_assembly_us"] = preparsed - raw
            out["decomposition"].setdefault(algorithm, {})[payload] = entry
    return out


def summarise_scenarios(scenarios: Optional[pd.DataFrame]) -> dict:
    """Per-scenario latency and CPU means across runs, per throughput window."""
    if scenarios is None or scenarios.empty:
        return {"available": False, "reason": "scenarios.csv absent"}
    out = {"available": True, "scenarios": {}}
    metrics = ["throughput_rps", "latency_mean_ms", "latency_p50_ms", "latency_p90_ms",
               "latency_p95_ms", "latency_p99_ms", "latency_stdev_ms",
               "cpu_app_millicores", "cpu_sidecar_millicores",
               "cpu_ingress_millicores", "cpu_limit_millicores"]
    for scenario in psao_io.scenarios_present(scenarios):
        frame = scenarios[scenarios["scenario"] == scenario]
        entry = {"description": psao_io.SCENARIO_DESCRIPTIONS.get(scenario, "")}
        for window in ("steady", "full"):
            window_frame = frame[frame["throughput_window"] == window]
            stats = {"n_runs": int(len(window_frame))}
            for metric in metrics:
                values = window_frame[metric].dropna().to_numpy(float)
                stats[metric] = {
                    "mean": float(values.mean()) if len(values) else None,
                    "sd": float(values.std(ddof=1)) if len(values) > 1 else None,
                    "n": int(len(values)),
                }
                # 95% CI of the mean across runs, t-based. With n = 3 this is
                # wide, which is the correct message rather than a defect.
                if len(values) > 1:
                    half = float(scipy_stats.t.ppf(0.975, len(values) - 1)
                                 * values.std(ddof=1) / math.sqrt(len(values)))
                    stats[metric]["ci95_halfwidth"] = half
            entry[window] = stats
        out["scenarios"][scenario] = entry
    return out


# ---------------------------------------------------------------------------
# LaTeX macros
# ---------------------------------------------------------------------------

@dataclass
class Macro:
    key: str
    value: Optional[float]
    unit: str
    description: str
    digits: int = 3

    @property
    def name(self) -> str:
        return psao_io.macro_name(self.key)

    def render(self, synthetic: bool) -> str:
        if self.value is None or (isinstance(self.value, float)
                                  and not math.isfinite(self.value)):
            body = f"\\PLACEHOLDER{{{self.key}}}"
        else:
            if isinstance(self.value, str):
                text = self.value
            elif float(self.value).is_integer() and self.digits == 0:
                text = str(int(self.value))
            else:
                text = f"{self.value:.{self.digits}f}"
            body = f"\\SYNTHVAL{{{text}}}" if synthetic else text
        comment = f"  % {self.description}" + (f" [{self.unit}]" if self.unit else "")
        return f"\\newcommand{{\\{self.name}}}{{{body}}}{comment}"


def dig(source: Any, *path, default=None):
    """Walk nested dicts safely; missing means missing, never a default value."""
    current = source
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and isinstance(key, int) and -len(current) <= key < len(current):
            current = current[key]
        else:
            return default
    if isinstance(current, float) and not math.isfinite(current):
        return default
    return current


def build_macros(results: dict) -> list[Macro]:
    """Every number the manuscript cites, in one place.

    Adding a claim to the paper means adding a line here. A quantity listed here
    that the data does not contain becomes a red \\PLACEHOLDER, which is exactly
    the outcome we want for a claim the experiments do not support yet.
    """
    macros: list[Macro] = []
    scen = results["scenarios"]
    amort = results["amortized_cpu"]
    elbow = results["elbow_fit"]
    tests = results["stats_tests"]
    ctrl = results["controller"]
    bench = results["microbench"]

    # -- per scenario ------------------------------------------------------
    for scenario in psao_io.SCENARIO_ORDER:
        base = f"{scenario}_"
        entry = dig(scen, "scenarios", scenario, default={})
        for metric, unit, digits in (
            ("latency_mean_ms", "ms", 3),
            ("latency_p50_ms", "ms", 3),
            ("latency_p95_ms", "ms", 3),
            ("latency_p99_ms", "ms", 3),
            ("throughput_rps", "req/s", 2),
            ("cpu_app_millicores", "m", 1),
            ("cpu_sidecar_millicores", "m", 1),
            ("cpu_ingress_millicores", "m", 1),
        ):
            macros.append(Macro(
                base + metric, dig(entry, "steady", metric, "mean"), unit,
                f"{scenario} steady-window {metric}, mean across runs", digits))
        macros.append(Macro(
            base + "latency_mean_ci95", dig(entry, "steady", "latency_mean_ms", "ci95_halfwidth"),
            "ms", f"{scenario} 95% CI half-width of the mean latency across runs", 3))
        macros.append(Macro(
            base + "n_runs", dig(entry, "steady", "n_runs"), "runs",
            f"{scenario} number of steady-window runs", 0))

        # amortised CPU, both normalisations, because the paper is ambiguous
        for window in ("steady", "full"):
            macros.append(Macro(
                f"{base}cpu_per_request_{window}",
                dig(amort, "scenarios", scenario, window, "total", "per_request_mcore_s_mean"),
                "mcore-s/req",
                f"{scenario} amortised total CPU per request, normalised by "
                f"{window}-window throughput", 4))
            macros.append(Macro(
                f"{base}cpu_app_per_request_{window}",
                dig(amort, "scenarios", scenario, window, "app", "per_request_mcore_s_mean"),
                "mcore-s/req",
                f"{scenario} amortised APPLICATION CPU per request, "
                f"{window}-window throughput", 4))
        macros.append(Macro(
            base + "cpu_per_request_ambiguity",
            dig(amort, "scenarios", scenario, "ambiguity_percent"), "%",
            f"{scenario} percentage difference between the two amortisation choices", 1))

    # -- elbow fits --------------------------------------------------------
    for scenario in psao_io.SCENARIO_ORDER:
        fits = dig(elbow, "scenarios", scenario, default={})
        if not fits:
            continue
        for model in ("mm1", "md1"):
            macros.append(Macro(f"{scenario}_{model}_mu", dig(fits, "fits", model, "mu_rps"),
                                "req/s", f"{scenario} fitted service rate, {model.upper()}", 1))
            macros.append(Macro(f"{scenario}_{model}_rmse", dig(fits, "fits", model, "rmse_ms"),
                                "ms", f"{scenario} {model.upper()} fit RMSE", 3))
            macros.append(Macro(f"{scenario}_{model}_mape", dig(fits, "fits", model, "mape_percent"),
                                "%", f"{scenario} {model.upper()} fit MAPE", 2))
            macros.append(Macro(f"{scenario}_{model}_elbow_lambda",
                                dig(fits, "elbow", model, "lambda_rps"), "req/s",
                                f"{scenario} elbow arrival rate, {model.upper()}", 1))
            macros.append(Macro(f"{scenario}_{model}_elbow_latency",
                                dig(fits, "elbow", model, "latency_ms"), "ms",
                                f"{scenario} latency at the elbow, {model.upper()}", 2))
            macros.append(Macro(f"{scenario}_{model}_elbow_rho",
                                dig(fits, "elbow", model, "rho"), "",
                                f"{scenario} utilisation at the elbow, {model.upper()}", 3))
            macros.append(Macro(f"{scenario}_{model}_elbow_cpu_app",
                                dig(fits, "elbow", model, "cpu", "app_millicores"), "m",
                                f"{scenario} application CPU measured at the elbow, "
                                f"{model.upper()}", 1))
            macros.append(Macro(f"{scenario}_{model}_elbow_cpu_total",
                                dig(fits, "elbow", model, "cpu", "total_millicores"), "m",
                                f"{scenario} app+sidecar CPU measured at the elbow, "
                                f"{model.upper()}", 1))
            macros.append(Macro(f"{scenario}_{model}_trigger_lambda",
                                dig(fits, "psao_trigger", model, "lambda_rps"), "req/s",
                                f"{scenario} arrival rate at the PSAO trigger, "
                                f"{model.upper()}", 1))

    # -- significance ------------------------------------------------------
    for family_name, family in (("runmeans", dig(tests, "families", "run_means", default={})),
                                ("perrequest", dig(tests, "families", "per_request", default={}))):
        for comparison in dig(family, "comparisons", default=[]) or []:
            scenario = str(comparison["label"]).split()[0]
            base = f"{scenario}_{family_name}_"
            macros.append(Macro(base + "welch_p", dig(comparison, "welch_t", "p_value"), "",
                                f"{comparison['label']} Welch p ({family_name})", 5))
            macros.append(Macro(base + "welch_p_bonf",
                                dig(comparison, "welch_t", "p_value_bonferroni"), "",
                                f"{comparison['label']} Bonferroni-corrected Welch p", 5))
            macros.append(Macro(base + "mwu_p", dig(comparison, "mann_whitney_u", "p_value"), "",
                                f"{comparison['label']} Mann-Whitney p", 5))
            macros.append(Macro(base + "cohens_d", dig(comparison, "cohens_d", "value"), "",
                                f"{comparison['label']} Cohen's d (pooled SD)", 3))
            macros.append(Macro(base + "median_diff",
                                dig(comparison, "bca_median_difference", "estimate"), "ms",
                                f"{comparison['label']} median latency difference", 4))
            macros.append(Macro(base + "median_diff_ci_low",
                                dig(comparison, "bca_median_difference", "ci_low"), "ms",
                                f"{comparison['label']} BCa CI lower bound", 4))
            macros.append(Macro(base + "median_diff_ci_high",
                                dig(comparison, "bca_median_difference", "ci_high"), "ms",
                                f"{comparison['label']} BCa CI upper bound", 4))

    # -- controller --------------------------------------------------------
    macros += [
        Macro("controller_transitions", dig(ctrl, "transitions"), "",
              "Total mode transitions in the controller run", 0),
        Macro("controller_offloads", dig(ctrl, "offloads"), "",
              "Offload transitions", 0),
        Macro("controller_reverts", dig(ctrl, "reverts"), "", "Revert transitions", 0),
        Macro("controller_suppressed_flaps", dig(ctrl, "suppressed_flaps"), "",
              "Would-be transitions suppressed by hysteresis or dwell", 0),
        Macro("controller_suppressed_dwell", dig(ctrl, "suppressed_by_dwell"), "",
              "Suppressed specifically by the minimum dwell time", 0),
        Macro("controller_suppressed_consecutive", dig(ctrl, "suppressed_by_consecutive"), "",
              "Suppressed specifically by the consecutive-sample requirement", 0),
        Macro("actuation_latency_mean", dig(ctrl, "actuation_latency_ms", "mean"), "ms",
              "Mean actuation latency: decision to policy observed in effect", 1),
        Macro("actuation_latency_median", dig(ctrl, "actuation_latency_ms", "median"), "ms",
              "Median actuation latency", 1),
        Macro("actuation_latency_max", dig(ctrl, "actuation_latency_ms", "max"), "ms",
              "Worst observed actuation latency", 1),
        Macro("actuation_samples", dig(ctrl, "actuation_latency_ms", "n"), "",
              "Number of actuations timed", 0),
        Macro("controller_first_offload_lambda", dig(ctrl, "first_offload", "lambda_rps"),
              "req/s", "Arrival rate at the first offload decision", 1),
        Macro("controller_first_offload_rho", dig(ctrl, "first_offload", "rho"), "",
              "Utilisation at the first offload decision", 3),
        Macro("controller_first_offload_time", dig(ctrl, "first_offload", "t_rel_s"), "s",
              "Time into the run of the first offload decision", 1),
        Macro("controller_sidecar_fraction", dig(ctrl, "mode_sample_fraction", "sidecar"), "",
              "Fraction of control intervals spent with verification in the sidecar", 3),
        Macro("controller_duration", dig(ctrl, "duration_s"), "s",
              "Duration of the controller run", 1),
    ]

    # -- microbenchmark ----------------------------------------------------
    for algorithm in ("HS256", "RS256"):
        for payload in ("0.5", "2.0", "4.0"):
            # payload_kb may be stored as 2 or 2.0 depending on the writer.
            entry = (dig(bench, "decomposition", algorithm, payload)
                     or dig(bench, "decomposition", algorithm, payload.rstrip("0").rstrip("."))
                     or {})
            tag = payload.replace(".", "p")
            base = f"bench_{algorithm}_{tag}_"
            macros += [
                Macro(base + "full_verify", entry.get("full_verify_us"), "us",
                      f"{algorithm} {payload} KB: full jwt.verify()", 3),
                Macro(base + "decode_only", entry.get("decode_only_us"), "us",
                      f"{algorithm} {payload} KB: parsing only, no signature check", 3),
                Macro(base + "primitive_preparsed", entry.get("primitive_preparsed_us"), "us",
                      f"{algorithm} {payload} KB: crypto primitive, pre-parsed key", 3),
                Macro(base + "primitive_raw", entry.get("primitive_raw_us"), "us",
                      f"{algorithm} {payload} KB: crypto primitive over raw bytes", 3),
                Macro(base + "parsing_share", entry.get("parsing_share_percent"), "%",
                      f"{algorithm} {payload} KB: share of jwt.verify() that is parsing", 1),
                Macro(base + "crypto_share", entry.get("crypto_share_percent"), "%",
                      f"{algorithm} {payload} KB: share that is the crypto primitive", 1),
            ]
    return macros


PREAMBLE = r"""% generated_macros.tex -- GENERATED FILE, DO NOT EDIT BY HAND.
%
% Regenerate with:   make analysis DATA=<your data directory>
% Source of truth:   analysis/run_all.py (build_macros)
%
% Every number the manuscript cites is defined here as a macro, so the paper and
% the analysis cannot drift apart. A quantity the data does not contain is
% emitted as \PLACEHOLDER{key} and renders in red as [MISSING: key]. Never
% replace a \PLACEHOLDER by typing a number into the manuscript: add the
% measurement, or drop the claim.
%
% Requires \usepackage{xcolor} in the document preamble.
%
\providecommand{\PLACEHOLDER}[1]{%
  \textcolor{red}{\textbf{[MISSING: \texttt{#1}]}}%
}
% Wraps every value derived from synthetic example data, so example output can
% never be mistaken for a measurement even after it has been typeset.
\providecommand{\SYNTHVAL}[1]{%
  \textcolor{red}{#1\textsuperscript{\dag}}%
}
"""

SYNTHETIC_BANNER = r"""
% =====================================================================
% *** THESE MACROS WERE GENERATED FROM SYNTHETIC EXAMPLE DATA ***
% Every value below is wrapped in \SYNTHVAL and typesets in red with a
% dagger. This file exercises the pipeline; it is NOT publishable.
% Regenerate with DATA pointing at a real measurement directory.
% =====================================================================
"""


def write_macros(macros: list[Macro], path: Path, *, synthetic: bool,
                 data_dir: Path) -> dict:
    lines = [PREAMBLE]
    if synthetic:
        lines.append(SYNTHETIC_BANNER)
    lines.append(f"% data directory: {data_dir}")
    defined = sum(1 for m in macros if m.value is not None)
    lines.append(f"% {defined} of {len(macros)} quantities are available; "
                 f"{len(macros) - defined} are PLACEHOLDERs.\n")
    for macro in macros:
        lines.append(macro.render(synthetic))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return {
        "path": str(path),
        "total": len(macros),
        "defined": defined,
        "placeholders": [m.key for m in macros if m.value is None],
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run(data_dir: Path, out_dir: Path, macros_path: Path, *,
        n_boot: int = stats_tests.N_BOOTSTRAP, seed: int = stats_tests.DEFAULT_SEED,
        rho_trigger: float = elbow_fit.DEFAULT_RHO_TRIGGER) -> dict:
    bundle = psao_io.load_bundle(data_dir)

    results = {
        "data_dir": str(data_dir),
        "synthetic": bundle.synthetic,
        "inputs_missing": bundle.missing,
        "scenarios": summarise_scenarios(bundle.scenarios),
        "elbow_fit": elbow_fit.analyse(bundle, rho_trigger=rho_trigger),
        "stats_tests": stats_tests.analyse(bundle, n_boot=n_boot, seed=seed),
        "amortized_cpu": amortized_cpu.analyse(bundle),
        "controller": summarise_controller(bundle.controller_trace),
        "microbench": summarise_microbench(bundle.microbench),
    }

    macros = build_macros(results)
    results["macros"] = write_macros(macros, macros_path,
                                     synthetic=bundle.synthetic, data_dir=data_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis.json").write_text(json.dumps(results, indent=2, default=str))

    summary = format_summary(results, bundle)
    (out_dir / "summary.txt").write_text(summary)
    return results


def format_summary(results: dict, bundle: psao_io.DataBundle) -> str:
    parts = [
        "PSAO ARTIFACT -- ANALYSIS SUMMARY",
        "=" * 78,
        bundle.describe(),
        "",
    ]
    if bundle.synthetic:
        parts += [
            "*" * 78,
            "*** SYNTHETIC EXAMPLE DATA. Nothing below is a measurement. Figures are",
            "*** watermarked and every generated macro is wrapped in \\SYNTHVAL.",
            "*" * 78,
            "",
        ]
    if results["inputs_missing"]:
        parts += [f"missing inputs: {', '.join(results['inputs_missing'])}", ""]

    parts.append(elbow_fit.format_text(results["elbow_fit"]))
    parts.append(stats_tests.format_text(results["stats_tests"]))
    parts.append(amortized_cpu.format_text(results["amortized_cpu"]))

    parts.append("CONTROLLER RUN")
    parts.append("=" * 78)
    ctrl = results["controller"]
    if not ctrl.get("available"):
        parts.append(f"unavailable -- {ctrl.get('reason')}")
    else:
        parts.append(f"  rows {ctrl['rows']}, duration {ctrl['duration_s']:.1f} s")
        parts.append(f"  transitions: {ctrl['transitions']} "
                     f"({ctrl['offloads']} offload, {ctrl['reverts']} revert)")
        parts.append(f"  suppressed flaps: {ctrl['suppressed_flaps']} "
                     f"({ctrl['suppressed_by_dwell']} by dwell, "
                     f"{ctrl['suppressed_by_consecutive']} by consecutive-sample rule)")
        act = ctrl["actuation_latency_ms"]
        if act["n"]:
            parts.append(f"  actuation latency: mean {act['mean']:.1f} ms, "
                         f"median {act['median']:.1f} ms, max {act['max']:.1f} ms "
                         f"(n={act['n']})")
        else:
            parts.append("  actuation latency: no transition completed")
        if "first_offload" in ctrl:
            first = ctrl["first_offload"]
            lam = "n/a" if first["lambda_rps"] is None else f"{first['lambda_rps']:.1f}"
            rho = "n/a" if first["rho"] is None else f"{first['rho']:.3f}"
            parts.append(f"  first offload at t={first['t_rel_s']:.1f}s, "
                         f"lambda={lam} rps, rho={rho}")
            parts.append(f"    reason: {first['trigger_reason']}")
    parts.append("")

    parts.append("MICROBENCHMARK DECOMPOSITION")
    parts.append("=" * 78)
    bench = results["microbench"]
    if not bench.get("available"):
        parts.append(f"unavailable -- {bench.get('reason')}")
    else:
        parts.append(f"  {'alg':<7}{'kB':>5}{'full':>10}{'decode':>10}{'crypto':>10}"
                     f"{'raw':>10}{'parse%':>9}{'crypto%':>9}")
        for algorithm, by_payload in bench["decomposition"].items():
            for payload, entry in sorted(by_payload.items(), key=lambda kv: float(kv[0])):
                def cell(key, fmt="{:.3f}"):
                    value = entry.get(key)
                    return "n/a" if value is None else fmt.format(value)
                parts.append(f"  {algorithm:<7}{float(payload):>5.1f}"
                             f"{cell('full_verify_us'):>10}{cell('decode_only_us'):>10}"
                             f"{cell('primitive_preparsed_us'):>10}"
                             f"{cell('primitive_raw_us'):>10}"
                             f"{cell('parsing_share_percent', '{:.1f}'):>9}"
                             f"{cell('crypto_share_percent', '{:.1f}'):>9}")
                if entry.get("note"):
                    parts.append(f"      note: {entry['note']}")
    parts.append("")

    macro_info = results["macros"]
    parts.append("GENERATED LATEX MACROS")
    parts.append("=" * 78)
    parts.append(f"  {macro_info['path']}")
    parts.append(f"  {macro_info['defined']} of {macro_info['total']} quantities defined; "
                 f"{len(macro_info['placeholders'])} PLACEHOLDERs.")
    if macro_info["placeholders"]:
        parts.append("  Missing (each renders in red as [MISSING: key]):")
        for key in macro_info["placeholders"][:40]:
            parts.append(f"    {key}")
        if len(macro_info["placeholders"]) > 40:
            parts.append(f"    ... and {len(macro_info['placeholders']) - 40} more "
                         "(full list in analysis.json)")
    parts.append("")
    return "\n".join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example", help="data directory")
    parser.add_argument("--out", default="analysis/output", help="where to write JSON and summary")
    parser.add_argument("--macros", default="paper/generated_macros.tex")
    parser.add_argument("--n-boot", type=int, default=stats_tests.N_BOOTSTRAP)
    parser.add_argument("--seed", type=int, default=stats_tests.DEFAULT_SEED)
    parser.add_argument("--rho-trigger", type=float, default=elbow_fit.DEFAULT_RHO_TRIGGER,
                        help="must match control.thresholds.rho_trigger in controller/config.yaml")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    results = run(Path(args.data), Path(args.out), Path(args.macros),
                  n_boot=args.n_boot, seed=args.seed, rho_trigger=args.rho_trigger)
    if not args.quiet:
        print((Path(args.out) / "summary.txt").read_text())
    print(f"wrote {args.out}/analysis.json, {args.out}/summary.txt and {args.macros}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
