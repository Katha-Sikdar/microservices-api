#!/usr/bin/env python3
"""fig_cpu_latency_scatter.py -- the cost/latency trade-off, all scenarios.

Latency and CPU are usually reported in separate tables, which lets each
scenario be described by whichever of the two flatters it. Putting them on one
plane forces the trade-off into the open: the desirable corner is bottom-left
(cheap and fast), and every scenario's position relative to S1 and S5 is
readable at a glance.

Each point is a scenario, positioned at its mean across runs, with 95% CI bars
on both axes. Points are labelled by scenario identity -- that is a name, not a
data value, so it is safe to burn in and it removes the need to trace colours
back to a legend.

Total CPU (ingress + application + sidecar) is plotted by default, because a
claim about cost has to count the cost wherever it landed. --component app plots
application CPU alone, which is the right view for a claim about the event loop.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import style
from analysis import io as psao_io

CPU_COLUMNS = ["cpu_ingress_millicores", "cpu_app_millicores", "cpu_sidecar_millicores"]


def build(bundle: psao_io.DataBundle, *, window: str = "steady",
          component: str = "total"):
    scenarios = bundle.require("scenarios")
    frame = scenarios[scenarios["throughput_window"] == window]
    present = psao_io.scenarios_present(frame)

    fig, ax = style.new_figure(width=style.COLUMN_WIDTH * 1.05, height=2.8)

    plotted = 0
    for scenario in present:
        rows = frame[frame["scenario"] == scenario]
        if component == "total":
            complete = rows.dropna(subset=CPU_COLUMNS)
            cpu = complete[CPU_COLUMNS].sum(axis=1).to_numpy(float)
        else:
            complete = rows.dropna(subset=[f"cpu_{component}_millicores"])
            cpu = complete[f"cpu_{component}_millicores"].to_numpy(float)
        latency = complete["latency_mean_ms"].to_numpy(float)
        if len(cpu) == 0 or len(latency) == 0:
            continue

        colour = style.scenario_color(scenario)
        x, y = float(np.mean(cpu)), float(np.mean(latency))
        ax.errorbar(x, y,
                    xerr=(style.ci95_halfwidth(cpu) or 0.0),
                    yerr=(style.ci95_halfwidth(latency) or 0.0),
                    fmt="o", markersize=5, color=colour, ecolor=colour,
                    elinewidth=0.9, capsize=2.5, zorder=3)
        # Offset the label so it does not sit on its own error bar.
        ax.annotate(scenario, (x, y), textcoords="offset points",
                    xytext=(6, 5), fontsize=7.5, color=colour, fontweight="bold")
        plotted += 1

    if plotted == 0:
        ax.text(0.5, 0.5, "no scenario has both CPU and latency measured",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=8, color="#C0392B")

    label = ("Total CPU (ingress + app + sidecar, millicores)"
             if component == "total" else
             f"{component.capitalize()} CPU (millicores)")
    ax.set_xlabel(label)
    ax.set_ylabel("Mean response time (ms)")
    ax.margins(0.12)
    ax.text(0.01, 0.02, "cheaper and faster: bottom-left", transform=ax.transAxes,
            fontsize=6, color="#8A929B", ha="left", va="bottom")
    style.add_data_provenance(fig, bundle.data_dir)
    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example")
    parser.add_argument("--out", default="figures/output/fig_cpu_latency_scatter.pdf")
    parser.add_argument("--window", default="steady", choices=["steady", "full"])
    parser.add_argument("--component", default="total",
                        choices=["total", "app", "sidecar", "ingress"])
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    fig = build(bundle, window=args.window, component=args.component)
    style.finalize(fig, args.out, bundle.data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
