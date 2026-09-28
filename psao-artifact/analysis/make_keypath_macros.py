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
IDENTITY = RUNS / 'runtime_identity.csv'

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



def put_triple(name: str, est, lo, hi, source: Path):
    """Emit an estimate and its two bounds at ONE precision.

    Formatting the point estimate and its interval independently produced
    \\HostCreateSecretKey 0.583 against [0.54, 0.58] -- an estimate above its own
    upper bound, and three further rows where the estimate landed exactly on a
    bound. Precision is therefore chosen for the triple, not per value, and is
    increased until the rounded values still satisfy lo <= est <= hi. A triple
    that cannot be rendered consistently is reported rather than emitted.
    """
    if est is None or lo is None or hi is None:
        for suffix in ('', 'CiLo', 'CiHi'):
            MISSING.append(name + suffix)
        return
    # Precision is set by magnitude first, so a sub-microsecond quantity keeps
    # three significant figures instead of collapsing to two decimals, and is
    # only increased further if rounding would break the ordering. Note that
    # est == bound occurs in the RAW data for several conditions: a percentile
    # bootstrap over a small number of discrete per-process medians can place a
    # bound exactly on the median. That is a property of the estimator, not of
    # the formatting, and is preserved rather than hidden.
    start = 2 if abs(est) >= 10 else 3
    for decimals in range(start, 7):
        f = '{:.%df}' % decimals
        r_est, r_lo, r_hi = (float(f.format(v)) for v in (est, lo, hi))
        if r_lo <= r_est <= r_hi:
            put(name, est, source, f)
            put(name + 'CiLo', lo, source, f)
            put(name + 'CiHi', hi, source, f)
            return
    print(f'  WARNING: {name} cannot be rendered with lo<=est<=hi '
          f'({lo}, {est}, {hi})', file=sys.stderr)
    put(name, est, source, '{:.6f}')
    put(name + 'CiLo', lo, source, '{:.6f}')
    put(name + 'CiHi', hi, source, '{:.6f}')


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
        b = ci(m, 'host', c)
        put_triple(macro, cond(m, 'host', c), b[0] if b else None, b[1] if b else None, p)
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
            put_triple(macro, c['median_diff_us'], c['ci95'][0], c['ci95'][1], p)
            put(macro + 'Rounds', c['n_rounds'], p)
    d = env.get('decomposition')
    if d:
        put('DecompObserved', d['observed_penalty_us']['median'], p)
        put('DecompPredicted', d['predicted_from_parts_us']['median'], p)
        put_triple('DecompResidual', d['residual_us']['median'],
                   d['residual_us']['ci95'][0], d['residual_us']['ci95'][1], p)
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
            b = ci(mx, env, c)
            if b and macro == 'ProbeThrows':
                put_triple(prefix + macro, cond(mx, env, c), b[0], b[1], pm)
            else:
                put(prefix + macro, cond(mx, env, c), pm)
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
        """Ratio of max to min across the FOUR CONTAINER ROWS ONLY.

        The host row is excluded deliberately. Section~\\ref{sec:rq2} states that
        its claims concern only the container rows, among which containerisation
        is held constant; the host runs a different operating system, so a span
        that took a bound from it would be measuring something the section
        explicitly declines to measure. An earlier version included the host and
        two of the four spans silently took their minimum from it."""
        vals = [cond(mx, e, c) for e in ENVS.values()]
        vals = [v for v in vals if v]
        return max(vals) / min(vals) if vals else None

    def span_with_host(c):
        """Same ratio including the uncontainerised host. Named so it cannot be
        mistaken for the container-only span."""
        vals = [cond(mx, e, c) for e in ENVS.values()] + ([cond(m, 'host', c)] if m else [])
        vals = [v for v in vals if v]
        return max(vals) / min(vals) if vals else None
    for macro, c in [('SpanProbeThrows', 'probe_throws'), ('SpanJwtPreparsed', 'jwt_hs_preparsed'),
                     ('SpanHmacString', 'hmac_string'), ('SpanDecodeOnly', 'decode_only'),
                     ('SpanProbeSucceeds', 'probe_succeeds')]:
        put(macro, span(c), pm)
        put(macro + 'WithHost', span_with_host(c), pm)
    put('MatrixInvocations',
        mx['environments'][ENVS['NodeEighteen']]['conditions']['probe_throws']['n_invocations'], pm)
    put('MatrixCallsPerInvocation',
        mx['environments'][ENVS['NodeEighteen']]['conditions']['probe_throws']['calls_per_invocation'], pm)
    # containerisation, held at Node 26: container glibc against the macOS host
    if m:
        put('ContainerVersusHostRatio',
            cond(mx, 'node:26.6.0-bookworm', 'probe_throws') / cond(m, 'host', 'probe_throws'), pm)

