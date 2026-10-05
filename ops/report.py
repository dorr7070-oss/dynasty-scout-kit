#!/usr/bin/env python3
"""League report: consensus power rankings + a focus-team breakdown.

Run after fetch.py / values.py / profiles.py:
    python3 ops/report.py            # league table + my team (config my_username)
    python3 ops/report.py someowner  # focus any owner instead
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_format as LF  # noqa: E402
from picks import pick_value, owned_future_picks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))

players = json.load(open(os.path.join(DATA, 'players.json')))
seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
latest = seasons[-1]
rosters = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
users = json.load(open(os.path.join(DATA, latest, 'users.json')))
cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
profiles = json.load(open(os.path.join(ROOT, 'profiles', 'profiles.json')))

uid_name = {u['user_id']: ((u.get('metadata') or {}).get('team_name') or u['display_name'])
            for u in users}
uid_user = {u['user_id']: u['display_name'] for u in users}


def pval(pid):
    return cons.get(pid, {}).get('mean', 0)


# future-pick value per team from the shared tier model (Early/Mid/Late by original owner)
OWNED = owned_future_picks()
PKVAL = {rid: sum(pick_value(s, rnd, orig)[0] for s, rnd, orig in OWNED.get(rid, []))
         for rid in OWNED}


def team(r):
    plist = [p for p in (r.get('players') or [])
             if players.get(p, {}).get('position') in ('QB', 'RB', 'WR', 'TE')]
    plist.sort(key=lambda p: -pval(p))
    sv, _ = LF.best_lineup_ids((pval(p), p, players[p]['position']) for p in plist)
    pk = PKVAL.get(r['roster_id'], 0.0)
    tot = sum(pval(p) for p in plist)
    return sv, tot, pk, plist


rows = []
for r in rosters:
    uid = r.get('owner_id')
    sv, tot, pk, plist = team(r)
    rows.append({'name': uid_name.get(uid, '?'), 'user': uid_user.get(uid, '?'),
                 'sv': sv, 'tot': tot, 'pk': pk, 'g': tot + pk, 'plist': plist})

print(f"\n=== {latest} CONSENSUS POWER RANKINGS "
      f"(players FC/KTC/expert; picks by Early/Mid/Late tier) ===")
print(f"  starters = win-now (this-season) lineup · total = dynasty (roster + picks)")
print(f"{'#':>2} {'team':30} {'starters':>9} {'roster':>8} {'picks':>7} {'total':>8}")
for i, r in enumerate(sorted(rows, key=lambda x: -x['g']), 1):
    print(f"{i:2} {r['name'][:29]:30} {r['sv']:9.0f} {r['tot']:8.0f} {r['pk']:7.0f} {r['g']:8.0f}")

focus_user = sys.argv[1] if len(sys.argv) > 1 else CFG['my_username']
focus = next((r for r in rows if r['user'] == focus_user), None)
if focus:
    print(f"\n=== FOCUS: {focus['name']} ({focus_user}) ===")
    for p in focus['plist'][:16]:
        pl = players[p]
        c = cons.get(p, {})
        flag = '  <- wide spread, negotiate with source choice' if c.get('spread', 0) > 1200 else ''
        print(f"  {pl['position']:3} {pl.get('full_name',''):24} age {pl.get('age','?'):>2} "
              f"{c.get('mean',0):6.0f} (n={c.get('n',0)}){flag}")
    prof = profiles.get(focus_user)
    if prof:
        print('  picks:', ', '.join(prof['picks']) or 'none')
        print('  read:', ' | '.join(prof['labels']))
