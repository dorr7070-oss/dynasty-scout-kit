#!/usr/bin/env python3
"""Deeper usage: red zone, goal line, routes, depth of target, role trend (after usage.py).

Snap and target share (usage.py) say who is on the field and who gets the ball. This adds
WHERE and HOW: who gets the scoring chances, how far downfield, how efficiently a receiver
earns yards per route, and whether the role is growing or shrinking. Merged into
data/usage.json under the same sleeper ids. Free nflverse data only:

  play_by_play_<season>.csv.gz   every play: yard line, passer/receiver/rusher, air yards, dropbacks
  snap_counts_<season>.csv       weekly offense snaps (for the role trend + route estimate)
  pbp_participation_<season>.csv who was on the field each play — the only free source of
                                 routes run. Published after the season, so for the CURRENT
                                 season routes are ESTIMATED (snap share x team dropbacks) and
                                 last season's true routes are kept alongside.

Fields added per player (season = the one usage.py chose):
  rz_tgt_share, rz_carry_share   share of team targets / carries inside the 20
  gl_carry_share                 share of team carries inside the 5
  adot                           average depth of target (air yards per target)
  route_pct_est, yprr_est        routes ~ snap% x team dropbacks; receiving yards per route
  routes_prev, yprr_prev         last season, true routes run (count) and yards per route, from participation
  snap_trend                     last-3-games snap share minus season snap share (+ = growing role)
  wk                             {week: {pts, snap, tgt, car}} for ops/weekly.py
"""
import csv, gzip, json, os, statistics, subprocess, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
BASE = 'https://github.com/nflverse/nflverse-data/releases/download'
POS = ('QB', 'RB', 'WR', 'TE')


def grab(url, path, max_age=86400):
    import time
    if os.path.exists(path) and os.path.getsize(path) > 1000 and time.time() - os.path.getmtime(path) < max_age:
        return path
    r = subprocess.run(['curl', '-sL', '-w', '%{http_code}', '--max-time', '300', '-o', path + '.tmp', url],
                       capture_output=True, text=True)
    if r.stdout.strip() != '200' or os.path.getsize(path + '.tmp') < 1000:
        os.path.exists(path + '.tmp') and os.remove(path + '.tmp')
        return path if os.path.exists(path) else None
    os.replace(path + '.tmp', path)
    return path


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def opener(path):
    return gzip.open(path, 'rt', encoding='utf-8', errors='replace') if path.endswith('.gz') else \
        open(path, encoding='utf-8', errors='replace')


def crosswalk(season):
    p = grab(f'{BASE}/rosters/roster_{season}.csv', f'{CACHE}/roster_{season}.csv', 7 * 86400)
    g, f = {}, {}
    for r in csv.DictReader(opener(p)) if p else []:
        if r.get('sleeper_id'):
            if r.get('gsis_id'):
                g[r['gsis_id']] = r['sleeper_id']
            if r.get('pfr_id'):
                f[r['pfr_id']] = r['sleeper_id']
    return g, f


def pbp_usage(season, gs):
    p = grab(f'{BASE}/pbp/play_by_play_{season}.csv.gz', f'{CACHE}/pbp_{season}.csv.gz')
    if not p:
        return {}, {}
    team = defaultdict(lambda: defaultdict(float))       # team -> counters
    dropbacks = defaultdict(float)                        # (team, week) -> dropbacks
    pl = defaultdict(lambda: defaultdict(float))         # sleeper -> counters
    for r in csv.DictReader(opener(p)):
        if r.get('season_type') != 'REG' or not r.get('posteam'):
            continue
        t, wk, yl = r['posteam'], r['week'], num(r.get('yardline_100'))
        if r.get('qb_dropback') == '1':
            dropbacks[(t, wk)] += 1
        rec, rus = gs.get(r.get('receiver_player_id')), gs.get(r.get('rusher_player_id'))
        if r.get('pass_attempt') == '1' and r.get('receiver_player_id'):
            team[t]['tgt'] += 1
            if yl is not None and yl <= 20:
                team[t]['rz_tgt'] += 1
            if rec:
                pl[rec]['tgt'] += 1
                pl[rec]['air'] += num(r.get('air_yards')) or 0
                pl[rec]['rec_yds'] += num(r.get('receiving_yards')) or 0
                if yl is not None and yl <= 20:
                    pl[rec]['rz_tgt'] += 1
                pl[rec]['team:' + t] = 1
        if r.get('rush_attempt') == '1' and r.get('rusher_player_id'):
            team[t]['car'] += 1
            if yl is not None and yl <= 20:
                team[t]['rz_car'] += 1
            if yl is not None and yl <= 5:
                team[t]['gl_car'] += 1
            if rus:
                if yl is not None and yl <= 20:
                    pl[rus]['rz_car'] += 1
                if yl is not None and yl <= 5:
                    pl[rus]['gl_car'] += 1
                pl[rus]['team:' + t] = 1
    out = {}
    for sid, c in pl.items():
        teams = [k[5:] for k in c if k.startswith('team:')]
        t = teams[-1] if teams else None
        T = team.get(t, {})
        out[sid] = {
            'rz_tgt_share': round(c['rz_tgt'] / T['rz_tgt'], 3) if T.get('rz_tgt') else None,
            'rz_carry_share': round(c['rz_car'] / T['rz_car'], 3) if T.get('rz_car') else None,
            'gl_carry_share': round(c['gl_car'] / T['gl_car'], 3) if T.get('gl_car') else None,
            'adot': round(c['air'] / c['tgt'], 1) if c['tgt'] else None,
            '_rec_yds': c['rec_yds'], '_team': t}
    return out, dropbacks


