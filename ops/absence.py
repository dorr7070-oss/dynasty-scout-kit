#!/usr/bin/env python3
"""Missing starters THIS week (added 2026-10-04) — the live side of ops/absence_study.py.

Starters come from this season's snap counts (60%+ of the unit's snaps in most recent games: 2 of 3, 3 of 4); a starter is
counted missing when Sleeper lists him Out, Doubtful, IR, PUP, suspended or otherwise unavailable. weekly.py multiplies
in only the effects that passed the study's holdout test (data/absence_effects.json "use"), and shows every missing
starter as a flag either way, labelled with whether it moves the projection.

  live(season, week) -> {team: {'ol': [names], 'db': [names], 'front': [names]}}
  multiplier(pos, team, opp, live_) -> (mult, flag text or '')
"""
import csv, json, os, re, sys, unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import absence_study as AS  # noqa: E402

OUT = {'Out', 'Doubtful', 'IR', 'PUP', 'Sus', 'NA', 'DNR', 'COV', 'NFI'}
_E = json.load(open(os.path.join(DATA, 'absence_effects.json'))) if os.path.exists(os.path.join(DATA, 'absence_effects.json')) else {}
TO_SLEEPER = {'LA': 'LAR', 'WAS': 'WAS'}


def norm(n):
    n = unicodedata.normalize('NFKD', n or '').encode('ascii', 'ignore').decode().lower()
    n = re.sub(r"[.'\-]", '', n)
    n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def live(season, week):
    path = os.path.join(CACHE, f'snap_counts_{season}.csv')
    if not os.path.exists(path):
        return {}
    weeks = defaultdict(lambda: defaultdict(dict))
    for r in csv.DictReader(open(path, encoding='utf-8')):
        if r['game_type'] == 'REG' and r['week'].isdigit() and int(r['week']) < week:
            t = TO_SLEEPER.get(r['team'], r['team'])
            weeks[t][int(r['week'])][norm(r['player'])] = (r['position'], float(r['offense_pct'] or 0), float(r['defense_pct'] or 0), r['player'])
    P = json.load(open(os.path.join(DATA, 'players.json')))
    status = {}
    for p in P.values():
        if p.get('team') and p.get('full_name'):
            st = p.get('injury_status') or ('Inactive' if p.get('status') in ('Inactive', 'Injured Reserve') else None)
            status[(norm(p['full_name']), p['team'])] = st
    out = {}
    for t, wk in weeks.items():
        prev = sorted(wk)[-4:]
        if len(prev) < 3:
            continue
        seen, info = defaultdict(int), {}
        for w in prev:
            for n, (pos, op, dp, nm) in wk[w].items():
                if (op if pos in AS.OL else dp) >= 0.6:
                    seen[n] += 1; info[n] = (pos, nm)
        miss = {'ol': [], 'db': [], 'front': []}
        for n, k in seen.items():
            if k < -(-3 * len(prev) // 5):      # same starter rule as the study: 2 of 3, 3 of 4
                continue
            st = status.get((n, t))
            if st in OUT or st == 'Inactive':
                pos, nm = info[n]
                g = 'ol' if pos in AS.OL else 'db' if pos in AS.DB else 'front' if pos in AS.FRONT else None
                if g:
                    miss[g].append(f'{nm} ({pos}, {st})')
        out[t] = miss
    return out


def multiplier(pos, team, opp, live_):
    """(projection multiplier, flag) for one player. Only holdout-approved groups move the number."""
    eff, use = _E.get('effects') or {}, _E.get('use') or {}
    own, op = live_.get(team) or {}, live_.get(opp) or {}
    n = {'own_ol': len(own.get('ol', [])), 'opp_db': len(op.get('db', [])), 'opp_front': len(op.get('front', []))}
    m = AS.mult(eff, pos, n['own_ol'], n['opp_db'], n['opp_front'], use=use) if eff else 1.0
    bits = []
    if n['own_ol']:
        bits.append(f"own OL missing {n['own_ol']} starter{'s' if n['own_ol'] > 1 else ''}: {', '.join(own['ol'])}")
    if n['opp_db']:
        bits.append(f"{opp} secondary missing {n['opp_db']}: {', '.join(op['db'])}")
    if n['opp_front']:
        bits.append(f"{opp} front missing {n['opp_front']}: {', '.join(op['front'])}")
    if not bits:
        return 1.0, ''
    moved = f'projection x{m:.3f}' if abs(m - 1) > 0.0005 else 'shown for context; the measured effect did not hold up in testing'
    return m, 'missing starters: ' + '; '.join(bits) + f' ({moved})'


if __name__ == '__main__':
    import time
    lv = live(int(time.strftime('%Y')), int(sys.argv[1]) if len(sys.argv) > 1 else 5)
    for t, m in sorted(lv.items()):
        if any(m.values()):
            print(t, {k: v for k, v in m.items() if v})
