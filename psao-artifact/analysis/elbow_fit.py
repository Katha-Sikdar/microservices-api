"""elbow_fit.py -- fit queueing models to the open-loop ramp and locate the elbow.

The manuscript models the service as a single-server queue and reports a fitted
service rate, but reports no goodness of fit at all, and fits only M/M/1. Two
problems, both addressed here.

M/D/1 IS THE MORE DEFENSIBLE MODEL
----------------------------------
Token verification is a fixed-cost operation: the same signature check over a
payload of the same size, every request. Its service time is close to
deterministic, not exponential. M/D/1 is the model for deterministic service,
and it predicts exactly half the queueing delay of M/M/1 at the same
utilisation:

    M/M/1   W = 1 / (mu - lambda)
    M/D/1   W = 1/mu + rho / (2 * mu * (1 - rho)),   rho = lambda/mu

Fitting only M/M/1 therefore risks attributing to the security layers a delay
the model's own variance assumption produced. Both are fitted here, and both are
reported with RMSE and MAPE so a reader can see which one the data supports
rather than taking the choice on trust.

WHICH POINTS ARE FITTED
-----------------------
Only steps where the load generator actually delivered the requested rate
(achieved_rps >= `keep_fraction` * target_rps, default 0.95). Past saturation the
generator falls behind, so the nominal lambda is not the offered lambda, and
fitting those points fits the load generator rather than the service. The
excluded points are reported, never silently dropped.

THE FIXED-OFFSET VARIANT
------------------------
Measured HTTP latency includes ingress, mesh and network time that no
single-server model accounts for. Fitting W(lambda) with no offset forces mu to
absorb that constant, biasing mu downwards. So each model is fitted twice: once
exactly as written above (the manuscript's form, reported as primary), and once
as W(lambda) + W0 with W0 >= 0 free. If the offset variant fits far better, the
paper needs to say so -- that difference IS the discrepancy between the fitted
and the CPU-derived service rate that the artifact set out to explain.

THE ELBOW
---------
Located as the point of maximum curvature of the fitted curve, computed after
normalising both axes to [0, 1] over the measured range. The normalisation is
not cosmetic: curvature has units, so without it the "knee" would move if you
reported latency in microseconds instead of milliseconds. Normalising over the
measured range also means the elbow is reported only where there is data -- if
the maximum curvature lands on the edge of the ramp, the elbow is reported as
UNRESOLVED and the correct response is a longer ramp, not an extrapolation.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from . import io as psao_io

# rho at which PSAO offloads. Mirrors control.thresholds.rho_trigger in
# controller/config.yaml; it is a policy parameter, not a measurement, and is
# passed in explicitly by run_all.py so the two cannot drift apart unnoticed.
DEFAULT_RHO_TRIGGER = 0.70

GRID_POINTS = 4000


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def mm1_wait_s(lam: np.ndarray, mu: float) -> np.ndarray:
    """M/M/1 mean response time, seconds. Undefined at lambda >= mu."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(lam < mu, 1.0 / (mu - lam), np.inf)


def md1_wait_s(lam: np.ndarray, mu: float) -> np.ndarray:
    """M/D/1 mean response time, seconds. Undefined at lambda >= mu."""
    with np.errstate(divide="ignore", invalid="ignore"):
        rho = lam / mu
        queueing = rho / (2.0 * mu * (1.0 - rho))
        return np.where(rho < 1.0, 1.0 / mu + queueing, np.inf)


MODELS = {"mm1": mm1_wait_s, "md1": md1_wait_s}
MODEL_LABELS = {"mm1": "M/M/1", "md1": "M/D/1"}


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------

@dataclass
class FitResult:
    model: str
    with_offset: bool
    mu_rps: Optional[float]
    offset_ms: Optional[float]
    rmse_ms: Optional[float]
    mape_percent: Optional[float]
    n_points: int
    converged: bool
    note: str = ""

    def predict_ms(self, lam) -> np.ndarray:
        """Fitted latency in ms at the given arrival rates."""
        lam = np.atleast_1d(np.asarray(lam, dtype=float))
        if self.mu_rps is None:
            return np.full_like(lam, np.nan)
        base = MODELS[self.model](lam, self.mu_rps) * 1000.0
        return base + (self.offset_ms or 0.0)


