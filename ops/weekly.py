#!/usr/bin/env python3
"""Weekly start/sit engine -> data/weekly.json (after usage_adv.py and project.py).

Owner's choice (2026-10-02): start/sit first, using every free signal — Vegas lines, matchup,
weather forecast, rest, travel, backup-QB starts, practice reports, injuries, recent form and
usage — each weighted by its MEASURED historical effect (ops/weekly_study.py ->
data/weekly_effects.json), and the model itself chosen by a BACKTEST, not by taste.

Per player for the coming week:
  sleeper   Sleeper's own weekly projection (league scoring, PPR)
  form      this season's points per game, shrunk toward the Sleeper number (k = 3 games)
  mults     one multiplier per condition = 1 + (measured effect - 1) x n / (n + 300)
  proj      the variant that won the backtest (data/weekly_model.json), then injury rules:
            Out / IR / suspended / bye -> 0; Doubtful -> x0.25; Questionable and DID NOT
            PRACTICE on the latest report -> x0.7 (flagged); Questionable otherwise -> flagged only
Then each team's best legal lineup by `proj`, compared with the lineup currently set in the
league, and swaps worth >= 2 points listed (smaller gaps are called coin flips).

  python3 ops/weekly.py              this week (the first week with unplayed games)
  python3 ops/weekly.py --backtest   score the model variants on last season -> data/weekly_model.json
"""
import csv, json, os, statistics, subprocess, sys, time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import nfl_sites as NS  # noqa: E402
import weekly_study as WS  # noqa: E402

BASE = 'https://github.com/nflverse/nflverse-data/releases/download'
GAMES_URL = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
SLEEPER = 'https://api.sleeper.com/projections/nfl'
K_SHRINK, K_FORM = 300, 3
# Sleeper team code -> nflverse code. Sleeper writes the Rams 'LAR', nflverse 'LA'; missing this
# zeroed every Rams player as 'bye' (caught 2026-10-02 in the kit test: Davante Adams 14.7 -> 0).
SLEEPER_TO_NV = {'LAR': 'LA'}
INJ = {}   # measured game-day odds by status|practice, loaded in live()
MARKET = ('implied', 'matchup')
CONDITIONS = ('wind', 'temp', 'precip', 'rest', 'travel', 'backup_qb')
# Extremes only: the backtest (2026-10-02) showed blanket multipliers HURT — Sleeper already prices
# Vegas lines and ordinary weather — while extreme weather and backup-QB starts are where it is
# wrong (2025: Sleeper over-projected QB/WR/TE in bad-weather games by 1.8 pts per player).
EXTREME = {'wind': ('15-20 mph', '20+ mph'), 'precip': ('rain', 'heavy rain', 'snow'), 'temp': ('<25F',),
           'backup_qb': ('backup',)}
VARIANTS = {'sleeper': ('sleeper', ()), 'form': ('form', ()),
            'sleeper+extremes': ('sleeper', tuple(EXTREME)), 'form+extremes': ('form', tuple(EXTREME)),
            'sleeper+conditions': ('sleeper', CONDITIONS), 'sleeper+all': ('sleeper', MARKET + CONDITIONS),
            'form+conditions': ('form', CONDITIONS), 'form+all': ('form', MARKET + CONDITIONS)}


def fetch(url, path, max_age):
    if os.path.exists(path) and os.path.getsize(path) > 1000 and time.time() - os.path.getmtime(path) < max_age:
        return path
    r = subprocess.run(['curl', '-sL', '-w', '%{http_code}', '--max-time', '180', '-A', 'Mozilla/5.0',
                        '-o', path + '.tmp', url], capture_output=True, text=True)
    if r.stdout.strip() == '200' and os.path.getsize(path + '.tmp') > 100:
        os.replace(path + '.tmp', path)
    elif os.path.exists(path + '.tmp'):
        os.remove(path + '.tmp')
    return path if os.path.exists(path) else None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def mult(effects, pos, factor, bucket):
    c = effects.get(pos, {}).get(factor, {}).get(bucket)
    if not c:
        return 1.0
    return 1 + (c['effect'] - 1) * c['n'] / (c['n'] + K_SHRINK)


def sleeper_week(season, week):
    path = os.path.join(CACHE, f'sleeper_proj_{season}_{week}.json')
    q = '&'.join(f'position[]={p}' for p in LF.POS)
    age = 6 * 3600 if season >= int(time.strftime('%Y')) else 365 * 86400
    fetch(f'{SLEEPER}/{season}/{week}?season_type=regular&{q}&order_by=ppr', path, age)
    out = {}
    for x in json.load(open(path)) if path and os.path.exists(path) else []:
        v = (x.get('stats') or {}).get('pts_ppr')
        if v is not None:
            out[x['player_id']] = v
    return out


