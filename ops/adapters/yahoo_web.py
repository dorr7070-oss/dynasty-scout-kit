#!/usr/bin/env python3
"""Yahoo league read from its WEB PAGES -> the same Sleeper-shaped files the API adapter writes.

Why: since mid-2026 Yahoo answers every Fantasy API call from a new developer app with HTTP 403
"This application is not authorized" until Yahoo approves the app by hand (reported 2-4 weeks).
The league's own pages still show everything, so Claude reads them in the owner's logged-in
browser and saves data/yahoo_web/snapshot.json (+ settings.json). This file translates that
snapshot. Built 2026-10-11 on a live 12-team Yahoo league.

snapshot.json shape (written by the browser capture in docs/YAHOO_WEB.md):
  teams:     [{tid, name, manager, players: [[slot, yahoo_id, name, nfl_team, pos, status], ...]}]
  standings: [[tid, "rank name W-L-T PF PA streak $FAAB waiver moves"], ...]
  weeks:     {"1": [[[tid_a, tid_b], [pts_a, proj_a, pts_b, proj_b]], ...], ...}
  trades:    [{txt, ids, teams}]   (one row per receiving side)
"""
import json, os, re

DIR = 'yahoo_web'


def load(data_dir, name):
    p = os.path.join(data_dir, DIR, name)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None


def available(data_dir):
    return load(data_dir, 'snapshot.json') is not None


