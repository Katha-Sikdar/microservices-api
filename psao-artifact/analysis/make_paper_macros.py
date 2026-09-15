#!/usr/bin/env python3
"""make_paper_macros.py -- LaTeX macros for the token-validation cost paper.

Every numeric claim in paper/not-the-cryptography.tex resolves to a macro defined
here, and every macro here is read out of a file under data/runs/. Nothing is
typed in by hand, and a quantity that is not in the data is emitted as
\\PLACEHOLDER{key} rather than guessed.

The provenance map this prints (--map) is the audit trail: macro -> source file.
"""
from __future__ import annotations

import argparse, csv, json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / 'data' / 'runs'

NUM = {}      # macro name -> formatted value
SRC = {}      # macro name -> source file (repo-relative)
MISSING = []


def put(name: str, value, source: Path, fmt: str = '{:.2f}'):
    if value is None:
        MISSING.append(name)
        return
    NUM[name] = fmt.format(value) if isinstance(value, float) else str(value)
    SRC[name] = str(Path(source).relative_to(ROOT))


def words(n: int) -> str:
    w = {0: 'Zero', 1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five',
         10: 'Ten', 25: 'TwentyFive', 50: 'Fifty', 100: 'Hundred',
         200: 'TwoHundred', 400: 'FourHundred'}
    return w.get(n, str(n))


# --- in-situ rate sweeps ----------------------------------------------------
SWEEPS = {
    'HsString':    '2026-09-14T05-57-22Z-verifyrate-hs256',
    'HsPreparsed': '2026-09-14T15-01-36Z-verifyrate-hs256-preparsed',
    'RsPreparsed': '2026-09-14T06-41-56Z-verifyrate-rs256',
}

sweep_data = {}
for tag, d in SWEEPS.items():
    path = RUNS / d / 'verify_rate_curve.csv'
    if not path.exists():
        MISSING.append(f'sweep:{tag}')
        continue
    rows = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            rows.setdefault(r['pass'], {})[int(r['rate_rps'])] = r
    sweep_data[tag] = rows
    for pass_name in ('asc', 'desc'):
        for rate, r in rows.get(pass_name, {}).items():
            p = 'Asc' if pass_name == 'asc' else 'Desc'
            base = f'Vr{tag}{p}{words(rate)}'
            put(base + 'Mean', float(r['verify_mean_us']), path)
            put(base + 'PFifty', float(r['verify_p50_us']), path)
            put(base + 'PNinetyNine', float(r['verify_p99_us']), path)
            put(base + 'Count', int(r['verify_count']), path)
            if r['host_load1']:
                put(base + 'Load', float(r['host_load1']), path, '{:.2f}')

# saving from pre-parsing, per rate
if 'HsString' in sweep_data and 'HsPreparsed' in sweep_data:
    p1 = RUNS / SWEEPS['HsString'] / 'verify_rate_curve.csv'
    for rate in sorted(sweep_data['HsString'].get('asc', {})):
        a = sweep_data['HsString']['asc'].get(rate)
        b = sweep_data['HsPreparsed']['asc'].get(rate)
        if not (a and b):
            continue
        am, bm = float(a['verify_mean_us']), float(b['verify_mean_us'])
        put(f'VrSaved{words(rate)}', am - bm, p1)
        put(f'VrRatio{words(rate)}', am / bm, p1, '{:.1f}')
        put(f'VrConvPct{words(rate)}', 100.0 * (am - bm) / am, p1, '{:.0f}')

# RS256 / HS256 like for like
if 'RsPreparsed' in sweep_data and 'HsPreparsed' in sweep_data:
    p2 = RUNS / SWEEPS['RsPreparsed'] / 'verify_rate_curve.csv'
    for rate in sorted(sweep_data['RsPreparsed'].get('asc', {})):
        a = sweep_data['RsPreparsed']['asc'].get(rate)
        b = sweep_data['HsPreparsed']['asc'].get(rate)
        if not (a and b):
            continue
        put(f'VrAlgRatio{words(rate)}',
            float(a['verify_mean_us']) / float(b['verify_mean_us']), p2, '{:.2f}')

