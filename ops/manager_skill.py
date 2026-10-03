#!/usr/bin/env python3
"""Manager-skill analysis: how well each owner actually RUNS their team,
separate from how they trade.

Three lenses (per owner, keyed by Sleeper user_id so they follow the owner
across seasons/team-name changes):

  1. Lineup efficiency  -- EXACT. For every played week we compute the best
     legal lineup from the players that owner actually rostered that week
     (using real weekly scoring in matchups.json) and compare it to what they
     started. Surfaces who leaves points on the bench.
  2. Drop analysis      -- PROXY (current consensus value). Players an owner
     cut to waivers who are now valuable assets = drops that aged badly.
  3. Waiver / draft hit  -- PROXY (current consensus value). Share of an
     owner's waiver adds / rookie-draft picks that are now real assets.

Only lens #1 is ground-truth (actual points scored). #2 and #3 use current
value as a stand-in for "did it matter" -- we don't have historical
rest-of-season production for unrostered players, so treat them as directional,
not gospel. Labeled as such in the output.

Writes MANAGER_SKILL.md (human) and data/manager_skill.json (machine).
Run after fetch.py + values.py (stdlib only, no network).
"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_format as LF  # noqa: E402
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

players = json.load(open(os.path.join(DATA, 'players.json')))
seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
consensus = {}
cpath = os.path.join(DATA, 'values', 'consensus.json')
if os.path.exists(cpath):
    consensus = json.load(open(cpath))

# thresholds for the value-proxy lenses (dynasty 0-10,000 scale)
ASSET = 1500      # a useful bench/flex asset
STARTER = 2000    # a real contributor / draft "hit"


def load(season, name):
    path = os.path.join(DATA, season, name)
    return json.load(open(path)) if os.path.exists(path) else None


def pos(pid):
    return (players.get(pid) or {}).get('position') or '?'


def pname(pid):
    p = players.get(pid) or {}
    return p.get('full_name') or p.get('last_name') or (f"{pos(pid)} {pid}" if pid else '?')


def pval(pid):
    return consensus.get(pid, {}).get('mean', 0)


# starting slots come from the current league config (BN excluded)
league = load(seasons[-1], 'league.json') or {}
SLOTS = [s for s in (league.get('roster_positions') or []) if s != 'BN']
FLEX_OK = {'RB', 'WR', 'TE'}


def optimal_points(pts_by_pid):
    """Max-points legal lineup from {pid: week_points}, for this league's slots
    (any flex types: FLEX, SUPER_FLEX, WR/RB, WR/TE)."""
    by_pos = defaultdict(list)
    for pid, pt in pts_by_pid.items():
        by_pos[pos(pid)].append(pt)
    return LF.fill_slots(SLOTS, by_pos)


# ---- gather per-owner data across all seasons -------------------------------
class Mgr:
    def __init__(self):
        self.actual = 0.0
        self.optimal = 0.0
        self.weeks = 0
        self.worst = None            # (season, week, points_left)
        self.drops = []              # (pid, season)
        self.waiver_adds = []        # pid
        self.rookie_picks = []       # pid
        self.name = None


mgr = defaultdict(Mgr)

for season in seasons:
    rosters = load(season, 'rosters.json') or []
    users = load(season, 'users.json') or []
    rid_uid = {r['roster_id']: r.get('owner_id') for r in rosters}
    for u in users:
        team = (u.get('metadata') or {}).get('team_name')
        mgr[u['user_id']].name = f"{team or u['display_name']} ({u['display_name']})"

    # lineup efficiency (exact) --------------------------------------------
    matchups = load(season, 'matchups.json') or {}
    for week, entries in matchups.items():
        for e in entries:
            uid = rid_uid.get(e.get('roster_id'))
            if not uid:
                continue
            starters_pts = [p for p in (e.get('starters_points') or []) if p is not None]
            actual = sum(starters_pts)
            ppts = {pid: pt for pid, pt in (e.get('players_points') or {}).items()}
            # skip unplayed weeks (future season / bye) -- nobody scored
            if actual <= 0 and not any(v > 0 for v in ppts.values()):
                continue
            opt = optimal_points(ppts)
            m = mgr[uid]
            m.actual += actual
            m.optimal += opt
            m.weeks += 1
            left = opt - actual
            if m.worst is None or left > m.worst[2]:
                m.worst = (season, week, left)

    # drops + waiver adds + rookie picks -----------------------------------
    for t in load(season, 'transactions.json') or []:
        if t.get('status') != 'complete':
            continue
        typ = t.get('type')
        if typ in ('waiver', 'free_agent'):
            for pid, rid in (t.get('adds') or {}).items():
                uid = rid_uid.get(rid)
                if uid:
                    mgr[uid].waiver_adds.append(pid)
            for pid, rid in (t.get('drops') or {}).items():
                uid = rid_uid.get(rid)
                if uid:
                    mgr[uid].drops.append((pid, season))

    for dr in load(season, 'drafts.json') or []:
        if len(dr.get('picks', [])) > 60:      # startup draft -- not a "hit rate" signal
            continue
        for pk in dr.get('picks', []):
            uid = pk.get('picked_by')
            if uid:
                mgr[uid].rookie_picks.append(pk['player_id'])

# who currently rosters each player (for "the drop is now on X's team")
current_owner = {}
latest = seasons[-1]
for r in load(latest, 'rosters.json') or []:
    uid = r.get('owner_id')
    for pid in (r.get('players') or []):
        current_owner[pid] = uid
uid_shortname = {uid: (m.name or uid).split('(')[-1].rstrip(')') for uid, m in mgr.items()}


# ---- build report -----------------------------------------------------------
rows = []
for uid, m in mgr.items():
    if not m.name or m.weeks == 0:
        continue
    eff = m.actual / m.optimal if m.optimal else 0
    left_total = m.optimal - m.actual
    left_pg = left_total / m.weeks if m.weeks else 0

    notable_drops = sorted(
        ((pid, s, pval(pid)) for pid, s in m.drops if pval(pid) >= ASSET),
        key=lambda x: -x[2])
    # dedupe by player (a player cut more than once shows once, highest value)
    seen = set()
    nd = []
    for pid, s, v in notable_drops:
        if pid in seen:
            continue
        seen.add(pid)
        nd.append((pid, s, v))

    add_hits = sum(1 for pid in set(m.waiver_adds) if pval(pid) >= ASSET)
    add_total = len(set(m.waiver_adds))
    pick_hits = sum(1 for pid in m.rookie_picks if pval(pid) >= STARTER)
    pick_total = len(m.rookie_picks)

    rows.append({
        'uid': uid, 'name': m.name, 'short': uid_shortname.get(uid, uid),
        'efficiency': round(eff * 100, 1), 'weeks': m.weeks,
        'left_total': round(left_total, 1), 'left_per_game': round(left_pg, 1),
        'worst': m.worst,
        'notable_drops': nd[:6],
        'add_hits': add_hits, 'add_total': add_total,
        'add_rate': round(100 * add_hits / add_total, 1) if add_total else 0,
        'pick_hits': pick_hits, 'pick_total': pick_total,
        'pick_rate': round(100 * pick_hits / pick_total, 1) if pick_total else 0,
    })

rows.sort(key=lambda r: -r['efficiency'])

md = ['# Manager Skill — how each owner RUNS their team',
      '',
      '_Generated from full league history. **Lineup efficiency is exact** '
      '(real weekly scoring, best legal lineup vs what they started). '
      'Drops / waiver / draft use **current consensus value as a proxy** for '
      '"did it matter" — directional, not gospel._',
      '',
      '## Lineup efficiency — league ranking',
      '',
      'Higher = starts closer to their optimal lineup. Points/game left on the '
      'bench is the beatable-manager signal.',
      '',
      '| # | Team | Efficiency | Pts left/gm | Total pts left | Weeks |',
      '|---|---|---|---|---|---|']
for i, r in enumerate(rows, 1):
    md.append(f"| {i} | {r['name']} | {r['efficiency']}% | "
              f"{r['left_per_game']} | {r['left_total']} | {r['weeks']} |")

md += ['', '## Per-owner detail', '']
for r in rows:
    md.append(f"### {r['name']}")
    md.append(f"- **Lineup efficiency:** {r['efficiency']}% "
              f"({r['left_per_game']} pts/game left on bench over {r['weeks']} played weeks)")
    if r['worst']:
        s, w, left = r['worst']
        md.append(f"- **Worst single week:** {s} wk{w} — left {round(left, 1)} on the bench")
    if r['add_total']:
        md.append(f"- **Waiver hit rate (proxy):** {r['add_rate']}% "
                  f"({r['add_hits']}/{r['add_total']} adds are now ≥{ASSET} value)")
    if r['pick_total']:
        md.append(f"- **Rookie-draft hit rate (proxy):** {r['pick_rate']}% "
                  f"({r['pick_hits']}/{r['pick_total']} picks are now ≥{STARTER} value)")
    if r['notable_drops']:
        md.append(f"- **Notable drops (now ≥{ASSET} value):**")
        for pid, s, v in r['notable_drops']:
            now = current_owner.get(pid)
            where = f" — now on {uid_shortname.get(now)}" if now else " — currently a free agent"
            md.append(f"    - {pname(pid)} ({pos(pid)}, {round(v):,}), cut {s}{where}")
    md.append('')

open(os.path.join(ROOT, 'MANAGER_SKILL.md'), 'w').write('\n'.join(md))
json.dump({r['short']: r for r in rows},
          open(os.path.join(DATA, 'manager_skill.json'), 'w'), indent=1, default=str)
print(f"manager skill written: {len(rows)} owners -> MANAGER_SKILL.md")
lead = rows[0] if rows else None
tail = rows[-1] if rows else None
if lead and tail:
    print(f"  most efficient: {lead['short']} {lead['efficiency']}%  |  "
          f"least: {tail['short']} {tail['efficiency']}% "
          f"({tail['left_per_game']} pts/gm left on bench)")
