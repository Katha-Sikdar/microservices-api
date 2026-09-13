#!/usr/bin/env python3
"""fig_elbow.py -- latency against arrival rate, with both queueing fits.

THE PAPER'S MISSING ANCHOR FIGURE. Everything else in the manuscript refers to a
saturation point that was never plotted: the elbow was asserted from closed-loop
runs that cannot produce one. This figure is the open-loop measurement it needed.

What is drawn, per scenario (S1, S3, S5):
  * measured points at each ramp step, with 95% CI error bars across repeated
    sweeps of the ramp
  * the fitted M/M/1 curve (dashed) and the fitted M/D/1 curve (solid)
  * the PSAO trigger rate, marked on the x-axis

No numbers are burned into the axes. The fitted mu, the RMSE and the elbow all
live in generated_macros.tex, so the caption cites them and they cannot drift
away from the figure.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import style
from analysis import elbow_fit, io as psao_io

SCENARIOS = ["S1", "S3", "S5"]


def build(bundle: psao_io.DataBundle, *, scenarios=None, rho_trigger=None,
          with_offset: bool = False):
    scenarios = scenarios or SCENARIOS
    ramp = bundle.require("openloop_ramp")
    rho_trigger = rho_trigger if rho_trigger is not None else elbow_fit.DEFAULT_RHO_TRIGGER
    suffix = "_offset" if with_offset else ""

    fig, ax = style.new_figure(width=style.DOUBLE_WIDTH * 0.62, height=3.4)
    present = [s for s in scenarios if s in set(ramp["scenario"].dropna())]

    for scenario in present:
        colour = style.scenario_color(scenario)
        frame = ramp[ramp["scenario"] == scenario]

        # Repeated sweeps of the ramp appear as several rows per target rate.
        # Aggregate them into a mean with a 95% CI; a single sweep gets no error
        # bar rather than a zero-width one, which would imply precision we do
        # not have.
        grouped = frame.groupby("target_rps", dropna=True)
        x, y, err = [], [], []
        for _target, rows in grouped:
            rates = rows["achieved_rps"].dropna().to_numpy(float)
            latencies = rows["latency_mean_ms"].dropna().to_numpy(float)
            if len(rates) == 0 or len(latencies) == 0:
                continue
            x.append(float(np.mean(rates)))
            y.append(float(np.mean(latencies)))
            half = style.ci95_halfwidth(latencies)
            err.append(np.nan if half is None else half)

        order = np.argsort(x)
        x = np.asarray(x)[order]
        y = np.asarray(y)[order]
        err = np.asarray(err)[order]

        ax.errorbar(x, y, yerr=np.where(np.isnan(err), 0.0, err),
                    fmt="o", markersize=2.8, color=colour,
                    ecolor=colour, elinewidth=0.8, capsize=2.0,
                    linestyle="none", zorder=3,
                    label=style.scenario_label(scenario))

        fitted = elbow_fit.fit_scenario(ramp, scenario, rho_trigger=rho_trigger)
        grid = np.linspace(x.min(), x.max(), 500)
        for model in ("mm1", "md1"):
            info = fitted["fits"].get(model + suffix)
            if not info or info["mu_rps"] is None:
                continue
            result = elbow_fit.FitResult(**{k: v for k, v in info.items()})
            curve = result.predict_ms(grid)
            visible = np.isfinite(curve)
            ax.plot(grid[visible], curve[visible], color=colour,
                    linestyle=style.MODEL_STYLES[model]["linestyle"],
                    linewidth=style.MODEL_STYLES[model]["linewidth"],
                    alpha=0.85, zorder=2)

        # PSAO trigger: the rate at which rho reaches the configured threshold
        # under the M/D/1 fit. Marked only when it falls inside the measured
        # range -- marking an extrapolated trigger would assert a measurement
        # the ramp does not contain.
        trigger = fitted["psao_trigger"].get("md1")
        if trigger and trigger["within_measured_range"]:
            ax.axvline(trigger["lambda_rps"], color=colour, linestyle=":",
                       linewidth=1.0, alpha=0.75, zorder=1)

    ax.set_xlabel("Offered arrival rate λ (requests/s)")
    ax.set_ylabel("Mean response time (ms)")
    ax.set_ylim(bottom=0)
    ax.margins(x=0.02)

    from matplotlib.lines import Line2D
    handles, labels = ax.get_legend_handles_labels()
    handles += [
        Line2D([0], [0], color="#666666", **{k: v for k, v in style.MODEL_STYLES["mm1"].items()
                                             if k != "label"}),
        Line2D([0], [0], color="#666666", **{k: v for k, v in style.MODEL_STYLES["md1"].items()
                                             if k != "label"}),
        Line2D([0], [0], color="#666666", linestyle=":", linewidth=1.0),
    ]
    offset_note = " + fixed offset" if with_offset else ""
    labels += [style.MODEL_STYLES["mm1"]["label"] + offset_note,
               style.MODEL_STYLES["md1"]["label"] + offset_note,
               f"PSAO trigger (ρ = {rho_trigger:g})"]
    # Below the axes, not inside them: the scenario descriptions are long, and an
    # in-axes legend at this aspect ratio covers the low-load half of the curve
    # -- which is the half a reader checks the fit against.
    ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.22),
              ncol=2, frameon=False)
    style.add_data_provenance(fig, bundle.data_dir)
    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example")
    parser.add_argument("--out", default="figures/output/fig_elbow.pdf")
    parser.add_argument("--rho-trigger", type=float, default=elbow_fit.DEFAULT_RHO_TRIGGER)
    parser.add_argument("--with-offset", action="store_true",
                        help="plot the W(lambda) + W0 variants instead of the "
                             "manuscript's offset-free model form. The offset "
                             "absorbs ingress and network time; elbow_fit.py "
                             "reports the RMSE of both so the choice is visible.")
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    fig = build(bundle, rho_trigger=args.rho_trigger, with_offset=args.with_offset)
    style.finalize(fig, args.out, bundle.data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