# ascending vs descending agreement (the JIT-warmth control)
if 'HsString' in sweep_data:
    p3 = RUNS / SWEEPS['HsString'] / 'verify_rate_curve.csv'
    worst = 0.0
    for rate in sweep_data['HsString'].get('asc', {}):
        a = sweep_data['HsString']['asc'].get(rate)
        d = sweep_data['HsString'].get('desc', {}).get(rate)
        if a and d:
            am, dm = float(a['verify_mean_us']), float(d['verify_mean_us'])
            worst = max(worst, abs(dm - am) / am * 100.0)
    put('VrPassAgreementPct', worst, p3, '{:.1f}')

# --- isolated microbenchmark ------------------------------------------------
MB = RUNS / '2026-09-13T20-34-41Z-microbench' / 'microbench.csv'
if MB.exists():
    rows = list(csv.DictReader(open(MB)))
    for alg in ('HS256', 'RS256'):
        for kb, tagkb in (('0.5', 'HalfKb'), ('2', 'TwoKb'), ('4', 'FourKb')):
            d = {r['stage']: r for r in rows
                 if r['algorithm'] == alg and r['payload_kb'] == kb}
            if not d:
                continue
            a = 'Hs' if alg == 'HS256' else 'Rs'
            full = float(d['full_verify']['mean_us'])
            dec = float(d['decode_only']['mean_us'])
            cry = float(d['primitive_preparsed']['mean_us'])
            put(f'Mb{a}{tagkb}Full', full, MB)
            put(f'Mb{a}{tagkb}Decode', dec, MB, '{:.3f}')
            put(f'Mb{a}{tagkb}Primitive', cry, MB, '{:.3f}')
            put(f'Mb{a}{tagkb}Residual', full - dec - cry, MB)
            put(f'Mb{a}{tagkb}PrimitivePct', 100.0 * cry / full, MB, '{:.1f}')
            put(f'Mb{a}{tagkb}ResidualPct', 100.0 * (full - dec - cry) / full, MB, '{:.1f}')
            put(f'Mb{a}{tagkb}Iterations', int(d['full_verify']['iterations']), MB)

SPREAD = RUNS / '2026-09-13T20-34-41Z-microbench' / 'microbench.spread.txt'
if SPREAD.exists():
    worst_full, worst_any = 0.0, 0.0
    for line in open(SPREAD):
        parts = line.strip().split(',')
        if len(parts) < 5:
            continue
        stage, spread = parts[1], float(parts[4])
        worst_any = max(worst_any, spread)
        if stage == 'full_verify':
            worst_full = max(worst_full, spread)
    put('MbFullVerifySpreadPct', worst_full, SPREAD, '{:.1f}')
    put('MbWorstStageSpreadPct', worst_any, SPREAD, '{:.1f}')

# --- inter-arrival gap ------------------------------------------------------
GAP = RUNS / 'MECHANISM-2026-09-14-interarrival-gap' / 'gap_keyform_incontainer.csv'
if GAP.exists():
    for r in csv.DictReader(open(GAP)):
        gap = r['gap_ms']
        # LaTeX control sequences are letters only, so gap values are spelled
        # out. A macro named \Gap10MsString would silently parse as \Gap
        # followed by the literal text "10MsString".
        gapword = {'0': 'Tight', '1': 'GapOneMs', '2': 'GapTwoMs', '5': 'GapFiveMs',
                   '10': 'GapTenMs', '20': 'GapTwentyMs', '50': 'GapFiftyMs',
                   '100': 'GapHundredMs', '200': 'GapTwoHundredMs'}
        tag = gapword.get(gap)
        if tag is None:
            continue
        put(f'{tag}String', float(r['string_secret_us']), GAP)
        put(f'{tag}Preparsed', float(r['preparsed_key_us']), GAP)
        put(f'{tag}KeyRatio', float(r['ratio']), GAP, '{:.1f}')
    rows = list(csv.DictReader(open(GAP)))
    if rows:
        t, w = rows[0], rows[-1]
        put('GapEffectStringRatio',
            float(w['string_secret_us']) / float(t['string_secret_us']), GAP, '{:.1f}')
        put('GapEffectPreparsedRatio',
            float(w['preparsed_key_us']) / float(t['preparsed_key_us']), GAP, '{:.1f}')