def fetch(data_dir, cfg, profile, save, players):
    snap = load(data_dir, 'snapshot.json')
    season = str(profile.get('season'))
    sid_of = {str(p['yahoo_id']): sid for sid, p in players.items() if p.get('yahoo_id')}
    name_of = {}
    for sid, p in players.items():
        if p.get('full_name') and p.get('position') in ('QB', 'RB', 'WR', 'TE', 'K'):
            name_of.setdefault(re.sub(r'[^a-z]', '', p['full_name'].lower()), sid)
    unmatched = []
    names_by_yid = {str(pl[1]): pl[2] for t in snap['teams'] for pl in t['players']}

    def sid(yid, name=''):
        name = name or names_by_yid.get(str(yid), '')
        s = sid_of.get(str(yid))
        if not s and name:   # fallback: exact name match (suffixes stripped)
            key = re.sub(r'[^a-z]', '', re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', name.lower()))
            s = name_of.get(key) or name_of.get(re.sub(r'[^a-z]', '', name.lower()))
        if not s:
            unmatched.append(f'{name or yid}')
        return s

    stand = {}
    for tid, row in snap.get('standings', []):
        m = re.search(r'(\d+)-(\d+)-(\d+) (-?[\d.]+) (-?[\d.]+) \S+ \$(\d+)', row)
        if m:
            stand[str(tid)] = {'w': int(m[1]), 'l': int(m[2]), 't': int(m[3]), 'pf': float(m[4]),
                               'pa': float(m[5]), 'faab': int(m[6])}

    users, rosters = [], []
    for t in snap['teams']:
        tid = int(t['tid'])
        uid = f"yahoo_t{tid}"
        users.append({'user_id': uid, 'display_name': t.get('manager') or t['name'],
                      'metadata': {'team_name': t['name']}})
        st = stand.get(str(tid), {})
        pf = st.get('pf', 0.0)
        r = {'roster_id': tid, 'owner_id': uid, 'co_owners': [], 'players': [], 'starters': [],
             'reserve': [], 'taxi': [],
             'settings': {'wins': st.get('w', 0), 'losses': st.get('l', 0), 'ties': st.get('t', 0),
                          'fpts': int(pf), 'fpts_decimal': round(pf % 1 * 100),
                          'fpts_against': int(st.get('pa', 0)), 'fpts_against_decimal': round(st.get('pa', 0) % 1 * 100),
                          'ppts': int(pf), 'ppts_decimal': round(pf % 1 * 100),
                          'waiver_budget_used': max(0, int((profile.get('waivers') or {}).get('budget') or 100) - st.get('faab', 0))}}
        for slot, yid, name, _team, _pos, status in t['players']:
            s = sid(yid, name)
            if not s:
                continue
            r['players'].append(s)
            if slot == 'IR':
                r['reserve'].append(s)
            elif slot != 'BN':
                r['starters'].append(s)
        rosters.append(r)

    matchups, last_week = {}, 0
    for wk, games in (snap.get('weeks') or {}).items():
        for mi, (tids, pts) in enumerate(games):
            if len(tids) != 2 or len(pts) != 4:
                continue
            for side, tid in enumerate(tids):
                p = float(pts[side * 2])
                matchups.setdefault(str(wk), []).append({'roster_id': int(tid), 'matchup_id': mi + 1, 'points': p,
                                                         'projected': float(pts[side * 2 + 1])})
            if any(float(pts[i]) for i in (0, 2)):
                last_week = max(last_week, int(wk))

    # trades: Yahoo lists one row per receiving team; rows with the same timestamp are one trade
    groups = {}
    for row in snap.get('trades', []):
        when = (re.search(r'\)\s*(\w{3} \d+, [\d:]+ [ap]m)', row['txt']) or [None, row['txt'][-20:]])[1]
        groups.setdefault(when, []).append(row)
    txns = []
    for when, rows in groups.items():
        adds, rids = {}, set()
        for row in rows:
            dest = int(row['teams'][0]) if row.get('teams') else None
            ids = [i for i in row['ids'] if i.isdigit()]
            for yid in ids:
                s = sid(yid)
                if s and dest:
                    adds[s] = dest
                    rids.add(dest)
        # source team = the other receiver in the same trade (two-team trades)
        drops = {}
        for s, dest in adds.items():
            others = rids - {dest}
            if len(others) == 1:
                drops[s] = next(iter(others))
        if adds:
            txns.append({'transaction_id': f'yweb-{when}', 'type': 'trade', 'status': 'complete', 'created': 0,
                         'note': when, 'roster_ids': sorted(rids), 'adds': adds, 'drops': drops, 'draft_picks': []})

    slots = []
    for k, n in profile.get('slots', {}).items():
        slots += [k] * int(n or 0)
    names = {('RB', 'TE', 'WR'): 'FLEX', ('RB', 'WR'): 'WRRB_FLEX', ('TE', 'WR'): 'REC_FLEX', ('QB', 'RB', 'TE', 'WR'): 'SUPER_FLEX'}
    slots += [names.get(tuple(sorted(f)), 'FLEX') for f in profile.get('flex', [])] + ['BN'] * int(profile.get('bench') or 0)
    start = int((profile.get('playoff') or {}).get('start_week') or 15)
    league = {'league_id': cfg['league_id'], 'name': profile.get('name'), 'season': season, 'sport': 'nfl',
              'status': 'in_season', 'total_rosters': len(rosters), 'roster_positions': slots, 'previous_league_id': None,
              'settings': {'num_teams': len(rosters), 'playoff_teams': (profile.get('playoff') or {}).get('teams'),
                           'playoff_week_start': start, 'last_scored_leg': last_week, 'leg': last_week,
                           'type': 1 if profile.get('league_type') == 'keeper' else 0,
                           'waiver_budget': (profile.get('waivers') or {}).get('budget') or 100},
              'scoring_settings': {'rec': (profile.get('scoring') or {}).get('rec', 0), 'bonus_rec_te': 0}}
    d = os.path.join(data_dir, season)
    for name, obj in (('league', league), ('users', users), ('rosters', rosters), ('matchups', matchups),
                      ('transactions', txns), ('traded_picks', []), ('drafts', []), ('winners_bracket', [])):
        save(f'{d}/{name}.json', obj)
    save(os.path.join(data_dir, 'seasons.json'), [season])
    um = sorted(set(unmatched))
    print(f"  Yahoo (web pages, captured {snap.get('captured', '?')[:16]}) {season}: {len(rosters)} teams, "
          f"{sum(len(r['players']) for r in rosters)} rostered players, {len(matchups)} weeks, {len(txns)} trades"
          + (f' — {len(um)} players had no Sleeper match (dropped): {um[:15]}' if um else ''))
    return season
