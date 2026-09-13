"""stats_tests.py -- significance testing against the S1 baseline.

The manuscript compares scenario means without stating a test, an effect size,
an interval, or -- most consequentially -- WHAT THE UNIT OF ANALYSIS WAS. That
last omission is the serious one. With three repetitions per scenario the honest
n is 3; with per-request samples the n is tens of thousands and every difference
becomes "significant" because requests within a run are not independent
observations of the treatment. The two answers differ by orders of magnitude in
their p-values, and a reader cannot tell which was reported.

So this module computes both, keeps them in separate families, and labels every
result with its unit:

    unit = "run_means"           n = number of repetitions. The defensible unit
                                 for a claim about the CONFIGURATION, because the
                                 run is the thing that was randomised.
    unit = "per_request_samples" n = number of requests. Describes the observed
                                 latency DISTRIBUTION, not the configuration.
                                 p-values here are not evidence about the
                                 treatment and are labelled as such.

Reported per comparison against S1:
  * Welch's t-test (unequal variances; scenario variances are visibly unequal)
  * Mann-Whitney U (no normality assumption; latency is right-skewed)
  * Cohen's d with pooled SD
  * BCa bootstrap CI on the difference of medians, 10,000 resamples
  * Bonferroni correction across the comparisons WITHIN each family
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from . import io as psao_io

N_BOOTSTRAP = 10_000
# Fixed so a rerun reproduces the interval exactly. Bootstrap CIs that move
# between runs of the same analysis are not reportable.
DEFAULT_SEED = 20250906
ALPHA = 0.05


# ---------------------------------------------------------------------------
# Effect size
# ---------------------------------------------------------------------------

def cohens_d_pooled(x: np.ndarray, y: np.ndarray) -> tuple[Optional[float], str]:
    """Cohen's d using the pooled standard deviation.

    Pooled rather than Welch-corrected: d is being reported as a descriptive
    effect size on a common scale, and the pooled SD is the conventional
    denominator readers will assume. The variance heterogeneity is handled where
    it matters, in Welch's t-test.
    """
    nx, ny = len(x), len(y)
    if nx < 2 or ny < 2:
        return None, "need at least 2 observations per group"
    sx2, sy2 = np.var(x, ddof=1), np.var(y, ddof=1)
    pooled = math.sqrt(((nx - 1) * sx2 + (ny - 1) * sy2) / (nx + ny - 2))
    if pooled == 0:
        return None, "pooled SD is zero"
    d = float((np.mean(x) - np.mean(y)) / pooled)
    note = ""
    if min(nx, ny) < 10:
        # With n = 3 runs the small-sample bias in d is on the order of tens of
        # percent, upward. The reader must be told before quoting it.
        note = (f"n={min(nx, ny)}: Cohen's d is upward-biased at this sample size; "
                "treat it as descriptive, not as an estimate of the population effect")
    return d, note


# ---------------------------------------------------------------------------
# BCa bootstrap
# ---------------------------------------------------------------------------

def _median_diff(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.median(x) - np.median(y))


def bca_median_difference(x: np.ndarray, y: np.ndarray, *,
                          n_boot: int = N_BOOTSTRAP, alpha: float = ALPHA,
                          seed: int = DEFAULT_SEED) -> dict:
    """Bias-corrected and accelerated bootstrap CI for median(x) - median(y).

    The median is used rather than the mean because latency is right-skewed and
    the paper's claims are about typical behaviour. BCa rather than the
    percentile interval because the bootstrap distribution of a difference of
    medians is both biased and skewed; the percentile interval is visibly
    mis-centred at the sample sizes involved here.

    Bias correction z0 comes from the proportion of bootstrap replicates below
    the observed statistic; acceleration a from a leave-one-out jackknife taken
    across both samples. Degenerate cases (every replicate identical, all
    bootstrap values on one side of the estimate) fall back to the percentile
    interval and say so, rather than emitting an interval built from an infinite
    z0.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    nx, ny = len(x), len(y)
    result = {
        "statistic": "median(x) - median(y)",
        "estimate": None, "ci_low": None, "ci_high": None,
        "n_boot": n_boot, "alpha": alpha, "method": "BCa", "note": "",
    }
    if nx < 2 or ny < 2:
        result["note"] = "need at least 2 observations per group"
        return result

    theta_hat = _median_diff(x, y)
    result["estimate"] = theta_hat

    rng = np.random.default_rng(seed)
    # Resample the two groups independently: they are independent samples, and
    # resampling a pooled set would impose the null hypothesis on the interval.
    boot_x = rng.choice(x, size=(n_boot, nx), replace=True)
    boot_y = rng.choice(y, size=(n_boot, ny), replace=True)
    replicates = np.median(boot_x, axis=1) - np.median(boot_y, axis=1)

    proportion_below = float(np.mean(replicates < theta_hat))
    if proportion_below <= 0.0 or proportion_below >= 1.0:
        low, high = np.percentile(replicates, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        result.update({
            "ci_low": float(low), "ci_high": float(high), "method": "percentile",
            "note": ("every bootstrap replicate fell on one side of the estimate, so "
                     "the bias correction z0 is undefined; percentile interval reported "
                     "instead"),
        })
        return result

    z0 = float(stats.norm.ppf(proportion_below))

    # Jackknife across the combined sample: leave out one observation at a time
    # from x, then from y, recomputing the statistic each time.
    jackknife = np.empty(nx + ny)
    for i in range(nx):
        jackknife[i] = _median_diff(np.delete(x, i), y)
    for j in range(ny):
        jackknife[nx + j] = _median_diff(x, np.delete(y, j))
    deviations = jackknife.mean() - jackknife
    denominator = 6.0 * (np.sum(deviations ** 2) ** 1.5)
    a = 0.0 if denominator == 0 else float(np.sum(deviations ** 3) / denominator)

    z_alpha = stats.norm.ppf(alpha / 2)
    z_1_alpha = stats.norm.ppf(1 - alpha / 2)

    def adjusted(z):
        numerator = z0 + z
        return float(stats.norm.cdf(z0 + numerator / (1 - a * numerator)))

    a1, a2 = adjusted(z_alpha), adjusted(z_1_alpha)
    if not (0 < a1 < a2 < 1):
        low, high = np.percentile(replicates, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        result.update({
            "ci_low": float(low), "ci_high": float(high), "method": "percentile",
            "note": (f"BCa adjusted percentiles ({a1:.4f}, {a2:.4f}) are degenerate; "
                     "percentile interval reported instead"),
        })
        return result

    low, high = np.percentile(replicates, [100 * a1, 100 * a2])
    result.update({"ci_low": float(low), "ci_high": float(high),
                   "z0": z0, "acceleration": a,
                   "adjusted_percentiles": [a1, a2]})
    return result


# ---------------------------------------------------------------------------
# One comparison
# ---------------------------------------------------------------------------

def compare(treatment: np.ndarray, baseline: np.ndarray, *, label: str, unit: str,
            n_boot: int = N_BOOTSTRAP, seed: int = DEFAULT_SEED) -> dict:
    treatment = np.asarray(treatment, dtype=float)
    baseline = np.asarray(baseline, dtype=float)
    treatment = treatment[np.isfinite(treatment)]
    baseline = baseline[np.isfinite(baseline)]

    out = {
        "label": label,
        "unit": unit,
        "n_treatment": int(len(treatment)),
        "n_baseline": int(len(baseline)),
        "mean_treatment": float(np.mean(treatment)) if len(treatment) else None,
        "mean_baseline": float(np.mean(baseline)) if len(baseline) else None,
        "median_treatment": float(np.median(treatment)) if len(treatment) else None,
        "median_baseline": float(np.median(baseline)) if len(baseline) else None,
    }
    if len(treatment) < 2 or len(baseline) < 2:
        out["note"] = "fewer than 2 observations in one group; no test performed"
        return out

    welch = stats.ttest_ind(treatment, baseline, equal_var=False)
    out["welch_t"] = {"statistic": float(welch.statistic), "p_value": float(welch.pvalue),
                      "df": float(getattr(welch, "df", np.nan))}

    # Two-sided, and exact for small n (scipy chooses automatically); ties are
    # handled by the normal approximation with a tie correction.
    mwu = stats.mannwhitneyu(treatment, baseline, alternative="two-sided")
    out["mann_whitney_u"] = {"statistic": float(mwu.statistic), "p_value": float(mwu.pvalue)}

    d, note = cohens_d_pooled(treatment, baseline)
    out["cohens_d"] = {"value": d, "pooled_sd": True, "note": note}

    out["bca_median_difference"] = bca_median_difference(
        treatment, baseline, n_boot=n_boot, seed=seed)
    return out


def apply_bonferroni(comparisons: list[dict], alpha: float = ALPHA) -> None:
    """Bonferroni-correct in place, across the comparisons in ONE family.

    m is the number of comparisons against the baseline within this family, not
    across families: correcting run-mean and per-request comparisons together
    would penalise each for the other's existence when they are two views of the
    same experiment, not two experiments.
    """
    m = len([c for c in comparisons if "welch_t" in c])
    for comparison in comparisons:
        comparison["bonferroni"] = {"n_comparisons": m, "alpha": alpha,
                                    "corrected_alpha": alpha / m if m else None}
        if "welch_t" not in comparison:
            continue
        for test in ("welch_t", "mann_whitney_u"):
            p = comparison[test]["p_value"]
            comparison[test]["p_value_bonferroni"] = float(min(1.0, p * m))
            comparison[test]["significant_after_correction"] = bool(p < alpha / m)


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

def run_mean_family(scenarios: pd.DataFrame, *, window: str = "steady",
                    metric: str = "latency_mean_ms", n_boot: int = N_BOOTSTRAP,
                    seed: int = DEFAULT_SEED) -> dict:
    """Each observation is one run's mean. This is the defensible unit."""
    frame = scenarios[scenarios["throughput_window"] == window]
    baseline = frame[frame["scenario"] == psao_io.BASELINE_SCENARIO][metric].to_numpy(float)

    family = {
        "unit": "run_means",
        "metric": metric,
        "window": window,
        "description": (
            "One observation per repetition (the run's own mean). n is the number "
            "of runs. This is the unit that supports a claim about the "
            "configuration, because the run is what was repeated."),
        "baseline": psao_io.BASELINE_SCENARIO,
        "n_baseline_runs": int(len(baseline)),
        "comparisons": [],
    }
    if len(baseline) < 2:
        family["note"] = (f"baseline {psao_io.BASELINE_SCENARIO} has "
                          f"{len(baseline)} run(s) in the {window} window; at least 2 "
                          "are needed for any test")
        return family

    for scenario in psao_io.scenarios_present(frame):
        if scenario == psao_io.BASELINE_SCENARIO:
            continue
        values = frame[frame["scenario"] == scenario][metric].to_numpy(float)
        family["comparisons"].append(compare(
            values, baseline,
            label=f"{scenario} vs {psao_io.BASELINE_SCENARIO}",
            unit="run_means", n_boot=n_boot, seed=seed))
    apply_bonferroni(family["comparisons"])
    return family


def per_request_family(samples: pd.DataFrame, *, n_boot: int = N_BOOTSTRAP,
                       seed: int = DEFAULT_SEED) -> dict:
    """Each observation is one request. Describes distributions, not treatments."""
    baseline = samples[samples["scenario"] == psao_io.BASELINE_SCENARIO]["latency_ms"].to_numpy(float)
    family = {
        "unit": "per_request_samples",
        "metric": "latency_ms",
        "description": (
            "One observation per request. n is enormous and requests within a run "
            "are not independent draws of the treatment, so these p-values describe "
            "the observed latency DISTRIBUTIONS and must NOT be read as evidence "
            "about the configuration. The effect sizes and intervals here are "
            "meaningful; the p-values are not."),
        "baseline": psao_io.BASELINE_SCENARIO,
        "n_baseline_requests": int(len(baseline)),
        "comparisons": [],
    }
    if len(baseline) < 2:
        family["note"] = "baseline has too few per-request samples"
        return family

    for scenario in psao_io.scenarios_present(samples):
        if scenario == psao_io.BASELINE_SCENARIO:
            continue
        values = samples[samples["scenario"] == scenario]["latency_ms"].to_numpy(float)
        family["comparisons"].append(compare(
            values, baseline,
            label=f"{scenario} vs {psao_io.BASELINE_SCENARIO}",
            unit="per_request_samples", n_boot=n_boot, seed=seed))
    apply_bonferroni(family["comparisons"])
    return family


def analyse(bundle: psao_io.DataBundle, *, n_boot: int = N_BOOTSTRAP,
            seed: int = DEFAULT_SEED) -> dict:
    out = {"synthetic": bundle.synthetic, "n_bootstrap": n_boot, "seed": seed,
           "families": {}}
    if bundle.scenarios is not None and not bundle.scenarios.empty:
        out["families"]["run_means"] = run_mean_family(
            bundle.scenarios, n_boot=n_boot, seed=seed)
    else:
        out["families"]["run_means"] = {"available": False,
                                        "reason": "scenarios.csv absent"}
    if bundle.latency_samples is not None and not bundle.latency_samples.empty:
        out["families"]["per_request"] = per_request_family(
            bundle.latency_samples, n_boot=n_boot, seed=seed)
    else:
        out["families"]["per_request"] = {"available": False,
                                          "reason": "latency_samples.csv absent"}
    return out


def format_text(results: dict) -> str:
    lines = ["SIGNIFICANCE TESTS vs S1", "=" * 78]
    if results.get("synthetic"):
        lines.append("*** SYNTHETIC EXAMPLE DATA -- these numbers are not measurements ***")
    lines.append(f"bootstrap: {results['n_bootstrap']} resamples, seed {results['seed']}")

    for name, family in results["families"].items():
        lines.append("")
        lines.append(f"--- family: {name} ---")
        if family.get("available") is False:
            lines.append(f"  unavailable: {family['reason']}")
            continue
        lines.append(f"  unit: {family['unit']}")
        for chunk in family["description"].split(". "):
            if chunk.strip():
                lines.append(f"    {chunk.strip().rstrip('.')}.")
        if "note" in family:
            lines.append(f"  NOTE: {family['note']}")
            continue
        corrected = (family["comparisons"][0]["bonferroni"]["corrected_alpha"]
                     if family["comparisons"] else None)
        if corrected:
            lines.append(f"  Bonferroni: {family['comparisons'][0]['bonferroni']['n_comparisons']} "
                         f"comparisons, corrected alpha = {corrected:.5f}")
        for c in family["comparisons"]:
            lines.append("")
            lines.append(f"  {c['label']}  (n={c['n_treatment']} vs {c['n_baseline']})")
            if "welch_t" not in c:
                lines.append(f"    {c.get('note', 'no test performed')}")
                continue
            lines.append(f"    mean {c['mean_treatment']:.4f} vs {c['mean_baseline']:.4f}   "
                         f"median {c['median_treatment']:.4f} vs {c['median_baseline']:.4f}")
            w = c["welch_t"]
            lines.append(f"    Welch t = {w['statistic']:+.3f}  p = {w['p_value']:.3g}  "
                         f"p_bonf = {w['p_value_bonferroni']:.3g}  "
                         f"{'SIGNIFICANT' if w['significant_after_correction'] else 'not significant'}"
                         " after correction")
            u = c["mann_whitney_u"]
            lines.append(f"    Mann-Whitney U = {u['statistic']:.1f}  p = {u['p_value']:.3g}  "
                         f"p_bonf = {u['p_value_bonferroni']:.3g}")
            d = c["cohens_d"]
            if d["value"] is None:
                lines.append(f"    Cohen's d: n/a ({d['note']})")
            else:
                lines.append(f"    Cohen's d (pooled SD) = {d['value']:+.3f}")
                if d["note"]:
                    lines.append(f"      {d['note']}")
            b = c["bca_median_difference"]
            if b["ci_low"] is None:
                lines.append(f"    median difference CI: n/a ({b['note']})")
            else:
                lines.append(f"    median difference = {b['estimate']:+.4f} ms, "
                             f"95% {b['method']} CI [{b['ci_low']:+.4f}, {b['ci_high']:+.4f}]")
                if b["note"]:
                    lines.append(f"      {b['note']}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example")
    parser.add_argument("--json")
    parser.add_argument("--n-boot", type=int, default=N_BOOTSTRAP)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    results = analyse(bundle, n_boot=args.n_boot, seed=args.seed)
    print(format_text(results))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