# --- CPU A/B: verification on vs off ---------------------------------------
def ramp_row(d):
    p = RUNS / d / 'openloop_ramp.csv'
    if not p.exists():
        return None, p
    rows = list(csv.DictReader(open(p)))
    return (rows[0] if rows else None), p

jwt_row, jwt_p = ramp_row('INSITU-AB-authmode-jwt')
non_row, non_p = ramp_row('INSITU-AB-authmode-none')
if jwt_row and non_row:
    cj, cn = float(jwt_row['cpu_app_millicores']), float(non_row['cpu_app_millicores'])
    rate = float(jwt_row['achieved_rps'])
    put('AbCpuJwt', cj, jwt_p)
    put('AbCpuNone', cn, non_p)
    put('AbCpuDelta', cj - cn, jwt_p)
    put('AbRate', rate, jwt_p, '{:.0f}')
    put('AbCpuPerRequestUs', (cj - cn) / rate * 1000.0, jwt_p, '{:.1f}')
    put('AbLatencyJwt', float(jwt_row['latency_mean_ms']), jwt_p, '{:.4f}')
    put('AbLatencyNone', float(non_row['latency_mean_ms']), non_p, '{:.4f}')

# --- client vs server latency ----------------------------------------------
INSITU = RUNS / 'INSITU-2026-09-14-verify-cost'
def prom_delta(metric, filt=None):
    b, a = INSITU / 'before.prom', INSITU / 'after.prom'
    if not (b.exists() and a.exists()):
        return None
    def agg(path):
        s = c = 0.0
        for line in open(path):
            if line.startswith('#') or not line.startswith(metric):
                continue
            if filt and filt not in line:
                continue
            try:
                v = float(line.rsplit(' ', 1)[1])
            except (IndexError, ValueError):
                continue
            if line.startswith(metric + '_sum'):
                s += v
            elif line.startswith(metric + '_count'):
                c += v
        return s, c
    s0, c0 = agg(b); s1, c1 = agg(a)
    return (1e6 * (s1 - s0) / (c1 - c0)) if (c1 - c0) > 0 else None

hv = prom_delta('psao_verify_duration_seconds', 'algorithm="HS256",result="ok"')
hh = prom_delta('psao_request_duration_seconds')
put('InsituVerifyMean', hv, INSITU / 'after.prom')
put('InsituHandlerMean', hh, INSITU / 'after.prom')
ir = ramp_row('INSITU-2026-09-14-verify-cost')[0]
if ir:
    cl = float(ir['latency_mean_ms']) * 1000.0
    put('InsituClientMean', cl, RUNS / 'INSITU-2026-09-14-verify-cost' / 'openloop_ramp.csv', '{:.0f}')
    if hh:
        put('InsituAppSharePct', 100.0 * hh / cl,
            RUNS / 'INSITU-2026-09-14-verify-cost' / 'openloop_ramp.csv', '{:.0f}')

# --- key-form isolation, in container --------------------------------------
# All four algorithm x key-form combinations, measured in one process inside the
# deployed container so the only variable is how the key reaches jwt.verify().
KF = RUNS / 'KEYFORM-2026-09-14' / 'keyform_incontainer.csv'
if KF.exists():
    kf = {}
    for r in csv.DictReader(open(KF)):
        a = 'Hs' if r['algorithm'] == 'HS256' else 'Rs'
        f = 'String' if r['key_form'] == 'string' else 'Preparsed'
        kf[(a, f)] = float(r['mean_us'])
        put(f'Kf{a}{f}', float(r['mean_us']), KF, '{:.2f}')
        put(f'Kf{a}{f}PFifty', float(r['p50_us']), KF, '{:.2f}')
        put(f'Kf{a}{f}Iterations', int(r['iterations']), KF)
    for a in ('Hs', 'Rs'):
        if (a, 'String') in kf and (a, 'Preparsed') in kf:
            put(f'Kf{a}Ratio', kf[(a, 'String')] / kf[(a, 'Preparsed')], KF, '{:.1f}')
            put(f'Kf{a}ConvPct',
                100.0 * (kf[(a, 'String')] - kf[(a, 'Preparsed')]) / kf[(a, 'String')],
                KF, '{:.1f}')
    if ('Rs', 'Preparsed') in kf and ('Hs', 'Preparsed') in kf:
        put('KfAlgRatioPreparsed',
            kf[('Rs', 'Preparsed')] / kf[('Hs', 'Preparsed')], KF, '{:.1f}')
    if ('Rs', 'String') in kf and ('Hs', 'String') in kf:
        put('KfAlgRatioString',
            kf[('Rs', 'String')] / kf[('Hs', 'String')], KF, '{:.2f}')

