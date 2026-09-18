#!/usr/bin/env python3
"""make_keypath_macros.py -- LaTeX macros for the key-path manuscript.

Every macro is read out of a file under data/runs/ or survey/. Nothing is typed
in by hand. A quantity that is not in the data is emitted as \\PLACEHOLDER{key}
and shows up red in the compiled document rather than silently absent.

Macro names may not contain digits: LaTeX parses \\FooTen followed by literal
text, not \\Foo10. Numbers in names are spelled.

Usage:
  python3 -m analysis.make_keypath_macros [--out paper/keypath_macros.tex]
"""
from __future__ import annotations
import argparse, csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / 'data' / 'runs'
MECH = RUNS / '2026-09-17T08-42-17Z-keypath-mechanism'
MATRIX = RUNS / '2026-09-17T08-57-13Z-keypath-runtime-matrix'
SURVEY = ROOT / 'survey' / 'data'

NUM: dict[str, str] = {}
SRC: dict[str, str] = {}
MISSING: list[str] = []
# Declared here, resolved only if the measurement exists. Kept explicit so the
# manuscript's gaps are enumerable rather than discovered at compile time.
DECLARED_PLACEHOLDERS = {
    'xEightSixReplication':
        'x86_64 replication of the runtime matrix. Not performed: the Oracle '
        'Cloud instance was unreachable. See threats to validity.',
}


def put(name: str, value, source: Path, fmt='{:.2f}'):
    if re.search(r'\d', name):
        raise SystemExit(f'macro name contains a digit: {name}')
    if value is None:
        MISSING.append(name); return
    NUM[name] = fmt.format(value) if isinstance(value, float) else str(value)
    SRC[name] = str(Path(source).relative_to(ROOT))


def stats(run: Path) -> dict | None:
    p = run / 'keypath_stats.json'
    return json.loads(p.read_text()) if p.exists() else None


def cond(st, env, name, field='median_of_medians_us'):
    try:
        return st['environments'][env]['conditions'][name][field]
    except (KeyError, TypeError):
        return None


def ci(st, env, name):
    try:
        return st['environments'][env]['conditions'][name]['ci95']
    except (KeyError, TypeError):
        return None


# --- the mechanism run (host, arm64) ----------------------------------------
m = stats(MECH)
p = MECH / 'keypath_stats.json'
if m:
    for macro, c in [('HostJwtString', 'jwt_hs_string'),
                     ('HostJwtPreparsed', 'jwt_hs_preparsed'),
                     ('HostJwtStringSafe', 'jwt_hs_string_safe'),
                     ('HostProbeThrows', 'probe_throws'),
                     ('HostProbeSucceeds', 'probe_succeeds'),
                     ('HostCreateSecretKey', 'create_secret_key'),
                     ('HostHmacString', 'hmac_string'),
                     ('HostHmacKeyObject', 'hmac_keyobject'),
                     ('HostDecodeOnly', 'decode_only'),
                     ('HostTimerOverhead', 'timer_overhead'),
                     ('HostJwtRsPemString', 'jwt_rs_pem_string'),
                     ('HostJwtRsPreparsed', 'jwt_rs_preparsed')]:
        put(macro, cond(m, 'host', c), p, '{:.3f}' if c in ('create_secret_key', 'timer_overhead') else '{:.2f}')
        b = ci(m, 'host', c)
        if b:
            put(macro + 'CiLo', b[0], p, '{:.2f}'); put(macro + 'CiHi', b[1], p, '{:.2f}')
    env = m['environments']['host']
    put('HostInvocations', env['conditions']['jwt_hs_string']['n_invocations'], p)
    put('HostCallsPerInvocation', env['conditions']['jwt_hs_string']['calls_per_invocation'], p)
    cvs = [c['between_invocation_cv_pct'] for c in env['conditions'].values()]
    put('HostCvMax', max(cvs), p, '{:.1f}')
    for macro, key in [('HostStringPenalty', 'string_key_penalty_hs256'),
                       ('HostSafePatchSaving', 'safe_patch_saving_hs256'),
                       ('HostSafePatchResidual', 'safe_patch_residual'),
                       ('HostRsStringPenalty', 'string_key_penalty_rs256')]:
        c = env['contrasts'].get(key)
        if c:
            put(macro, c['median_diff_us'], p)
            put(macro + 'CiLo', c['ci95'][0], p); put(macro + 'CiHi', c['ci95'][1], p)
            put(macro + 'Rounds', c['n_rounds'], p)
    d = env.get('decomposition')
    if d:
        put('DecompObserved', d['observed_penalty_us']['median'], p)
        put('DecompPredicted', d['predicted_from_parts_us']['median'], p)
        put('DecompResidual', d['residual_us']['median'], p)
        put('DecompResidualCiLo', d['residual_us']['ci95'][0], p)
        put('DecompResidualCiHi', d['residual_us']['ci95'][1], p)
        put('DecompExplainedPct', 100 * d['explained_fraction'], p, '{:.1f}')
    put('HostProbeShareOfCall',
        100 * cond(m, 'host', 'probe_throws') / cond(m, 'host', 'jwt_hs_string'), p, '{:.0f}')
    put('HostSafePatchRatio',
        cond(m, 'host', 'jwt_hs_string') / cond(m, 'host', 'jwt_hs_string_safe'), p)
