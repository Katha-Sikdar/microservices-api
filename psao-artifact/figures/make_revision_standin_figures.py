#!/usr/bin/env python3
"""make_revision_standin_figures.py -- stand-ins for fig_decomposition.pdf and
fig_runtime_matrix.pdf, which main.tex references but which are not in this
repository (the authors' figures/make_figures.py is not committed). Drawn from
the same committed keypath_stats.json files the tables are generated from, so
the figures cannot disagree with the tables. Replace with the authors'
originals if available.

Usage: python3 figures/make_revision_standin_figures.py [outdir]
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'paper' / 'revision' / 'figures'
OUT.mkdir(parents=True, exist_ok=True)
MECH = json.loads((ROOT / 'data/runs/2026-09-17T08-42-17Z-keypath-mechanism/keypath_stats.json').read_text())
MATRIX = json.loads((ROOT / 'data/runs/2026-09-17T08-57-13Z-keypath-runtime-matrix/keypath_stats.json').read_text())
plt.rcParams.update({'font.size': 8, 'font.family': 'serif', 'axes.spines.top': False,
                     'axes.spines.right': False, 'pdf.fonttype': 42})
EMPH, BASE = '#B02A1E', '#52514E'

# --- fig_decomposition: (a) Table 1 rows, (b) the penalty decomposed ---------
host = MECH['environments']['host']
rows = [('verify(), string secret', 'jwt_hs_string'),
        ('discarded asym. parse', 'probe_throws'),
        ('successful asym. parse', 'probe_succeeds'),
        ('verify(), pre-parsed key', 'jwt_hs_preparsed'),
        ('HMAC, string key', 'hmac_string'),
        ('HMAC, pre-parsed key', 'hmac_keyobject'),
        ('structural decode', 'decode_only'),
        ('symmetric key constructor', 'create_secret_key'),
        ('timer overhead', 'timer_overhead')]
fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.4), gridspec_kw={'width_ratios': [3, 2]})
for i, (label, c) in enumerate(rows):
    v = host['conditions'][c]
    col = EMPH if c in ('probe_throws', 'create_secret_key') else BASE
    a.barh(i, v['median_of_medians_us'], color=col, height=0.6)
    lo, hi = v['ci95']
    a.plot([lo, hi], [i, i], color='black', lw=0.8)
a.set_yticks(range(len(rows)), [r[0] for r in rows]); a.invert_yaxis()
a.set_xlabel('median of per-process medians (µs)'); a.set_title('(a) operations in the validation path', loc='left')
d = host['decomposition']
cs = host['conditions']
segs = [('discarded parse', cs['probe_throws']['median_of_medians_us'], EMPH),
        ('key conversion', cs['create_secret_key']['median_of_medians_us'], '#D98C3F'),
        ('unattributed', d['residual_us']['median'], '#C9C8C3')]
left = 0
for label, w, col in segs:
    b.barh(0, w, left=left, color=col, height=0.5, label=label); left += w
b.axvline(d['observed_penalty_us']['median'], color='black', lw=0.8, ls='--')
b.text(d['observed_penalty_us']['median'], 0.42, ' observed penalty', fontsize=7, va='bottom')
b.set_yticks([]); b.set_xlabel('µs per call'); b.set_ylim(-0.6, 0.9)
b.set_title('(b) string-secret penalty, decomposed', loc='left'); b.legend(frameon=False, fontsize=7, loc='lower right')
fig.tight_layout(); fig.savefig(OUT / 'fig_decomposition.pdf'); plt.close(fig)

# --- fig_runtime_matrix: the four container rows, log axis ------------------
envs = [('Node 18\nmusl', 'node:18.20.8-alpine'), ('Node 20\nmusl', 'node:20-alpine'),
        ('Node 26\nmusl', 'node:26.6.0-alpine'), ('Node 26\nglibc', 'node:26.6.0-bookworm')]
fig, ax = plt.subplots(figsize=(7.0, 2.3))
x = range(len(envs))
for off, c, col, lab in [(-0.18, 'probe_throws', EMPH, 'discarded parse'),
                         (0.18, 'jwt_hs_preparsed', BASE, 'pre-parsed verify()')]:
    vals = [MATRIX['environments'][e]['conditions'][c]['median_of_medians_us'] for _, e in envs]
    ax.bar([i + off for i in x], vals, width=0.34, color=col, label=lab)
ax.axvline(1.5, color='black', lw=0.8, ls='--')
ax.text(1.5, ax.get_ylim()[1] if False else 1, ' OpenSSL 3.0 | 3.5', fontsize=7, ha='center', va='bottom')
ax.set_yscale('log'); ax.set_ylabel('µs per call (log)')
ax.set_xticks(list(x), [e[0] for e in envs]); ax.legend(frameon=False, fontsize=7)
fig.tight_layout(); fig.savefig(OUT / 'fig_runtime_matrix.pdf'); plt.close(fig)
print('wrote', OUT / 'fig_decomposition.pdf', OUT / 'fig_runtime_matrix.pdf')
