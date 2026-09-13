#!/usr/bin/env python3
"""make_all.py -- render every figure from one data directory.

Each figure is rendered independently: one that cannot be built (its input CSV is
missing) is reported and skipped, and the rest still render. A partial run of the
experiments should still produce the figures it can support.

The exit status is non-zero if any figure failed, so `make figures` fails loudly
rather than leaving a stale PDF from a previous run in place.

Every figure produced here goes through style.finalize(), which applies the
synthetic-data watermark. There is no other save path.
"""
from __future__ import annotations

import argparse
import traceback
from pathlib import Path

import style
from analysis import io as psao_io

import fig_controller_trace
import fig_cpu_latency_scatter
import fig_cpu_stacked
import fig_elbow
import fig_latency_density
import fig_latency_scenarios
import fig_validation_path

# (module, output stem, whether tight_layout applies, required input)
FIGURES = [
    (fig_elbow, "fig_elbow", True, "openloop_ramp"),
    (fig_controller_trace, "fig_controller_trace", False, "controller_trace"),
    (fig_latency_scenarios, "fig_latency_scenarios", False, "scenarios"),
    (fig_latency_density, "fig_latency_density", False, "latency_samples"),
    (fig_cpu_stacked, "fig_cpu_stacked", False, "scenarios"),
    (fig_cpu_latency_scatter, "fig_cpu_latency_scatter", True, "scenarios"),
    (fig_validation_path, "fig_validation_path", False, "microbench"),
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/example", help="data directory")
    parser.add_argument("--out", default="figures/output", help="output directory")
    args = parser.parse_args(argv)

    data_dir = Path(args.data)
    out_dir = Path(args.out)
    bundle = psao_io.load_bundle(data_dir)

    print(f"rendering {len(FIGURES)} figures from {data_dir}")
    if bundle.synthetic:
        print("  SYNTHETIC DATA: every figure will be watermarked "
              "'SYNTHETIC EXAMPLE DATA - NOT FOR PUBLICATION'")

    rendered, skipped, failed = [], [], []
    for module, stem, tight, required in FIGURES:
        out_path = out_dir / f"{stem}.pdf"
        if getattr(bundle, required) is None:
            print(f"  SKIP {stem}: {required}.csv is not in {data_dir}")
            skipped.append((stem, f"{required}.csv missing"))
            continue
        try:
            fig = module.build(bundle)
            style.finalize(fig, out_path, bundle.data_dir, tight=tight)
            rendered.append(stem)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {stem}: {exc}")
            traceback.print_exc()
            failed.append((stem, str(exc)))

    print(f"\n{len(rendered)} rendered, {len(skipped)} skipped, {len(failed)} failed")
    for stem, reason in skipped:
        print(f"  skipped {stem}: {reason}")
    for stem, reason in failed:
        print(f"  failed  {stem}: {reason}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
