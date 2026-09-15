#!/usr/bin/env python3
"""Summarise a verify_rate_sweep run: in-situ jwt.verify() cost vs arrival rate.

Reads the before-/after- Prometheus scrape pairs a sweep leaves behind and
differences them, which is what isolates each rate point's histogram from the
cumulative counters.
"""
import argparse, csv, json, os, re, sys, glob

def parse(path, metric, label_filter=None):
    buckets, total, count = {}, 0.0, 0.0
    with open(path) as fh:
        for line in fh:
            if line.startswith('#') or not line.startswith(metric):
                continue
            if label_filter and label_filter not in line:
                continue
            try:
                value = float(line.rsplit(' ', 1)[1])
            except (IndexError, ValueError):
                continue
            if line.startswith(metric + '_bucket'):
                m = re.search(r'le="([^"]+)"', line)
                if m:
                    le = float(m.group(1))
                    buckets[le] = buckets.get(le, 0.0) + value
            elif line.startswith(metric + '_sum'):
                total += value
            elif line.startswith(metric + '_count'):
                count += value
    return buckets, total, count


def quantile(buckets, count, p):
    """Linear interpolation within the containing bucket, as Prometheus does."""
    target = count * p
    prev_le, prev_c = 0.0, 0.0
    for le in sorted(buckets):
        if buckets[le] >= target:
            if le == float('inf'):
                return prev_le * 1e6
            span = buckets[le] - prev_c
            frac = (target - prev_c) / span if span > 0 else 0.0
            return 1e6 * (prev_le + frac * (le - prev_le))
        prev_le, prev_c = le, buckets[le]
    return float('nan')


def point(run_dir, tag, metric, label_filter=None):
    before = os.path.join(run_dir, f'before-{tag}.prom')
    after = os.path.join(run_dir, f'after-{tag}.prom')
    if not (os.path.exists(before) and os.path.exists(after)):
        return None
    b0, s0, c0 = parse(before, metric, label_filter)
    b1, s1, c1 = parse(after, metric, label_filter)
    db = {k: b1[k] - b0.get(k, 0.0) for k in sorted(b1)}
    ds, dc = s1 - s0, c1 - c0
    if dc <= 0:
        return None
    return {
        'count': int(dc),
        'mean_us': 1e6 * ds / dc,
        'p50_us': quantile(db, dc, 0.50),
        'p90_us': quantile(db, dc, 0.90),
        'p99_us': quantile(db, dc, 0.99),
        'buckets': {('inf' if k == float('inf') else f'{k*1e6:.0f}'): int(v)
                    for k, v in db.items() if v > 0},
    }


def host_load(run_dir, tag):
    path = os.path.join(run_dir, f'host-{tag}.txt')
    if not os.path.exists(path):
        return None
    m = re.search(r'load averages?: *([0-9.]+)', open(path).read())
    return float(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--algorithm', default='HS256')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    tags = sorted(os.path.basename(p)[7:-5]
                  for p in glob.glob(os.path.join(args.run_dir, 'before-*.prom')))
    rows = []
    for tag in tags:
        pass_name, rate = tag.split('-')
        v = point(args.run_dir, tag, 'psao_verify_duration_seconds',
                  f'algorithm="{args.algorithm}",result="ok"')
        h = point(args.run_dir, tag, 'psao_request_duration_seconds')
        if not v:
            continue
        rows.append({
            'pass': pass_name, 'rate_rps': int(rate),
            'verify_count': v['count'], 'verify_mean_us': v['mean_us'],
            'verify_p50_us': v['p50_us'], 'verify_p90_us': v['p90_us'],
            'verify_p99_us': v['p99_us'],
            'handler_mean_us': h['mean_us'] if h else None,
            'host_load1': host_load(args.run_dir, tag),
            'buckets': v['buckets'],
        })

    out = args.out or os.path.join(args.run_dir, 'verify_rate_curve.csv')
    with open(out, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['pass', 'rate_rps', 'verify_count', 'verify_mean_us',
                    'verify_p50_us', 'verify_p90_us', 'verify_p99_us',
                    'handler_mean_us', 'host_load1'])
        for r in rows:
            w.writerow([r['pass'], r['rate_rps'], r['verify_count'],
                        f"{r['verify_mean_us']:.2f}", f"{r['verify_p50_us']:.2f}",
                        f"{r['verify_p90_us']:.2f}", f"{r['verify_p99_us']:.2f}",
                        f"{r['handler_mean_us']:.2f}" if r['handler_mean_us'] else '',
                        r['host_load1'] if r['host_load1'] is not None else ''])
    with open(out.replace('.csv', '.json'), 'w') as fh:
        json.dump(rows, fh, indent=2)

    print(f'{args.algorithm} in-situ jwt.verify() vs arrival rate  ({args.run_dir})\n')
    print('%-5s %6s %8s %10s %9s %9s %10s %10s %6s'
          % ('pass', 'rps', 'n', 'mean us', 'p50', 'p90', 'p99', 'handler', 'load1'))
    for r in rows:
        print('%-5s %6d %8d %10.2f %9.2f %9.2f %10.2f %10s %6s'
              % (r['pass'], r['rate_rps'], r['verify_count'], r['verify_mean_us'],
                 r['verify_p50_us'], r['verify_p90_us'], r['verify_p99_us'],
                 f"{r['handler_mean_us']:.1f}" if r['handler_mean_us'] else '-',
                 r['host_load1'] if r['host_load1'] is not None else '-'))
    print(f'\nwrote {out}')


if __name__ == '__main__':
    sys.exit(main())