else:
    for n in ('HostJwtString', 'HostProbeThrows', 'HostJwtPreparsed'):
        MISSING.append(n)

# --- the runtime matrix (containers, arm64) ---------------------------------
mx = stats(MATRIX)
pm = MATRIX / 'keypath_stats.json'
ENVS = {'NodeEighteen': 'node:18.20.8-alpine', 'NodeTwenty': 'node:20-alpine',
        'NodeTwentySixMusl': 'node:26.6.0-alpine',
        'NodeTwentySixGlibc': 'node:26.6.0-bookworm'}
if mx:
    for prefix, env in ENVS.items():
        for macro, c in [('ProbeThrows', 'probe_throws'), ('ProbeSucceeds', 'probe_succeeds'),
                         ('JwtString', 'jwt_hs_string'), ('JwtPreparsed', 'jwt_hs_preparsed'),
                         ('HmacString', 'hmac_string'), ('DecodeOnly', 'decode_only')]:
            put(prefix + macro, cond(mx, env, c), pm)
            b = ci(mx, env, c)
            if b and macro == 'ProbeThrows':
                put(prefix + macro + 'CiLo', b[0], pm); put(prefix + macro + 'CiHi', b[1], pm)
        rt = mx['environments'][env]['runtime']
        put(prefix + 'OpensslLiteral', rt['openssl_version'][0], pm)
        # Version labels are read from the data too, so that a runtime relabelled
        # in the matrix cannot silently disagree with the prose describing it.
        put(prefix + 'NodeLiteral', rt['node_version'][0].lstrip('v'), pm)
        put(prefix + 'NodeMajor', rt['node_version'][0].lstrip('v').split('.')[0], pm)
        put(prefix + 'OpensslSeries',
            '.'.join(rt['openssl_version'][0].split('.')[:2]), pm)
    # spans across every environment measured, host included
    allenvs = {**{v: mx for v in ENVS.values()}}
    def span(c):
        vals = [cond(mx, e, c) for e in ENVS.values()] + ([cond(m, 'host', c)] if m else [])
        vals = [v for v in vals if v]
        return max(vals) / min(vals) if vals else None
    for macro, c in [('SpanProbeThrows', 'probe_throws'), ('SpanJwtPreparsed', 'jwt_hs_preparsed'),
                     ('SpanHmacString', 'hmac_string'), ('SpanDecodeOnly', 'decode_only'),
                     ('SpanProbeSucceeds', 'probe_succeeds')]:
        put(macro, span(c), pm)
    put('MatrixInvocations',
        mx['environments'][ENVS['NodeEighteen']]['conditions']['probe_throws']['n_invocations'], pm)
    put('MatrixCallsPerInvocation',
        mx['environments'][ENVS['NodeEighteen']]['conditions']['probe_throws']['calls_per_invocation'], pm)
    # containerisation, held at Node 26: container glibc against the macOS host
    if m:
        put('ContainerVersusHostRatio',
            cond(mx, 'node:26.6.0-bookworm', 'probe_throws') / cond(m, 'host', 'probe_throws'), pm)

# --- cpu profile -------------------------------------------------------------
for macro, f in [('ProfEighteenPct', MATRIX / 'cpuprof_node_18_20_8-alpine.csv'),
                 ('ProfTwentySixPct', MATRIX / 'cpuprof_node_26_6_0-alpine.csv'),
                 ('ProfHostPct', MECH / 'cpuprof_jwt_hs_string.csv')]:
    if f.exists():
        r = list(csv.DictReader(f.open()))
        top = next((x for x in r if 'createPublicKey' in x['function']), None)
        put(macro, float(top['self_pct']) if top else None, f, '{:.1f}')
    else:
        MISSING.append(macro)

