#!/usr/bin/env python3
"""make_revision_macros.py -- LaTeX macros for the measurements added in the
2026-09-24 revision: the plain-C OpenSSL probe (item 6), the V8 exception-cost
baseline and the decomposition it enables (item 7), the second-architecture
repetition of Tables 1 and 2 (item 8) and the cross-library comparison
(item 10).

Same rules as make_keypath_macros.py: every macro is read out of a file under
data/runs/; nothing is typed; a quantity that is absent is emitted as
\\PLACEHOLDER{name} so that it shows in the compiled paper; macro names contain
no digits; and paper/revision_macros_provenance.csv maps each macro to the
file it came from.

Statistics follow analysis/keypath_stats.py: the unit is one process; a figure
is the median of per-process medians; intervals are 95% percentile bootstraps
over processes (10,000 resamples, fixed seed). Differences between two
conditions of the SAME run are paired by round. Combinations of quantities from
DIFFERENT runs (the item-7 decomposition) cannot be paired and are bootstrapped
by resampling each run's processes independently.

Usage:
  python3 -m analysis.make_revision_macros [--out paper/revision_macros.tex]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / 'data' / 'runs'
BOOT = 10000
SEED = 20260924

NUM: dict[str, str] = {}
SRC: dict[str, str] = {}
MISSING: list[str] = []


def latest(suffix: str) -> Path | None:
    """The newest run directory whose name ends in `suffix` and whose
    run_metadata.json records a clean exit. A run that failed or is still in
    progress is never picked up silently."""
    cands = sorted(p for p in RUNS.glob(f'*-{suffix}') if p.is_dir())
    for p in reversed(cands):
        md = p / 'run_metadata.json'
        try:
            meta = json.loads(md.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get('exit_status') == 0:
            return p
    return None


def spell(version: str) -> str:
    """3.0.16 -> ThreeZeroSixteen: macro names may not contain digits."""
    words = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight',
             'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen',
             'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen', 'Twenty']
    out = []
    for part in re.split(r'[.\-]', version):
        n = int(part)
        if n <= 20:
            out.append(words[n])
        else:
            tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty']
            out.append(tens[n // 10] + (words[n % 10] if n % 10 else ''))
    return ''.join(out)


def put(name: str, value, source: Path, fmt='{:.2f}'):
    if re.search(r'\d', name):
        raise SystemExit(f'macro name contains a digit: {name}')
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        MISSING.append(name)
        return
    NUM[name] = fmt.format(value) if isinstance(value, float) else str(value)
    SRC[name] = str(Path(source).relative_to(ROOT))


def put_triple(name: str, est, lo, hi, source: Path):
    """Estimate and bounds at ONE precision, chosen so lo <= est <= hi survives
    rounding (see make_keypath_macros.put_triple for why)."""
    if est is None or lo is None or hi is None:
        for s in ('', 'CiLo', 'CiHi'):
            MISSING.append(name + s)
        return
    start = 1 if abs(est) >= 100 else 2 if abs(est) >= 10 else 3
    for d in range(start, 7):
        f = '{:.%df}' % d
        r = [float(f.format(v)) for v in (lo, est, hi)]
        if r[0] <= r[1] <= r[2]:
            break
    put(name, float(est), source, f)
    put(name + 'CiLo', float(lo), source, f)
    put(name + 'CiHi', float(hi), source, f)


def boot_ci(values, rng, stat=np.median):
    v = np.asarray(values, dtype=float)
    if v.size < 2:
        return (float('nan'), float('nan'))
    idx = rng.integers(0, v.size, size=(BOOT, v.size))
    d = stat(v[idx], axis=1)
    return (float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)))


def boot_draws(values, rng):
    """BOOT bootstrap replicates of the median, for combining across runs."""
    v = np.asarray(values, dtype=float)
    idx = rng.integers(0, v.size, size=(BOOT, v.size))
    return np.median(v[idx], axis=1)


def summarise(df: pd.DataFrame, rng, env_col: str, env: str, cond: str):
    g = df[(df[env_col] == env) & (df['condition'] == cond)]['median_us'].to_numpy(float)
    if g.size == 0:
        return None
    lo, hi = boot_ci(g, rng)
    return {'est': float(np.median(g)), 'lo': lo, 'hi': hi, 'n': int(g.size), 'values': g,
            'cv': float(100 * g.std(ddof=1) / g.mean()) if g.size > 1 else float('nan')}


def paired(df: pd.DataFrame, rng, env_col, env, a, b):
    sub = df[df[env_col] == env]
    w = sub.pivot_table(index='invocation', columns='condition', values='median_us', aggfunc='median')
    if a not in w or b not in w:
        return None
    p = w[[a, b]].dropna()
    d = (p[a] - p[b]).to_numpy()
    lo, hi = boot_ci(d, rng)
    return {'est': float(np.median(d)), 'lo': lo, 'hi': hi, 'n': int(d.size)}


rng = np.random.default_rng(SEED)

# =============================================================================
# Item 6 -- the parse in plain C, across OpenSSL versions built identically
# =============================================================================
C = latest('openssl-c-probe')
C_MEDIANS: dict[tuple[str, str], np.ndarray] = {}
if C:
    f = C / 'openssl_c_probe.csv'
    df = pd.read_csv(f)
    # Identity check: the version each binary REPORTED LOADING must equal the
    # version it was built against. A mismatch means the rpath failed and the
    # system libcrypto was measured instead.
    df['openssl_requested'] = df['openssl_requested'].astype(str)
    mism = int((df['openssl_version'].astype(str) != df['openssl_requested']).sum())
    put('CProbeIdentityMismatches', mism, f)
    df = df[df['openssl_version'].astype(str) == df['openssl_requested']]
    versions = sorted(df['openssl_requested'].unique(), key=lambda v: [int(x) for x in v.split('.')])
    put('CProbeVersionCount', len(versions), f)
    put('CProbeVersionFirst', versions[0], f)
    put('CProbeVersionLast', versions[-1], f)
    put('CProbeInvocations', int(df.groupby(['openssl_requested', 'condition']).size().min()), f)
    put('CProbeCallsPerInvocation', int(df['n'].iloc[0]), f)
    put('CProbeErrorsQueued', int(df['errors_queued'].max()), f)
    table_rows = []
    for v in versions:
        s = spell(v)
        for cond, tag in [('full', 'Full'), ('public_tries', 'PublicTries'),
                          ('private_parse', 'PrivateParse'), ('error_strings', 'ErrorStrings'),
                          ('spki_ok', 'SpkiOk'), ('timer_overhead', 'Timer')]:
            r = summarise(df, rng, 'openssl_requested', v, cond)
            if r:
                put_triple(f'C{tag}V{s}', r['est'], r['lo'], r['hi'], f)
                C_MEDIANS[(v, cond)] = r['values']
        put(f'CVersionLiteralV{s}', v, f)
        full = C_MEDIANS.get((v, 'full'))
        priv = C_MEDIANS.get((v, 'private_parse'))
        if full is not None and priv is not None:
            put(f'CPrivateShareV{s}', 100 * float(np.median(priv)) / float(np.median(full)), f, '{:.0f}')
        table_rows.append(v)
    # the two versions Node actually bundles in the runtimes measured
    old, new = '3.0.16', '3.5.8'
    if (old, 'full') in C_MEDIANS and (new, 'full') in C_MEDIANS:
        a, b = boot_draws(C_MEDIANS[(old, 'full')], rng), boot_draws(C_MEDIANS[(new, 'full')], rng)
        ratio = a / b
        put_triple('CFullRatioOldNew', float(np.median(C_MEDIANS[(old, 'full')]) / np.median(C_MEDIANS[(new, 'full')])),
                   float(np.percentile(ratio, 2.5)), float(np.percentile(ratio, 97.5)), f)
    # where the drop happens: the first version whose full-path median is below
    # half of 3.0.16's
    if (old, 'full') in C_MEDIANS:
        ref = float(np.median(C_MEDIANS[(old, 'full')]))
        first = next((v for v in versions if (v, 'full') in C_MEDIANS
                      and float(np.median(C_MEDIANS[(v, 'full')])) < ref / 2), None)
        put('CFirstFastVersion', first, f)
    # widest 95% interval on the full sequence, as a half-width percentage of
    # its median, across releases (quoted in the caption of the C-probe table)
    hw = []
    for v in versions:
        if (v, 'full') in C_MEDIANS:
            vals = C_MEDIANS[(v, 'full')]
            lo, hi = boot_ci(vals, np.random.default_rng(SEED))
            med = float(np.median(vals))
            hw.append(100 * max(med - lo, hi - med) / med)
    if hw:
        put('CFullCiMaxHalfWidthPct', float(np.ceil(max(hw) * 10) / 10), f, '{:.1f}')
    fl = [float(np.median(C_MEDIANS[(v, 'full')])) for v in versions if (v, 'full') in C_MEDIANS]
    if fl:
        put('CFullSpan', max(fl) / min(fl), f)
    md = json.loads((C / 'run_metadata.json').read_text())
    put('CProbeCpuModel', md.get('run_parameters', {}).get('cpu_model'), C / 'run_metadata.json')
    b = (C / 'builds.csv').read_text().splitlines()
    # 'gcc (Ubuntu 13.3.0-...) 13.3.0' -> 'GCC 13.3.0'; '~' would typeset as a space
    put('CProbeCompiler', 'GCC ' + b[1].split(',"')[1].split('"')[0].split()[-1] if len(b) > 1 else None,
        C / 'builds.csv')
else:
    MISSING.append('CFullVThreeZeroSixteen')

# =============================================================================
# Item 7 -- exception-cost baseline, and the three-way decomposition
# =============================================================================
E = latest('exception-cost')
if E:
    f = E / 'exception_cost.csv'
    df = pd.read_csv(f)
    envs = pd.read_csv(E / 'environments.csv')
    put('ExcInvocations', int(df.groupby(['environment', 'condition']).size().min()), f)
    put('ExcCallsPerInvocation', int(df['n'].iloc[0]), f)
    put('ExcDepth', int(df['depth'].iloc[0]), f)
    put('ExcErrorCode', str(df['error_code'].iloc[0]).replace('_', r'\_'), f)
    for _, row in envs.iterrows():
        env = row['runtime']
        ver = row['node_version'].lstrip('v')
        s = 'Rt' + spell(ver.split('.')[0])  # 'Node...' is taken by keypath_macros
        put(s + 'Literal', ver, E / 'environments.csv')
        put(s + 'Openssl', row['openssl_version'], E / 'environments.csv')
        put(s + 'Veight', row['v8_version'].split('.')[0], E / 'environments.csv')
        put(s + 'VeightFull', row['v8_version'].split('-')[0], E / 'environments.csv')
        R = {}
        for cond, tag in [('exc_plain', 'ExcPlain'), ('exc_node_like', 'ExcNodeLike'),
                          ('exc_node_like_nostack', 'ExcNoStack'),
                          ('exc_node_internal', 'ExcNodeInternal'),
                          ('probe_throws', 'Probe'), ('probe_throws_nostack', 'ProbeNoStack'),
                          ('timer_overhead', 'Timer')]:
            r = summarise(df, rng, 'environment', env, cond)
            if r:
                put_triple(s + tag, r['est'], r['lo'], r['hi'], f)
                R[cond] = r
        st = paired(df, rng, 'environment', env, 'probe_throws', 'probe_throws_nostack')
        if st:
            put_triple(s + 'StackCapture', st['est'], st['lo'], st['hi'], f)
        # --- the decomposition: probe = C parse + exception + binding --------
        ossl = str(row['openssl_version'])
        cfull = C_MEDIANS.get((ossl, 'full'))
        if cfull is not None and 'probe_throws' in R and 'exc_node_like' in R:
            pd_ = boot_draws(R['probe_throws']['values'], rng)
            cd_ = boot_draws(cfull, rng)
            ed_ = boot_draws(R['exc_node_like']['values'], rng)
            left = pd_ - cd_ - ed_
            probe = R['probe_throws']['est']
            c_est = float(np.median(cfull))
            e_est = R['exc_node_like']['est']
            l_est = probe - c_est - e_est
            put_triple(s + 'DecompC', c_est, *boot_ci(cfull, rng), f)
            put_triple(s + 'DecompLeftover', l_est, float(np.percentile(left, 2.5)),
                       float(np.percentile(left, 97.5)), f)
            put(s + 'DecompCPct', 100 * c_est / probe, f, '{:.0f}')
            put(s + 'DecompExcPct', 100 * e_est / probe, f, '{:.1f}')
            put(s + 'DecompLeftoverPct', 100 * l_est / probe, f, '{:.1f}')
            put(s + 'DecompCVersion', ossl, f)
        elif 'probe_throws' in R:
            MISSING.append(s + 'DecompC')
    md = json.loads((E / 'run_metadata.json').read_text())
    put('ExcCpuModel', md.get('run_parameters', {}).get('cpu_model'), E / 'run_metadata.json')
else:
    MISSING.append('RtEighteenProbe')

# =============================================================================
# Item 10 -- cross-library comparison
# =============================================================================
X = latest('crosslib')
if X:
    f = X / 'crosslib.csv'
    df = pd.read_csv(f)
    # the Node libraries were run under two runtimes; the key is library+backend
    df['cell'] = df['library'] + '|' + df['crypto_backend'].astype(str)
    put('XlibInvocations', int(df.groupby(['cell', 'condition']).size().min()), f)
    put('XlibCallsPerInvocation', int(df['n'].iloc[0]), f)
    rows = []
    PEN_EXCL: dict[str, bool] = {}  # the SAME intervals the table prints
    for cell, sub in df.groupby('cell'):
        lib, backend = cell.split('|')
        tag = {'jsonwebtoken': 'Jsonwebtoken', 'fastjwt': 'Fastjwt', 'jose': 'Jose',
               'pyjwt': 'Pyjwt', 'golangjwt': 'Golangjwt', 'nimbus': 'Nimbus',
               'jjwt': 'Jjwt'}[lib]
        if backend.startswith('openssl 3.0'):
            tag += 'OldSsl'
        elif backend.startswith('openssl 3.5'):
            tag += 'NewSsl'
        ss = summarise(sub.assign(e='x'), rng, 'e', 'x', f'{lib}_string')
        pp = summarise(sub.assign(e='x'), rng, 'e', 'x', f'{lib}_preparsed')
        pen = paired(sub.assign(e='x'), rng, 'e', 'x', f'{lib}_string', f'{lib}_preparsed')
        if ss and pp and pen:
            put_triple(f'Xlib{tag}String', ss['est'], ss['lo'], ss['hi'], f)
            put_triple(f'Xlib{tag}Preparsed', pp['est'], pp['lo'], pp['hi'], f)
            put_triple(f'Xlib{tag}Penalty', pen['est'], pen['lo'], pen['hi'], f)
            put(f'Xlib{tag}Ratio', ss['est'] / pp['est'], f)
            # does the paired-difference interval exclude zero?
            excl = pen['lo'] > 0 or pen['hi'] < 0
            put(f'Xlib{tag}PenaltyExcludesZero', 'yes' if excl else 'no', f)
            PEN_EXCL.setdefault(lib, False)
            PEN_EXCL[lib] |= excl
        put(f'Xlib{tag}Version', str(sub['library_version'].iloc[0]).lstrip('v'), f)
        put(f'Xlib{tag}Runtime', str(sub['runtime'].iloc[0]).replace('_', r'\_'), f)
        put(f'Xlib{tag}Backend', re.sub(r' [0-9]+ [A-Z][a-z]+ [0-9]{4}$', '', re.sub(r'^openssl ', 'OpenSSL ', backend))
            .replace('hashlib/hmac OpenSSL', 'hashlib, OpenSSL').split('  ')[0]
            .replace('_', r'\_'), f)
    # which libraries have a per-call penalty whose interval excludes zero
    # (in any runtime)? counted per LIBRARY, not per (library, runtime) cell
    pos = {l for l, e in PEN_EXCL.items() if e}
    zero = {l for l, e in PEN_EXCL.items() if not e}
    words = ['none', 'one', 'two', 'three', 'four', 'five', 'six', 'seven']
    put('XlibPenaltyLibCount', words[len(pos)], f)
    put('XlibZeroPenaltyLibCount', words[len(zero)], f)
    put('XlibLibCount', words[len(pos | zero)], f)
    try:
        jo = float(np.median(df[(df.condition == 'jsonwebtoken_string') & df.crypto_backend.str.startswith('openssl 3.0')].median_us)) - \
             float(np.median(df[(df.condition == 'jsonwebtoken_preparsed') & df.crypto_backend.str.startswith('openssl 3.0')].median_us))
        js = float(np.median(df[(df.condition == 'jose_string') & df.crypto_backend.str.startswith('openssl 3.0')].median_us)) - \
             float(np.median(df[(df.condition == 'jose_preparsed') & df.crypto_backend.str.startswith('openssl 3.0')].median_us))
        put('XlibJwtOverJoseOldSsl', jo / js, f, '{:.0f}')
    except ZeroDivisionError:
        pass
else:
    MISSING.append('XlibJsonwebtokenNewSslString')

# =============================================================================
# Item 8 -- Tables 1 and 2 repeated on x86_64
# =============================================================================
def keypath_stats(run: Path) -> dict | None:
    js = run / 'keypath_stats.json'
    if not js.exists():
        subprocess.run([sys.executable, '-m', 'analysis.keypath_stats', '--run', str(run)],
                       cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return json.loads(js.read_text())


def kcond(st, env, c, field='median_of_medians_us'):
    try:
        return st['environments'][env]['conditions'][c][field]
    except (KeyError, TypeError):
        return None


def kci(st, env, c):
    try:
        return st['environments'][env]['conditions'][c]['ci95']
    except (KeyError, TypeError):
        return None


T1 = latest('keypath-mechanism')
if T1 and T1.name.startswith('2026-09-17'):
    T1 = None  # the arm64 run; the x86_64 repetition must be a newer one
if T1:
    st = keypath_stats(T1)
    p = T1 / 'keypath_stats.json'
    env = 'host'
    for macro, c in [('JwtString', 'jwt_hs_string'), ('JwtPreparsed', 'jwt_hs_preparsed'),
                     ('JwtStringSafe', 'jwt_hs_string_safe'), ('ProbeThrows', 'probe_throws'),
                     ('ProbeSucceeds', 'probe_succeeds'), ('CreateSecretKey', 'create_secret_key'),
                     ('HmacString', 'hmac_string'), ('HmacKeyObject', 'hmac_keyobject'),
                     ('DecodeOnly', 'decode_only'), ('TimerOverhead', 'timer_overhead')]:
        b = kci(st, env, c)
        put_triple('Xh' + macro, kcond(st, env, c), b[0] if b else None, b[1] if b else None, p)
    e = st['environments'][env]
    put('XhInvocations', e['conditions']['jwt_hs_string']['n_invocations'], p)
    put('XhCallsPerInvocation', e['conditions']['jwt_hs_string']['calls_per_invocation'], p)
    put('XhCvMax', max(c['between_invocation_cv_pct'] for c in e['conditions'].values()), p, '{:.1f}')
    put('XhNode', e['runtime']['node_version'][0].lstrip('v'), p)
    put('XhOpenssl', e['runtime']['openssl_version'][0], p)
    c = e['contrasts'].get('string_key_penalty_hs256')
    if c:
        put_triple('XhStringPenalty', c['median_diff_us'], c['ci95'][0], c['ci95'][1], p)
    put('XhProbeShareOfCall', 100 * kcond(st, env, 'probe_throws') / kcond(st, env, 'jwt_hs_string'), p, '{:.0f}')
    d = e.get('decomposition')
    if d:
        put('XhDecompExplainedPct', 100 * d['explained_fraction'], p, '{:.1f}')
    md = json.loads((T1 / 'run_metadata.json').read_text())
    # the metadata of run_keypath_mechanism.sh does not carry the CPU model;
    # it is the same machine as the revision's other runs
else:
    MISSING.append('XhJwtString')

T2 = latest('keypath-runtime-matrix')
if T2 and T2.name.startswith('2026-09-17'):
    T2 = None
if T2:
    st = keypath_stats(T2)
    p = T2 / 'keypath_stats.json'
    ENVS = {'XmEighteen': 'node:18.20.8-alpine', 'XmTwenty': 'node:20-alpine',
            'XmTwentySixMusl': 'node:26.6.0-alpine', 'XmTwentySixGlibc': 'node:26.6.0-bookworm'}
    for prefix, env in ENVS.items():
        if env not in st['environments']:
            MISSING.append(prefix + 'ProbeThrows')
            continue
        for macro, c in [('ProbeThrows', 'probe_throws'), ('ProbeSucceeds', 'probe_succeeds'),
                         ('JwtString', 'jwt_hs_string'), ('JwtPreparsed', 'jwt_hs_preparsed'),
                         ('HmacString', 'hmac_string'), ('DecodeOnly', 'decode_only')]:
            b = kci(st, env, c)
            if b and macro in ('ProbeThrows', 'JwtString', 'JwtPreparsed'):
                put_triple(prefix + macro, kcond(st, env, c), b[0], b[1], p)
            else:
                put(prefix + macro, kcond(st, env, c), p)
        rt = st['environments'][env]['runtime']
        put(prefix + 'Openssl', rt['openssl_version'][0], p)

    def span(c):
        vals = [kcond(st, e, c) for e in ENVS.values()]
        vals = [v for v in vals if v]
        return max(vals) / min(vals) if vals else None
    for macro, c in [('XmSpanProbeThrows', 'probe_throws'), ('XmSpanJwtPreparsed', 'jwt_hs_preparsed'),
                     ('XmSpanHmacString', 'hmac_string'), ('XmSpanDecodeOnly', 'decode_only'),
                     ('XmSpanProbeSucceeds', 'probe_succeeds')]:
        put(macro, span(c), p)
    put('XmInvocations', st['environments'][ENVS['XmEighteen']]['conditions']['probe_throws']['n_invocations'], p)
    put('XmCallsPerInvocation',
        st['environments'][ENVS['XmEighteen']]['conditions']['probe_throws']['calls_per_invocation'], p)
    envcsv = T2 / 'environments.csv'
    if envcsv.exists():
        ids = {r['image']: r for r in csv.DictReader(envcsv.open())}
        for prefix, env in ENVS.items():
            if env in ids:
                put(prefix + 'Arch', ids[env]['arch'], envcsv)
    # ordering check against the arm64 matrix: same rank order of probe_throws?
    arm = RUNS / '2026-09-17T08-57-13Z-keypath-runtime-matrix' / 'keypath_stats.json'
    if arm.exists():
        a = json.loads(arm.read_text())
        order_x = sorted(ENVS.values(), key=lambda e: kcond(st, e, 'probe_throws') or 0)
        order_a = sorted(ENVS.values(), key=lambda e: kcond(a, e, 'probe_throws') or 0)
        put('XmOrderingMatchesArm', 'the same' if order_x == order_a else 'a different', p)
        # the OpenSSL-series ordering is what the claim rests on: every 3.0 row
        # slower than every 3.5 row, on both architectures
        def series_split(s):
            old = [kcond(s, e, 'probe_throws') for e in ENVS.values()
                   if s['environments'][e]['runtime']['openssl_version'][0].startswith('3.0')]
            new = [kcond(s, e, 'probe_throws') for e in ENVS.values()
                   if not s['environments'][e]['runtime']['openssl_version'][0].startswith('3.0')]
            return min(old) > max(new)
        put('XmSeriesSplitHolds', 'holds' if series_split(st) and series_split(a) else 'does not hold', p)
else:
    MISSING.append('XmEighteenProbeThrows')

# =============================================================================
# Between-process dispersion of the x86_64-only runs (shared VM). The largest
# coefficient of variation of per-process medians across every condition that
# carries a claim; the timer-overhead rows are excluded (their CV is the clock's
# resolution, not the machine's noise). Added 2026-09-26.
# =============================================================================
def cv_max(csvpath: Path, keys: list[str], exclude=('timer_overhead',)):
    d = pd.read_csv(csvpath)
    d = d[~d['condition'].isin(exclude)]
    g = d.groupby(keys)['median_us']
    cv = 100 * g.std(ddof=1) / g.mean()
    return float(cv.max()), float(cv.median())

if C:
    _mx, _md = cv_max(C / 'openssl_c_probe.csv', ['openssl_requested', 'condition'])
    put('CProbeCvMedian', _md, C / 'openssl_c_probe.csv', '{:.1f}')
    put('CProbeCvMax', _mx,
        C / 'openssl_c_probe.csv', '{:.1f}')
if E:
    _mx, _md = cv_max(E / 'exception_cost.csv', ['environment', 'condition'])
    put('ExcCvMedian', _md, E / 'exception_cost.csv', '{:.1f}')
    put('ExcCvMax', _mx,
        E / 'exception_cost.csv', '{:.1f}')
if X:
    _mx, _md = cv_max(X / 'crosslib.csv', ['library', 'crypto_backend', 'condition'])
    put('XlibCvMedian', _md, X / 'crosslib.csv', '{:.1f}')
    put('XlibCvMax', _mx,
        X / 'crosslib.csv', '{:.1f}')

# =============================================================================
ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument('--out', default=str(ROOT / 'paper' / 'revision_macros.tex'))
args = ap.parse_args()
out = Path(args.out)
lines = ['% Generated by analysis/make_revision_macros.py -- do not edit by hand.',
         '% Each macro is read from the file named in revision_macros_provenance.csv.',
         r'\providecommand{\PLACEHOLDER}[1]{\textcolor{red}{\textbf{[#1]}}}']
for k in sorted(NUM):
    lines.append(f'\\newcommand{{\\{k}}}{{{NUM[k]}}}')
for k in sorted(set(MISSING) - set(NUM)):
    lines.append(f'\\newcommand{{\\{k}}}{{\\PLACEHOLDER{{{k}}}}}')
out.write_text('\n'.join(lines) + '\n')
with (out.parent / 'revision_macros_provenance.csv').open('w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['macro', 'value', 'source'])
    for k in sorted(NUM):
        w.writerow([k, NUM[k], SRC[k]])
print(f'{len(NUM)} macros, {len(set(MISSING) - set(NUM))} placeholders -> {out}')
for k in sorted(set(MISSING) - set(NUM)):
    print(f'  PLACEHOLDER {k}', file=sys.stderr)
