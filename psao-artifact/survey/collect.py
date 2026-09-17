#!/usr/bin/env python3
"""collect.py -- how do real projects hand a key to jwt.verify()?

The upstream finding is that passing anything other than a KeyObject makes
jsonwebtoken attempt createPublicKey() on every call. Whether that matters
depends on how often real code does it, which is a question about the
population, not about our testbed.

SAMPLING, STATED PLAINLY. GitHub code search is not a random sample of code. It
is relevance-ranked, deduplicated in ways we do not control, restricted to
public repositories, and capped at 1000 results per query. Several queries are
issued to widen coverage, and results are deduplicated per repository so a
single large project cannot dominate. The result is a convenience sample of
public JavaScript/TypeScript. It supports a claim of the form "this pattern is
common in public code"; it does not support an unqualified population
proportion, and the write-up must say so.

Usage:  python3 survey/collect.py --out survey/data [--per-query 100]
"""
from __future__ import annotations
import argparse, base64, json, re, subprocess, sys, time
from pathlib import Path

QUERIES = [
    # Deliberately NOT including a "process.env" term: an earlier pass did, and
    # it biased the sample toward exactly the bucket under investigation.
    ('jwt.verify language:javascript', 'js'),
    ('jwt.verify language:typescript', 'ts'),
    ('jsonwebtoken.verify language:javascript', 'js'),
    ('"jwt.verify(" language:typescript', 'ts'),
    ('"require(\'jsonwebtoken\')" language:javascript', 'js'),
    ('"from \'jsonwebtoken\'" language:typescript', 'ts'),
    # Targeted counter-search: if pre-parsing exists in public code, this finds
    # it. Included so the sample cannot miss the good pattern by construction.
    ('jwt.verify createSecretKey', 'mixed'),
    ('jsonwebtoken createSecretKey', 'mixed'),
]


def gh(args: list[str], retries: int = 3):
    """Run gh, tolerating the secondary rate limit rather than dying on it."""
    for attempt in range(retries):
        p = subprocess.run(['gh'] + args, capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
        err = (p.stderr or '').lower()
        if 'rate limit' in err or 'abuse' in err or 'secondary' in err:
            wait = 30 * (attempt + 1)
            print(f'    rate limited, waiting {wait}s', file=sys.stderr)
            time.sleep(wait)
            continue
        return None
    return None


def search(query: str, limit: int):
    out = gh(['search', 'code', query, '--limit', str(limit),
              '--json', 'path,repository'])
    if not out:
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return []


def fetch(repo: str, path: str) -> str | None:
    out = gh(['api', f'/repos/{repo}/contents/{path}',
              '--jq', '.content // empty'])
    if not out or not out.strip():
        return None
    try:
        return base64.b64decode(out.strip()).decode('utf-8', errors='replace')
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='survey/data')
    ap.add_argument('--per-query', type=int, default=100)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    seen_repo_path, seen_repo = set(), {}
    hits = []
    for q, lang in QUERIES:
        print(f'  query: {q}', file=sys.stderr)
        for r in search(q, a.per_query):
            repo = r['repository']['nameWithOwner']
            path = r['path']
            key = (repo, path)
            if key in seen_repo_path:
                continue
            seen_repo_path.add(key)
            # One file per repository. A monorepo with 40 matching files would
            # otherwise count 40 times and swamp 39 other projects.
            if repo in seen_repo:
                continue
            seen_repo[repo] = path
            hits.append({'repo': repo, 'path': path, 'lang': lang, 'query': q})
        time.sleep(3)   # code search is ~10 req/min authenticated

    print(f'  {len(hits)} distinct repositories', file=sys.stderr)
    (out / 'hits.json').write_text(json.dumps(hits, indent=1))

    fetched = 0
    corpus = out / 'files'; corpus.mkdir(exist_ok=True)
    for i, h in enumerate(hits, 1):
        safe = (h['repo'] + '__' + h['path']).replace('/', '_')[:180]
        dest = corpus / (safe + '.txt')
        if dest.exists():
            fetched += 1; continue
        src = fetch(h['repo'], h['path'])
        if src is None:
            continue
        dest.write_text(src)
        h['file'] = dest.name
        fetched += 1
        if i % 25 == 0:
            print(f'    fetched {fetched}/{len(hits)}', file=sys.stderr)
    (out / 'hits.json').write_text(json.dumps(hits, indent=1))
    print(f'  fetched {fetched} files into {corpus}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
