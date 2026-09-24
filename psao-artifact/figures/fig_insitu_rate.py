#!/usr/bin/env python3
"""fig_insitu_rate.py -- in-situ validation cost against arrival rate.

Reads the committed verify_rate_curve.csv of each sweep. No value is typed into
this file: every point plotted is read from a run directory, and the axis limits
are derived from the data. Ascending and descending passes are drawn separately
rather than averaged, because Section 7.2 of the paper reports that they differ
systematically -- averaging them would hide the finding the figure exists beside.

Usage: python3 figures/fig_insitu_rate.py [--out figures/output/fig_insitu_rate.pdf]
"""
from __future__ import annotations
import argparse, csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
SWEEPS = [
    ('HS256, string secret',  '2026-09-14T05-57-22Z-verifyrate-hs256',           '#1f4e79'),
    ('HS256, pre-parsed key', '2026-09-14T15-01-36Z-verifyrate-hs256-preparsed', '#c0504d'),
    ('RS256, pre-parsed key', '2026-09-14T06-41-56Z-verifyrate-rs256',           '#4f6228'),
]


def load(run: str):
    p = ROOT / 'data' / 'runs' / run / 'verify_rate_curve.csv'
    out = {}
    for r in csv.DictReader(p.open()):
        out.setdefault(r['pass'], []).append(
            (int(r['rate_rps']), float(r['verify_mean_us'])))
    for k in out:
        out[k].sort()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'figures' / 'output' / 'fig_insitu_rate.pdf'))
    a = ap.parse_args()

    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    for label, run, colour in SWEEPS:
        d = load(run)
        for pas, style, marker in (('asc', '-', 'o'), ('desc', '--', 's')):
            if pas not in d:
                continue
            xs = [x for x, _ in d[pas]]
            ys = [y for _, y in d[pas]]
            ax.plot(xs, ys, style, color=colour, marker=marker, markersize=4,
                    linewidth=1.3, label=f'{label} ({pas})')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlabel('Arrival rate (requests/s, log scale)')
    ax.set_ylabel('Mean cost per validation ($\\mu$s, log scale)')
    ax.grid(True, which='both', linewidth=0.3, alpha=0.4)
    ax.legend(fontsize=6, frameon=False, ncol=1, loc='lower left')
    fig.tight_layout()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out)
    print(f'wrote {a.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
