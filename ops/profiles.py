#!/usr/bin/env python3
"""Build/update owner profiles from full league history.

For every owner (keyed by Sleeper user_id so profiles follow them across
seasons and team-name changes) this mines:
  - franchise results per season (record, points, playoff finish)
  - complete trade ledger (players + picks + FAAB, both sides, per partner)
  - draft behavior (position mix by round, startup vs rookie drafts)
  - waiver/FAAB behavior (adds per season, budget spent)
  - behavioral tendencies (computed): trade appetite, pick hoarder vs
    spender, youth-seeker vs win-now buyer, positional biases
  - current stance: window classification from consensus values

Writes profiles/<username>.md (human) and profiles/profiles.json (machine).
Anything you write below the MANUAL SCOUTING NOTES marker in a profile is
preserved verbatim across regenerations - that's where your own reads go.

Run after fetch.py and values.py.
"""
import json, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_format as LF  # noqa: E402
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
PROF = os.path.join(ROOT, 'profiles')
NOTES_MARK = '<!-- MANUAL SCOUTING NOTES - everything below survives regeneration -->'

players = json.load(open(os.path.join(DATA, 'players.json')))
seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
consensus = {}
cpath = os.path.join(DATA, 'values', 'consensus.json')
if os.path.exists(cpath):
    consensus = json.load(open(cpath))


def pname(pid):
    p = players.get(pid, {})
    return p.get('full_name') or (f"{p.get('position','?')} {pid}" if pid else '?')


def ppos(pid):
    return players.get(pid, {}).get('position') or '?'


def page(pid):
    return players.get(pid, {}).get('age') or 0


def pval(pid):
    return consensus.get(pid, {}).get('mean', 0)


def load(season, name):
    path = os.path.join(DATA, season, name)
    return json.load(open(path)) if os.path.exists(path) else None


class Owner:
    def __init__(self, uid):
        self.uid = uid
        self.names = {}          # season -> display/team name
        self.results = {}        # season -> dict
        self.trades = []         # chronological trade dicts
        self.drafts = {}         # season -> list of picks
        self.waivers = {}        # season -> {'adds': n, 'faab': n}
        self.current_roster = []
        self.current_picks = []


owners = {}


def owner(uid):
    if uid not in owners:
        owners[uid] = Owner(uid)
    return owners[uid]


champions = {}

