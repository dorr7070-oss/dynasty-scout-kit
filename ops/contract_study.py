#!/usr/bin/env python3
"""Measure what a contract year actually does to next season -> data/contract_effects.json

Question: when a fantasy-relevant player is in the LAST year of his NFL contract, how much of
his production does he keep the next season, and how often does he change teams — compared
with similar players who are NOT in a contract year? Measured, not guessed, so ops/contracts.py
can weight contract years by evidence (owner decision, 2026-10-02).

Data (free, nflverse):
  historical_contracts.csv.gz  every OverTheCap contract: year_signed, years, apy, draft year
  stats_player_reg_<year>.csv  season totals incl. PPR points, games, team
Window: seasons 2018-2021 (the contract file is complete for signings through 2021; 2022+
signings are partial, which would mislabel extended players as walk years), outcome = the
following season (2019-2022).

Method: a player-season is a contract year when his latest contract signed on/before that
season ends that season. Retention = next-season PPR per game / this season's (a season with
fewer than 4 games next year counts as 0, the "washout"; capped at 2.0). Compared within
position x deal type (rookie deal vs veteran deal) x age band. Effect = contract-year mean
retention / non-contract-year mean retention. Joined on name + position (no shared id).
"""
import csv, gzip, json, os, re, statistics, subprocess, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'data', 'cache', 'contracts_hist')
OUT = os.path.join(ROOT, 'data', 'contract_effects.json')
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
SEASONS = range(2018, 2022)
POS = ('QB', 'RB', 'WR', 'TE')
MIN_G, MIN_PPG = 6, 6.0          # fantasy-relevant this season


def grab(url, path):
    if not os.path.exists(path) or os.path.getsize(path) < 10000:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(['curl', '-sL', '-m', '180', '-o', path, url], check=True)
    return path


def norm(n):
    n = re.sub(r"[^a-z ]", '', (n or '').lower().replace('.', '').replace('-', ' '))
    return ' '.join(w for w in n.split() if w not in ('jr', 'sr', 'ii', 'iii', 'iv', 'v'))


def age_band(age):
    return '<=25' if age <= 25 else '26-28' if age <= 28 else '29+'


def main():
    if os.path.exists(OUT) and '--force' not in sys.argv:
        print('contract study: data/contract_effects.json already built (historical, fixed) — skip; --force to redo')
        return
    cpath = grab(f'{REL}/contracts/historical_contracts.csv.gz', os.path.join(CACHE, 'historical_contracts.csv.gz'))
    contracts = defaultdict(list)
    for r in csv.DictReader(gzip.open(cpath, 'rt', encoding='utf-8')):
        try:
            ys, yrs = int(r['year_signed']), int(r['years'])
        except ValueError:
            continue
        if ys <= 0 or yrs <= 0 or r['position'] not in POS:
            continue
        dy = int(r['draft_year']) if (r.get('draft_year') or '').isdigit() else None
        contracts[(norm(r['player']), r['position'])].append(
            {'ys': ys, 'end': ys + yrs - 1, 'rookie': dy is not None and ys == dy, 'dy': dy,
             'apy': float(r['apy'] or 0)})

    stats = {}
    for y in range(min(SEASONS), max(SEASONS) + 2):
        p = grab(f'{REL}/stats_player/stats_player_reg_{y}.csv', os.path.join(CACHE, f'stats_reg_{y}.csv'))
        for r in csv.DictReader(open(p, encoding='utf-8')):
            if r.get('position') not in POS:
                continue
            g = int(float(r.get('games') or 0))
            pts = float(r.get('fantasy_points_ppr') or 0)
            stats[(norm(r['player_display_name'] or r['player_name']), r['position'], y)] = \
                {'g': g, 'ppg': pts / g if g else 0, 'team': r.get('recent_team')}

    rows = []
    for (nm, pos, y), s in stats.items():
        if y not in SEASONS or s['g'] < MIN_G or s['ppg'] < MIN_PPG:
            continue
        cs = [c for c in contracts.get((nm, pos), []) if c['ys'] <= y]
        if not cs:
            continue
        cur = max(cs, key=lambda c: (c['ys'], c['end']))
        if cur['end'] < y:
            continue                                  # no contract on record for this season
        walk = cur['end'] == y
        dy = cur['dy'] or next((c['dy'] for c in cs if c['dy']), None)
        age = (y - dy + 22) if dy else 27             # draft age ~22 when birth date is missing
        nxt = stats.get((nm, pos, y + 1))
        ret = min(2.0, nxt['ppg'] / s['ppg']) if nxt and nxt['g'] >= 4 else 0.0
        moved = bool(nxt and nxt['team'] and s['team'] and nxt['team'] != s['team'])
        rows.append({'pos': pos, 'deal': 'rookie' if cur['rookie'] else 'veteran', 'age': age_band(age),
                     'walk': walk, 'ret': ret, 'moved': moved, 'washout': ret == 0})

    def summarize(sel):
        out = {}
        for walk in (True, False):
            g = [r for r in sel if r['walk'] == walk]
            if g:
                out['walk' if walk else 'other'] = {
                    'n': len(g), 'retention': round(statistics.mean(r['ret'] for r in g), 3),
                    'moved': round(sum(r['moved'] for r in g) / len(g), 3),
                    'washout': round(sum(r['washout'] for r in g) / len(g), 3)}
        if 'walk' in out and 'other' in out and out['other']['retention']:
            out['effect'] = round(out['walk']['retention'] / out['other']['retention'], 3)
        return out

    cells = {}
    for pos in POS:
        cells[pos] = summarize([r for r in rows if r['pos'] == pos])
        for deal in ('rookie', 'veteran'):
            cells[f'{pos}|{deal}'] = summarize([r for r in rows if r['pos'] == pos and r['deal'] == deal])
            for band in ('<=25', '26-28', '29+'):
                cells[f'{pos}|{deal}|{band}'] = summarize([r for r in rows if r['pos'] == pos and r['deal'] == deal and r['age'] == band])
    result = {'window': f'{min(SEASONS)}-{max(SEASONS)} seasons, outcome next season', 'rows': len(rows),
              'all': summarize(rows), 'cells': cells}
    json.dump(result, open(OUT, 'w'), indent=1)
    print(f'contract study -> data/contract_effects.json ({len(rows)} player-seasons)')
    a = result['all']
    print(f"  ALL: contract year retention {a['walk']['retention']:.2f} (n={a['walk']['n']}, moved {a['walk']['moved']:.0%}) "
          f"vs other {a['other']['retention']:.2f} (n={a['other']['n']}, moved {a['other']['moved']:.0%}) -> effect {a.get('effect')}")
    for k in sorted(cells):
        c = cells[k]
        if 'walk' in c and c['walk']['n'] >= 8:
            print(f"  {k:22} walk n={c['walk']['n']:3} ret {c['walk']['retention']:.2f} moved {c['walk']['moved']:.0%} wash {c['walk']['washout']:.0%}"
                  + (f" | other n={c['other']['n']:3} ret {c['other']['retention']:.2f} moved {c['other']['moved']:.0%} -> effect {c.get('effect')}" if 'other' in c else ''))


if __name__ == '__main__':
    main()
