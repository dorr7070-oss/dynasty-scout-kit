#!/usr/bin/env python3
"""ESPN league -> the Sleeper-shaped files every analysis reads (data/<season>/...).

Translation, not a second pipeline: once these files exist, values, rankings, trade
grades, the season sim and dashboards run unchanged. Players are matched to the Sleeper
player database through its espn_id field. Built 2026-10-02 from ESPN's v3 league API as
documented by the open-source espn-api project (views mTeam/mRoster/mMatchup/mSettings,
communication message type 244 = traded player). NOT yet run against a live ESPN league:
the first real league is the test, and every missing field is reported, never guessed.

Known limits (ESPN itself): no future draft-pick trading, no taxi squad, no Max PF field
(Max PF falls back to points scored), history = current season only.
Private leagues need the owner's espn_s2 + SWID cookies (set_platform_login.py espn).
"""
import json, os, subprocess, time

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/128'
BASE = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{lid}'
LOGIN = os.path.join(os.path.expanduser('~'), '.config', 'dynasty-scout', 'espn.json')
SLOT_NAME = {0: 'QB', 2: 'RB', 4: 'WR', 6: 'TE', 16: 'DEF', 17: 'K', 23: 'FLEX', 3: 'WRRB_FLEX',
             5: 'REC_FLEX', 7: 'SUPER_FLEX', 20: 'BN', 21: 'IR'}


def _get(url, params, cookies, fltr=None):
    q = '&'.join(f'{k}={v}' for k, vals in params.items() for v in (vals if isinstance(vals, list) else [vals]))
    hdr = ''
    if cookies:
        hdr += f"Cookie: espn_s2={cookies['espn_s2']}; SWID={cookies['swid']}\n"
    if fltr:
        hdr += f'x-fantasy-filter: {json.dumps(fltr)}\n'
    r = subprocess.run(['curl', '-s', '-m', '60', '-A', UA, '-w', '\n%{http_code}', '-H', '@-', f'{url}?{q}'],
                       input=hdr, capture_output=True, text=True)
    body, _, code = r.stdout.rpartition('\n')
    if code == '401':
        raise SystemExit('ESPN: this league is private — run "python set_platform_login.py espn" to save your '
                         'ESPN login cookies, then run the update again.')
    if code != '200':
        raise SystemExit(f'ESPN: HTTP {code} for {url}')
    return json.loads(body)