# --- environment ------------------------------------------------------------
META = RUNS / '2026-09-14T15-01-36Z-verifyrate-hs256-preparsed' / 'run_metadata.json'
if META.exists():
    m = json.load(open(META))
    nv = (m.get('node_version') or '').lstrip('v')
    if nv:
        NUM['EnvNodeVersion'] = nv
        SRC['EnvNodeVersion'] = str(META.relative_to(ROOT))
    kv = (m.get('kubernetes_version') or {}).get('serverVersion', {}).get('gitVersion')
    if kv:
        NUM['EnvKubernetesVersion'] = kv.lstrip('v')
        SRC['EnvKubernetesVersion'] = str(META.relative_to(ROOT))


# --- rate labels -------------------------------------------------------------
# The rate points are experiment parameters, so they are emitted as macros too
# rather than typed into the prose. The sweep's own parameter record is the
# source: if the sweep is re-run at different rates, the prose follows.
RATE_META = RUNS / SWEEPS['HsPreparsed'] / 'run_metadata.json' if 'HsPreparsed' in SWEEPS else None
if RATE_META and RATE_META.exists():
    meta = json.load(open(RATE_META))
    spec = (meta.get('run_parameters') or {}).get('rates', '')
    for tok in spec.split():
        if tok.isdigit():
            NUM[words(int(tok))] = tok
            SRC[words(int(tok))] = str(RATE_META.relative_to(ROOT))

# in-situ vs isolated, the headline ratio
if 'InsituVerifyMean' in NUM and 'MbHsHalfKbFull' in NUM:
    try:
        r = float(NUM['InsituVerifyMean']) / float(NUM['MbHsHalfKbFull'])
        NUM['InsituVersusMicrobenchRatio'] = '{:.1f}'.format(r)
        SRC['InsituVersusMicrobenchRatio'] = SRC['InsituVerifyMean'] + ' + ' + SRC['MbHsHalfKbFull']
    except ValueError:
        MISSING.append('InsituVersusMicrobenchRatio')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'paper' / 'paper_macros.tex'))
    ap.add_argument('--map', default=str(ROOT / 'paper' / 'paper_macros_provenance.csv'))
    args = ap.parse_args()

    lines = [
        '% paper_macros.tex -- GENERATED. Do not edit by hand.',
        '% Regenerate: .venv/bin/python analysis/make_paper_macros.py',
        '% Every macro below is read out of a file under data/runs/; the',
        '% macro -> file map is in paper_macros_provenance.csv.',
        '',
        '\\providecommand{\\PLACEHOLDER}[1]{\\textcolor{red}{[MISSING: #1]}}',
        '',
    ]
    bad = [k for k in NUM if not k.isalpha()]
    if bad:
        raise SystemExit('macro names must be letters only (LaTeX control '
                         'sequences cannot contain digits): ' + ', '.join(sorted(bad)))
    for k in sorted(NUM):
        lines.append('\\newcommand{\\%s}{%s}%% %s' % (k, NUM[k], SRC[k]))
    for k in sorted(set(MISSING)):
        lines.append('\\newcommand{\\%s}{\\PLACEHOLDER{%s}}' % (k, k))
    Path(args.out).write_text('\n'.join(lines) + '\n')

    with open(args.map, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['macro', 'value', 'source_file'])
        for k in sorted(NUM):
            w.writerow([k, NUM[k], SRC[k]])
        for k in sorted(set(MISSING)):
            w.writerow([k, 'PLACEHOLDER', ''])

    print(f'{len(NUM)} macros defined, {len(set(MISSING))} placeholders')
    print(f'wrote {args.out}')
    print(f'wrote {args.map}')
    if MISSING:
        print('placeholders: ' + ', '.join(sorted(set(MISSING))))


if __name__ == '__main__':
    sys.exit(main())
