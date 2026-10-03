#!/usr/bin/env python3
"""Measure what game conditions do to a player's weekly fantasy score -> data/weekly_effects.json

Owner's choice (2026-10-02): weekly start/sit should weigh weather, Vegas lines, matchup,
rest, travel and backup-QB starts by MEASURED effect, not folklore. One-off, like
ops/contract_study.py: skips when the file exists unless --force.

Data (all free):
  nflverse stats_player_week_<y>.csv   PPR points per player-game, team, opponent, game_id
  nfldata games.csv                    kickoff, roof, rest days, closing spread/total, starting QBs
  Open-Meteo archive                   temp / wind / rain / snow at the stadium, kickoff to +3h
                                       (same source the live forecast in ops/weekly.py uses)
Window: 2015-2025 regular seasons.

Method: each player-game is scored as a RATIO to that player's own season average with
the game itself left out (needs 6+ other games and a 6+ PPR average). That removes "good
players score more" and leaves what the conditions did. For each factor bucket:
effect = mean ratio in the bucket / mean ratio for that position overall. Weekly scores
are noisy, so ops/weekly.py shrinks each effect toward 1.0 by n / (n + 300).

Factors (position x bucket):
  implied   team's implied points (Vegas total/2 +- spread/2) minus that team's season-average
            implied points: how much better/worse than usual the market expects this offense to do
  matchup   opponent's prior-weeks average ratio allowed to the position (needs 3+ prior weeks)
  wind / temp / precip   outdoor games only; 'indoor' bucket for domes and closed roofs
  rest      days since the team's last game
  travel    away games by time zones crossed; west-coast teams in 1 PM Eastern games; international
  backup_qb the team started someone other than its most-used QB that season (non-QBs only)
"""
import csv, json, os, statistics, subprocess, sys, time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import nfl_sites as NS  # noqa: E402

CACHE = os.path.join(ROOT, 'data', 'cache', 'weekly_hist')
OUT = os.path.join(ROOT, 'data', 'weekly_effects.json')
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
GAMES_URL = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
SEASONS = range(2015, 2026)
POS = ('QB', 'RB', 'WR', 'TE')
WEST = ('America/Los_Angeles',)


def grab(url, path, min_size=10000):
    if not os.path.exists(path) or os.path.getsize(path) < min_size:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(['curl', '-sL', '-m', '300', '-o', path, url], check=True)
    return path


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---- bucket functions (shared with ops/weekly.py) ----
def b_implied(delta):
    return None if delta is None else ('much lower' if delta <= -4 else 'lower' if delta <= -1.5 else
                                       'usual' if delta < 1.5 else 'higher' if delta < 4 else 'much higher')


def b_matchup(idx):
    return None if idx is None else ('tough' if idx < 0.88 else 'below avg' if idx < 0.96 else
                                     'average' if idx <= 1.04 else 'soft' if idx <= 1.12 else 'very soft')


def b_wind(w):
    return None if w is None else ('calm <10' if w < 10 else '10-15 mph' if w < 15 else '15-20 mph' if w < 20 else '20+ mph')


def b_temp(t):
    return None if t is None else ('<25F' if t < 25 else '25-40F' if t < 40 else '40-80F' if t <= 80 else '80F+')


def b_precip(rain, snow):
    if rain is None:
        return None
    return 'snow' if (snow or 0) >= 0.5 else 'heavy rain' if rain >= 5 else 'rain' if rain >= 0.8 else 'dry'


def b_rest(days):
    return None if days is None else ('short (<=5)' if days <= 5 else 'normal' if days <= 8 else
                                      'extra (9-12)' if days <= 12 else 'off bye (13+)')


def indoor(roof):
    return roof in ('dome', 'closed', '')