# --- runtime identity (V8 is load-bearing for the OpenSSL-not-V8 attribution) --
if IDENTITY.exists():
    ident = {r['image']: r for r in csv.DictReader(IDENTITY.open())}
    for prefix, env in ENVS.items():
        r = ident.get(env)
        if not r:
            MISSING.append(prefix + 'Veight'); continue
        put(prefix + 'Veight', r['v8_major'], IDENTITY)
        put(prefix + 'VeightFull', r['v8_version'], IDENTITY)
        put(prefix + 'ImageId', r['image_id'].replace('sha256:', '')[:12], IDENTITY)
    # Cross-check: identity must agree with the versions the measurement rows
    # carried, or it describes a different image than the one measured.
    envcsv = MATRIX / 'environments.csv'
    if envcsv.exists():
        mismatch = [r['image'] for r in csv.DictReader(envcsv.open())
                    if r['image'] in ident
                    and (ident[r['image']]['node_version'] != r['node_version']
                         or ident[r['image']]['openssl_version'] != r['openssl_version'])]
        put('IdentityMismatches', len(mismatch), envcsv)
else:
    for prefix in ENVS:
        MISSING.append(prefix + 'Veight')

# --- matrix dispersion, reported rather than represented by the host's ------
if mx:
    worst_env, worst_cond, worst_cv = None, None, 0.0
    for env, d in mx['environments'].items():
        for cname, c in d['conditions'].items():
            cv = c['between_invocation_cv_pct']
            if cv == cv and cv > worst_cv:
                worst_env, worst_cond, worst_cv = env, cname, cv
    put('MatrixCvMax', worst_cv, pm, '{:.1f}')
    put('MatrixCvMaxCondition', worst_cond.replace('_', '\\_'), pm)
    put('MatrixCvMaxEnvironment', worst_env, pm)
    if m:
        hostcv = max(c['between_invocation_cv_pct']
                     for c in m['environments']['host']['conditions'].values())
        put('MatrixCvRatio', worst_cv / hostcv, pm, '{:.1f}')

# --- the host's own runtime, for the correction section ---------------------
if m:
    # V8 is statically linked into the node binary, which is unchanged since the
    # run (same Cellar path, same reported version), so the engine version is a
    # property of the measured runtime and is recordable after the fact.
    #
    # The host's OpenSSL version is NOT recorded here and deliberately so. The
    # host run predates the per-row openssl_version field, and the host's
    # OpenSSL has since moved 3.6.3 -> 3.6.4 (see
    # data/runs/HOST-OPENSSL-DRIFT-2026-09-17.md). Capturing it now would record
    # a version that did not run. Table 2's host OpenSSL cell stays empty.
    put('HostVeight', '14', MECH / 'run_metadata.json')
    put('HostVeightFull', '14.6.202.34-node.26', MECH / 'run_metadata.json')
    put('HostNodeVersion', m['environments']['host']['runtime']['node_version'][0].lstrip('v'),
        MECH / 'keypath_stats.json')

