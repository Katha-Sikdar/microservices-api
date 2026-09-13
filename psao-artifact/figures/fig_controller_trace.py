#!/usr/bin/env python3
"""fig_controller_trace.py -- PSAO acting, as a time series.

This is the figure that answers "does the policy actually work?", which the
pseudocode in the manuscript could not. Three stacked panels sharing a time axis:

  offered load λ   what the controller is reacting to
  mean latency     what it is defending
  utilisation ρ    what it decides on, against the trigger and revert bands

The instant of each actuation is marked, and the interval during which
verification ran in the sidecar is shaded. The point a reader should be able to
check by eye is that latency flattens after the offload while λ keeps climbing;
if it does not, PSAO did not work on this run and the figure says so rather than
hiding it.

The hysteresis band is drawn explicitly, because "why does it not oscillate?" is
the first question this figure invites.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import yaml

import style
from analysis import io as psao_io

ARTIFACT_ROOT = Path(__file__).resolve().parent.parent
OFFLOAD_COLOR = style.SCENARIO_COLORS["S7"]
REVERT_COLOR = style.SCENARIO_COLORS["S5"]


def read_thresholds(config_path: Path) -> dict:
    """Read the trigger and revert thresholds actually in force.

    Taken from the controller's config rather than hard-coded here, so the bands
    drawn on the figure are the bands the run used.
    """
    try:
        config = yaml.safe_load(config_path.read_text())
        thresholds = config["control"]["thresholds"]
        return {"rho_trigger": float(thresholds["rho_trigger"]),
                "rho_revert": float(thresholds["rho_revert"])}
    except Exception:  # noqa: BLE001
        return {}


def build(bundle: psao_io.DataBundle, *, config_path: Path | None = None):
    trace = bundle.require("controller_trace").sort_values("t_rel_s")
    thresholds = read_thresholds(config_path or (ARTIFACT_ROOT / "controller" / "config.yaml"))

    fig, axes = style.new_figure(width=style.DOUBLE_WIDTH * 0.62, height=4.6,
                                 nrows=3, sharex=True,
                                 gridspec_kw={"height_ratios": [1, 1, 1.1],
                                              "hspace": 0.18})
    t = trace["t_rel_s"].to_numpy(float)

    offloads = trace[trace["decision"] == "offload"]
    reverts = trace[trace["decision"] == "revert"]

    # Shade every interval spent enforcing in the sidecar. Built from the mode
    # column rather than from the decisions, so a run that ended while still
    # offloaded is shaded to the end of the trace.
    sidecar = (trace["mode"] == "sidecar").to_numpy()
    spans = []
    start = None
    for index, flag in enumerate(sidecar):
        if flag and start is None:
            start = t[index]
        elif not flag and start is not None:
            spans.append((start, t[index]))
            start = None
    if start is not None:
        spans.append((start, t[-1]))

    panels = [
        (axes[0], "lambda_rps", "Offered load λ\n(requests/s)", style.SCENARIO_COLORS["S3"]),
        (axes[1], "latency_mean_ms", "Mean latency\n(ms)", style.SCENARIO_COLORS["S5"]),
        (axes[2], "rho", "Utilisation ρ", style.SCENARIO_COLORS["S7"]),
    ]
    for ax, column, label, colour in panels:
        values = trace[column].replace([np.inf, -np.inf], np.nan).to_numpy(float)
        ax.plot(t, values, color=colour, linewidth=1.0)
        ax.set_ylabel(label)
        for span_start, span_end in spans:
            ax.axvspan(span_start, span_end, color=OFFLOAD_COLOR, alpha=0.08,
                       linewidth=0, zorder=0)
        for _, row in offloads.iterrows():
            ax.axvline(row["t_rel_s"], color=OFFLOAD_COLOR, linewidth=1.1,
                       linestyle="-", alpha=0.9, zorder=4)
        for _, row in reverts.iterrows():
            ax.axvline(row["t_rel_s"], color=REVERT_COLOR, linewidth=1.1,
                       linestyle="--", alpha=0.9, zorder=4)

    # The hysteresis band, on the rho panel. Without it the figure cannot answer
    # why the controller does not chatter across a single threshold.
    if thresholds:
        rho_ax = axes[2]
        rho_ax.axhline(thresholds["rho_trigger"], color="#444444",
                       linewidth=0.8, linestyle=":")
        rho_ax.axhline(thresholds["rho_revert"], color="#444444",
                       linewidth=0.8, linestyle=":")
        rho_ax.axhspan(thresholds["rho_revert"], thresholds["rho_trigger"],
                       color="#444444", alpha=0.06, linewidth=0, zorder=0)

    axes[2].set_xlabel("Time since start of run (s)")
    axes[2].set_ylim(bottom=0)
    axes[0].set_ylim(bottom=0)
    axes[1].set_ylim(bottom=0)

    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [
        Line2D([0], [0], color=OFFLOAD_COLOR, linewidth=1.1, label="offload actuated"),
        Line2D([0], [0], color=REVERT_COLOR, linewidth=1.1, linestyle="--",
               label="revert actuated"),
        Patch(facecolor=OFFLOAD_COLOR, alpha=0.18, label="verification in the sidecar"),
    ]
    if thresholds:
        handles.append(Patch(facecolor="#444444", alpha=0.12,
                             label=f"hysteresis band (ρ {thresholds['rho_revert']:g}–"
                                   f"{thresholds['rho_trigger']:g})"))
    axes[0].legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 1.55),
                   ncol=2, frameon=False)
    style.add_data_provenance(fig, bundle.data_dir)
    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example")
    parser.add_argument("--out", default="figures/output/fig_controller_trace.pdf")
    parser.add_argument("--config", default=str(ARTIFACT_ROOT / "controller" / "config.yaml"))
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    fig = build(bundle, config_path=Path(args.config))
    # tight=False: the shared-axis gridspec is already spaced by hspace, and the
    # legend sits outside the axes where savefig's tight bbox picks it up.
    style.finalize(fig, args.out, bundle.data_dir, tight=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
