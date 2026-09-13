#!/usr/bin/env python3
"""fig_latency_scenarios.py -- mean latency with confidence intervals, S1..S9.

The manuscript's headline comparison, done properly. Two things it adds:

  * A 95% CI across repetitions, so a reader can see immediately which
    differences the three runs actually support. Bars without intervals invited
    exactly the over-reading the reviewers objected to.
  * All nine scenarios on one axis, including the three alternatives to PSAO
    (S7 sidecar offload, S8 token cache, S9 cluster mode). Showing only S1..S5
    lets a reader assume the cheap alternatives were not tried.

Points with intervals rather than bars: a bar's area implies a ratio scale from
zero, and the interesting differences here are a couple of milliseconds on top
of a ~3 ms floor. The floor would dominate the ink and hide the effect.

No values are printed on the axes; they are in generated_macros.tex.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import style
from analysis import io as psao_io


def build(bundle: psao_io.DataBundle, *, window: str = "steady",
          metric: str = "latency_mean_ms"):
    scenarios = bundle.require("scenarios")
    frame = scenarios[scenarios["throughput_window"] == window]
    present = psao_io.scenarios_present(frame)

    fig, ax = style.new_figure(width=style.DOUBLE_WIDTH * 0.62, height=2.8)

    for index, scenario in enumerate(present):
        values = frame[frame["scenario"] == scenario][metric].dropna().to_numpy(float)
        if len(values) == 0:
            continue
        mean = float(np.mean(values))
        half = style.ci95_halfwidth(values)
        ax.errorbar(index, mean, yerr=(0.0 if half is None else half),
                    fmt="o", markersize=5, color=style.scenario_color(scenario),
                    ecolor=style.scenario_color(scenario), elinewidth=1.2,
                    capsize=3.5, zorder=3)
        if half is None:
            # A single run gets no interval. Marking it hollow is the honest
            # signal: the point is a measurement, the spread is unknown.
            ax.plot(index, mean, "o", markersize=5, markerfacecolor="white",
                    markeredgecolor=style.scenario_color(scenario), zorder=4)

    # A reference line at the baseline mean makes the added cost of each layer
    # readable without annotating numbers onto the plot.
    baseline = frame[frame["scenario"] == psao_io.BASELINE_SCENARIO][metric].dropna()
    if len(baseline):
        ax.axhline(float(baseline.mean()), color=style.scenario_color("S1"),
                   linewidth=0.8, linestyle=":", alpha=0.8, zorder=1)

    ax.set_xticks(range(len(present)))
    ax.set_xticklabels(present)
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Mean response time (ms)")
    ax.set_ylim(bottom=0)
    ax.margins(x=0.06)

    # Scenario names spelled out in the legend rather than on the axis: the axis
    # stays readable at column width, and the identities stay in the figure.
    from matplotlib.lines import Line2D
    handles = [Line2D([0], [0], marker="o", linestyle="none", markersize=4,
                      color=style.scenario_color(s), label=style.scenario_label(s))
               for s in present]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.28),
              ncol=2, frameon=False, handletextpad=0.4, columnspacing=1.0)
    style.add_data_provenance(fig, bundle.data_dir)
    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example")
    parser.add_argument("--out", default="figures/output/fig_latency_scenarios.pdf")
    parser.add_argument("--window", default="steady", choices=["steady", "full"])
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    fig = build(bundle, window=args.window)
    style.finalize(fig, args.out, bundle.data_dir, tight=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
