#!/usr/bin/env python3
"""counterexamples.py -- fetch and VERIFY every file that co-occurs
`jsonwebtoken` with `createSecretKey`.

The population counts say such files are rare (~130 across ~1.1M). Rare is not
the same as "pre-parses correctly": a file can mention createSecretKey while
still passing a string to verify(), e.g. because it pre-parses for sign() only.
This turns a co-occurrence count into a checked one.

NOTE: `gh search code` returns [] for multi-term queries that the underlying
search API answers normally. These queries therefore go through `gh api
search/code` directly. That discrepancy cost an earlier pass its entire
counter-search arm, silently.
"""
from __future__ import annotations
import base64, json, re, subprocess, sys, time
from pathlib import Path

QUERIES = [
    'jwt.verify createSecretKey language:javascript',
    'jwt.verify createSecretKey language:typescript',
    "\"require('jsonwebtoken')\" createSecretKey language:javascript",
    "\"from 'jsonwebtoken'\" createSecretKey language:typescript",
]
OUT = Path('survey/data/counterexamples'); OUT.mkdir(parents=True, exist_ok=True)


def api(args, retries=3):
    for i in range(retries):
        p = subprocess.run(['gh', 'api'] + args, capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
        if 'rate limit' in (p.stderr or '').lower():
            time.sleep(30 * (i + 1)); continue
        return None
    return None


seen, records = set(), []
for q in QUERIES:
    for page in (1, 2):
        out = api(['-X', 'GET', 'search/code', '-f', f'q={q}',
                   '-f', 'per_page=100', '-f', f'page={page}',
                   '--jq', '.items[] | .repository.full_name + "\\t" + .path'])
        time.sleep(7)
        if not out or not out.strip():
            break
        for line in out.strip().splitlines():
            repo, path = line.split('\t', 1)
            if (repo, path) in seen:
                continue
            seen.add((repo, path))
            records.append({'repo': repo, 'path': path, 'query': q})

print(f'{len(records)} distinct co-occurrence files', file=sys.stderr)

CALL = re.compile(r'\b(?:jwt|jsonwebtoken)\s*\.\s*verify\s*\(')
results = []
for r in records:
    src = api(['-X', 'GET', f"/repos/{r['repo']}/contents/{r['path']}", '--jq', '.content // empty'])
    if not src or not src.strip():
        continue
    try:
        text = base64.b64decode(src.strip()).decode('utf-8', errors='replace')
    except Exception:
        continue
    fn = (r['repo'] + '__' + r['path']).replace('/', '_')[:180] + '.txt'
    (OUT / fn).write_text(text)
    # Does a KeyObject actually reach verify() in this file?
    verifies = [m.end() for m in CALL.finditer(text)]
    has_cso = bool(re.search(r'createSecretKey|createPublicKey', text))
    # crude but conservative: KeyObject-derived identifiers in the file
    ko_names = set(re.findall(r'(?:const|let|var)\s+([\w$]+)\s*=\s*[^\n;]*create(?:Secret|Public)Key', text))
    passes_ko = False
    for pos in verifies:
        seg = text[pos:pos + 200]
        arg2 = seg.split(',')[1] if ',' in seg else ''
        if any(n in arg2 for n in ko_names) or 'create' in arg2 and 'Key' in arg2:
            passes_ko = True
    results.append({'repo': r['repo'], 'path': r['path'],
                    'verify_calls': len(verifies), 'mentions_keyobject_api': has_cso,
                    'keyobject_reaches_verify': passes_ko,
                    'keyobject_names': ';'.join(sorted(ko_names))})

Path('survey/data/counterexamples.json').write_text(json.dumps(results, indent=1))
n = len(results)
withv = [r for r in results if r['verify_calls'] > 0]
passing = [r for r in withv if r['keyobject_reaches_verify']]
print(f'fetched {n}; {len(withv)} contain a verify() call; '
      f'{len(passing)} pass a KeyObject to it', file=sys.stderr)
