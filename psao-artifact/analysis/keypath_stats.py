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
    # Runs predating the runtime matrix have no environment column; they are
    # all host runs. Pooling environments would average a 375 us probe with an
    # 18 us one and report neither.
    if "environment" not in df.columns:
        df["environment"] = "host"
    rng = np.random.default_rng(SEED)

    def analyse(sub: pd.DataFrame) -> dict:
        """Everything the single-environment analysis reported, for one environment."""
        conditions = {}
        for cond, grp in sub.groupby("condition"):
            med = grp["median_us"].to_numpy(dtype=float)
            lo, hi = boot_ci(med, rng)
            conditions[cond] = {
                "n_invocations": int(grp.shape[0]),
                "calls_per_invocation": int(grp["n"].iloc[0]),
                "median_of_medians_us": float(np.median(med)),
                "ci95": [lo, hi],
                "between_invocation_cv_pct": float(100 * med.std(ddof=1) / med.mean())
                if med.size > 1 else float("nan"),
                "median_p99_us": float(grp["p99_us"].median()),
                "median_timer_overhead_us": float(grp["timer_overhead_us"].median()),
            }
        contrasts = {
            "string_key_penalty_hs256": paired_diff(sub, "jwt_hs_string", "jwt_hs_preparsed", rng),
            "safe_patch_saving_hs256": paired_diff(sub, "jwt_hs_string", "jwt_hs_string_safe", rng),
            "safe_patch_residual": paired_diff(sub, "jwt_hs_string_safe", "jwt_hs_preparsed", rng),
            "string_key_penalty_rs256": paired_diff(sub, "jwt_rs_pem_string", "jwt_rs_preparsed", rng),
        }
        wide = sub.pivot_table(index="invocation", columns="condition",
                               values="median_us", aggfunc="median")
        need = ["jwt_hs_string", "jwt_hs_preparsed", "probe_throws", "create_secret_key"]
        decomposition = None
        if all(c in wide.columns for c in need):
            pair = wide[need].dropna()
            if not pair.empty:
                observed = (pair["jwt_hs_string"] - pair["jwt_hs_preparsed"]).to_numpy()
                predicted = (pair["probe_throws"] + pair["create_secret_key"]).to_numpy()
                resid = observed - predicted
                decomposition = {
                    "n_rounds": int(pair.shape[0]),
                    "observed_penalty_us": {"median": float(np.median(observed)),
                                            "ci95": list(boot_ci(observed, rng))},
                    "predicted_from_parts_us": {"median": float(np.median(predicted)),
                                                "ci95": list(boot_ci(predicted, rng))},
                    "residual_us": {"median": float(np.median(resid)),
                                    "ci95": list(boot_ci(resid, rng))},
                    "explained_fraction": float(np.median(predicted) / np.median(observed))
                    if np.median(observed) else float("nan"),
                }
        runtime = {}
        for col in ("node_version", "openssl_version", "platform"):
            if col in sub.columns:
                runtime[col] = sorted(set(sub[col].astype(str)))
        return {"runtime": runtime, "conditions": conditions,
                "contrasts": contrasts, "decomposition": decomposition}

    environments = {env: analyse(sub) for env, sub in df.groupby("environment")}

    # --- across environments --------------------------------------------------
    # The question the matrix exists to answer: what varies between runtimes, and
    # is it the whole call or only the failed probe? Ratios are taken against the
    # host, which is where the isolated microbenchmark in the manuscript was run.
    REF = "host" if "host" in environments else sorted(environments)[0]
    cross = {"reference": REF, "ratio_vs_reference": {}}
    ref_conds = environments[REF]["conditions"]
    for env, data in environments.items():
        if env == REF:
            continue
        row = {}
        for cond, c in data["conditions"].items():
            if cond in ref_conds and ref_conds[cond]["median_of_medians_us"] > 0:
                row[cond] = round(c["median_of_medians_us"]
                                  / ref_conds[cond]["median_of_medians_us"], 3)
        cross["ratio_vs_reference"][env] = row

    result = {
        "run_dir": str(run),
        "source_csv": str(csv),
        "bootstrap_resamples": BOOT,
        "bootstrap_seed": SEED,
        "unit_of_measurement": "one process invocation; each contributes its median of N calls",
        "environments": environments,
        "cross_environment": cross,
    }

    out = Path(args.out) if args.out else run / "keypath_stats.json"
    out.write_text(json.dumps(result, indent=2) + "\n")

    # --- readable summary -----------------------------------------------------
    lines = [f"key-path mechanism — {run.name}", ""]
    for env in sorted(environments):
        data = environments[env]
        rt = data["runtime"]
        tag = " | ".join(f"{k.split('_')[0]}={','.join(v)}" for k, v in rt.items())
        lines += [f"### {env}    {tag}", ""]
        lines.append(f"{'condition':<22} {'invocs':>6} {'median us':>11} {'95% CI':>24} {'CV%':>6}")
        for cond in sorted(data["conditions"],
                           key=lambda c: -data["conditions"][c]["median_of_medians_us"]):
            c = data["conditions"][cond]
            lines.append(f"{cond:<22} {c['n_invocations']:>6} {c['median_of_medians_us']:>11.3f} "
                         f"{'[%.3f, %.3f]' % tuple(c['ci95']):>24} "
                         f"{c['between_invocation_cv_pct']:>6.1f}")
        for name, c in data["contrasts"].items():
            if c:
                lines.append(f"  {name}: {c['median_diff_us']:.3f} us "
                             f"[{c['ci95'][0]:.3f}, {c['ci95'][1]:.3f}] over {c['n_rounds']} rounds")
        d = data["decomposition"]
        if d:
            lines.append(f"  decomposition: observed {d['observed_penalty_us']['median']:.3f}, "
                         f"probe+conversion {d['predicted_from_parts_us']['median']:.3f}, "
                         f"residual {d['residual_us']['median']:.3f} "
                         f"({100 * d['explained_fraction']:.1f}% explained)")
        lines.append("")
    if len(environments) > 1:
        lines += [f"### ratio vs {cross['reference']}", ""]
        conds = sorted({c for r in cross["ratio_vs_reference"].values() for c in r})
        lines.append(f"{'environment':<26}" + "".join(f"{c[:14]:>16}" for c in conds))
        for env, row in sorted(cross["ratio_vs_reference"].items()):
            lines.append(f"{env:<26}" + "".join(f"{row.get(c, float('nan')):>16.2f}" for c in conds))
        lines.append("")
    text = "\n".join(lines) + "\n"
    (run / "keypath_stats.txt").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
