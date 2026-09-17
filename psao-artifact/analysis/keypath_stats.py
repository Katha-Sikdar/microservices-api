#!/usr/bin/env python3
"""keypath_stats.py -- aggregate the key-path mechanism runs ACROSS invocations.

The unit of measurement here is one process invocation, not one call. Each
invocation contributes its own median of N calls; the reported figure is the
median of those per-invocation medians, and the interval around it is a
percentile bootstrap over invocations. An interval computed over the calls
inside a single process would describe only that process's steady state and
would be far too narrow -- it cannot see the between-process variation that
makes a benchmark hard to reproduce.

Differences between conditions are bootstrapped PAIRED BY ROUND, because the
runner cycles through every condition within each round: two conditions from the
same round saw the same machine state, so pairing removes drift that would
otherwise widen both intervals.

Usage:
  python3 -m analysis.keypath_stats --run data/runs/<...>-keypath-mechanism
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

BOOT = 10000
SEED = 20260917


def boot_ci(values: np.ndarray, rng, stat=np.median, alpha=0.05):
    """Percentile bootstrap CI for `stat` over a sample of invocations."""
    values = np.asarray(values, dtype=float)
    if values.size < 2:
        return (float("nan"), float("nan"))
    idx = rng.integers(0, values.size, size=(BOOT, values.size))
    draws = stat(values[idx], axis=1)
    return (float(np.percentile(draws, 100 * alpha / 2)),
            float(np.percentile(draws, 100 * (1 - alpha / 2))))


def paired_diff(df: pd.DataFrame, a: str, b: str, rng):
    """Median of (a - b) across rounds present in both, with a paired bootstrap."""
    wide = df.pivot_table(index="invocation", columns="condition",
                          values="median_us", aggfunc="median")
    if a not in wide.columns or b not in wide.columns:
        return None
    pair = wide[[a, b]].dropna()
    if pair.empty:
        return None
    d = (pair[a] - pair[b]).to_numpy()
    lo, hi = boot_ci(d, rng)
    return {"a": a, "b": b, "n_rounds": int(pair.shape[0]),
            "median_diff_us": float(np.median(d)), "ci95": [lo, hi]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, help="a *-keypath-mechanism run directory")
    ap.add_argument("--out", default=None, help="defaults to <run>/keypath_stats.json")
    args = ap.parse_args(argv)

    run = Path(args.run)
    csv = run / "keypath_mechanism.csv"
    if not csv.exists():
        raise SystemExit(f"no keypath_mechanism.csv in {run}")
    df = pd.read_csv(csv)
    rng = np.random.default_rng(SEED)

    # --- per-condition summary ------------------------------------------------
    conditions = {}
    for cond, grp in df.groupby("condition"):
        med = grp["median_us"].to_numpy(dtype=float)
        lo, hi = boot_ci(med, rng)
        conditions[cond] = {
            "n_invocations": int(grp.shape[0]),
            "calls_per_invocation": int(grp["n"].iloc[0]),
            "median_of_medians_us": float(np.median(med)),
            "ci95": [lo, hi],
            "min_invocation_median_us": float(med.min()),
            "max_invocation_median_us": float(med.max()),
            # Spread across processes. This is the number a single-process
            # benchmark cannot report and the one that says how reproducible
            # the condition actually is.
            "between_invocation_cv_pct": float(100 * med.std(ddof=1) / med.mean())
            if med.size > 1 else float("nan"),
            "median_p99_us": float(grp["p99_us"].median()),
            "median_timer_overhead_us": float(grp["timer_overhead_us"].median()),
        }

    # --- the contrasts the paper makes ---------------------------------------
    contrasts = {
        # What a service pays for passing a string instead of a KeyObject.
        "string_key_penalty_hs256": paired_diff(df, "jwt_hs_string", "jwt_hs_preparsed", rng),
        # What the safe patch removes, leaving the caller's code unchanged.
        "safe_patch_saving_hs256": paired_diff(df, "jwt_hs_string", "jwt_hs_string_safe", rng),
        # Residual after the patch: the conversion the patch still performs.
        "safe_patch_residual": paired_diff(df, "jwt_hs_string_safe", "jwt_hs_preparsed", rng),
        # RS256's string path pays a probe that SUCCEEDS, so its cost is real
        # parsing rather than a discarded failure.
        "string_key_penalty_rs256": paired_diff(df, "jwt_rs_pem_string", "jwt_rs_preparsed", rng),
    }

    # --- is the penalty accounted for by the failed probe? --------------------
    # Prediction: jwt_hs_string - jwt_hs_preparsed  ~=  probe_throws + create_secret_key
    wide = df.pivot_table(index="invocation", columns="condition",
                          values="median_us", aggfunc="median")
    need = ["jwt_hs_string", "jwt_hs_preparsed", "probe_throws", "create_secret_key"]
    decomposition = None
    if all(c in wide.columns for c in need):
        pair = wide[need].dropna()
        observed = (pair["jwt_hs_string"] - pair["jwt_hs_preparsed"]).to_numpy()
        predicted = (pair["probe_throws"] + pair["create_secret_key"]).to_numpy()
        resid = observed - predicted
        lo_o, hi_o = boot_ci(observed, rng)
        lo_p, hi_p = boot_ci(predicted, rng)
        lo_r, hi_r = boot_ci(resid, rng)
        decomposition = {
            "n_rounds": int(pair.shape[0]),
            "observed_penalty_us": {"median": float(np.median(observed)), "ci95": [lo_o, hi_o]},
            "predicted_from_parts_us": {"median": float(np.median(predicted)), "ci95": [lo_p, hi_p]},
            "residual_us": {"median": float(np.median(resid)), "ci95": [lo_r, hi_r]},
            "explained_fraction": float(np.median(predicted) / np.median(observed))
            if np.median(observed) else float("nan"),
            "_note": "Residual is what the failed probe plus the key conversion do NOT "
                     "account for: jsonwebtoken's own type and claim checks on the "
                     "non-KeyObject path. A residual whose CI excludes zero means the "
                     "two measured parts are not the whole story.",
        }

    result = {
        "run_dir": str(run),
        "source_csv": str(csv),
        "bootstrap_resamples": BOOT,
        "bootstrap_seed": SEED,
        "unit_of_measurement": "one process invocation; each contributes its median of N calls",
        "conditions": conditions,
        "contrasts": contrasts,
        "decomposition": decomposition,
    }

    out = Path(args.out) if args.out else run / "keypath_stats.json"
    out.write_text(json.dumps(result, indent=2) + "\n")

    # --- readable summary -----------------------------------------------------
    lines = [f"key-path mechanism — {run.name}", ""]
    lines.append(f"{'condition':<22} {'invocs':>6} {'median us':>10} {'95% CI':>22} {'CV%':>6}")
    for cond in sorted(conditions, key=lambda c: -conditions[c]["median_of_medians_us"]):
        c = conditions[cond]
        lines.append(f"{cond:<22} {c['n_invocations']:>6} {c['median_of_medians_us']:>10.3f} "
                     f"{'[%.3f, %.3f]' % tuple(c['ci95']):>22} {c['between_invocation_cv_pct']:>6.1f}")
    lines.append("")
    for name, c in contrasts.items():
        if c:
            lines.append(f"{name}: {c['a']} - {c['b']} = {c['median_diff_us']:.3f} us "
                         f"[{c['ci95'][0]:.3f}, {c['ci95'][1]:.3f}] over {c['n_rounds']} rounds")
    if decomposition:
        d = decomposition
        lines += ["", "decomposition of the HS256 string-key penalty:",
                  f"  observed            {d['observed_penalty_us']['median']:.3f} us "
                  f"[{d['observed_penalty_us']['ci95'][0]:.3f}, {d['observed_penalty_us']['ci95'][1]:.3f}]",
                  f"  probe + conversion  {d['predicted_from_parts_us']['median']:.3f} us "
                  f"[{d['predicted_from_parts_us']['ci95'][0]:.3f}, {d['predicted_from_parts_us']['ci95'][1]:.3f}]",
                  f"  residual            {d['residual_us']['median']:.3f} us "
                  f"[{d['residual_us']['ci95'][0]:.3f}, {d['residual_us']['ci95'][1]:.3f}]",
                  f"  explained           {100 * d['explained_fraction']:.1f}%"]
    text = "\n".join(lines) + "\n"
    (run / "keypath_stats.txt").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