class Season:
    """Everything known about one season's games, for live use or a backtest."""

    def __init__(self, season, live):
        self.season, self.live = season, live
        gp = fetch(GAMES_URL, os.path.join(CACHE, 'games.csv'), 6 * 3600)
        allg = list(csv.DictReader(open(gp, encoding='utf-8')))
        self.games = [g for g in allg if g['season'] == str(season) and g['game_type'] == 'REG']
        self.sites, self.owners = NS.sites(), NS.stadium_owners(allg)
        imp = defaultdict(list)
        self.implied = {}
        for g in self.games:
            sp, tot = num(g['spread_line']), num(g['total_line'])
            if sp is not None and tot is not None:
                self.implied[(g['game_id'], g['home_team'])] = tot / 2 + sp / 2
                self.implied[(g['game_id'], g['away_team'])] = tot / 2 - sp / 2
        for (gid, t), v in self.implied.items():
            imp[t].append(v)
        self.team_mean = {t: statistics.mean(v) for t, v in imp.items()}
        sp = fetch(f'{BASE}/stats_player/stats_player_week_{season}.csv',
                   os.path.join(CACHE, f'stats_player_week_{season}.csv'), 12 * 3600 if live else 365 * 86400)
        self.stats = [r for r in csv.DictReader(open(sp, encoding='utf-8'))
                      if r['season_type'] == 'REG' and r['position'] in LF.POS] if sp else []
        rp = fetch(f'{BASE}/rosters/roster_{season}.csv', os.path.join(CACHE, f'roster_{season}.csv'), 7 * 86400)
        self.gs = {r['gsis_id']: r['sleeper_id'] for r in csv.DictReader(open(rp, encoding='utf-8'))
                   if r.get('gsis_id') and r.get('sleeper_id')} if rp else {}
        starts = defaultdict(lambda: defaultdict(int))
        for g in self.games:
            for side in ('home', 'away'):
                if g[f'{side}_qb_id'] and g['home_score']:
                    starts[g[f'{side}_team']][g[f'{side}_qb_id']] += 1
        self.main_qb = {t: max(c, key=c.get) for t, c in starts.items()}
        self.wx_hist = {}
        hp = os.path.join(CACHE, 'weekly_hist', 'game_weather.json')
        if not live and os.path.exists(hp):
            self.wx_hist = json.load(open(hp))
        self._forecast = {}

    def week_games(self, week):
        return [g for g in self.games if int(g['week']) == week]

    def weather(self, g):
        if WS.indoor(g['roof']):
            return 'indoor'
        if not self.live:
            return self.wx_hist.get(g['game_id'])
        s = NS.game_site(g, self.sites, self.owners)
        if not s:
            return None
        k = (s['lat'], s['lon'])
        if k not in self._forecast:
            try:
                self._forecast[k] = NS.forecast(s)
            except RuntimeError:
                self._forecast[k] = {}
        return NS.game_weather(self._forecast[k], g['gameday'], g['gametime'])

    def matchup_index(self, week):
        """(def_team, pos) -> mean ratio allowed in weeks before `week` (3+ weeks needed)."""
        tot = defaultdict(lambda: [0.0, 0])
        for r in self.stats:
            if int(r['week']) < week:
                t = tot[r['player_id']]
                t[0] += num(r['fantasy_points_ppr']) or 0
                t[1] += 1
        allowed = defaultdict(list)
        for r in self.stats:
            w = int(r['week'])
            if w >= week:
                continue
            s, n = tot[r['player_id']]
            pts = num(r['fantasy_points_ppr']) or 0
            if n - 1 >= 2 and (s - pts) / (n - 1) >= 6:
                allowed[(r['opponent_team'], r['position'])].append((w, min(4.0, pts / ((s - pts) / (n - 1)))))
        return {k: statistics.mean(x for _, x in v) for k, v in allowed.items() if len({w for w, _ in v}) >= 3}

    def form(self, week):
        """sleeper_id -> (points, games) this season before `week`."""
        f = defaultdict(lambda: [0.0, 0])
        for r in self.stats:
            sid = self.gs.get(r['player_id'])
            if sid and int(r['week']) < week:
                f[sid][0] += num(r['fantasy_points_ppr']) or 0
                f[sid][1] += 1
        return f

    def team_context(self, g, team, out_qbs=()):
        home = g['home_team'] == team
        side = 'home' if home else 'away'
        imp = self.implied.get((g['game_id'], team))
        delta = None if imp is None or team not in self.team_mean else imp - self.team_mean[team]
        s = NS.game_site(g, self.sites, self.owners)
        if g['location'] == 'Neutral' and s and not s['tz'].startswith('America/'):
            travel = 'international'
        elif home:
            travel = 'home'
        else:
            mine = self.sites.get(team)
            if mine and s:
                dz = abs(NS.tz_offset(s['tz'], g['gameday']) - NS.tz_offset(mine['tz'], g['gameday']))
                early = (g['gametime'] or '13:00') <= '13:05'
                travel = ('west team, 1 PM ET' if mine['tz'] in WS.WEST and early and dz >= 3 else
                          'same zone' if dz < 1 else '1 zone' if dz < 2 else '2-3 zones')
            else:
                travel = None
        w = self.weather(g)
        if w == 'indoor':
            wind = temp = precip = 'indoor'
        elif w:
            wind, temp, precip = WS.b_wind(w['wind']), WS.b_temp(w['temp']), WS.b_precip(w['rain'], w['snow'])
        else:
            wind = temp = precip = None
        if self.live:
            backup = 'backup' if self.main_qb.get(team) in out_qbs else 'starter'
        else:
            qb = g[f'{side}_qb_id']
            backup = None if not qb else ('backup' if qb != self.main_qb.get(team) else 'starter')
        return {'implied': WS.b_implied(delta), 'implied_pts': None if imp is None else round(imp, 1),
                'wind': wind, 'temp': temp, 'precip': precip, 'weather': w,
                'rest': WS.b_rest(num(g[f'{side}_rest'])), 'travel': travel, 'backup_qb': backup,
                'opp': g['away_team'] if home else g['home_team'], 'kickoff': f"{g['weekday']} {g['gametime']} ET"}