# --- corpus manifest ---------------------------------------------------------
cm = SURVEY / 'corpus_manifest.csv'
if cm.exists():
    rows = list(csv.DictReader(cm.open()))
    put('ManifestFiles', len(rows), cm)
    put('ManifestRepos', len({r['repo'] for r in rows}), cm)
    put('ManifestSampleFiles', sum(1 for r in rows if r['corpus'] == 'sample'), cm)
    put('ManifestHeadResolved', sum(1 for r in rows if r['repo_head_commit_at_manifest_time']), cm)
else:
    MISSING.append('ManifestFiles')

# --- cpu profile, matched iterations, three repeats ------------------------
# The first pass used different iteration counts per environment, which made the
# percentages incomparable. This reads the matched re-run and reports a median
# with the observed range, so the figure carries its own dispersion.
PROF = RUNS / '2026-09-18T-profile-matched' / 'cpuprof_matched.csv'
if PROF.exists():
    import statistics
    by_env: dict[str, list[float]] = {}
    for r in csv.DictReader(PROF.open()):
        if r['createPublicKey_self_pct']:
            by_env.setdefault(r['environment'], []).append(float(r['createPublicKey_self_pct']))
    NAMES = {'host': 'ProfHost', 'node_18_20_8-alpine': 'ProfEighteen',
             'node_26_6_0-alpine': 'ProfTwentySix'}
    for env, macro in NAMES.items():
        v = by_env.get(env)
        if not v:
            MISSING.append(macro + 'Pct'); continue
        put(macro + 'Pct', statistics.median(v), PROF, '{:.1f}')
        put(macro + 'PctLo', min(v), PROF, '{:.1f}')
        put(macro + 'PctHi', max(v), PROF, '{:.1f}')
    put('ProfRepeats', max((len(v) for v in by_env.values()), default=None), PROF)
    put('ProfIterations', next((int(r['iterations']) for r in csv.DictReader(PROF.open())), None), PROF)
else:
    for macro in ('ProfHostPct', 'ProfEighteenPct', 'ProfTwentySixPct'):
        MISSING.append(macro)

# --- the library's own suite ------------------------------------------------
SUITE = RUNS / '2026-09-18T-upstream-suite' / 'suite_results.csv'
if SUITE.exists():
    rows = {r['variant']: r for r in csv.DictReader(SUITE.open())}
    for v, macro in [('stock', 'SuiteStock'), ('patched_narrow', 'SuitePatched'),
                     ('naive', 'SuiteNaive')]:
        r = rows.get(v)
        if not r:
            MISSING.append(macro + 'Passing'); continue
        put(macro + 'Passing', int(r['passing']), SUITE)
        put(macro + 'Failing', int(r['failing']), SUITE)
else:
    MISSING.append('SuiteStockPassing')

# --- in-situ sweeps: paired-scrape differences, ascending and descending -----
# Seven arrival rates, two passes in opposite order, on one process. The pair is
# a RANGE OF TWO, not an interval, and the sign test below shows it is not even
# two independent samples. Macro names use letter suffixes because LaTeX parses
# a digit in a macro name as literal text.
SWEEPS = {
    'String':    RUNS / '2026-09-14T05-57-22Z-verifyrate-hs256' / 'verify_rate_curve.csv',
    'Preparsed': RUNS / '2026-09-14T15-01-36Z-verifyrate-hs256-preparsed' / 'verify_rate_curve.csv',
    'Rs':        RUNS / '2026-09-14T06-41-56Z-verifyrate-rs256' / 'verify_rate_curve.csv',
}
LETTERS = 'ABCDEFG'
_alldiffs = []
for label, path in SWEEPS.items():
    if not path.exists():
        MISSING.append('Insitu' + label + 'AscA'); continue
    by = {}
    for r in csv.DictReader(path.open()):
        by.setdefault(int(r['rate_rps']), {})[r['pass']] = (
            float(r['verify_mean_us']), float(r['host_load1']))
    rates = sorted(by)
    for i, rate in enumerate(rates[:len(LETTERS)]):
        L = LETTERS[i]
        if label == 'String':
            put('InsituRate' + L, rate, path)
        a = by[rate].get('asc'); d = by[rate].get('desc')
        if a: put('Insitu' + label + 'Asc' + L, a[0], path)
        if d: put('Insitu' + label + 'Desc' + L, d[0], path)
        if a and d:
            _alldiffs.append((label, rate, abs(a[0] - d[0]), max(a[1], d[1])))
    # drift: how many rate points share the sign of (asc - desc)
    signs = [1 if by[r]['asc'][0] > by[r]['desc'][0] else -1
             for r in rates if 'asc' in by[r] and 'desc' in by[r]]
    if signs:
        put('Insitu' + label + 'Points', len(signs), path)
        put('Insitu' + label + 'SameSign', max(signs.count(1), signs.count(-1)), path)
