#!/usr/bin/env python3
"""make_revision_standin_figures.py -- fig_decomposition.pdf, fig_runtime_matrix.pdf
and fig_insitu_rate.pdf for paper/revision/main.tex, drawn from the committed
keypath_stats.json and verify_rate_curve.csv files the tables are generated
from, so a figure cannot disagree with its table.

Palette: the validated categorical slots blue #2a78d6 / orange #eb6834 / aqua
#1baf7a (dataviz reference palette; CVD and contrast checks pass, aqua carries
a visible label). Identity is never colour alone: series also differ by marker
or are labelled directly, so the figures survive greyscale printing.

Usage: python3 figures/make_revision_standin_figures.py [outdir]
"""
import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'paper' / 'revision' / 'figures'
OUT.mkdir(parents=True, exist_ok=True)
RUNS = ROOT / 'data' / 'runs'
MECH = json.loads((RUNS / '2026-09-17T08-42-17Z-keypath-mechanism/keypath_stats.json').read_text())
MATRIX = json.loads((RUNS / '2026-09-17T08-57-13Z-keypath-runtime-matrix/keypath_stats.json').read_text())
SWEEP = RUNS / '2026-09-14T05-57-22Z-verifyrate-hs256' / 'verify_rate_curve.csv'

BLUE, ORANGE, AQUA = '#2a78d6', '#eb6834', '#1baf7a'
INK, INK2, GRID = '#0b0b0b', '#52514e', '#e4e3df'
plt.rcParams.update({
    'font.size': 8, 'font.family': 'serif', 'pdf.fonttype': 42,
    'axes.spines.top': False, 'axes.spines.right': False,
    'axes.edgecolor': INK2, 'axes.labelcolor': INK, 'xtick.color': INK2,
    'ytick.color': INK2, 'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False,
})
plain = FuncFormatter(lambda v, _: f'{v:g}')

# --- Figure: decomposition ---------------------------------------------------
host = MECH['environments']['host']
C = host['conditions']
rows = [('verify(), string secret', 'jwt_hs_string'),
        ('discarded asym. parse', 'probe_throws'),
        ('successful asym. parse', 'probe_succeeds'),
        ('verify(), pre-parsed key', 'jwt_hs_preparsed'),
        ('HMAC, string key', 'hmac_string'),
        ('HMAC, pre-parsed key', 'hmac_keyobject'),
        ('structural decode', 'decode_only'),
        ('symmetric key constructor', 'create_secret_key'),
        ('timer overhead', 'timer_overhead')]
EMPH = {'probe_throws', 'create_secret_key'}
fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.5), gridspec_kw={'width_ratios': [3, 2], 'wspace': 0.55})
for i, (label, c) in enumerate(rows):
    v = C[c]
    a.barh(i, v['median_of_medians_us'], color=ORANGE if c in EMPH else BLUE, height=0.62)
    lo, hi = v['ci95']
    a.plot([lo, hi], [i, i], color=INK, lw=0.8)
a.set_yticks(range(len(rows)), [r[0] for r in rows])
for t, (_, c) in zip(a.get_yticklabels(), rows):
    if c in EMPH:
        t.set_fontweight('bold')
a.invert_yaxis(); a.grid(axis='y', visible=False)
a.set_xlabel(r'median of per-process medians ($\mu$s)')
a.set_title('(a) operations in the validation path', loc='left', fontsize=8)

d = host['decomposition']
segs = [('discarded parse', C['probe_throws']['median_of_medians_us'], ORANGE),
        ('key conversion', C['create_secret_key']['median_of_medians_us'], AQUA),
        ('unattributed', d['residual_us']['median'], '#c9c8c3')]
left = 0
for label, w, col in segs:
    b.barh(0, w, left=left, color=col, height=0.45, edgecolor='white', linewidth=1)
    left += w
