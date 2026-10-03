#!/usr/bin/env python3
"""Yahoo league -> the Sleeper-shaped files every analysis reads (data/<season>/...).

Translation, not a second pipeline. Players are matched to the Sleeper player database via
its yahoo_id field. Built 2026-10-02 from the Yahoo Fantasy Sports API v2 JSON layout as
parsed by the open-source yahoo_fantasy_api project (league/{key}/teams, team/{key}/roster,
league/{key}/standings, league/{key}/scoreboard;week=N, league/{key}/transactions;types=trade).
NOT yet run against a live Yahoo league: the first real league is the test.

Yahoo JSON is lists of one-key objects; yflat() merges them so fields read by name.
Needs the owner's Yahoo developer app + consent (set_platform_login.py yahoo). Known limits:
no taxi squad, no Max PF field (points scored stands in), history = current season only.
"""
import json, os, subprocess

API = 'https://fantasysports.yahooapis.com/fantasy/v2'


def yflat(x):
    """Merge Yahoo's [{'a': 1}, {'b': 2}, [...]] lists into one dict (recursively for lists)."""
    if isinstance(x, list):
        out = {}
        for e in x:
            f = yflat(e)
            if isinstance(f, dict):
                out.update(f)
        return out
    return x


def items(container, key):
    """Yahoo collections look like {'0': {key: ...}, '1': {...}, 'count': n} -> list of the values."""
    if not isinstance(container, dict):
        return []
    return [v[key] for k, v in sorted(((k, v) for k, v in container.items() if k.isdigit()), key=lambda kv: int(kv[0]))
            if isinstance(v, dict) and key in v]


def _get(path, token):
    r = subprocess.run(['curl', '-s', '-m', '60', '-w', '\n%{http_code}', '-H', '@-', f'{API}/{path}?format=json'],
                       input=f'Authorization: Bearer {token}\n', capture_output=True, text=True)
    body, _, code = r.stdout.rpartition('\n')
    if code == '401':
        raise SystemExit('Yahoo: login expired or not set — run "python set_platform_login.py yahoo", then update again.')
    if code != '200':
        raise SystemExit(f'Yahoo: HTTP {code} for {path}')
    return json.loads(body)['fantasy_content']


def team_id(key):
    return int(str(key).rsplit('.t.', 1)[-1])