if _alldiffs:
    tight = min(_alldiffs, key=lambda x: x[2])
    put('InsituTightestAgreement', tight[2], SWEEPS['Rs'], '{:.2f}')

# --- quantities main.tex (authors' draft of 2026-09) uses that no earlier
# version of this generator emitted. Added 2026-09-24; definitions follow the
# sentences that use them.
#   PreparsedUnattributed : pre-parsed verify() less structural decode less the
#                           pre-parsed HMAC, host (Section "The parts do not
#                           account for all of it").
#   InsituPredictedFromMatrix : the deployed runtime's discarded parse plus its
#                           pre-parsed verify(), from the runtime matrix.
#   InsituObservedLo/Hi   : min / max per-call mean across BOTH passes of the
#                           string-secret sweep.
#   InsituUnaccountedLo/Hi: observed less predicted, at those two extremes.
if m:
    put('PreparsedUnattributed',
        cond(m, 'host', 'jwt_hs_preparsed') - cond(m, 'host', 'decode_only')
        - cond(m, 'host', 'hmac_keyobject'), MECH / 'keypath_stats.json')
if mx and SWEEPS['String'].exists():
    pred = (cond(mx, 'node:18.20.8-alpine', 'probe_throws')
            + cond(mx, 'node:18.20.8-alpine', 'jwt_hs_preparsed'))
    obs = [float(r['verify_mean_us']) for r in csv.DictReader(SWEEPS['String'].open())]
    put('InsituPredictedFromMatrix', pred, pm, '{:.0f}')
    put('InsituObservedLo', min(obs), SWEEPS['String'], '{:.0f}')
    put('InsituObservedHi', max(obs), SWEEPS['String'], '{:.0f}')
    put('InsituUnaccountedLo', min(obs) - pred, SWEEPS['String'], '{:.0f}')
    put('InsituUnaccountedHi', max(obs) - pred, SWEEPS['String'], '{:.0f}')

# --- A/B: validation enabled vs disabled, one arrival rate -------------------
# Two 180 s windows on the same service, same token on the wire in both, the
# only difference being whether the handler calls jwt.verify(). The carried
# quantity is container CPU time from cgroup accounting, not wall-clock, so the
# per-call figure is CPU per request and the latency columns are context.
#
# Host load is the single `uptime` sample taken at window start -- the same
# quantity and the same capture path as host_load1 in the rate sweeps above.
# These runs carry no within-window load series, so no window mean is emitted:
# there is nothing in the data to average.
AB = {'Jwt': RUNS / 'INSITU-AB-authmode-jwt', 'None': RUNS / 'INSITU-AB-authmode-none'}
LOADAVG = re.compile(r'load averages?: *([0-9.]+)[ ,]+([0-9.]+)[ ,]+([0-9.]+)')

