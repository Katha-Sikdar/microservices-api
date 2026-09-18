#!/usr/bin/env python3
"""make_manifest.py -- pin the survey corpus without redistributing it.

survey/data/files/ and survey/data/counterexamples/ hold third-party source and
are not committed. A reviewer therefore cannot check the corpus-level claims by
inspection. This manifest is the substitute: for every file examined it records
the repository, the path, the git blob SHA-1 (directly comparable to the `sha`
field GitHub's contents API returns for that path), the SHA-256 of the exact
bytes analysed, and -- for adjudicated repositories -- the verdict.

The verdict column is REPO-LEVEL. survey/data/hand_adjudication.csv records one
row per adjudicated call site and identifies it by repository, not by path, so a
repository that contributed two files to the corpus shows its verdict on both
rows. Do not count verdicts from this file; count them from
hand_adjudication.csv, which is what the paper does.

Anyone can therefore re-fetch a file, hash it, and establish that they are
looking at what we looked at, or that the file has changed since.

The repository HEAD commit is recorded per repository AT MANIFEST TIME, not at
fetch time, which was not captured. It is a weaker pin than the file hashes and
is labelled as such: if a file changed between fetch and manifest, the blob hash
will disagree and the HEAD commit will not tell you that. The blob hash is the
authoritative column.
"""
from __future__ import annotations
import csv, hashlib, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'survey' / 'data'


def git_blob_sha1(b: bytes) -> str:
    return hashlib.sha1(b'blob %d\0' % len(b) + b).hexdigest()


def head_sha(repo: str, cache: dict) -> str:
    """Default-branch HEAD in ONE call. `/commits?per_page=1` already resolves
    the default branch server-side, so asking for it separately doubled the
    request count for no information."""
    if repo in cache:
        return cache[repo]
    p = subprocess.run(['gh', 'api', f'/repos/{repo}/commits?per_page=1', '--jq', '.[0].sha'],
                       capture_output=True, text=True)
    cache[repo] = p.stdout.strip() if p.returncode == 0 else ''
    return cache[repo]


def main() -> int:
    verdicts = {}
    ha = DATA / 'hand_adjudication.csv'
    if ha.exists():
        for r in csv.DictReader(ha.open()):
            verdicts.setdefault(r['repo'], r['verdict'])

    rows, cache = [], {}
    # corpus 1: the classified sample
    hits = json.loads((DATA / 'hits.json').read_text())
    for h in hits:
        if not h.get('file'):
            continue
        f = DATA / 'files' / h['file']
        if not f.exists():
            continue
        b = f.read_bytes()
        rows.append({'corpus': 'sample', 'repo': h['repo'], 'path': h['path'],
                     'git_blob_sha1': git_blob_sha1(b),
                     'sha256': hashlib.sha256(b).hexdigest(),
                     'bytes': len(b), 'verdict_repo_level': verdicts.get(h['repo'], '')})
    # corpus 2: the co-occurrence counter-search
    ce = DATA / 'counterexamples.json'
    if ce.exists():
        for r in json.loads(ce.read_text()):
            fn = (r['repo'] + '__' + r['path']).replace('/', '_')[:180] + '.txt'
            f = DATA / 'counterexamples' / fn
            if not f.exists():
                continue
            b = f.read_bytes()
            rows.append({'corpus': 'counter_search', 'repo': r['repo'], 'path': r['path'],
                         'git_blob_sha1': git_blob_sha1(b),
                         'sha256': hashlib.sha256(b).hexdigest(),
                         'bytes': len(b), 'verdict_repo_level': verdicts.get(r['repo'], '')})

    repos = sorted({r['repo'] for r in rows})
    print(f'{len(rows)} files, {len(repos)} repositories; fetching HEAD commits',
          file=sys.stderr)
    for i, repo in enumerate(repos, 1):
        head_sha(repo, cache)
        if i % 50 == 0:
            print(f'  {i}/{len(repos)}', file=sys.stderr)
    for r in rows:
        r['repo_head_commit_at_manifest_time'] = cache.get(r['repo'], '')

    out = DATA / 'corpus_manifest.csv'
    cols = ['corpus', 'repo', 'path', 'git_blob_sha1', 'sha256', 'bytes',
            'verdict', 'repo_head_commit_at_manifest_time']
    with out.open('w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
    resolved = sum(1 for r in rows if r['repo_head_commit_at_manifest_time'])
    print(f'wrote {out}: {len(rows)} files, HEAD resolved for {resolved}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