def score(base, effects, pos, ctx, mi, factors, extremes_only=False):
    m, parts = 1.0, {}
    for f in factors:
        if extremes_only and ctx.get(f) not in EXTREME.get(f, ()):
            continue
        if f == 'matchup':
            idx = mi.get((ctx['opp'], pos))
            b = WS.b_matchup(idx)
        elif f == 'backup_qb' and pos == 'QB':
            continue
        else:
            b = ctx.get(f)
        x = mult(effects, pos, f, b) if b else 1.0
        if abs(x - 1) >= 0.005:
            parts[f] = (b, round(x, 3))
        m *= x
    return base * m, parts


def backtest():
    effects = json.load(open(os.path.join(DATA, 'weekly_effects.json')))['effects']
    season = max(int(d) for d in os.listdir(DATA) if d.isdigit()) - 1
    S = Season(season, live=False)
    if not S.wx_hist:
        sys.exit('backtest needs data/cache/weekly_hist/game_weather.json (run ops/weekly_study.py)')
    err = {v: [] for v in VARIANTS}
    P = json.load(open(os.path.join(DATA, 'players.json')))
    for week in range(4, 18):
        sl, fm, mi = sleeper_week(season, week), S.form(week), S.matchup_index(week)
        games = {}
        for g in S.week_games(week):
            games[g['home_team']] = g
            games[g['away_team']] = g
        for r in S.stats:
            if int(r['week']) != week:
                continue
            sid = S.gs.get(r['player_id'])
            if not sid or sid not in sl or sl[sid] < 5 or r['team'] not in games:
                continue
            pos, actual = r['position'], num(r['fantasy_points_ppr']) or 0
            ctx = S.team_context(games[r['team']], r['team'])
            pts, n = fm.get(sid, (0, 0))
            bases = {'sleeper': sl[sid], 'form': (pts + K_FORM * sl[sid]) / (n + K_FORM)}
            for v, (b, fac) in VARIANTS.items():
                p, _ = score(bases[b], effects, pos, ctx, mi, fac, v.endswith('+extremes'))
                err[v].append((p, actual, pos))
    res = {}
    for v, rows in err.items():
        mae = statistics.mean(abs(p - a) for p, a, _ in rows)
        res[v] = {'mae': round(mae, 3), 'n': len(rows),
                  'by_pos': {pos: round(statistics.mean(abs(p - a) for p, a, ps in rows if ps == pos), 3)
                             for pos in LF.POS}}
    best = min(res, key=lambda v: res[v]['mae'])
    out = {'season': season, 'weeks': '4-17', 'variants': res, 'chosen': best,
           'note': 'mean absolute error in PPR points per player-week; players Sleeper projected 5+ who played'}
    json.dump(out, open(os.path.join(DATA, 'weekly_model.json'), 'w'), indent=1)
    print(f'weekly backtest {season} wk4-17 ({res[best]["n"]:,} player-weeks) — lower is better:')
    for v in sorted(res, key=lambda v: res[v]['mae']):
        print(f"  {v:20} MAE {res[v]['mae']:.3f}   " + ' '.join(f"{p} {x:.2f}" for p, x in res[v]['by_pos'].items()))
    print(f'  chosen: {best}')


