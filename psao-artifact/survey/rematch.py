#!/usr/bin/env python3
"""rematch.py -- re-examine corpus files the original matcher did not classify.

The original matcher recognised only `jwt.verify(`, `jsonwebtoken.verify(` and
`jwtLib.verify(`. That filters the corpus toward one import idiom and misses:

  const X = require('jsonwebtoken');          X.verify(...)      arbitrary alias
  import X from 'jsonwebtoken';               X.verify(...)
  import * as X from 'jsonwebtoken';          X.verify(...)
  const { verify } = require('jsonwebtoken'); verify(...)        destructured
  import { verify } from 'jsonwebtoken';      verify(...)
  const { verify: v } = require(...);         v(...)             renamed
  require('jsonwebtoken').verify(...)                            direct

This resolves the local binding(s) per file and matches accordingly. Reads only
files already on disk; performs no network access.

Usage: python3 survey/rematch.py [--all]   (--all re-runs over the whole corpus)
"""
from __future__ import annotations
import csv, json, re, sys
from pathlib import Path

DATA = Path('survey/data')
Q = r"['\"]jsonwebtoken['\"]"

NS_REQUIRE = re.compile(r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(\s*%s\s*\)' % Q)
NS_IMPORT  = re.compile(r'\bimport\s+([A-Za-z_$][\w$]*)\s*(?:,\s*\{[^}]*\})?\s*from\s*%s' % Q)
NS_STAR    = re.compile(r'\bimport\s*\*\s*as\s+([A-Za-z_$][\w$]*)\s*from\s*%s' % Q)
DESTR_REQ  = re.compile(r'\b(?:const|let|var)\s*\{([^}]*)\}\s*=\s*require\(\s*%s\s*\)' % Q)
DESTR_IMP  = re.compile(r'\bimport\s*\{([^}]*)\}\s*from\s*%s' % Q)
DIRECT     = re.compile(r'require\(\s*%s\s*\)\s*\.\s*verify\s*\(' % Q)


def bindings(src: str) -> tuple[set[str], set[str]]:
    """-> (namespace names used as NS.verify(...), bare names called directly)."""
    ns = {m.group(1) for m in NS_REQUIRE.finditer(src)}
    ns |= {m.group(1) for m in NS_IMPORT.finditer(src)}
    ns |= {m.group(1) for m in NS_STAR.finditer(src)}
    bare: set[str] = set()
    for rx in (DESTR_REQ, DESTR_IMP):
        for m in rx.finditer(src):
            for part in m.group(1).split(','):
                part = part.strip()
                if not part:
                    continue
                if ':' in part:
                    orig, alias = (x.strip() for x in part.split(':', 1))
                    if orig == 'verify':
                        bare.add(alias)
                elif re.fullmatch(r'verify\s+as\s+[\w$]+', part):
                    bare.add(part.split()[-1])
                elif part == 'verify':
                    bare.add('verify')
    return ns, bare


def callsites(src: str) -> list[tuple[str, int]]:
    """-> [(how, index-of-open-paren)] for every resolved verify call."""
    ns, bare = bindings(src)
    out = []
    for name in ns:
        for m in re.finditer(r'\b%s\s*\.\s*verify\s*\(' % re.escape(name), src):
            out.append(('%s.verify' % name, m.end() - 1))
    for name in bare:
        for m in re.finditer(r'(?<![.\w])%s\s*\(' % re.escape(name), src):
            out.append(('destructured %s' % name, m.end() - 1))
    for m in DIRECT.finditer(src):
        out.append(("require('jsonwebtoken').verify", m.end() - 1))
    return sorted(set(out), key=lambda x: x[1])


def main() -> int:
    do_all = '--all' in sys.argv
    classified = {r['repo'] for r in csv.DictReader((DATA / 'callsites.csv').open())}
    hits = [h for h in json.loads((DATA / 'hits.json').read_text()) if h.get('file')]
    rows = []
    for h in hits:
        f = DATA / 'files' / h['file']
        if not f.exists():
            continue
        was_matched = h['repo'] in classified
        if was_matched and not do_all:
            continue
        src = f.read_text(errors='replace')
        for how, pos in callsites(src):
            rows.append({'repo': h['repo'], 'path': h['path'], 'file': h['file'],
                         'how': how, 'pos': pos,
                         'previously_matched': was_matched})
    out = DATA / ('rematch_all.csv' if do_all else 'rematch_residue.csv')
    with out.open('w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['repo', 'path', 'file', 'how', 'pos',
                                           'previously_matched'])
        w.writeheader(); w.writerows(rows)
    scope = 'whole corpus' if do_all else 'the unmatched residue'
    print(f'{scope}: {len(rows)} resolved call sites in '
          f'{len({r["repo"] for r in rows})} repositories -> {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
