#!/usr/bin/env python3
"""fig_cpu_stacked.py -- where the CPU goes, per scenario.

PSAO's claim is that it MOVES verification cost off the event loop, not that it
makes the cost disappear. A figure showing only application CPU would make PSAO
look free and would be dishonest. This one stacks all three components measured
in the testbed:

    ingress   the edge proxy
    app       the Node.js container (the saturating single server)
    sidecar   the Envoy sidecar (where PSAO relocates verification to)

Read S5 against S7: the total should barely move while the application segment
shrinks and the sidecar segment grows. Read S9 against S5: the total should be
roughly unchanged per unit time even though throughput rose, because forking
workers multiplies capacity without making a verification cheaper.

The pod CPU limit is drawn as a reference line where it was recorded, because a
stack that reaches it is a stack that is being throttled, and every latency
number from such a run means something different.

Component colours are deliberately outside the scenario palette so a component
can never be misread as a scenario.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import style
from analysis import io as psao_io

COMPONENTS = [
    ("cpu_ingress_millicores", "ingress", "Ingress"),
    ("cpu_app_millicores", "app", "Application"),
    ("cpu_sidecar_millicores", "sidecar", "Envoy sidecar"),
]


def build(bundle: psao_io.DataBundle, *, window: str = "steady"):
    scenarios = bundle.require("scenarios")
    frame = scenarios[scenarios["throughput_window"] == window]
    present = psao_io.scenarios_present(frame)

    fig, ax = style.new_figure(width=style.DOUBLE_WIDTH * 0.60, height=2.8)

    positions = np.arange(len(present))
    bottoms = np.zeros(len(present))
    any_missing = False

    for column, key, label in COMPONENTS:
        heights = []
        for scenario in present:
            values = frame[frame["scenario"] == scenario][column].dropna().to_numpy(float)
            if len(values) == 0:
                any_missing = True
                heights.append(0.0)  # nothing measured: contributes no segment
            else:
                heights.append(float(np.mean(values)))
        heights = np.asarray(heights)
        ax.bar(positions, heights, bottom=bottoms, width=0.62,
               color=style.COMPONENT_COLORS[key], edgecolor="white",
               linewidth=0.6, label=label, zorder=2)
        bottoms += heights

    # Error bars on the TOTAL only. Stacking per-component intervals would imply
    # the components vary independently, which they do not -- they share a run.
    for index, scenario in enumerate(present):
        rows = frame[frame["scenario"] == scenario]
        complete = rows.dropna(subset=[c for c, _, _ in COMPONENTS])
        if len(complete) < 2:
            continue
        totals = complete[[c for c, _, _ in COMPONENTS]].sum(axis=1).to_numpy(float)
        half = style.ci95_halfwidth(totals)
        if half:
            ax.errorbar(index, float(np.mean(totals)), yerr=half, fmt="none",
                        ecolor="#33393F", elinewidth=0.9, capsize=3, zorder=4)

    limits = frame["cpu_limit_millicores"].dropna().unique()
    if len(limits) == 1:
        ax.axhline(float(limits[0]), color="#C0392B", linewidth=0.9,
                   linestyle="--", alpha=0.8, zorder=3,
                   label="pod CPU limit")
    elif len(limits) > 1:
        # Different limits across scenarios would make the stacks incomparable;
        # say so rather than drawing one of them.
        ax.text(0.5, 0.97, "pod CPU limit differs between scenarios; not drawn",
                transform=ax.transAxes, ha="center", va="top", fontsize=6,
                color="#C0392B")

    ax.set_xticks(positions)
    ax.set_xticklabels(present)
    ax.set_xlabel("Scenario")
    ax.set_ylabel("CPU (millicores)")
    ax.margins(x=0.04)
    if any_missing:
        ax.text(0.01, 0.97, "components with no measurement contribute no segment",
                transform=ax.transAxes, ha="left", va="top", fontsize=6,
                color="#8A929B")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=4,
              frameon=False)
    style.add_data_provenance(fig, bundle.data_dir)
    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example")
    parser.add_argument("--out", default="figures/output/fig_cpu_stacked.pdf")
    parser.add_argument("--window", default="steady", choices=["steady", "full"])
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    fig = build(bundle, window=args.window)
    style.finalize(fig, args.out, bundle.data_dir, tight=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