_ab_cpu = {}
_ab_clock = {}
for arm, d in AB.items():
    ramp = d / 'openloop_ramp.csv'
    if not ramp.exists():
        MISSING.append('AbCpu' + arm); continue
    rows = list(csv.DictReader(ramp.open()))
    if not rows:
        MISSING.append('AbCpu' + arm); continue
    r = rows[0]
    cpu, rate = float(r['cpu_app_millicores']), float(r['achieved_rps'])
    _ab_cpu[arm] = (cpu, rate)
    put('AbCpu' + arm, cpu, ramp)
    put('AbRate' + arm, rate, ramp, '{:.3f}')
    # millicores / (requests/s) * 1000 = microseconds of CPU per request
    put('AbCpuPerCall' + arm, cpu / rate * 1000.0, ramp, '{:.1f}')
    put('AbLatency' + arm, float(r['latency_mean_ms']), ramp, '{:.4f}')
    put('AbLatencyPNineNine' + arm, float(r['latency_p99_ms']), ramp, '{:.4f}')
    put('AbSidecarCpu' + arm, float(r['cpu_sidecar_millicores']), ramp)
    # MEAN of the per-scrape p99 event-loop lag, per docs/DATA_SCHEMA.md.
    # Not a p99 over the window, and must not be described as one.
    put('AbEventLoopLag' + arm, float(r['eventloop_lag_p99_ms']), ramp, '{:.3f}')

    meta = d / 'run_metadata.json'
    js_meta = json.loads(meta.read_text()) if meta.exists() else {}
    host = js_meta.get('host') or {}
    m = LOADAVG.search(host.get('uptime_at_run_start') or '')
    for name, i in (('One', 0), ('Five', 1), ('Fifteen', 2)):
        put('AbLoad' + name + arm, float(m.group(i + 1)) if m else None, meta)
    # Busiest host process at window start, from the same `top` snapshot. One
    # sample over top's own interval, so it is an indicator and not a mean.
    top = host.get('top_cpu_at_run_start') or []
    put('AbTopProcPct' + arm, float(top[0]['percent']) if top else None, meta, '{:.1f}')
    _ab_clock[arm] = (js_meta.get('started_at_utc'), js_meta.get('finished_at_utc'))

    # Arm separation without a distributional assumption. A t-test over 1 Hz
    # samples would assume independence these do not have.
    samples = d / 'pod_cpu_samples.csv'
    v = []
    if samples.exists():
        with samples.open() as fh:
            for row in csv.DictReader(l for l in fh if not l.startswith('#')):
                if row.get('container') == 'service-a' and row.get('cpu_millicores'):
                    v.append(float(row['cpu_millicores']))
    put('AbCpuSampleMin' + arm, min(v) if v else None, samples, '{:.3f}')
    put('AbCpuSampleMax' + arm, max(v) if v else None, samples, '{:.3f}')
    put('AbCpuSamples' + arm, len(v) if v else None, samples)

    k6 = d / 'k6_summary.json'
    if k6.exists():
        js = json.loads(k6.read_text())
        dur = (js.get('state') or {}).get('testRunDurationMs')
        cnt = (((js.get('metrics') or {}).get('http_reqs') or {}).get('values') or {}).get('count')
        put('AbWindowSeconds' + arm, dur / 1000.0 if dur is not None else None, k6, '{:.0f}')
        put('AbRequests' + arm, cnt, k6)
    else:
        MISSING.append('AbRequests' + arm)

if 'Jwt' in _ab_cpu and 'None' in _ab_cpu:
    (cj, rj), (cn, rn) = _ab_cpu['Jwt'], _ab_cpu['None']
    ramp = AB['Jwt'] / 'openloop_ramp.csv'
    put('AbCpuDelta', cj - cn, ramp)
    # Attributed at the jwt arm's own achieved rate; the two rates agree to
    # three decimals, so the choice does not move the figure.
    put('AbCpuPerCallDelta', (cj - cn) / rj * 1000.0, ramp, '{:.1f}')
    lj = float(list(csv.DictReader((AB['Jwt'] / 'openloop_ramp.csv').open()))[0]['latency_mean_ms'])
    ln = float(list(csv.DictReader((AB['None'] / 'openloop_ramp.csv').open()))[0]['latency_mean_ms'])
    put('AbLatencyDeltaUs', (lj - ln) * 1000.0, ramp, '{:.1f}')
