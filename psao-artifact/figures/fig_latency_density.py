#!/usr/bin/env python3
"""fig_latency_density.py -- per-request latency distributions.

Means and p99s hide the shape. This figure shows the whole distribution for the
four scenarios whose shapes the paper's argument depends on:

  S1  baseline, the floor
  S5  full stack with HS256 verification on the event loop
  S6  the same with RS256, which costs an order of magnitude more per token
  S7  PSAO: verification relocated to the Envoy sidecar

The question a reader should be able to answer from this figure is whether S7's
improvement is a shift of the whole distribution or only a shortened tail. Those
are different claims and the manuscript's summary statistics cannot distinguish
them.

Violins rather than a KDE overlay: overlapping density curves at four scenarios
become unreadable at column width, and a violin carries the quartiles without
needing numeric labels. The distribution is drawn from the per-request samples
in latency_samples.csv, pooled across runs -- which is stated here because
pooling across runs mixes between-run variation into the shape.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import style
from analysis import io as psao_io

SCENARIOS = ["S1", "S5", "S6", "S7"]


def build(bundle: psao_io.DataBundle, *, scenarios=None, clip_percentile: float = 99.5):
    scenarios = scenarios or SCENARIOS
    samples = bundle.require("latency_samples")
    present = [s for s in scenarios if s in set(samples["scenario"].dropna())]

    fig, ax = style.new_figure(width=style.DOUBLE_WIDTH * 0.55, height=2.7)

    series = []
    for scenario in present:
        values = samples[samples["scenario"] == scenario]["latency_ms"].dropna().to_numpy(float)
        series.append(values[np.isfinite(values)])

    parts = ax.violinplot(series, positions=range(len(present)), widths=0.75,
                          showextrema=False, showmedians=True)
    for body, scenario in zip(parts["bodies"], present):
        body.set_facecolor(style.scenario_color(scenario))
        body.set_edgecolor(style.scenario_color(scenario))
        body.set_alpha(0.45)
        body.set_linewidth(0.8)
    if "cmedians" in parts:
        parts["cmedians"].set_color("#222222")
        parts["cmedians"].set_linewidth(1.0)

    # Quartile whiskers inside each violin: the box-plot information a reader
    # expects, without a second set of artists competing for space.
    for index, values in enumerate(series):
        if len(values) == 0:
            continue
        q1, q3 = np.percentile(values, [25, 75])
        ax.vlines(index, q1, q3, color="#222222", linewidth=3.0, alpha=0.6, zorder=3)

    # The extreme tail is clipped from the AXIS ONLY, never from the data: the
    # violins are computed over every sample. Without a clip one scenario's
    # outliers set the y-range and every distribution collapses to a line.
    if series:
        top = max(float(np.percentile(v, clip_percentile)) for v in series if len(v))
        ax.set_ylim(0, top * 1.10)

    ax.set_xticks(range(len(present)))
    ax.set_xticklabels(present)
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Per-request response time (ms)")
    ax.text(0.99, 0.98,
            f"axis clipped at the {clip_percentile:g}th percentile;\n"
            "violins use every sample",
            transform=ax.transAxes, ha="right", va="top", fontsize=6,
            color="#8A929B")

    from matplotlib.patches import Patch
    handles = [Patch(facecolor=style.scenario_color(s), alpha=0.5,
                     edgecolor=style.scenario_color(s), label=style.scenario_label(s))
               for s in present]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.26),
              ncol=1, frameon=False)
    style.add_data_provenance(fig, bundle.data_dir)
    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example")
    parser.add_argument("--out", default="figures/output/fig_latency_density.pdf")
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    fig = build(bundle)
    style.finalize(fig, args.out, bundle.data_dir, tight=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