def fit_model(lam: np.ndarray, latency_ms: np.ndarray, model: str,
              with_offset: bool) -> FitResult:
    """Least-squares fit of one model to (lambda, latency) in rps and ms."""
    n = len(lam)
    if n < 3:
        return FitResult(model, with_offset, None, None, None, None, n, False,
                         "fewer than 3 usable points; not fitted")

    lam_max = float(np.max(lam))
    latency_s = latency_ms / 1000.0
    wait = MODELS[model]

    # mu must exceed the largest offered rate or the model is at or past its own
    # singularity on a point we are asking it to reproduce. The 1e-6 keeps the
    # bound strictly open.
    mu_lower = lam_max * (1.0 + 1e-6)

    def residuals(params):
        mu = params[0]
        predicted = wait(lam, mu)
        if with_offset:
            predicted = predicted + params[1]
        # Guard against the optimiser stepping onto the pole.
        predicted = np.where(np.isfinite(predicted), predicted, 1e6)
        return predicted - latency_s

    # Start well clear of the singularity; a start too close to mu_lower makes
    # the first Jacobian enormous and trf takes a long time to recover.
    mu0 = lam_max * 1.5
    if with_offset:
        x0 = [mu0, max(0.0, float(np.min(latency_s)) * 0.5)]
        bounds = ([mu_lower, 0.0], [np.inf, np.inf])
    else:
        x0 = [mu0]
        bounds = ([mu_lower], [np.inf])

    try:
        solution = least_squares(residuals, x0=x0, bounds=bounds, method="trf",
                                 max_nfev=20000)
    except Exception as exc:  # noqa: BLE001
        return FitResult(model, with_offset, None, None, None, None, n, False,
                         f"least_squares failed: {exc}")

    mu = float(solution.x[0])
    offset_ms = float(solution.x[1] * 1000.0) if with_offset else 0.0

    predicted_s = wait(lam, mu) + (offset_ms / 1000.0)
    if not np.all(np.isfinite(predicted_s)):
        return FitResult(model, with_offset, mu, offset_ms, None, None, n, False,
                         "fitted curve is not finite at every measured point")

    residual_ms = (predicted_s - latency_s) * 1000.0
    rmse = float(np.sqrt(np.mean(residual_ms ** 2)))
    with np.errstate(divide="ignore", invalid="ignore"):
        mape = float(np.mean(np.abs(residual_ms / latency_ms)) * 100.0)

    note = ""
    if mu <= mu_lower * (1.0 + 1e-9):
        # The optimiser wanted a mu below the highest offered rate and was held
        # at the bound. The fit is not trustworthy and the caller must be told.
        note = ("fitted mu pinned at the lower bound (max offered rate); the ramp "
                "reached or passed saturation and mu is not identified")
    return FitResult(model, with_offset, mu, offset_ms, rmse, mape, n,
                     bool(solution.success), note)


# ---------------------------------------------------------------------------
# Elbow
# ---------------------------------------------------------------------------

@dataclass
class ElbowResult:
    lambda_rps: Optional[float]
    latency_ms: Optional[float]
    rho: Optional[float]
    resolved: bool
    note: str