def live():
    ep, mp = os.path.join(DATA, 'weekly_effects.json'), os.path.join(DATA, 'weekly_model.json')
    effects = json.load(open(ep))['effects'] if os.path.exists(ep) else {}
    # until the study and backtest exist, run on Sleeper's projection + injury/practice rules only
    chosen = (json.load(open(mp))['chosen'] if os.path.exists(mp) else 'sleeper+conditions') if effects else 'sleeper'
    base_kind, factors = VARIANTS[chosen]
    season = max(int(d) for d in os.listdir(DATA) if d.isdigit())
    S = Season(season, live=True)
    open_weeks = sorted({int(g['week']) for g in S.games if not g['home_score']})
    if not open_weeks:
        print('weekly: no unplayed regular-season games left')
        return
    week = open_weeks[0]
    P = json.load(open(os.path.join(DATA, 'players.json')))
    R = json.load(open(os.path.join(DATA, str(season), 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, str(season), 'users.json')))}
    _ip = os.path.join(DATA, 'injury_effects.json')
    global INJ
    INJ = json.load(open(_ip))['gameday'] if os.path.exists(_ip) else {}
    sl, fm, mi = sleeper_week(season, week), S.form(week), S.matchup_index(week)
    games = {}
    for g in S.week_games(week):
        games[g['home_team']] = g
        games[g['away_team']] = g
    # practice reports (latest entry per player this week)
    prac = {}
    ip = fetch(f'{BASE}/injuries/injuries_{season}.csv', os.path.join(CACHE, f'injuries_{season}.csv'), 6 * 3600)
    for r in csv.DictReader(open(ip, encoding='utf-8')) if ip else []:
        if r['week'] == str(week):
            sid = S.gs.get(r['gsis_id'])
            if sid:
                prac[sid] = {'practice': r['practice_status'], 'report': r['report_status'],
                             'injury': r['report_primary_injury'] or r['practice_primary_injury']}
    out_status = ('Out', 'IR', 'Sus', 'PUP', 'NA', 'DNR', 'COV')
    out_qbs = {gid for gid, sid in S.gs.items() if (P.get(sid, {}).get('injury_status') in out_status
                                                       or prac.get(sid, {}).get('report') == 'Out')}
    players = {}
    for r in R:
        for pid in r.get('players') or []:
            p = P.get(pid, {})
            pos, team = p.get('position'), p.get('team')
            if pos not in LF.POS:
                continue
            row = {'name': p.get('full_name'), 'pos': pos, 'team': team, 'owner': U.get(r.get('owner_id')),
                   'roster_id': r['roster_id'], 'sleeper': round(sl.get(pid, 0), 1), 'flags': []}
            nvt = SLEEPER_TO_NV.get(team, team)      # games/sites are keyed by nflverse codes
            if not team or nvt not in games:
                row.update(proj=0.0, flags=['bye' if team else 'no NFL team'])
                players[pid] = row
                continue
            ctx = S.team_context(games[nvt], nvt, out_qbs)
            pts, n = fm.get(pid, (0, 0))
            base = sl.get(pid, 0) if base_kind == 'sleeper' else (pts + K_FORM * sl.get(pid, 0)) / (n + K_FORM)
            proj, parts = score(base, effects, pos, ctx, mi, factors, chosen.endswith('+extremes'))
            status = p.get('injury_status')
            pr = prac.get(pid, {})
            if status in out_status or pr.get('report') == 'Out':
                proj, why = 0.0, f"OUT ({pr.get('injury') or p.get('injury_body_part') or status})"
                row['flags'].append(why)
            elif status in ('Doubtful', 'Questionable') or pr.get('report') in ('Doubtful', 'Questionable'):
                # Measured game-day odds (ops/injury_study.py): how often players with this status and
                # practice level actually took a snap, 2015-2025. Applied in the LINEUP step, where a
                # same-or-later-kickoff bench fallback makes the decision free (decide at inactives).
                st_ = 'Doubtful' if (status == 'Doubtful' or pr.get('report') == 'Doubtful') else 'Questionable'
                pl = 'DNP' if 'Did Not' in (pr.get('practice') or '') else 'Limited' if 'Limited' in (pr.get('practice') or '') \
                    else 'Full' if 'Full' in (pr.get('practice') or '') else 'none'
                g = (INJ.get(f'{st_}|{pl}') or INJ.get(f'{st_}|none') or {})
                row['p_play'] = g.get('p_play', 0.25 if st_ == 'Doubtful' else 0.7)
                row['flags'].append(f"{st_} ({pr.get('practice') or 'no practice report yet'}) — plays {row['p_play']:.0%} historically")
            w = ctx['weather']
            if isinstance(w, dict) and (w['wind'] >= 15 or w['snow'] >= 0.5 or w['rain'] >= 5):
                row['flags'].append(f"weather: {w['wind']:.0f} mph wind, {w['temp']:.0f}F"
                                    + (', snow' if w['snow'] >= 0.5 else ', heavy rain' if w['rain'] >= 5 else ''))
            if ctx['implied_pts'] is not None and ctx['implied_pts'] < 18:
                row['flags'].append(f"team implied {ctx['implied_pts']} pts")
            if ctx['backup_qb'] == 'backup' and pos != 'QB':
                row['flags'].append('backup QB starting')
            row.update(proj=round(proj, 1), form_ppg=round(pts / n, 1) if n else None, opp=ctx['opp'],
                       kickoff=ctx['kickoff'], ko=f"{games[nvt]['gameday']} {games[nvt]['gametime']}", implied_pts=ctx['implied_pts'], weather=w,
                       adjustments={f: {'bucket': b, 'mult': x} for f, (b, x) in parts.items()})
            players[pid] = row

    flex_pos = set().union(*LF.FLEX_SLOTS) if LF.FLEX_SLOTS else set()
    teams = {}
    for r in R:
        mine = [pid for pid in (r.get('players') or []) if pid in players
                and pid not in (r.get('taxi') or []) and pid not in (r.get('reserve') or [])]

        def hedge(pid, lineup):
            """Best healthy BENCH player (not in `lineup`) who can fill his slot and kicks off at the same
            time or later — the swap you make when he is ruled inactive."""
            x = players[pid]
            elig = flex_pos if x['pos'] in flex_pos else {x['pos']}
            cands = [q for q in mine if q != pid and q not in lineup and players[q]['pos'] in elig and players[q]['proj'] > 0
                     and 'p_play' not in players[q] and (players[q].get('ko') or '') >= (x.get('ko') or '~')]
            return max(cands, key=lambda q: players[q]['proj'], default=None)

        # pass 1: game-time players at full value (assume a fallback exists); pass 2: discount the ones
        # whose lineup has no bench fallback by their measured odds of playing, and re-pick the lineup
        _, first = LF.best_lineup_ids((players[p]['proj'], p, players[p]['pos']) for p in mine)
        unhedged = {p for p in mine if 'p_play' in players[p] and not hedge(p, first)}

        def lineup_val(pid):
            x = players[pid]
            return x['proj'] * x['p_play'] if pid in unhedged else x['proj']
        total, best = LF.best_lineup_ids((lineup_val(p), p, players[p]['pos']) for p in mine)
        set_now = [p for p in (r.get('starters') or []) if p in players]
        cur = sum(lineup_val(p) for p in set_now)
        ins = [p for p in best if p not in set_now]
        outs = [p for p in set_now if p not in best]
        plans = []
        for p in best:
            if 'p_play' in players[p]:
                h = hedge(p, best)
                plans.append({'pid': p, 'p_play': players[p]['p_play'], 'fallback': h,
                              'lock': players[p].get('kickoff')})
        teams[r['roster_id']] = {'owner': U.get(r.get('owner_id')), 'best': best, 'best_total': round(total, 1),
                                 'set': set_now, 'set_total': round(cur, 1), 'gain': round(total - cur, 1),
                                 'swap_in': ins, 'swap_out': outs, 'gametime_plans': plans}
    json.dump({'season': season, 'week': week, 'model': chosen, 'generated': time.strftime('%Y-%m-%d %H:%M'),
               'players': players, 'teams': teams}, open(os.path.join(DATA, 'weekly.json'), 'w'))
    me = json.load(open(os.path.join(ROOT, 'config.json'))).get('my_username')
    t = next((v for v in teams.values() if v['owner'] == me), None)
    print(f'weekly -> data/weekly.json: week {week}, model {chosen}, {len(players)} rostered players')
    if t:
        print(f"  {me}: set lineup {t['set_total']} vs best {t['best_total']} (+{t['gain']})"
              + (': start ' + ', '.join(players[p]['name'] for p in t['swap_in']) + ' over '
                 + ', '.join(players[p]['name'] for p in t['swap_out']) if t['gain'] >= 2 else ' — no swap worth 2+ pts'))


if __name__ == '__main__':
    backtest() if '--backtest' in sys.argv else live()