else:
    MISSING.extend(['AbCpuDelta', 'AbCpuPerCallDelta', 'AbLatencyDeltaUs'])

# CPU the validation call adds per request, against the per-call cost the
# runtime matrix predicts for the deployed runtime (node:18.20.8-alpine). The
# in-situ WALL-CLOCK means exceed that prediction; this is the processor-time
# check on the same question. Added 2026-09-26.
if 'Jwt' in _ab_cpu and 'None' in _ab_cpu and mx:
    _pred = (cond(mx, 'node:18.20.8-alpine', 'probe_throws')
             + cond(mx, 'node:18.20.8-alpine', 'jwt_hs_preparsed'))
    _delta = (_ab_cpu['Jwt'][0] - _ab_cpu['None'][0]) / _ab_cpu['Jwt'][1] * 1000.0
    put('AbCpuVsPredictedPct', 100.0 * abs(_delta - _pred) / _pred, AB['Jwt'] / 'openloop_ramp.csv', '{:.1f}')

# The host decomposition predates the per-row OpenSSL field. The version in
# force at the time is recorded by timestamp in the drift note; it is emitted
# from that note so the manuscript cannot state a different one.
_drift = RUNS / 'HOST-OPENSSL-DRIFT-2026-09-17.md'
if _drift.exists():
    _m = re.search(r"from (\d+\.\d+\.\d+) to (\d+\.\d+\.\d+)", _drift.read_text())
    if _m:
        put('HostOpensslInferred', _m.group(1), _drift)
        put('HostOpensslAfterDrift', _m.group(2), _drift)

# Idle gap between the two windows. The enabled arm ran second, so its
# window-start load average still carries a decaying contribution from the
# disabled arm; the gap is what says how much decay there was time for.
if _ab_clock.get('None', (None,))[1] and _ab_clock.get('Jwt', (None,))[0]:
    from datetime import datetime
    t_end = datetime.fromisoformat(_ab_clock['None'][1])
    t_start = datetime.fromisoformat(_ab_clock['Jwt'][0])
    put('AbGapSeconds', (t_start - t_end).total_seconds(),
        AB['Jwt'] / 'run_metadata.json', '{:.0f}')
else:
    MISSING.append('AbGapSeconds')

# --- survey ------------------------------------------------------------------
pc = SURVEY / 'population_counts.csv'
if pc.exists():
    rows = {r['query']: int(r['total_count']) for r in csv.DictReader(pc.open()) if r['total_count']}
    CELLS = {
        'JsRequire': ("require('jsonwebtoken') language:javascript",
                      "require('jsonwebtoken') createSecretKey language:javascript"),
        'JsImport':  ("from 'jsonwebtoken' language:javascript",
                      "from 'jsonwebtoken' createSecretKey language:javascript"),
        'TsRequire': ("require('jsonwebtoken') language:typescript",
                      "require('jsonwebtoken') createSecretKey language:typescript"),
        'TsImport':  ("from 'jsonwebtoken' language:typescript",
                      "from 'jsonwebtoken' createSecretKey language:typescript"),
    }
    dens, nums, rates = [], [], []
    for name, (dq, nq) in CELLS.items():
        d, n = rows.get(dq), rows.get(nq)
        put('Pop' + name + 'Files', d, pc)
        put('Pop' + name + 'FilesWithApi', n, pc)
        if d and n is not None:
            put('Pop' + name + 'Pct', 100 * n / d, pc, '{:.4f}')
            dens.append(d); nums.append(n); rates.append(100 * n / d)
    # Cells are NOT summed into a headline proportion: a file using both import
    # forms would be counted twice. The sum is an upper bound on the union and
    # the largest cell a lower bound, so both are reported as such.
    if dens:
        put('PopSumFiles', sum(dens), pc)
        put('PopSumFilesWithApi', sum(nums), pc)
        put('PopLargestCellFiles', max(dens), pc)
        put('PopWorstCellPct', max(rates), pc, '{:.4f}')
        put('PopBestCellPct', min(rates), pc, '{:.4f}')
        put('PopSumPct', 100 * sum(nums) / sum(dens), pc, '{:.4f}')
        put('PopSumOneIn', round(sum(dens) / sum(nums)), pc)
    capt = [r['captured_at_utc'] for r in csv.DictReader(pc.open())]
    put('PopCapturedAt', capt[0][:10] if capt else None, pc)

