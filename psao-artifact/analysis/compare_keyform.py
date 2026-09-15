#!/usr/bin/env python3
"""Combine the verify-rate sweeps into one table: key form x algorithm x rate.

Reads the verify_rate_curve.csv each sweep produces and joins them on rate so
the string-vs-preparsed and HS256-vs-RS256 comparisons can be read off directly
rather than by flipping between files.
"""
import argparse, csv, os, sys


def load(path):
    out = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            out.setdefault(r['pass'], {})[int(r['rate_rps'])] = {
                'mean': float(r['verify_mean_us']),
                'p50': float(r['verify_p50_us']),
                'p99': float(r['verify_p99_us']),
                'handler': float(r['handler_mean_us']) if r['handler_mean_us'] else None,
                'n': int(r['verify_count']),
                'load': r['host_load1'],
            }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--curve', action='append', required=True, metavar='LABEL=PATH')
    ap.add_argument('--pass-name', default='asc')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    curves = {}
    for spec in args.curve:
        label, path = spec.split('=', 1)
        if not os.path.exists(path):
            print(f'missing: {path}', file=sys.stderr)
            continue
        curves[label] = load(path)

    rates = sorted({r for c in curves.values()
                    for r in c.get(args.pass_name, {})})
    labels = list(curves)

    print('mean in-situ jwt.verify() cost, us  (pass=%s)\n' % args.pass_name)
    head = '%6s' % 'rps'
    for l in labels:
        head += ' %18s' % l
    print(head)
    print('-' * len(head))
    rows = []
    for rate in rates:
        line = '%6d' % rate
        rec = {'rate_rps': rate}
        for l in labels:
            v = curves[l].get(args.pass_name, {}).get(rate)
            line += ' %18s' % (f'{v["mean"]:.2f}' if v else '-')
            rec[l] = v['mean'] if v else None
        rows.append(rec)
        print(line)

    # Ratios between the first two curves, which is where the interesting
    # comparison usually sits (string vs preparsed, or HS256 vs RS256).
    if len(labels) >= 2:
        a, b = labels[0], labels[1]
        print(f'\nratio {a} / {b}:')
        for rate in rates:
            va = curves[a].get(args.pass_name, {}).get(rate)
            vb = curves[b].get(args.pass_name, {}).get(rate)
            if va and vb:
                print('  %6d rps  %7.1fx   (%.1f us saved)'
                      % (rate, va['mean'] / vb['mean'], va['mean'] - vb['mean']))

    if args.out:
        with open(args.out, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['rate_rps'] + labels)
            for r in rows:
                w.writerow([r['rate_rps']] + [f'{r[l]:.2f}' if r[l] else '' for l in labels])
        print(f'\nwrote {args.out}')


if __name__ == '__main__':
    sys.exit(main())