for season in seasons:
    users = load(season, 'users.json') or []
    rosters = load(season, 'rosters.json') or []
    league = load(season, 'league.json') or {}
    uid_name = {}
    for u in users:
        team = (u.get('metadata') or {}).get('team_name')
        uid_name[u['user_id']] = {'user': u['display_name'], 'team': team}
        o = owner(u['user_id'])
        o.names[season] = f"{team or u['display_name']} ({u['display_name']})"
    rid_uid = {r['roster_id']: r.get('owner_id') for r in rosters}

    # results (a PAST season where nothing was ever scored is a draft-only/startup
    # year; the newest season is always "current" even at 0-0)
    played = season == max(seasons) or any(
        r['settings']['wins'] or r['settings']['losses'] or r['settings'].get('fpts')
        for r in rosters)
    standings = sorted(rosters, key=lambda r: (-r['settings']['wins'], -r['settings'].get('fpts', 0)))
    bracket = load(season, 'winners_bracket.json') or []
    champ_rid = None
    for m in bracket:
        if m.get('p') == 1 and m.get('w'):
            champ_rid = m['w']
    for place, r in enumerate(standings, 1):
        uid = r.get('owner_id')
        if not uid:
            continue
        s = r['settings']
        if not played:
            owner(uid).results[season] = {'record': '—', 'wins': 0, 'fpts': 0,
                                          'place': None, 'champion': False,
                                          'note': 'startup / draft only'}
            continue
        owner(uid).results[season] = {
            'record': f"{s['wins']}-{s['losses']}", 'wins': s['wins'],
            'fpts': s.get('fpts', 0), 'place': place,
            'champion': r['roster_id'] == champ_rid,
        }
        if r['roster_id'] == champ_rid:
            champions[season] = uid

    # drafts
    for dr in load(season, 'drafts.json') or []:
        dtype = 'startup' if len(dr.get('picks', [])) > 60 else 'rookie'
        for pk in dr.get('picks', []):
            uid = pk.get('picked_by')
            if not uid:
                continue
            owner(uid).drafts.setdefault(season, []).append({
                'round': pk['round'], 'pick': pk['pick_no'],
                'player': pk['player_id'], 'type': dtype,
            })

    # transactions
    for t in sorted(load(season, 'transactions.json') or [], key=lambda x: x.get('created', 0)):
        when = datetime.fromtimestamp(t.get('created', 0) / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
        if t.get('type') == 'trade' and t.get('status') == 'complete':
            sides = defaultdict(lambda: {'got_players': [], 'got_picks': [], 'got_faab': 0})
            for pid, rid in (t.get('adds') or {}).items():
                sides[rid]['got_players'].append(pid)
            for dp in t.get('draft_picks') or []:
                sides[dp['owner_id']]['got_picks'].append(
                    f"{dp['season']} R{dp['round']} (orig r{dp['roster_id']})")
            for wb in t.get('waiver_budget') or []:
                sides[wb['receiver']]['got_faab'] += wb['amount']
            rids = list(sides.keys()) or (t.get('roster_ids') or [])
            for rid in rids:
                uid = rid_uid.get(rid)
                if not uid:
                    continue
                others = [r for r in (t.get('roster_ids') or rids) if r != rid]
                partner = ', '.join(
                    (owners.get(rid_uid.get(r)) and owners[rid_uid[r]].names.get(season, '?')) or '?'
                    for r in others)
                gave_players = [p for r2, s2 in sides.items() if r2 != rid for p in s2['got_players']]
                gave_picks = [p for r2, s2 in sides.items() if r2 != rid for p in s2['got_picks']]
                owner(uid).trades.append({
                    'season': season, 'date': when, 'partner': partner,
                    'got_players': sides[rid]['got_players'],
                    'got_picks': sides[rid]['got_picks'],
                    'got_faab': sides[rid]['got_faab'],
                    'gave_players': gave_players, 'gave_picks': gave_picks,
                })
        elif t.get('type') in ('waiver', 'free_agent') and t.get('status') == 'complete':
            for pid, rid in (t.get('adds') or {}).items():
                uid = rid_uid.get(rid)
                if not uid:
                    continue
                w = owner(uid).waivers.setdefault(season, {'adds': 0, 'faab': 0})
                w['adds'] += 1
                w['faab'] += (t.get('settings') or {}).get('waiver_bid') or 0

# current roster + picks (latest season)
latest = seasons[-1]
rosters = load(latest, 'rosters.json') or []
traded = load(latest, 'traded_picks.json') or []
rid_uid = {r['roster_id']: r.get('owner_id') for r in rosters}
pick_owner = {}
future = [str(int(latest) + 1), str(int(latest) + 2)]
for rid in rid_uid:
    for season in future:
        for rnd in range(1, int(LF.PROFILE.get('rookie_draft_rounds') or 3) + 1):
            pick_owner[(season, rnd, rid)] = rid
for t in traded:
    if t['season'] in future:
        pick_owner[(t['season'], t['round'], t['roster_id'])] = t['owner_id']
for r in rosters:
    uid = r.get('owner_id')
    if not uid:
        continue
    o = owner(uid)
    o.current_roster = [p for p in (r.get('players') or []) if ppos(p) in ('QB', 'RB', 'WR', 'TE')]
    o.current_picks = sorted(
        f"{s} R{rnd}" + ('' if orig == r['roster_id'] else f" (via r{orig})")
        for (s, rnd, orig), own_rid in pick_owner.items() if own_rid == r['roster_id'])


def tendencies(o):
    n_seasons = max(1, len(o.results))
    t = {}
    t['trades_per_season'] = round(len(o.trades) / n_seasons, 1)
    picks_in = sum(len(x['got_picks']) for x in o.trades)
    picks_out = sum(len(x['gave_picks']) for x in o.trades)
    t['net_picks_traded'] = picks_in - picks_out
    ages_in = [page(p) for x in o.trades for p in x['got_players'] if page(p)]
    ages_out = [page(p) for x in o.trades for p in x['gave_players'] if page(p)]
    t['avg_age_acquired'] = round(statistics.mean(ages_in), 1) if ages_in else None
    t['avg_age_shipped'] = round(statistics.mean(ages_out), 1) if ages_out else None
    pos_in = Counter(ppos(p) for x in o.trades for p in x['got_players'])
    t['positions_bought'] = dict(pos_in.most_common())
    t['faab_per_season'] = round(sum(w['faab'] for w in o.waivers.values()) / n_seasons)
    t['adds_per_season'] = round(sum(w['adds'] for w in o.waivers.values()) / n_seasons, 1)
    roster_val = sum(pval(p) for p in o.current_roster)
    pickv = {1: 3000, 2: 1100, 3: 400}
    pick_val = sum(pickv.get(int(p.split('R')[1][0]), 150) for p in o.current_picks)   # any round count
    t['roster_value'] = round(roster_val)
    t['pick_value'] = pick_val
    t['pick_share'] = round(pick_val / (roster_val + pick_val) * 100, 1) if roster_val else 0
    ages = [page(p) for p in o.current_roster if page(p)]
    vals = [(pval(p), page(p)) for p in o.current_roster if page(p) and pval(p)]
    t['core_age'] = round(sum(v * a for v, a in vals) / sum(v for v, _ in vals), 1) if vals else None
    return t


def labels(o, t):
    out = []
    if t['trades_per_season'] >= 8:
        out.append('hyperactive trader')
    elif t['trades_per_season'] <= 2:
        out.append('reluctant trader — needs a strong opening offer')
    if t['net_picks_traded'] >= 4:
        out.append('pick hoarder — pitch picks-for-players')
    elif t['net_picks_traded'] <= -4:
        out.append('pick spender — will pay picks for win-now help')
    if t['avg_age_acquired'] and t['avg_age_shipped']:
        if t['avg_age_acquired'] - t['avg_age_shipped'] <= -1.0:
            out.append('youth-seeker — ages down in trades')
        elif t['avg_age_acquired'] - t['avg_age_shipped'] >= 1.0:
            out.append('win-now buyer — ages up in trades')
    if t['faab_per_season'] >= 60:
        out.append('aggressive FAAB spender')
    if t['pick_share'] >= 18:
        out.append('window: accumulating (rebuild/2-year build)')
    elif t['pick_share'] <= 7:
        out.append('window: all-in (little future capital)')
    else:
        out.append('window: balanced')
    return out


def fmt_trade(x):
    got = [pname(p) for p in x['got_players']] + x['got_picks'] + (
        [f"${x['got_faab']} FAAB"] if x['got_faab'] else [])
    gave = [pname(p) for p in x['gave_players']] + x['gave_picks']
    return f"- **{x['date']}** with {x['partner']}: got {', '.join(got) or '—'} · gave {', '.join(gave) or '—'}"


os.makedirs(PROF, exist_ok=True)
machine = {}
for uid, o in owners.items():
    if not o.results:
        continue
    latest_name = o.names.get(latest) or list(o.names.values())[-1]
    username = latest_name.split('(')[-1].rstrip(')')
    t = tendencies(o)
    labs = labels(o, t)
    titles = [s for s, c in champions.items() if c == uid]

    lines = [f"# {latest_name}", '']
    lines.append(f"user_id `{uid}` · profile regenerated {datetime.now().strftime('%Y-%m-%d')}"
                 + (f" · 🏆 champion: {', '.join(titles)}" if titles else ''))
    lines += ['', '## Franchise history', '', '| Season | Team | Record | Points | Finish |', '|---|---|---|---|---|']
    for s in seasons:
        r = o.results.get(s)
        if r:
            fin = ('🏆 CHAMPION' if r['champion'] else
                   f"#{r['place']}" if r['place'] else r.get('note', '—'))
            lines.append(f"| {s} | {o.names.get(s,'?')} | {r['record']} | {r['fpts']} | {fin} |")
    lines += ['', '## Read on this owner', '']
    for l in labs:
        lines.append(f'- {l}')
    lines += ['', '## Tendencies (computed)', '',
              f"- Trades/season: **{t['trades_per_season']}** · net picks traded: **{t['net_picks_traded']:+d}**",
              f"- Avg age acquired **{t['avg_age_acquired']}** vs shipped **{t['avg_age_shipped']}**",
              f"- Positions bought: {t['positions_bought'] or '—'}",
              f"- Waivers: {t['adds_per_season']} adds/season, ~${t['faab_per_season']} FAAB/season",
              f"- Current: roster value **{t['roster_value']:,}** · pick value **{t['pick_value']:,}**"
              f" ({t['pick_share']}% of assets in picks) · value-weighted core age **{t['core_age']}**"]
    lines += ['', f'## Current picks ({future[0]}–{future[1]})', '',
              ', '.join(o.current_picks) or 'none']
    top = sorted(o.current_roster, key=lambda p: -pval(p))[:8]
    lines += ['', '## Core roster (by consensus value)', '']
    for p in top:
        lines.append(f"- {ppos(p)} {pname(p)} ({page(p)}) — {pval(p):,.0f}")
    lines += ['', '## Trade ledger', '']
    for s in seasons:
        st = [x for x in o.trades if x['season'] == s]
        if st:
            lines.append(f'### {s} ({len(st)} trades)')
            lines += [fmt_trade(x) for x in st] + ['']
    if not o.trades:
        lines.append('_No trades on record._')
    dr_lines = []
    for s in seasons:
        pks = o.drafts.get(s, [])
        if pks:
            mix = Counter(ppos(p['player']) for p in pks)
            dr_lines.append(f"- {s} ({pks[0]['type']}): {len(pks)} picks — "
                            + ', '.join(f'{k}×{v}' for k, v in mix.most_common()))
    if dr_lines:
        lines += ['', '## Draft behavior', ''] + dr_lines

    # preserve manual notes
    path = os.path.join(PROF, f'{username}.md')
    manual = ''
    if os.path.exists(path):
        old = open(path).read()
        if NOTES_MARK in old:
            manual = old.split(NOTES_MARK, 1)[1]
    # Normalize the blank lines AROUND the notes, never the notes themselves.
    # `manual` is the whole tail after the marker, so it arrives with the
    # marker's own trailing newline attached; re-joining added another one every
    # run and the protected section grew by ~4 blank lines a week (one profile
    # had reached 110 by 2026-09-10). Strip only newlines at the two ends.
    manual = manual.strip('\n')
    lines += ['', '---', NOTES_MARK, '',
              manual or '_(your scouting notes here — this section is never overwritten)_']
    open(path, 'w').write('\n'.join(lines) + '\n')
    machine[username] = {'uid': uid, 'names': o.names, 'results': o.results,
                         'tendencies': t, 'labels': labs, 'titles': titles,
                         'picks': o.current_picks,
                         'trades': o.trades}
    print(f'  profiles/{username}.md  ({len(o.trades)} trades, {len(o.results)} seasons)')

json.dump(machine, open(os.path.join(PROF, 'profiles.json'), 'w'), indent=1)
print(f'done: {len(machine)} owner profiles -> profiles/')
