#!/usr/bin/env python3
"""Market-value trends: who is rising or crashing before the league reacts -> data/value_history/,
VALUE_TRENDS.md, dashboard "Market Movers" (after values.py / contracts.py).

Owner's choice (2026-10-02). Each run stores one compact snapshot per day of every player's MARKET
value (consensus `mean_market` — the contract-adjusted `mean` is our own view, not the market) in
data/value_history/<date>.json, then compares against ~7 and ~30 days ago.

Flags, for rostered players worth 500+ (or anyone on your roster):
  rising     +12% or more over 7 days (or +20% over 30): sell-high window on yours, act fast on theirs
  crashing   -12% or more over 7 days (or -20% over 30): buy-low candidate on theirs, decide on yours
A swing that size in a week is the market reacting to news (role change, injury, depth chart), and
the owner who moves first gets the old price.

  python3 ops/value_trends.py            snapshot + report
  python3 ops/value_trends.py --backfill rebuild past snapshots from this repo's git history of
                                         data/values/consensus.json (one per day; needs git)
"""
import json, os, subprocess, sys, time
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
HDIR = os.path.join(DATA, 'value_history')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402

MIN_VALUE, WEEK_PCT, MONTH_PCT = 500, 0.12, 0.20


def market(cons):
    return {pid: round(v.get('mean_market', v.get('mean', 0))) for pid, v in cons.items()
            if isinstance(v, dict) and (v.get('mean_market') or v.get('mean'))}


def backfill():
    git = lambda *a: subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True, timeout=60)
    log = git('log', '--format=%h %ad', '--date=short', '--', 'data/values/consensus.json').stdout.split('\n')
    seen = set()
    os.makedirs(HDIR, exist_ok=True)
    n = 0
    for line in log:                      # newest first: the first commit seen per day is that day's last
        if not line.strip():
            continue
        h, d = line.split()
        if d in seen or os.path.exists(os.path.join(HDIR, f'{d}.json')):
            seen.add(d)
            continue
        seen.add(d)
        r = git('show', f'{h}:data/values/consensus.json')
        if r.returncode == 0:
            json.dump(market(json.loads(r.stdout)), open(os.path.join(HDIR, f'{d}.json'), 'w'))
            n += 1
    print(f'value_trends: backfilled {n} daily snapshots from git history')


def nearest(days_ago, snaps):
    """Snapshot closest to N days ago (within +-60% of the span), or None."""
    target = date.today() - timedelta(days=days_ago)
    best = min(snaps, key=lambda d: abs((date.fromisoformat(d) - target).days), default=None)
    if best and abs((date.fromisoformat(best) - target).days) <= max(2, days_ago * 0.6):
        return best
    return None


def main():
    if '--backfill' in sys.argv:
        backfill()
    cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
    os.makedirs(HDIR, exist_ok=True)
    today = date.today().isoformat()
    now = market(cons)
    json.dump(now, open(os.path.join(HDIR, f'{today}.json'), 'w'))
    snaps = sorted(f[:-5] for f in os.listdir(HDIR) if f.endswith('.json') and f[:-5] != today)

    P = json.load(open(os.path.join(DATA, 'players.json')))
    season = max(d for d in os.listdir(DATA) if d.isdigit())
    R = json.load(open(os.path.join(DATA, season, 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, season, 'users.json')))}
    owner = {pid: U.get(r.get('owner_id')) for r in R for pid in (r.get('players') or [])}
    me = json.load(open(os.path.join(ROOT, 'config.json'))).get('my_username')

    refs = {k: nearest(d, snaps) for k, d in (('7d', 7), ('30d', 30))}
    hist = {k: json.load(open(os.path.join(HDIR, f'{d}.json'))) for k, d in refs.items() if d}
    rows = []
    for pid, v in now.items():
        if pid not in owner or P.get(pid, {}).get('position') not in LF.POS:
            continue
        if v < MIN_VALUE and owner[pid] != me:
            continue
        ch = {}
        for k, h in hist.items():
            old = h.get(pid)
            if old and old >= 100:
                ch[k] = (v - old) / old
        w, m = ch.get('7d'), ch.get('30d')
        tag = ('rising' if (w is not None and w >= WEEK_PCT) or (m is not None and m >= MONTH_PCT) else
               'crashing' if (w is not None and w <= -WEEK_PCT) or (m is not None and m <= -MONTH_PCT) else None)
        if tag:
            mine = owner[pid] == me
            act = (('SELL-HIGH window — shop him while the price is up' if mine else 'rising — buy now or the price keeps climbing')
                   if tag == 'rising' else
                   ('falling — check the news before selling into the dip' if mine else 'BUY-LOW candidate — the owner may sell at the new price'))
            rows.append({'pid': pid, 'name': P[pid].get('full_name'), 'pos': P[pid].get('position'),
                         'team': P[pid].get('team'), 'owner': owner[pid], 'value': v, 'w': w, 'm': m,
                         'tag': tag, 'action': act, 'injury': P[pid].get('injury_status')})
    rows.sort(key=lambda r: -abs(r['w'] if r['w'] is not None else r['m'] or 0))
    out = {'date': today, 'ref_7d': refs['7d'], 'ref_30d': refs['30d'], 'snapshots': len(snaps) + 1, 'movers': rows}
    json.dump(out, open(os.path.join(DATA, 'value_trends.json'), 'w'), indent=1)

    pct = lambda x: '—' if x is None else f'{x:+.0%}'
    L = [f'# Market Movers — {today}', '',
         f'_Market value (consensus of FantasyCalc / KTC / DynastyProcess / FantasyPros) vs {refs["7d"] or "n/a"} (7d) and '
         f'{refs["30d"] or "n/a"} (30d). Flags: ±{WEEK_PCT:.0%} in a week or ±{MONTH_PCT:.0%} in a month, rostered players worth '
         f'{MIN_VALUE}+ (all of yours). {len(snaps) + 1} daily snapshots on file._', '']
    for tag, title in (('rising', 'Rising'), ('crashing', 'Crashing')):
        L += [f'## {title}', '', '| Player | Owner | Value | 7d | 30d | Read |', '|---|---|---|---|---|---|']
        sel = [r for r in rows if r['tag'] == tag]
        L += [f"| {r['name']} ({r['pos']} {r['team'] or 'FA'}){' — ' + r['injury'] if r['injury'] else ''} | {r['owner']} | {r['value']:,} | "
              f"{pct(r['w'])} | {pct(r['m'])} | {r['action']} |" for r in sel[:15]] or ['| — | | | | | |']
        L.append('')
    open(os.path.join(ROOT, 'VALUE_TRENDS.md'), 'w').write('\n'.join(L))
    mine = [r for r in rows if r['owner'] == me]
    print(f"value_trends -> VALUE_TRENDS.md: {sum(r['tag'] == 'rising' for r in rows)} rising, "
          f"{sum(r['tag'] == 'crashing' for r in rows)} crashing (vs {refs['7d']} / {refs['30d']}); yours: "
          + (', '.join(f"{r['name']} {pct(r['w'] if r['w'] is not None else r['m'])}" for r in mine[:5]) or 'none'))


if __name__ == '__main__':
    main()
