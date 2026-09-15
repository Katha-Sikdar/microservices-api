"""fig_validation_cost.py -- the three figures supporting the cost decomposition.

  fig_cost_decomposition : where the time inside jwt.verify() actually goes
  fig_keyform            : string secret vs pre-parsed KeyObject, across rates
  fig_algorithm          : RS256 vs HS256, in deployment against in primitives

One colour per condition across all of them, matching fig_verify_rate.py.
"""
from __future__ import annotations

import argparse, csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

import style

# One colour per condition, used consistently in every figure of this paper.
C_STRING = '#1f77b4'
C_PREPARSED = '#d62728'
C_RS = '#2ca02c'
C_PRIMITIVE = '#7f7f7f'
C_DECODE = '#bcbd22'


def read_curve(path):
    rows = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            if r['pass'] != 'asc':
                continue
            rows[int(r['rate_rps'])] = float(r['verify_mean_us'])
    return rows


def read_microbench(path):
    out = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            out[(r['algorithm'], r['payload_kb'], r['stage'])] = float(r['mean_us'])
    return out


def fig_decomposition(mb, kf, out, data_dir):
    """Stacked: dispatch/allocation, decoding, key handling, primitive."""
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    conds, parts = [], []
    for alg, akey in (('HS256', 'HS256'), ('RS256', 'RS256')):
        full = mb[(akey, '0.5', 'full_verify')]
        dec = mb[(akey, '0.5', 'decode_only')]
        prim = mb[(akey, '0.5', 'primitive_preparsed')]
        conds.append(f'{alg}\nisolated, host')
        parts.append((prim, dec, 0.0, full - dec - prim))
    for alg in ('Hs', 'Rs'):
        name = 'HS256' if alg == 'Hs' else 'RS256'
        full = kf[(name, 'string')]
        prep = kf[(name, 'preparsed')]
        akey = name
        dec = mb[(akey, '0.5', 'decode_only')]
        prim = mb[(akey, '0.5', 'primitive_preparsed')]
        conds.append(f'{name}\nin container,\nstring key')
        # key handling is what pre-parsing removes; the rest of the pre-parsed
        # cost is dispatch and allocation.
        parts.append((prim, dec, full - prep, max(prep - dec - prim, 0.0)))

    labels = ['signature primitive', 'base64/JSON decoding',
              'key conversion (per call)', 'dispatch, allocation, claim checks']
    colors = [C_PRIMITIVE, C_DECODE, C_STRING, C_PREPARSED]
    arr = np.array(parts)
    bottom = np.zeros(len(conds))
    for i, (lab, col) in enumerate(zip(labels, colors)):
        ax.bar(conds, arr[:, i], bottom=bottom, label=lab, color=col, width=0.6)
        bottom += arr[:, i]
    ax.set_ylabel(r'mean time per call ($\mu$s)')
    ax.set_yscale('symlog', linthresh=10)
    ax.set_title('Where the time inside jwt.verify() goes (0.5 kB token)', fontsize=10)
    ax.legend(fontsize=7.5, loc='upper left')
    ax.grid(True, axis='y', alpha=0.25)
    return style.finalize(fig, out, data_dir)


def fig_keyform(string_curve, preparsed_curve, out, data_dir):
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    rates = sorted(set(string_curve) & set(preparsed_curve))
    ax.plot(rates, [string_curve[r] for r in rates], 'o-',
            color=C_STRING, label='string secret (as submitted)')
    ax.plot(rates, [preparsed_curve[r] for r in rates], 's-',
            color=C_PREPARSED, label='pre-parsed KeyObject')
    ax.fill_between(rates, [preparsed_curve[r] for r in rates],
                    [string_curve[r] for r in rates], color=C_STRING, alpha=0.12)
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_xlabel('offered arrival rate (requests/s)')
    ax.set_ylabel(r'mean jwt.verify() duration ($\mu$s)')
    ax.set_title('Cost removed by pre-parsing the key (shaded)', fontsize=10)
    ax.grid(True, which='both', alpha=0.25)
    ax.legend(fontsize=8)
    return style.finalize(fig, out, data_dir)


def fig_algorithm(hs_curve, rs_curve, mb, kf, out, data_dir):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.4, 3.8))
    rates = sorted(set(hs_curve) & set(rs_curve))
    ax1.plot(rates, [hs_curve[r] for r in rates], 's-', color=C_PREPARSED, label='HS256')
    ax1.plot(rates, [rs_curve[r] for r in rates], '^-', color=C_RS, label='RS256')
    ax1.set_xscale('log'); ax1.set_yscale('log')
    ax1.set_xlabel('arrival rate (req/s)')
    ax1.set_ylabel(r'mean duration ($\mu$s)')
    ax1.set_title('In deployment\n(both pre-parsed)', fontsize=9)
    ax1.grid(True, which='both', alpha=0.25); ax1.legend(fontsize=8)

    names = ['signature\nprimitive', 'whole\njwt.verify()']
    hs = [mb[('HS256', '0.5', 'primitive_preparsed')], kf[('HS256', 'preparsed')]]
    rs = [mb[('RS256', '0.5', 'primitive_preparsed')], kf[('RS256', 'preparsed')]]
    x = np.arange(len(names)); w = 0.35
    ax2.bar(x - w / 2, hs, w, label='HS256', color=C_PREPARSED)
    ax2.bar(x + w / 2, rs, w, label='RS256', color=C_RS)
    ax2.set_xticks(x); ax2.set_xticklabels(names, fontsize=8)
    ax2.set_ylabel(r'mean time ($\mu$s)')
    ax2.set_title('Primitive vs whole call', fontsize=9)
    ax2.grid(True, axis='y', alpha=0.25); ax2.legend(fontsize=8)
    return style.finalize(fig, out, data_dir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--string-curve', required=True)
    ap.add_argument('--preparsed-curve', required=True)
    ap.add_argument('--rs-curve', required=True)
    ap.add_argument('--microbench', required=True)
    ap.add_argument('--keyform', required=True)
    ap.add_argument('--outdir', default='figures/output')
    a = ap.parse_args()

    sc = read_curve(a.string_curve)
    pc = read_curve(a.preparsed_curve)
    rc = read_curve(a.rs_curve)
    mb = read_microbench(a.microbench)
    kf = {}
    with open(a.keyform) as fh:
        for r in csv.DictReader(fh):
            kf[(r['algorithm'], r['key_form'])] = float(r['mean_us'])

    o = Path(a.outdir)
    print('wrote', fig_decomposition(mb, kf, o / 'fig_cost_decomposition.pdf', a.data))
    print('wrote', fig_keyform(sc, pc, o / 'fig_keyform.pdf', a.data))
    print('wrote', fig_algorithm(pc, rc, mb, kf, o / 'fig_algorithm.pdf', a.data))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
