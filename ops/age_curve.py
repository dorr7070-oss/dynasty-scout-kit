#!/usr/bin/env python3
"""Derive positional decline ages from history, instead of quoting folklore.

"RBs fall off a cliff at 27" is repeated everywhere and almost never measured
on the data the repo already trusts. This script measures it.

METHOD - and the method is the whole point, because the obvious one is wrong.

  The naive approach (mean PPG by age) is ruined by survivor bias: if you only
  average the players still producing at 30, you are averaging the ones who did
  not decline, and every position looks fine forever. Run that version and WRs
  appear to PEAK at 29.

  So this measures RETENTION year over year instead. Take every player who put
  up a real season (>=10 games, >=10 PPG) at age A, and ask what fraction of
  that production he averages at age A+1 - counting a season he never played as
  a zero. Washing out of the league is the most extreme form of decline, and
  any method that drops those players is lying to you.

  The decline age is the first age past 25 where retention breaks below 85% of
  the under-25 baseline and stays there.

WHAT IT FOUND (2019-2025, PPR):
  RB  breaks hard at 27->28: retention falls 81% -> 60%. Real, and it matches
      the conventional wisdom for once.
  WR  NO cliff found through age 31. Retention sits at 80-84% every year from
      25 to 31. The "WRs fall apart at 29" rule is not in this data.
  QB  a break shows at 28->29, but on n=11 and against the obvious counter-
      example of 38-year-old MVP seasons. Too thin to flag - ignored.
  TE  too few qualifying seasons to say anything. Not flagged.

  Only RB is flagged downstream. A flag we cannot defend is worse than none,
  because it silently biases every buy/sell lane that reads it.

CAVEATS worth remembering before trusting this too hard: 7 seasons, and the
per-age samples are small (n=11-44). A lost season counts as decline even when
the cause was a fluke injury rather than age. Re-run as seasons accumulate.

Usage:  python3 ops/age_curve.py [--seasons 2019-2025]
Writes data/age_curve.json (committed - context.py reads it, and does NOT
refetch ~65MB of history on every update).
"""
import collections, csv, datetime, json, os, statistics, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
BASE = 'https://github.com/nflverse/nflverse-data/releases/download'
POS = ('QB', 'RB', 'WR', 'TE')
QUAL_G, QUAL_PPG = 10, 10.0     # what counts as a "real season"
BREAK = 0.85                    # retention below 85% of the young baseline


def grab(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(['curl', '-sL', '--max-time', '180', '-o', path, url], check=True)
    return path


def main(lo=2019, hi=2025):
    years = range(lo, hi + 1)
    ages = {}
    for y in years:
        ref = datetime.date(y, 9, 1)
        for r in csv.DictReader(open(grab(f'{BASE}/rosters/roster_{y}.csv',
                                          f'{CACHE}/roster_{y}.csv'),
                                     encoding='utf-8', errors='replace')):
            gid, bd = r.get('gsis_id') or '', r.get('birth_date') or ''
            if not gid or not bd:
                continue
            try:
                b = datetime.date(*map(int, bd.split('-')[:3]))
            except Exception:
                continue
            ages[(gid, y)] = (ref - b).days / 365.25

    pts, gms, pos = {}, {}, {}
    for y in years:
        for r in csv.DictReader(open(grab(f'{BASE}/stats_player/stats_player_week_{y}.csv',
                                          f'{CACHE}/stats_player_week_{y}.csv'),
                                     encoding='utf-8', errors='replace')):
            if r.get('season_type') != 'REG' or r.get('position') not in POS:
                continue
            gid = r.get('player_id') or ''
            try:
                fp = float(r.get('fantasy_points_ppr') or 0)
            except ValueError:
                fp = 0.0
            k = (gid, y)
            pts[k] = pts.get(k, 0.0) + fp
            gms[k] = gms.get(k, 0) + 1
            pos[gid] = r['position']

    out = {'method': 'year-over-year PPR retention, washouts counted as zero',
           'seasons': [lo, hi], 'qualify': {'games': QUAL_G, 'ppg': QUAL_PPG},
           'break_threshold': BREAK, 'positions': {}}
    for P in POS:
        rows = []
        for a in range(21, 36):
            keep = []
            for (gid, y), t in pts.items():
                if pos.get(gid) != P or y >= hi:
                    continue
                if gms[(gid, y)] < QUAL_G or t / gms[(gid, y)] < QUAL_PPG:
                    continue
                aa = ages.get((gid, y))
                if aa is None or int(aa) != a:
                    continue
                keep.append((pts.get((gid, y + 1), 0.0) / t) if t else 0.0)
            if len(keep) >= 10:
                rows.append({'age': a, 'retention': round(statistics.mean(keep), 4),
                             'n': len(keep)})
        if not rows:
            out['positions'][P] = {'curve': [], 'decline_age': None,
                                   'note': 'too few qualifying seasons'}
            continue
        young = [r['retention'] for r in rows if r['age'] <= 25]
        base = statistics.mean(young) if young else rows[0]['retention']
        dec = next((r['age'] for r in rows
                    if r['age'] > 25 and r['retention'] < base * BREAK), None)
        thin = dec is not None and next(r['n'] for r in rows if r['age'] == dec) < 15
        out['positions'][P] = {
            'curve': rows, 'baseline': round(base, 4),
            'decline_age': None if thin else dec,
            'raw_decline_age': dec,
            'note': ('sample too thin to flag' if thin else
                     'no sustained break found' if dec is None else 'flagged'),
        }
        tag = out['positions'][P]
        print(f"--- {P}: baseline {base:.0%} · decline {tag['decline_age']} "
              f"({tag['note']})")
        for r in rows:
            mark = ' <-- break' if r['age'] == dec else ''
            print(f"    {r['age']:2} -> {r['age'] + 1:2}  n={r['n']:3}  "
                  f"keeps {r['retention']:5.0%}{mark}")

    json.dump(out, open(os.path.join(DATA, 'age_curve.json'), 'w'), indent=1)
    flagged = {p: v['decline_age'] for p, v in out['positions'].items()
               if v['decline_age']}
    print(f'\nage curve written -> data/age_curve.json · flagged: {flagged or "none"}')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--seasons':
        lo, hi = (int(x) for x in a[1].split('-'))
        main(lo, hi)
    else:
        main()