def fetch(data_dir, cfg, profile, save, players, token):
    lkey = f"nfl.l.{cfg['league_id']}"
    season = str(profile.get('season'))
    sid_of = {str(p['yahoo_id']): sid for sid, p in players.items() if p.get('yahoo_id')}
    unmatched = []

    def sid(yid):
        s = sid_of.get(str(yid))
        if not s:
            unmatched.append(yid)
        return s

    # teams + standings
    st = _get(f'league/{lkey}/standings', token)['league']
    teams = items(yflat(st[1]['standings'])['teams'] if isinstance(st[1].get('standings'), list)
                  else st[1]['standings']['teams'], 'team')
    users, rosters, last_week = [], [], 0
    for t in teams:
        info = yflat(t[0])
        rest = yflat(t[1:])
        tid = team_id(info['team_key'])
        mgr = yflat((items(info.get('managers', {}), 'manager') or [{}])[0]) if isinstance(info.get('managers'), dict) \
            else yflat((info.get('managers') or [{}])[0].get('manager', {})) if info.get('managers') else {}
        uid = mgr.get('guid') or f'team{tid}'
        users.append({'user_id': uid, 'display_name': mgr.get('nickname') or info.get('name'),
                      'metadata': {'team_name': info.get('name')}})
        ts = rest.get('team_standings', {})
        ot = ts.get('outcome_totals', {})
        pf = float(ts.get('points_for') or (rest.get('team_points') or {}).get('total') or 0)
        rosters.append({'roster_id': tid, 'owner_id': uid, 'co_owners': [], 'players': [], 'starters': [],
                        'reserve': [], 'taxi': [], '_key': info['team_key'],
                        'settings': {'wins': int(ot.get('wins') or 0), 'losses': int(ot.get('losses') or 0),
                                     'ties': int(ot.get('ties') or 0), 'fpts': int(pf), 'fpts_decimal': round(pf % 1 * 100),
                                     'ppts': int(pf), 'ppts_decimal': round(pf % 1 * 100)}})

    # rosters (current week)
    for r in rosters:
        tm = _get(f"team/{r['_key']}/roster", token)['team']
        roster = yflat(tm[1])['roster'] if isinstance(tm[1], dict) else yflat(tm[1:])['roster']
        plist = items(roster.get('0', roster).get('players', {}) if isinstance(roster, dict) else {}, 'player')
        for pl in plist:
            info = yflat(pl[0]); sel = yflat(yflat(pl[1:]).get('selected_position', []))
            s = sid(info.get('player_id'))
            if not s:
                continue
            r['players'].append(s)
            pos = sel.get('position')
            if pos == 'IR':
                r['reserve'].append(s)
            elif pos != 'BN':
                r['starters'].append(s)

    # weekly scores
    matchups = {}
    start = int((profile.get('playoff') or {}).get('start_week') or 15)
    for wk in range(1, start):
        try:
            sb = _get(f'league/{lkey}/scoreboard;week={wk}', token)['league']
        except SystemExit:
            break
        board = yflat(sb[1:]).get('scoreboard', {})
        ms = items(yflat(board.get('0', board)).get('matchups', {}) if isinstance(board, dict) else {}, 'matchup')
        for mi, m in enumerate(ms):
            for t in items(m.get('0', {}).get('teams', {}), 'team'):
                info, rest = yflat(t[0]), yflat(t[1:])
                pts = float((rest.get('team_points') or {}).get('total') or 0)
                matchups.setdefault(str(wk), []).append({'roster_id': team_id(info['team_key']),
                                                         'matchup_id': mi + 1, 'points': pts})
                if pts:
                    last_week = max(last_week, wk)

    # trades (players and picks)
    txns = []
    try:
        tr = _get(f'league/{lkey}/transactions;types=trade', token)['league']
        for tx in items(yflat(tr[1:]).get('transactions', {}), 'transaction'):
            meta = yflat(tx[0]) if isinstance(tx, list) else yflat(tx)
            body = yflat(tx[1:]) if isinstance(tx, list) else {}
            if meta.get('status') not in ('successful', None):
                continue
            adds, drops, rids, picks = {}, {}, set(), []
            for pl in items(body.get('players', {}), 'player'):
                info, td = yflat(pl[0]), yflat(yflat(pl[1:]).get('transaction_data', []))
                s = sid(info.get('player_id'))
                if s and td.get('destination_team_key'):
                    a, b = team_id(td['destination_team_key']), team_id(td['source_team_key'])
                    adds[s], drops[s] = a, b; rids |= {a, b}
            for pk in (meta.get('picks') or body.get('picks') or []):
                p = pk.get('pick', pk)
                if p.get('destination_team_key'):
                    a, b = team_id(p['destination_team_key']), team_id(p['source_team_key'])
                    picks.append({'season': str(int(season) + 1), 'round': int(p.get('round') or 0),
                                  'roster_id': team_id(p.get('original_team_key') or p['source_team_key']),
                                  'owner_id': a, 'previous_owner_id': b})
                    rids |= {a, b}
            if adds or picks:
                txns.append({'transaction_id': meta.get('transaction_key'), 'type': 'trade', 'status': 'complete',
                             'created': int(meta.get('timestamp') or 0) * 1000, 'roster_ids': sorted(rids),
                             'adds': adds, 'drops': drops, 'draft_picks': picks})
    except SystemExit as e:
        print(f'  Yahoo: trade history unavailable ({e}) — trade grades will be empty')

    for r in rosters:
        r.pop('_key', None)
    slots = []
    for k, n in profile.get('slots', {}).items():
        slots += [k] * int(n or 0)
    names = {('RB', 'TE', 'WR'): 'FLEX', ('RB', 'WR'): 'WRRB_FLEX', ('TE', 'WR'): 'REC_FLEX', ('QB', 'RB', 'TE', 'WR'): 'SUPER_FLEX'}
    slots += [names.get(tuple(sorted(f)), 'FLEX') for f in profile.get('flex', [])] + ['BN'] * int(profile.get('bench') or 0)
    league = {'league_id': cfg['league_id'], 'name': profile.get('name'), 'season': season, 'sport': 'nfl',
              'status': 'in_season', 'total_rosters': len(rosters), 'roster_positions': slots, 'previous_league_id': None,
              'settings': {'num_teams': len(rosters), 'playoff_teams': (profile.get('playoff') or {}).get('teams'),
                           'playoff_week_start': start, 'last_scored_leg': last_week,
                           'type': 1 if profile.get('league_type') == 'keeper' else 0},
              'scoring_settings': {'rec': (profile.get('scoring') or {}).get('rec', 0), 'bonus_rec_te': 0}}
    traded = [p for t in txns for p in t['draft_picks']]
    d = os.path.join(data_dir, season)
    for name, obj in (('league', league), ('users', users), ('rosters', rosters), ('matchups', matchups),
                      ('transactions', txns), ('traded_picks', traded), ('drafts', []), ('winners_bracket', [])):
        save(f'{d}/{name}.json', obj)
    save(os.path.join(data_dir, 'seasons.json'), [season])
    um = sorted(set(map(str, unmatched)))
    print(f'  Yahoo {season}: {len(rosters)} teams, {sum(len(r["players"]) for r in rosters)} rostered players, '
          f'{len(matchups)} weeks, {len(txns)} trades'
          + (f' — {len(um)} Yahoo player ids had no Sleeper match (dropped): {um[:15]}' if um else ''))
    return season