# --- survey ------------------------------------------------------------------
pc = SURVEY / 'population_counts.csv'
if pc.exists():
    rows = {r['query']: int(r['total_count']) for r in csv.DictReader(pc.open()) if r['total_count']}
    def g(q): return rows.get(q)
    js, jsk = g("require('jsonwebtoken') language:javascript"), g("require('jsonwebtoken') createSecretKey language:javascript")
    ts, tsk = g("from 'jsonwebtoken' language:typescript"), g("from 'jsonwebtoken' createSecretKey language:typescript")
    put('PopJsFiles', js, pc); put('PopJsKeyObject', jsk, pc)
    put('PopTsFiles', ts, pc); put('PopTsKeyObject', tsk, pc)
    if None not in (js, jsk, ts, tsk):
        put('PopTotalFiles', js + ts, pc)
        put('PopTotalKeyObject', jsk + tsk, pc)
        put('PopKeyObjectPct', 100 * (jsk + tsk) / (js + ts), pc, '{:.3f}')
        put('PopOneIn', round((js + ts) / (jsk + tsk)), pc)

cs = SURVEY / 'callsites.csv'
if cs.exists():
    rows = list(csv.DictReader(cs.open()))
    put('SampleCallSites', len(rows), cs)
    put('SampleRepos', len({r['repo'] for r in rows}), cs)
    for bucket, macro in [('env_string', 'SampleEnvString'), ('unknown', 'SampleUnknown'),
                          ('string_literal', 'SampleStringLiteral'),
                          ('file_contents', 'SampleFileContents'), ('buffer', 'SampleBuffer')]:
        put(macro, sum(1 for r in rows if r['bucket'] == bucket), cs)
    put('SampleKeyObject', sum(1 for r in rows if r['bucket'] == 'keyobject'), cs)
    unspec = sum(1 for r in rows if r['algorithms'] == 'unspecified')
    put('SampleNoAlgorithms', unspec, cs)
    put('SampleNoAlgorithmsPct', 100 * unspec / len(rows), cs, '{:.0f}')

ha = SURVEY / 'hand_adjudication.csv'
if ha.exists():
    rows = list(csv.DictReader(ha.open()))
    put('AdjudicatedTotal', len(rows), ha)
    gen = [r for r in rows if r['verdict'] == 'genuine']
    put('AdjudicatedGenuine', len(gen), ha)
    put('AdjudicatedGenuineProjects', len({r['repo'] for r in gen}), ha)
    put('AdjudicatedFalsePositive', sum(1 for r in rows if r['verdict'] == 'false_positive'), ha)
    put('AdjudicatedUnresolved', sum(1 for r in rows if r['verdict'] == 'unresolved'), ha)

ce = SURVEY / 'counterexamples.json'
if ce.exists():
    recs = json.loads(ce.read_text())
    put('CounterFilesFetched', len(recs), ce)
    put('CounterWithVerify', sum(1 for r in recs if r['verify_calls'] > 0), ce)

# --- emit --------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'paper' / 'keypath_macros.tex'))
    ap.add_argument('--map', default=str(ROOT / 'paper' / 'keypath_macros_provenance.csv'))
    a = ap.parse_args()

    lines = [
        '% keypath_macros.tex -- GENERATED. Do not edit.',
        '% Regenerate: .venv/bin/python -m analysis.make_keypath_macros',
        '% Every value below is read from a file under data/runs/ or survey/.',
        '\\providecommand{\\PLACEHOLDER}[1]{\\textcolor{red}{\\textbf{[MISSING: #1]}}}',
        '',
    ]
    for k in sorted(NUM):
        lines.append('\\newcommand{\\%s}{%s}%% %s' % (k, NUM[k], SRC[k]))
    lines.append('')
    lines.append('% --- declared but unmeasured ------------------------------------------')
    for k, why in sorted(DECLARED_PLACEHOLDERS.items()):
        lines.append('%% %s: %s' % (k, why))
        lines.append('\\newcommand{\\%s}{\\PLACEHOLDER{%s}}' % (k, k))
    if MISSING:
        lines.append('')
        lines.append('% --- expected but absent from the data ---------------------------------')
        for k in sorted(set(MISSING)):
            lines.append('\\newcommand{\\%s}{\\PLACEHOLDER{%s}}' % (k, k))
    Path(a.out).write_text('\n'.join(lines) + '\n')

    with open(a.map, 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(['macro', 'value', 'source'])
        for k in sorted(NUM):
            w.writerow([k, NUM[k], SRC[k]])
        for k in sorted(DECLARED_PLACEHOLDERS):
            w.writerow([k, 'PLACEHOLDER', DECLARED_PLACEHOLDERS[k]])
        for k in sorted(set(MISSING)):
            w.writerow([k, 'PLACEHOLDER', 'expected but absent from the data'])

    print(f'{len(NUM)} macros defined, '
          f'{len(DECLARED_PLACEHOLDERS)} declared placeholders, '
          f'{len(set(MISSING))} unexpectedly missing')
    for k in sorted(set(MISSING)):
        print(f'  MISSING: {k}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