def main():
    if os.path.exists(OUT) and '--force' not in sys.argv:
        print('weekly study: data/weekly_effects.json already built (historical, fixed) — skip; --force to redo')
        return
    lock = os.path.join(CACHE, '.lock')
    if os.path.exists(lock):
        try:
            os.kill(int(open(lock).read()), 0)
            print('weekly study: another run is still pulling weather — skip')
            return
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    os.makedirs(CACHE, exist_ok=True)
    open(lock, 'w').write(str(os.getpid()))
    games = list(csv.DictReader(open(grab(GAMES_URL, os.path.join(CACHE, 'games.csv')), encoding='utf-8')))
    G = {g['game_id']: g for g in games if g['season'].isdigit() and int(g['season']) in SEASONS
         and g['game_type'] == 'REG'}
    site_map, owners = NS.sites(), NS.stadium_owners(games)

    # weather per outdoor game, from one archive pull per site
    wx_path = os.path.join(CACHE, 'game_weather.json')
    wx = json.load(open(wx_path)) if os.path.exists(wx_path) else {}
    # one single-day request per outdoor game (a multi-year range counts as hundreds of calls
    # against the free tier's limits); progress is saved every 50 games so a rerun resumes
    todo = [gid for gid, g in G.items() if gid not in wx and not indoor(g['roof'])]
    for i, gid in enumerate(todo, 1):
        g = G[gid]
        s = NS.game_site(g, site_map, owners)
        if s:
            try:
                wx[gid] = NS.game_weather(NS.history(s, g['gameday'], g['gameday']), g['gameday'], g['gametime'])
            except RuntimeError as e:
                json.dump(wx, open(wx_path, 'w'))
                sys.exit(f'weekly study: stopped at {len(wx)} games ({e}); rerun later to resume')
            time.sleep(0.12)
        if i % 50 == 0:
            json.dump(wx, open(wx_path, 'w'))
    json.dump(wx, open(wx_path, 'w'))
    print(f'weekly study: weather for {sum(1 for v in wx.values() if v)} outdoor games')

    # team-game context
    implied, starters = {}, defaultdict(Counter)
    for gid, g in G.items():
        sp, tot = num(g['spread_line']), num(g['total_line'])
        if sp is not None and tot is not None:
            implied[(gid, g['home_team'])] = tot / 2 + sp / 2
            implied[(gid, g['away_team'])] = tot / 2 - sp / 2
        for side in ('home', 'away'):
            if g[f'{side}_qb_id']:
                starters[(g['season'], g[f'{side}_team'])][g[f'{side}_qb_id']] += 1
    team_mean = defaultdict(list)
    for (gid, t), v in implied.items():
        team_mean[(G[gid]['season'], t)].append(v)
    team_mean = {k: statistics.mean(v) for k, v in team_mean.items()}
    main_qb = {k: c.most_common(1)[0][0] for k, c in starters.items()}

    def tctx(gid, team):
        g = G[gid]
        home = g['home_team'] == team
        side = 'home' if home else 'away'
        imp = implied.get((gid, team))
        delta = None if imp is None else imp - team_mean[(g['season'], team)]
        days = num(g[f'{side}_rest'])
        s = NS.game_site(g, site_map, owners)
        if g['location'] == 'Neutral' and s and not s['tz'].startswith('America/'):
            travel = 'international'
        elif home:
            travel = 'home'
        else:
            mine, there = site_map.get(team), s
            if not (mine and there):
                travel = None
            else:
                dz = abs(NS.tz_offset(there['tz'], g['gameday']) - NS.tz_offset(mine['tz'], g['gameday']))
                early = (g['gametime'] or '13:00') <= '13:05'
                travel = ('west team, 1 PM ET' if mine['tz'] in WEST and early and dz >= 3 else
                          'same zone' if dz < 1 else '1 zone' if dz < 2 else '2-3 zones')
        w = wx.get(gid)
        if indoor(g['roof']):
            wind = temp = precip = 'indoor'
        elif w:
            wind, temp, precip = b_wind(w['wind']), b_temp(w['temp']), b_precip(w['rain'], w['snow'])
        else:
            wind = temp = precip = None
        qb = g[f'{side}_qb_id']
        backup = None if not qb else ('backup' if qb != main_qb.get((g['season'], team)) else 'starter')
        return {'implied': b_implied(delta), 'wind': wind, 'temp': temp, 'precip': precip,
                'rest': b_rest(days), 'travel': travel, 'backup_qb': backup}

    # player-games
    rows = []
    for y in SEASONS:
        p = grab(f'{REL}/stats_player/stats_player_week_{y}.csv', os.path.join(CACHE, f'week_{y}.csv'))
        for r in csv.DictReader(open(p, encoding='utf-8')):
            if r['position'] in POS and r['season_type'] == 'REG' and r['game_id'] in G:
                rows.append({'pid': r['player_id'], 'pos': r['position'], 'season': y, 'week': int(r['week']),
                             'gid': r['game_id'], 'team': r['team'], 'opp': r['opponent_team'],
                             'pts': num(r['fantasy_points_ppr']) or 0.0})
    tot = defaultdict(lambda: [0.0, 0])
    for r in rows:
        t = tot[(r['pid'], r['season'])]
        t[0] += r['pts']
        t[1] += 1
    scored = []
    for r in rows:
        s, n = tot[(r['pid'], r['season'])]
        if n - 1 < 6:
            continue
        base = (s - r['pts']) / (n - 1)
        if base < 6:
            continue
        r['ratio'] = min(4.0, r['pts'] / base)
        scored.append(r)

    # matchup index: opponent's prior-weeks mean ratio allowed at the position
    allowed = defaultdict(list)          # (season, def_team, pos) -> [(week, ratio)]
    for r in scored:
        allowed[(r['season'], r['opp'], r['pos'])].append((r['week'], r['ratio']))
    for r in scored:
        prior = [x for w, x in allowed[(r['season'], r['opp'], r['pos'])] if w < r['week']]
        weeks = {w for w, _ in allowed[(r['season'], r['opp'], r['pos'])] if w < r['week']}
        r['matchup'] = b_matchup(statistics.mean(prior)) if len(weeks) >= 3 else None
        r.update(tctx(r['gid'], r['team']))

    factors = ('implied', 'matchup', 'wind', 'temp', 'precip', 'rest', 'travel', 'backup_qb')
    out = {'window': f'{min(SEASONS)}-{max(SEASONS)} regular seasons', 'player_games': len(scored),
           'shrink_k': 300, 'effects': {}}
    for pos in POS:
        sel = [r for r in scored if r['pos'] == pos]
        avg = statistics.mean(r['ratio'] for r in sel)
        out['effects'][pos] = {'n': len(sel)}
        for f in factors:
            cells = defaultdict(list)
            for r in sel:
                if r.get(f) is not None and not (f == 'backup_qb' and pos == 'QB'):
                    cells[r[f]].append(r['ratio'])
            out['effects'][pos][f] = {k: {'n': len(v), 'effect': round(statistics.mean(v) / avg, 3)}
                                      for k, v in sorted(cells.items()) if len(v) >= 30}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'weekly study -> data/weekly_effects.json ({len(scored):,} player-games)')
    for pos in POS:
        e = out['effects'][pos]
        print(f'  {pos}: ' + ' | '.join(f"{f}: " + ', '.join(f"{k} {v['effect']:.2f}" for k, v in e[f].items())
                                        for f in ('implied', 'matchup', 'wind', 'precip')))


if __name__ == '__main__':
    main()