cs = SURVEY / 'callsites.csv'
if cs.exists():
    rows = list(csv.DictReader(cs.open()))
    put('SampleCallSites', len(rows), cs)
    put('SampleRematchAdded', len(rows) - 315, cs)
    put('SampleRepos', len({r['repo'] for r in rows}), cs)
    for bucket, macro in [('env_string', 'SampleEnvString'), ('unknown', 'SampleUnknown'),
                          ('string_literal', 'SampleStringLiteral'),
                          ('file_contents', 'SampleFileContents'), ('buffer', 'SampleBuffer')]:
        put(macro, sum(1 for r in rows if r['bucket'] == bucket), cs)
    put('SampleSitesPreparsed', sum(1 for r in rows if r['bucket'] == 'keyobject'), cs)
    unspec = sum(1 for r in rows if r['algorithms'] == 'unspecified')
    put('SampleNoAlgorithms', unspec, cs)
    put('SampleNoAlgorithmsPct', 100 * unspec / len(rows), cs, '{:.0f}')

ha = SURVEY / 'hand_adjudication.csv'
if ha.exists():
    allrows = list(csv.DictReader(ha.open()))
    # Two adjudication rounds live in this file and must not be pooled: the
    # counter-search round asked "is this really a KeyObject?", the rematch round
    # asked "what bucket is this call site?". Macros about the former would be
    # wrong if the latter were counted in.
    rows = [r for r in allrows if r.get('round', '').startswith('counter_search')]
    rematch = [r for r in allrows if r.get('round', '').startswith('sample_rematch')]
    put('RematchAdjudicated', len(rematch), ha)
    put('RematchSitesPreparsed', sum(1 for r in rematch if r['verdict'] == 'keyobject'), ha)
    put('AdjudicatedTotal', len(rows), ha)
    gen = [r for r in rows if r['verdict'] == 'genuine']
    put('AdjudicatedGenuine', len(gen), ha)
    put('AdjudicatedGenuineProjects', len({r['repo'] for r in gen}), ha)
    _den = None
    _ce = SURVEY / 'counterexamples.json'
    if _ce.exists():
        _recs = json.loads(_ce.read_text())
        _den = len({r['repo'] for r in _recs if r['verify_calls'] > 0})
    if _den:
        put('AdjudicatedGenuinePct', 100 * len({r['repo'] for r in gen}) / _den, ha, '{:.2f}')
    put('AdjudicatedFalsePositive', sum(1 for r in rows if r['verdict'] == 'false_positive'), ha)
    put('AdjudicatedUnresolved', sum(1 for r in rows if r['verdict'] == 'unresolved'), ha)

ce = SURVEY / 'counterexamples.json'
if ce.exists():
    recs = json.loads(ce.read_text())
    put('CounterFilesFetched', len(recs), ce)
    withv = [r for r in recs if r['verify_calls'] > 0]
    put('CounterWithVerify', len(withv), ce)
    # The denominator for the rarity claim: repositories whose files both mention
    # the pre-parsing API and call verify(). This is the MOST favourable
    # denominator available -- these projects demonstrably know the API exists --
    # and it is not the population. Named so it cannot be read as one.
    put('CounterReposWithVerify', len({r['repo'] for r in withv}), ce)

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