obs = d['observed_penalty_us']['median']
b.axvline(obs, color=INK, lw=0.8, ls='--')
b.text(obs, 0.42, f'observed penalty\n{obs:.2f} $\\mu$s', ha='right', va='bottom', fontsize=7, color=INK)
b.set_yticks([]); b.set_ylim(-0.5, 1.05); b.grid(axis='y', visible=False)
b.set_xlim(0, obs * 1.08)
b.set_xlabel(r'$\mu$s per call')
b.set_title('(b) string-secret penalty, decomposed', loc='left', fontsize=8)
handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in segs]
b.legend(handles, [s[0] for s in segs], loc='upper center', bbox_to_anchor=(0.45, -0.24),
         ncol=3, fontsize=7, handlelength=1.0, columnspacing=0.8)
fig.savefig(OUT / 'fig_decomposition.pdf', bbox_inches='tight'); plt.close(fig)

# --- Figure: runtime matrix --------------------------------------------------
envs = [('Node 18, musl', 'node:18.20.8-alpine'), ('Node 20, musl', 'node:20-alpine'),
        ('Node 26, musl', 'node:26.6.0-alpine'), ('Node 26, glibc', 'node:26.6.0-bookworm')]
fig, ax = plt.subplots(figsize=(7.0, 2.4))
w = 0.36
for off, c, col, lab in [(-w / 2, 'probe_throws', ORANGE, 'discarded parse'),
                         (w / 2, 'jwt_hs_preparsed', BLUE, 'pre-parsed verify()')]:
    vals = [MATRIX['environments'][e]['conditions'][c]['median_of_medians_us'] for _, e in envs]
    bars = ax.bar([i + off for i in range(len(envs))], vals, width=w, color=col, label=lab)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, v * 1.12, f'{v:.3g}', ha='center', va='bottom',
                fontsize=6.5, color=INK2)
ax.set_yscale('log'); ax.yaxis.set_major_formatter(plain)
ax.set_ylim(3, 2000); ax.set_ylabel(r'$\mu$s per call (log scale)')
ax.set_xticks(range(len(envs)), [e[0] for e in envs]); ax.grid(axis='x', visible=False)
ax.axvline(1.5, color=INK2, lw=0.8, ls='--')
ax.text(0.5, 1500, 'OpenSSL 3.0', ha='center', va='top', fontsize=7, color=INK2)
ax.text(2.5, 1500, 'OpenSSL 3.5', ha='center', va='top', fontsize=7, color=INK2)
ax.legend(loc='upper left', bbox_to_anchor=(1.0, 1.0), fontsize=7)
fig.savefig(OUT / 'fig_runtime_matrix.pdf', bbox_inches='tight'); plt.close(fig)

# --- Figure: in-situ cost against arrival rate, string secret ----------------
by = {}
for r in csv.DictReader(SWEEP.open()):
    by.setdefault(r['pass'], {})[int(r['rate_rps'])] = float(r['verify_mean_us'])
rates = sorted(by['asc'])
asc = [by['asc'][r] for r in rates]; desc = [by['desc'][r] for r in rates]
fig, ax = plt.subplots(figsize=(3.3, 2.4))
ax.fill_between(rates, [min(x, y) for x, y in zip(asc, desc)], [max(x, y) for x, y in zip(asc, desc)],
                color=BLUE, alpha=0.15, linewidth=0, label='range between passes')
ax.plot(rates, asc, color=BLUE, lw=2, marker='o', ms=4, label='ascending pass')
ax.plot(rates, desc, color=ORANGE, lw=2, marker='s', ms=4, ls='--', label='descending pass')
ax.set_xscale('log'); ax.set_yscale('log')
ax.xaxis.set_major_formatter(plain); ax.yaxis.set_major_formatter(plain)
ax.set_xticks(rates); ax.set_yticks([400, 600, 800, 1000])
ax.set_xlabel('arrival rate (requests/s, log scale)')
ax.set_ylabel(r'mean per call ($\mu$s, log scale)')
ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.28), ncol=2, fontsize=6.5,
          handlelength=1.8, columnspacing=0.8)
fig.savefig(OUT / 'fig_insitu_rate.pdf', bbox_inches='tight'); plt.close(fig)
print('wrote', *(OUT / f for f in ('fig_decomposition.pdf', 'fig_runtime_matrix.pdf', 'fig_insitu_rate.pdf')))
