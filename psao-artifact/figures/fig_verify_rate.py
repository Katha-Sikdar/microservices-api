"""fig_verify_rate.py -- in-situ jwt.verify() cost against arrival rate.

THE FIGURE THIS ARTIFACT WAS MISSING
------------------------------------
Every other figure here plots a quantity that host contention can destroy. This
one plots a duration distribution of a CPU-bound call, which contention can only
inflate -- so the finding (in-situ cost sits far above the isolated benchmark) is
conservative under contention rather than produced by it.

The horizontal reference line is the isolated microbenchmark value measured on
the HOST. The gap between it and the in-situ curve is the artifact's central
correction: the benchmark and the service do not run on the same machine, and the
difference is roughly an order of magnitude.

Ascending and descending passes are drawn separately. They ran back to back on
one process, so if the curve were really JIT warmth rather than arrival rate, the
descending pass would sit uniformly at the warm floor. Plotting both is what
makes that distinguishable instead of asserted.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt

import style


def load(path: Path):
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            rows.append({
                'pass': r['pass'],
                'rate': int(r['rate_rps']),
                'mean': float(r['verify_mean_us']),
                'p50': float(r['verify_p50_us']),
                'p90': float(r['verify_p90_us']),
                'p99': float(r['verify_p99_us']),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--curve', action='append', required=True,
                    metavar='LABEL=PATH',
                    help='e.g. HS256=data/runs/<dir>/verify_rate_curve.csv')
    ap.add_argument('--reference', action='append', default=[],
                    metavar='LABEL=US',
                    help='isolated microbenchmark value, e.g. HS256=25.98')
    ap.add_argument('--data', required=True, help='data dir, for the watermark guard')
    ap.add_argument('--out', default='figures/output/fig_verify_rate.pdf')
    args = ap.parse_args()

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    colors = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd']

    for i, spec in enumerate(args.curve):
        label, path = spec.split('=', 1)
        rows = load(Path(path))
        c = colors[i % len(colors)]
        for pass_name, marker, ls, alpha in (('asc', 'o', '-', 1.0),
                                             ('desc', 's', '--', 0.65)):
            pts = sorted((r for r in rows if r['pass'] == pass_name),
                         key=lambda r: r['rate'])
            if not pts:
                continue
            ax.plot([p['rate'] for p in pts], [p['mean'] for p in pts],
                    marker=marker, linestyle=ls, color=c, alpha=alpha,
                    label=f'{label} in situ ({pass_name}ending)')

    for i, spec in enumerate(args.reference):
        label, value = spec.split('=', 1)
        ax.axhline(float(value), color=colors[i % len(colors)],
                   linestyle=':', linewidth=1.4, alpha=0.9)
        ax.text(ax.get_xlim()[1], float(value), f' {label} isolated ({value} us)',
                va='bottom', ha='right', fontsize=8,
                color=colors[i % len(colors)])

    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlabel('offered arrival rate (requests/s)')
    ax.set_ylabel(r'mean jwt.verify() duration ($\mu$s)')
    ax.set_title('In-situ verification cost vs arrival rate\n'
                 'dotted: same call measured in isolation on the host',
                 fontsize=10)
    ax.grid(True, which='both', alpha=0.25)
    ax.legend(fontsize=8, loc='best')

    out = style.finalize(fig, args.out, args.data)
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
