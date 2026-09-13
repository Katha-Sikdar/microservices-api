#!/usr/bin/env python3
"""fig_validation_path.py -- what jwt.verify() actually spends its time on.

The manuscript attributes application-layer JWT cost to "signature
verification". bench/jwt-path-microbench.js measures the four stages separately;
this figure stacks them so the attribution can be checked rather than assumed.

The stack, from the bottom:

  primitive_raw            the cryptographic operation over raw bytes: the floor
  signing input assembly   primitive_preparsed - primitive_raw
  decode_only              splitting, base64url-decoding and JSON-parsing
  library overhead         full_verify - (decode_only + primitive_preparsed)

A tick marks the independently measured full_verify total, so the reader can see
whether the parts add up to the whole.

WHY THE RESIDUAL MAY BE NEGATIVE, AND WHY IT IS NOT CLAMPED
-----------------------------------------------------------
The stages are measured in separate loops. An isolated loop gets specialised by
the JIT more aggressively than the same work inside the full call, and the
stages touch overlapping buffers, so decode_only + primitive_preparsed can
exceed full_verify. When that happens the residual is drawn as a hatched bar
BELOW the axis and labelled as over-attribution. Clamping it to zero would hide a
real property of the measurement, and the sign of that residual is itself
informative: it bounds how much of the decomposition is an artefact of measuring
the stages apart.

The comparison that matters for the paper: if decode_only is a large share of
full_verify, then relocating verification to the Envoy sidecar does not remove
that share -- the sidecar parses the token too. PSAO's benefit is then about
WHERE the work happens (off a single event loop, onto a proxy that can be scaled
independently), not about the work disappearing. That is a weaker and much more
defensible claim than the one the manuscript currently makes.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import style
from analysis import io as psao_io

# Bottom-to-top order of the stack.
LAYERS = [
    ("primitive_raw", "Crypto primitive (raw bytes)"),
    ("signing_input_assembly", "Signing-input assembly"),
    ("decode_only", "Parsing (split, base64url, JSON)"),
    ("library_overhead", "Library overhead (claims, options)"),
]


def decompose(bench, algorithm: str, payload: float) -> dict:
    """Stage means for one (algorithm, payload), and the derived layers."""
    rows = bench[(bench["algorithm"] == algorithm)
                 & (np.isclose(bench["payload_kb"].astype(float), payload))]
    if rows.empty:
        return {}
    stage_mean = rows.groupby("stage")["mean_us"].mean().to_dict()

    full = stage_mean.get("full_verify")
    decode = stage_mean.get("decode_only")
    preparsed = stage_mean.get("primitive_preparsed")
    raw = stage_mean.get("primitive_raw")
    if full is None or decode is None or preparsed is None or raw is None:
        return {}

    return {
        "full_verify": float(full),
        "primitive_raw": float(raw),
        "signing_input_assembly": float(preparsed - raw),
        "decode_only": float(decode),
        "library_overhead": float(full - decode - preparsed),
    }


def build(bundle: psao_io.DataBundle):
    bench = bundle.require("microbench")
    algorithms = [a for a in ("HS256", "RS256") if a in set(bench["algorithm"].dropna())]
    payloads = sorted(float(p) for p in bench["payload_kb"].dropna().unique())

    fig, axes = style.new_figure(width=style.DOUBLE_WIDTH * 0.62, height=2.9,
                                 ncols=max(1, len(algorithms)), sharey=False)
    axes = np.atleast_1d(axes)

    for ax, algorithm in zip(axes, algorithms):
        positions = np.arange(len(payloads))
        bottoms = np.zeros(len(payloads))
        negatives = np.zeros(len(payloads))
        totals = []

        columns = {key: [] for key, _ in LAYERS}
        for payload in payloads:
            parts = decompose(bench, algorithm, payload)
            totals.append(parts.get("full_verify", np.nan))
            for key, _ in LAYERS:
                columns[key].append(parts.get(key, np.nan))

        for key, label in LAYERS:
            values = np.asarray(columns[key], dtype=float)
            positive = np.where(np.isfinite(values) & (values > 0), values, 0.0)
            negative = np.where(np.isfinite(values) & (values < 0), values, 0.0)
            ax.bar(positions, positive, bottom=bottoms, width=0.6,
                   color=style.STAGE_COLORS.get(key, "#999999"),
                   edgecolor="white", linewidth=0.5, label=label, zorder=2)
            bottoms += positive
            if negative.any():
                # Over-attribution: drawn below zero, hatched, never clamped.
                ax.bar(positions, negative, bottom=negatives, width=0.6,
                       color="white", edgecolor=style.STAGE_COLORS["unattributed"],
                       linewidth=0.7, hatch="////", zorder=2,
                       label="Over-attribution (negative residual)")
                negatives += negative

        # The independently measured total, as a tick. If the stack does not
        # reach it, the parts did not add up, and that is visible.
        ax.scatter(positions, totals, marker="_", s=220, linewidths=1.3,
                   color="#22282E", zorder=5, label="Measured full_verify")

        ax.set_xticks(positions)
        ax.set_xticklabels([f"{p:g}" for p in payloads])
        ax.set_xlabel("Encoded payload (kB)")
        ax.set_title(algorithm)
        ax.axhline(0, color="#22282E", linewidth=0.7)
        if ax is axes[0]:
            ax.set_ylabel("Time per verification (µs)")

    # One legend for both panels: the layers are the same in each.
    handles, labels = axes[0].get_legend_handles_labels()
    seen, unique_handles, unique_labels = set(), [], []
    for handle, label in zip(handles, labels):
        if label in seen:
            continue
        seen.add(label)
        unique_handles.append(handle)
        unique_labels.append(label)
    # Reserve room at the bottom explicitly: the legend is a figure-level artist
    # and would otherwise land on the x-axis labels of both panels.
    fig.subplots_adjust(bottom=0.30, wspace=0.30, top=0.90)
    fig.legend(unique_handles, unique_labels, loc="upper center",
               bbox_to_anchor=(0.5, 0.16), ncol=2, frameon=False)
    style.add_data_provenance(fig, bundle.data_dir)
    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example")
    parser.add_argument("--out", default="figures/output/fig_validation_path.pdf")
    args = parser.parse_args(argv)

    bundle = psao_io.load_bundle(Path(args.data))
    fig = build(bundle)
    style.finalize(fig, args.out, bundle.data_dir, tight=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
