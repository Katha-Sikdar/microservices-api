#!/usr/bin/env python3
"""classify.py -- for each jwt.verify() call site, how is the key supplied?

The question is narrow: does the second argument reach jsonwebtoken as a
KeyObject, or as something the library must resolve on every call by attempting
createPublicKey() first?

Classification is deliberately conservative. Anything that cannot be decided
from the file alone is recorded as `unknown` rather than assigned to a bucket,
because the interesting number is small and an over-eager classifier would
manufacture it.

Usage:  python3 survey/classify.py --data survey/data --out survey/data
"""
from __future__ import annotations
import argparse, csv, json, re
from pathlib import Path

CALL = re.compile(r'\b(?:jwt|jsonwebtoken|jwtLib)\s*\.\s*verify\s*\(')

KEYOBJECT_SRC = re.compile(r'\b(createSecretKey|createPublicKey|generateKeyPairSync|KeyObject)\b')
READFILE      = re.compile(r'\b(readFileSync|readFile)\b')


def split_args(src: str, start: int) -> list[str] | None:
    """Split the argument list of a call whose '(' is at `start`. Respects
    nesting and string literals; returns None if the call is truncated."""
    depth, args, cur, i = 0, [], [], start
    quote = None
    while i < len(src):
        c = src[i]
        if quote:
            if c == '\\': cur.append(c); i += 1; cur.append(src[i] if i < len(src) else '')
            elif c == quote: quote = None; cur.append(c)
            else: cur.append(c)
        elif c in '"\'`':
            quote = c; cur.append(c)
        elif c in '([{':
            depth += 1
            if depth > 1: cur.append(c)
            i += 1; continue
        elif c in ')]}':
            depth -= 1
            if depth == 0:
                args.append(''.join(cur)); return [a.strip() for a in args]
            cur.append(c)
        elif c == ',' and depth == 1:
            args.append(''.join(cur)); cur = []
        else:
            cur.append(c)
        i += 1
    return None


def trace(ident: str, src: str) -> str | None:
    """Follow `const X = ...` one hop, to see whether X is a KeyObject."""
    if not re.fullmatch(r'[A-Za-z_$][\w$]*', ident):
        return None
    m = re.search(r'\b(?:const|let|var)\s+' + re.escape(ident) + r'\s*=\s*([^\n;]+)', src)
    return m.group(1) if m else None


def classify_arg(arg: str, src: str) -> tuple[str, str]:
    """-> (bucket, evidence). Buckets other than 'keyobject' all reach the probe."""
    a = arg.strip()
    if not a:
        return 'unknown', 'empty'
    # a function argument (jwks-rsa getKey and friends)
    if re.match(r'^(async\s+)?(function\b|\()', a) and '=>' in a or re.match(r'^function\b', a):
        return 'callback', a[:60]
    if KEYOBJECT_SRC.search(a):
        return 'keyobject', a[:60]
    if a[0] in '"\'`':
        return 'string_literal', a[:60]
    if 'process.env' in a:
        return 'env_string', a[:60]
    if READFILE.search(a):
        return 'file_contents', a[:60]
    if re.match(r'^Buffer\.from\b', a):
        return 'buffer', a[:60]
    # single identifier: one hop of tracing
    if re.fullmatch(r'[A-Za-z_$][\w$]*', a):
        rhs = trace(a, src)
        if rhs:
            if KEYOBJECT_SRC.search(rhs): return 'keyobject', f'{a} = {rhs[:50]}'
            if 'process.env' in rhs:      return 'env_string', f'{a} = {rhs[:50]}'
            if READFILE.search(rhs):      return 'file_contents', f'{a} = {rhs[:50]}'
            if rhs.strip()[:1] in '"\'`': return 'string_literal', f'{a} = {rhs[:50]}'
            if re.match(r'^(getKey|\w*[Kk]eyFunc)', rhs): return 'callback', f'{a} = {rhs[:50]}'
        return 'unknown', f'{a} (untraced)'
    if re.match(r'^[\w$]+(\.[\w$]+)+$', a):          # config.secret, this.key
        return 'unknown', f'{a} (member, untraced)'
    return 'unknown', a[:60]


def algorithms_of(args: list[str]) -> str:
    opts = ' '.join(args[2:3])
    algs = re.findall(r"['\"](HS\d{3}|RS\d{3}|ES\d{3}|PS\d{3})['\"]", opts)
    if not algs:
        return 'unspecified'
    fam = {x[:2] for x in algs}
    return '+'.join(sorted(fam))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='survey/data')
    ap.add_argument('--out', default='survey/data')
    a = ap.parse_args()
    data = Path(a.data)
    hits = json.loads((data / 'hits.json').read_text())
    by_file = {h.get('file'): h for h in hits if h.get('file')}

    rows = []
    for f in sorted((data / 'files').glob('*.txt')):
        h = by_file.get(f.name, {})
        src = f.read_text(errors='replace')
        for m in CALL.finditer(src):
            args = split_args(src, m.end() - 1)
            if args is None or len(args) < 2:
                continue
            bucket, evidence = classify_arg(args[1], src)
            rows.append({
                'repo': h.get('repo', '?'), 'path': h.get('path', '?'),
                'lang': h.get('lang', '?'),
                'bucket': bucket,
                'algorithms': algorithms_of(args),
                'evidence': evidence.replace('\n', ' ')[:80],
            })

    outp = Path(a.out) / 'callsites.csv'
    with outp.open('w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                           ['repo', 'path', 'lang', 'bucket', 'algorithms', 'evidence'])
        w.writeheader(); w.writerows(rows)
    print(f'{len(rows)} call sites from {len(set(r["repo"] for r in rows))} repositories -> {outp}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