def find_elbow(fit: FitResult, lam_min: float, lam_max: float) -> ElbowResult:
    """Maximum-curvature point of the fitted curve, on normalised axes."""
    if fit.mu_rps is None:
        return ElbowResult(None, None, None, False, "no fit")

    grid = np.linspace(lam_min, lam_max, GRID_POINTS)
    curve = fit.predict_ms(grid)
    finite = np.isfinite(curve)
    if finite.sum() < 5:
        return ElbowResult(None, None, None, False,
                           "fitted curve is not finite across the measured range")
    grid, curve = grid[finite], curve[finite]

    # Normalise both axes to [0, 1]. Curvature is not scale-invariant, so without
    # this the located knee would depend on the units latency is reported in.
    x_span = grid[-1] - grid[0]
    y_span = float(np.max(curve) - np.min(curve))
    if x_span <= 0 or y_span <= 0:
        return ElbowResult(None, None, None, False, "degenerate range; no knee")
    x = (grid - grid[0]) / x_span
    y = (curve - np.min(curve)) / y_span

    d1 = np.gradient(y, x)
    d2 = np.gradient(d1, x)
    curvature = np.abs(d2) / np.power(1.0 + d1 ** 2, 1.5)

    index = int(np.argmax(curvature))
    # A knee on the boundary means the maximum curvature inside the measured
    # window is at its edge, i.e. the ramp did not bracket the knee. Reporting a
    # boundary point as "the elbow" would be an extrapolation dressed as a
    # measurement.
    edge = max(2, GRID_POINTS // 100)
    if index < edge or index > len(curvature) - edge - 1:
        return ElbowResult(
            float(grid[index]), float(curve[index]),
            float(grid[index] / fit.mu_rps), False,
            "maximum curvature lies on the edge of the measured range: the ramp "
            "did not bracket the elbow. Extend the ramp rather than extrapolating.")

    lam_elbow = float(grid[index])
    return ElbowResult(lam_elbow, float(curve[index]), lam_elbow / fit.mu_rps, True, "")


# ---------------------------------------------------------------------------
# CPU at the elbow
# ---------------------------------------------------------------------------

def cpu_at_rate(frame: pd.DataFrame, rate: Optional[float]) -> dict:
    """CPU measured at an arrival rate, by linear interpolation between the two
    bracketing measured steps.

    This is the quantity the paper currently derives rather than measures. It is
    still an interpolation between two measurements, which is stated in the
    result, and it is NaN when the CPU columns are empty or the rate falls
    outside the measured range -- interpolating off the end would be invention.
    """
    result = {
        "app_millicores": math.nan,
        "sidecar_millicores": math.nan,
        "total_millicores": math.nan,
        "bracket_rps": None,
        "method": "not available",
    }
    if rate is None or not np.isfinite(rate):
        result["method"] = "no elbow to evaluate at"
        return result

    usable = frame.dropna(subset=["achieved_rps"]).sort_values("achieved_rps")
    have_app = usable["cpu_app_millicores"].notna()
    if not have_app.any():
        result["method"] = "cpu_app_millicores is empty: CPU was not measured on this run"
        return result

    usable = usable[have_app]
    x = usable["achieved_rps"].to_numpy(dtype=float)
    if rate < x.min() or rate > x.max():
        result["method"] = (f"elbow at {rate:.1f} rps lies outside the measured range "
                            f"[{x.min():.1f}, {x.max():.1f}] rps; not extrapolated")
        return result

    lower = x[x <= rate].max()
    upper = x[x >= rate].min()
    app = float(np.interp(rate, x, usable["cpu_app_millicores"].to_numpy(dtype=float)))
    sidecar = math.nan
    if usable["cpu_sidecar_millicores"].notna().any():
        side_frame = usable[usable["cpu_sidecar_millicores"].notna()]
        sidecar = float(np.interp(
            rate, side_frame["achieved_rps"].to_numpy(dtype=float),
            side_frame["cpu_sidecar_millicores"].to_numpy(dtype=float)))

    result.update({
        "app_millicores": app,
        "sidecar_millicores": sidecar,
        "total_millicores": app + (0.0 if math.isnan(sidecar) else sidecar),
        "bracket_rps": [float(lower), float(upper)],
        "method": ("linear interpolation between measured steps at "
                   f"{lower:.1f} and {upper:.1f} rps"),
    })
    return result


# ---------------------------------------------------------------------------
# Per-scenario driver
# ---------------------------------------------------------------------------

def fit_scenario(ramp: pd.DataFrame, scenario: str, *,
                 keep_fraction: float = 0.95,
                 rho_trigger: float = DEFAULT_RHO_TRIGGER) -> dict:
    frame = ramp[ramp["scenario"] == scenario].copy()
    usable = frame.dropna(subset=["achieved_rps", "latency_mean_ms"])
    delivered = usable["achieved_rps"] >= keep_fraction * usable["target_rps"]
    fitted_points = usable[delivered]
    excluded = usable[~delivered]

    result = {
        "scenario": scenario,
        "description": psao_io.SCENARIO_DESCRIPTIONS.get(scenario, ""),
        "n_steps": int(len(frame)),
        "n_fitted": int(len(fitted_points)),
        "n_excluded_underdelivered": int(len(excluded)),
        "excluded_target_rps": [float(v) for v in excluded["target_rps"]],
        "keep_fraction": keep_fraction,
        "fits": {},
        "elbow": {},
        "psao_trigger": {},
    }
    if len(fitted_points) < 3:
        result["note"] = (f"only {len(fitted_points)} usable steps; a queueing fit "
                          f"needs at least 3. Not fitted.")
        return result

    lam = fitted_points["achieved_rps"].to_numpy(dtype=float)
    latency = fitted_points["latency_mean_ms"].to_numpy(dtype=float)

    for model in ("mm1", "md1"):
        for with_offset in (False, True):
            fit = fit_model(lam, latency, model, with_offset)
            key = model + ("_offset" if with_offset else "")
            result["fits"][key] = asdict(fit)
            # The primary fits (no offset) are the manuscript's own model form,
            # so those are the ones the elbow and the trigger are derived from.
            if not with_offset:
                elbow = find_elbow(fit, float(lam.min()), float(lam.max()))
                result["elbow"][model] = asdict(elbow)
                result["elbow"][model]["cpu"] = cpu_at_rate(frame, elbow.lambda_rps)
                if fit.mu_rps is not None:
                    trigger_rate = rho_trigger * fit.mu_rps
                    result["psao_trigger"][model] = {
                        "rho_trigger": rho_trigger,
                        "lambda_rps": trigger_rate,
                        "predicted_latency_ms": float(fit.predict_ms(trigger_rate)[0]),
                        "within_measured_range": bool(lam.min() <= trigger_rate <= lam.max()),
                    }

    best = min(
        (k for k, v in result["fits"].items() if v["rmse_ms"] is not None),
        key=lambda k: result["fits"][k]["rmse_ms"], default=None)
    result["best_fit_by_rmse"] = best
    return result


def analyse(bundle: psao_io.DataBundle, *, keep_fraction: float = 0.95,
            rho_trigger: float = DEFAULT_RHO_TRIGGER) -> dict:
    ramp = bundle.openloop_ramp
    if ramp is None or ramp.empty:
        return {"available": False,
                "reason": "openloop_ramp.csv is absent; run experiments/run_openloop_ramp.sh"}
    out = {"available": True, "synthetic": bundle.synthetic, "scenarios": {}}
    for scenario in psao_io.scenarios_present(ramp):
        out["scenarios"][scenario] = fit_scenario(
            ramp, scenario, keep_fraction=keep_fraction, rho_trigger=rho_trigger)
    return out


def format_text(results: dict) -> str:
    if not results.get("available"):
        return f"ELBOW FIT: unavailable -- {results.get('reason')}\n"
    lines = ["ELBOW FIT (open-loop ramp)", "=" * 78]
    if results.get("synthetic"):
        lines.append("*** SYNTHETIC EXAMPLE DATA -- these numbers are not measurements ***")
    for scenario, r in results["scenarios"].items():
        lines.append("")
        lines.append(f"{scenario}  {r['description']}")
        lines.append(f"  steps: {r['n_steps']} total, {r['n_fitted']} fitted, "
                     f"{r['n_excluded_underdelivered']} excluded for under-delivery "
                     f"(achieved < {r['keep_fraction']:.0%} of target)")
        if "note" in r:
            lines.append(f"  {r['note']}")
            continue
        lines.append(f"  {'model':<12} {'mu (rps)':>10} {'offset(ms)':>11} "
                     f"{'RMSE(ms)':>9} {'MAPE(%)':>8}")
        for key, fit in r["fits"].items():
            label = MODEL_LABELS[fit["model"]] + (" + offset" if fit["with_offset"] else "")
            mu = "n/a" if fit["mu_rps"] is None else f"{fit['mu_rps']:.1f}"
            off = "-" if not fit["with_offset"] else f"{fit['offset_ms']:.3f}"
            rmse = "n/a" if fit["rmse_ms"] is None else f"{fit['rmse_ms']:.3f}"
            mape = "n/a" if fit["mape_percent"] is None else f"{fit['mape_percent']:.2f}"
            lines.append(f"  {label:<12} {mu:>10} {off:>11} {rmse:>9} {mape:>8}")
            if fit["note"]:
                lines.append(f"      note: {fit['note']}")
        lines.append(f"  best fit by RMSE: {r.get('best_fit_by_rmse')}")
        for model, elbow in r["elbow"].items():
            label = MODEL_LABELS[model]
            if elbow["resolved"]:
                lines.append(f"  elbow ({label}): {elbow['lambda_rps']:.1f} rps, "
                             f"{elbow['latency_ms']:.2f} ms, rho={elbow['rho']:.3f}")
            else:
                lines.append(f"  elbow ({label}): UNRESOLVED -- {elbow['note']}")
            cpu = elbow["cpu"]
            if math.isnan(cpu["app_millicores"]):
                lines.append(f"    CPU at elbow: not available -- {cpu['method']}")
            else:
                sidecar = ("n/a" if math.isnan(cpu["sidecar_millicores"])
                           else f"{cpu['sidecar_millicores']:.1f}m")
                lines.append(f"    CPU at elbow: app={cpu['app_millicores']:.1f}m "
                             f"sidecar={sidecar} ({cpu['method']})")
        for model, trigger in r["psao_trigger"].items():
            flag = "" if trigger["within_measured_range"] else "  [OUTSIDE MEASURED RANGE]"
            lines.append(f"  PSAO trigger ({MODEL_LABELS[model]}, rho="
                         f"{trigger['rho_trigger']:g}): {trigger['lambda_rps']:.1f} rps"
                         f"{flag}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example", help="data directory")
    parser.add_argument("--json", help="write results as JSON to this path")
    parser.add_argument("--keep-fraction", type=float, default=0.95)
    parser.add_argument("--rho-trigger", type=float, default=DEFAULT_RHO_TRIGGER)
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    results = analyse(bundle, keep_fraction=args.keep_fraction,
                      rho_trigger=args.rho_trigger)
    print(format_text(results))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