def fetch(data_dir, cfg, profile, save, players):
    lid, season = cfg['league_id'], str(profile.get('season') or cfg.get('season'))
    cookies = json.load(open(LOGIN, encoding='utf-8')) if os.path.exists(LOGIN) else None
    url = BASE.format(season=season, lid=lid)
    lg = _get(url, {'view': ['mTeam', 'mRoster', 'mMatchup', 'mSettings', 'mStandings']}, cookies)

    sid_of = {str(p['espn_id']): sid for sid, p in players.items() if p.get('espn_id')}
    unmatched = []

    def sid(espn_pid):
        s = sid_of.get(str(espn_pid))
        if not s and espn_pid and int(espn_pid) > 0:
            unmatched.append(espn_pid)
        return s

    members = {m['id']: m for m in lg.get('members', [])}
    users, rosters = [], []
    for t in lg.get('teams', []):
        owners = t.get('owners') or [f"team{t['id']}"]
        m = members.get(owners[0], {})
        name = t.get('name') or f"{t.get('location', '')} {t.get('nickname', '')}".strip()
        users.append({'user_id': owners[0], 'display_name': m.get('displayName') or name,
                      'metadata': {'team_name': name}})
        entries = (t.get('roster') or {}).get('entries', [])
        allp = [sid(e['playerId']) for e in entries]
        starters = [sid(e['playerId']) for e in entries if e.get('lineupSlotId') not in (20, 21)]
        reserve = [sid(e['playerId']) for e in entries if e.get('lineupSlotId') == 21]
        rec = (t.get('record') or {}).get('overall', {})
        pf = float(rec.get('pointsFor') or 0)
        rosters.append({'roster_id': t['id'], 'owner_id': owners[0], 'co_owners': owners[1:],
                        'players': [p for p in allp if p], 'starters': [p for p in starters if p],
                        'reserve': [p for p in reserve if p], 'taxi': [],
                        'settings': {'wins': rec.get('wins', 0), 'losses': rec.get('losses', 0),
                                     'ties': rec.get('ties', 0), 'fpts': int(pf), 'fpts_decimal': round(pf % 1 * 100),
                                     # ESPN has no Max PF; points scored stands in for it
                                     'ppts': int(pf), 'ppts_decimal': round(pf % 1 * 100)}})

    status = lg.get('status') or {}
    matchups = {}
    for g in lg.get('schedule', []):
        wk = str(g.get('matchupPeriodId'))
        for side in ('home', 'away'):
            s = g.get(side)
            if s:
                matchups.setdefault(wk, []).append({'roster_id': s['teamId'], 'matchup_id': g.get('id'),
                                                    'points': s.get('totalPoints', 0)})
    last_scored = max([int(w) for w, ms in matchups.items() if any(m['points'] for m in ms)] or [0])

    # trades: league activity feed, message type 244 = a player moving in a trade
    txns = []
    try:
        comm = _get(url + '/communication/', {'view': 'kona_league_communication'}, cookies, {
            'topics': {'filterType': {'value': ['ACTIVITY_TRANSACTIONS']}, 'limit': 500,
                       'limitPerMessageSet': {'value': 25}, 'offset': 0,
                       'sortMessageDate': {'sortPriority': 1, 'sortAsc': False},
                       'filterIncludeMessageTypeIds': {'value': [244]}}})
        for topic in comm.get('topics', []):
            adds, drops, rids = {}, {}, set()
            for msg in topic.get('messages', []):
                if msg.get('messageTypeId') != 244:
                    continue
                p = sid(msg.get('targetId'))
                if p:
                    adds[p], drops[p] = msg.get('to'), msg.get('from')
                    rids |= {msg.get('to'), msg.get('from')}
            if adds:
                txns.append({'transaction_id': str(topic.get('id')), 'type': 'trade', 'status': 'complete',
                             'created': topic.get('date', 0), 'roster_ids': sorted(r for r in rids if r is not None),
                             'adds': adds, 'drops': drops, 'draft_picks': []})
    except SystemExit as e:
        print(f'  ESPN: trade history unavailable ({e}) — trade grades will be empty')

    slots = []
    for k, n in profile.get('slots', {}).items():
        slots += [k] * int(n or 0)
    flexname = {tuple(sorted(v)): k for k, v in {'FLEX': ['RB', 'TE', 'WR'], 'WRRB_FLEX': ['RB', 'WR'],
                                                  'REC_FLEX': ['TE', 'WR'], 'SUPER_FLEX': ['QB', 'RB', 'TE', 'WR']}.items()}
    slots += [flexname.get(tuple(sorted(f)), 'FLEX') for f in profile.get('flex', [])] + ['BN'] * int(profile.get('bench') or 0)
    league = {'league_id': lid, 'name': profile.get('name'), 'season': season, 'sport': 'nfl',
              'status': 'in_season', 'total_rosters': len(rosters), 'roster_positions': slots,
              'previous_league_id': None,
              'settings': {'num_teams': len(rosters), 'playoff_teams': (profile.get('playoff') or {}).get('teams'),
                           'playoff_week_start': (profile.get('playoff') or {}).get('start_week'),
                           'last_scored_leg': last_scored, 'leg': status.get('currentMatchupPeriod'),
                           'type': 1 if profile.get('league_type') == 'keeper' else 0},
              'scoring_settings': {'rec': (profile.get('scoring') or {}).get('rec', 0),
                                   'bonus_rec_te': (profile.get('scoring') or {}).get('te_premium', 0)}}
    d = os.path.join(data_dir, season)
    save(f'{d}/league.json', league)
    save(f'{d}/users.json', users)
    save(f'{d}/rosters.json', rosters)
    save(f'{d}/matchups.json', matchups)
    save(f'{d}/transactions.json', txns)
    save(f'{d}/traded_picks.json', [])
    save(f'{d}/drafts.json', [])
    save(f'{d}/winners_bracket.json', [])
    save(os.path.join(data_dir, 'seasons.json'), [season])
    um = sorted(set(unmatched))
    print(f'  ESPN {season}: {len(rosters)} teams, {sum(len(r["players"]) for r in rosters)} rostered players, '
          f'{len(matchups)} weeks, {len(txns)} trades'
          + (f' — {len(um)} ESPN player ids had no Sleeper match (dropped): {um[:15]}' if um else ''))
    return season