def true_routes(season, gs):
    """Routes from participation (after-season file). {sleeper: (route_pct, yprr)}."""
    p = grab(f'{BASE}/pbp_participation/pbp_participation_{season}.csv',
             f'{CACHE}/participation_{season}.csv', 30 * 86400)
    pb = grab(f'{BASE}/pbp/play_by_play_{season}.csv.gz', f'{CACHE}/pbp_{season}.csv.gz', 30 * 86400)
    if not (p and pb):
        return {}
    yards, drop = {}, {}
    for r in csv.DictReader(opener(pb)):
        if r.get('season_type') == 'REG' and r.get('qb_dropback') == '1':
            drop[(r['game_id'], r['play_id'])] = r['posteam']
        if r.get('season_type') == 'REG' and r.get('receiver_player_id') and r.get('complete_pass') == '1':
            yards[r['receiver_player_id']] = yards.get(r['receiver_player_id'], 0) + (num(r.get('receiving_yards')) or 0)
    # The participation file misses some plays (unevenly by team), so routes are taken as the
    # player's SHARE of the tracked dropbacks for his team, scaled to that team's full count.
    team_all = defaultdict(int)
    for t in drop.values():
        team_all[t] += 1
    routes, team_db, pteam = defaultdict(int), defaultdict(int), {}
    for r in csv.DictReader(opener(p)):
        k = (r.get('nflverse_game_id'), r.get('play_id'))
        if k not in drop or not r.get('offense_players'):
            continue
        t = drop[k]
        team_db[t] += 1
        for pid, pos in zip(r['offense_players'].split(';'), (r.get('offense_positions') or '').split(';')):
            if pos in ('WR', 'TE', 'RB'):
                routes[(pid, t)] += 1
    best = {}
    for (gid, t), n in routes.items():
        full = n / team_db[t] * team_all[t]
        if full > best.get(gid, (0,))[0]:
            best[gid] = (full, t)
    out = {}
    for gid, (full, t) in best.items():
        sid = gs.get(gid)
        if sid and full >= 50:
            out[sid] = (round(full), round(yards.get(gid, 0) / full, 2))
    return out


def main():
    upath = os.path.join(DATA, 'usage.json')
    usage = json.load(open(upath)) if os.path.exists(upath) else {}
    if not usage:
        print('usage_adv: no usage.json — skipped')
        return
    season = max(v['season'] for v in usage.values())
    gs, fs = crosswalk(season)
    adv, dropbacks = pbp_usage(season, gs)

    # weekly rows: points / targets / carries (stats file) + snap share (snap counts)
    wk = defaultdict(dict)
    sp = os.path.join(CACHE, f'stats_player_week_{season}.csv')
    for r in csv.DictReader(opener(sp)) if os.path.exists(sp) else []:
        sid = gs.get(r.get('player_id'))
        if sid and r.get('season_type') == 'REG' and r.get('position') in POS:
            wk[sid][r['week']] = {'pts': num(r.get('fantasy_points_ppr')) or 0.0, 'tgt': num(r.get('targets')) or 0,
                                  'car': num(r.get('carries')) or 0, 'team': r.get('team')}
    sc = os.path.join(CACHE, f'snap_counts_{season}.csv')
    for r in csv.DictReader(opener(sc)) if os.path.exists(sc) else []:
        sid = fs.get(r.get('pfr_player_id'))
        if sid and r.get('game_type', 'REG') == 'REG' and r['week'] in wk.get(sid, {}):
            wk[sid][r['week']]['snap'] = num(r.get('offense_pct'))

    prev = true_routes(season - 1, crosswalk(season - 1)[0])
    added = 0
    for sid, u in usage.items():
        a = adv.get(sid, {})
        for k in ('rz_tgt_share', 'rz_carry_share', 'gl_carry_share', 'adot'):
            u[k] = a.get(k)
        weeks = wk.get(sid, {})
        est_routes = sum((w.get('snap') or 0) * dropbacks.get((w['team'], k), 0) for k, w in weeks.items())
        team_db = sum(dropbacks.get((w['team'], k), 0) for k, w in weeks.items())
        u['route_pct_est'] = round(est_routes / team_db, 3) if team_db else None
        u['yprr_est'] = round(a['_rec_yds'] / est_routes, 2) if a.get('_rec_yds') and est_routes >= 40 else None
        pv = prev.get(sid)
        u['routes_prev'], u['yprr_prev'] = (pv if pv else (None, None))
        snaps = [(int(k), w['snap']) for k, w in weeks.items() if w.get('snap') is not None]
        snaps.sort()
        if len(snaps) >= 4:
            u['snap_trend'] = round(statistics.mean(s for _, s in snaps[-3:]) - statistics.mean(s for _, s in snaps), 3)
        else:
            u['snap_trend'] = None
        u['wk'] = {k: {kk: w.get(kk) for kk in ('pts', 'snap', 'tgt', 'car')} for k, w in weeks.items()}
        added += 1 if a else 0
    json.dump(usage, open(upath, 'w'))
    print(f'usage_adv: red zone / routes / trend added for {added} of {len(usage)} players '
          f'({season}; true routes from {season - 1} for {len(prev)})')


if __name__ == '__main__':
    main()
