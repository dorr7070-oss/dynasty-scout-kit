#!/usr/bin/env python3
"""Data freshness check (added 2026-10-04, owner's rule: every analysis works off the most current data, and the data
gets updated wherever it needs to be). Runs near the end of every update and checks what each source CONTAINS, not
just when it was downloaded: a file fetched an hour ago can still stop at last week.

Each check is ok / stale / missing with a one-line reason -> data/freshness.json, printed, and shown on the dashboard.
It also does the one safe automatic fix: news overrides written for a past week are removed (they describe one game).

Run on its own any time:  python3 ops/freshness.py
--fix (first step of update.sh): only deletes lagging downloads so the same run fetches fresh ones; no report.
"""
import csv, gzip, json, os, re, sys, time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
NOW = time.time()
FIX = '--fix' in sys.argv     # start of update.sh: delete downloads whose contents lag, so this run re-fetches them
ET_DAY = time.strftime('%a', time.gmtime(NOW - 4 * 3600))
GAME_DAY = ET_DAY in ('Thu', 'Sun', 'Mon')


def hours(p):
    return (NOW - os.path.getmtime(p)) / 3600 if os.path.exists(p) else None


def max_week(path, season):
    if not os.path.exists(path):
        return None
    op = gzip.open if path.endswith('.gz') else open
    best = None
    with op(path, 'rt', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r.get('season', season) == season and (r.get('week') or '').isdigit():
                best = max(best or 0, int(r['week']))
    return best


def teams_in_week(path, season, week, col):
    """Distinct teams with rows for that week (a file can reach week N with only Thursday's game in it)."""
    if not os.path.exists(path):
        return set()
    op = gzip.open if path.endswith('.gz') else open
    with op(path, 'rt', encoding='utf-8') as fh:
        return {r[col] for r in csv.DictReader(fh) if r.get('season', season) == season and r.get('week') == str(week) and r.get(col)}


def main():
    checks, fixed = [], []

    def add(name, ok, detail, fix=''):
        checks.append({'source': name, 'status': ok, 'detail': detail, 'fix': fix})

    if not os.path.exists(os.path.join(DATA, 'seasons.json')):
        print('freshness: no league data yet (first run) — nothing to check; fetch.py pulls everything fresh')
        return
    latest = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))[-1]
    league = json.load(open(os.path.join(DATA, latest, 'league.json')))
    in_season = league.get('status') == 'in_season'
    done = (league.get('settings') or {}).get('last_scored_leg', 0)       # last week Sleeper has closed
    cur = done + 1
    season = latest

    # 1. live league + player status (Sleeper)
    h = hours(os.path.join(DATA, latest, 'rosters.json'))
    add('Sleeper rosters & lineups', 'ok' if h is not None and h <= 6 else 'stale', f'{h:.1f}h old' if h is not None else 'missing',
        'python3 ops/fetch.py')
    lim = (1 if GAME_DAY else 6) if in_season else 7 * 24
    h = hours(os.path.join(DATA, 'players.json'))
    add('Sleeper injury / practice / suspension status', 'ok' if h is not None and h <= lim + 0.25 else 'stale',
        f'{h:.1f}h old (limit {lim}h{" on a game day" if GAME_DAY and in_season else ""})' if h is not None else 'missing',
        'python3 ops/fetch.py (refreshes when older than the limit)')

    # 2. weekly stats and usage: must include the last completed week
    if in_season:
        games = [r for r in csv.DictReader(open(os.path.join(CACHE, 'games.csv'), encoding='utf-8'))
                 if r['season'] == season and r['game_type'] == 'REG'] if os.path.exists(os.path.join(CACHE, 'games.csv')) else []
        played = {t for r in games if r['week'] == str(done) for t in (r['home_team'], r['away_team'])}
        for name, f, col in (('Weekly box scores (nflverse)', f'stats_player_week_{season}.csv', 'team'),
                             ('Snap counts', f'snap_counts_{season}.csv', 'team'),
                             ('Play-by-play (red zone, routes)', f'pbp_{season}.csv.gz', 'posteam')):
            path = os.path.join(CACHE, f)
            have = teams_in_week(path, season, done, col) if done else set()
            # nflverse writes LA for the Rams; Sleeper/games.csv may say LAR
            gap = {t for t in played if t not in have and not (t in ('LA', 'LAR') and have & {'LA', 'LAR'})}
            if gap and FIX and (hours(path) or 0) > 2:    # lagging download: drop it so this run fetches a fresh copy
                os.remove(path)
                fixed.append(f)
            add(name, 'missing' if not os.path.exists(path) and f not in fixed else 'ok' if not gap else 'stale',
                (f'week {done} complete for all {len(played)} teams' if not gap else f'week {done} missing {len(gap)} of {len(played)} teams')
                + f'; through week {max_week(path, season)}; file {hours(path) or 0:.0f}h old',
                "nflverse posts a week's data within ~1 day; the next update re-downloads it")
        w = max_week(os.path.join(CACHE, f'injuries_{season}.csv'), season)
        add('Practice / injury reports (nflverse)', 'ok' if w is not None and w >= cur - (1 if ET_DAY in ('Tue', 'Wed') else 0) else 'stale',
            f'latest report week {w}, current week {cur}', 'reports start Wednesday; refreshed every 6h')
        g = [r for r in csv.DictReader(open(os.path.join(CACHE, 'games.csv'), encoding='utf-8'))
             if r['season'] == season and r['game_type'] == 'REG' and r['week'].isdigit() and int(r['week']) <= done] \
            if os.path.exists(os.path.join(CACHE, 'games.csv')) else []
        missing = sum(1 for r in g if not r['home_score'])
        add('Schedule, scores & Vegas lines', 'ok' if g and not missing else 'stale',
            f'{missing} completed games without a score' if g else 'no games file', 'refreshed every 6h')

    # 3. values, contracts, news
    h = hours(os.path.join(DATA, 'values', 'consensus.json'))
    add('Trade values (KTC / FantasyPros / DynastyProcess)', 'ok' if h is not None and h <= 36 else 'stale',
        f'{h:.0f}h old' if h is not None else 'missing', 'full update (update.sh)')
    h = hours(os.path.join(DATA, 'context.json'))
    add('Contracts (OverTheCap) & depth charts', 'ok' if h is not None and h <= 36 else 'stale',
        f'{h:.0f}h old' if h is not None else 'missing', 'full update (update.sh)')
    h = hours(os.path.join(DATA, 'cap_risk.json'))
    cr = json.load(open(os.path.join(DATA, 'cap_risk.json'))) if h is not None else {}
    add('Cut risk (OverTheCap dead money by season)', 'ok' if h is not None and h <= 36 and not cr.get('failed_teams') else 'stale' if h is not None else 'missing',
        f'{h:.0f}h old, {len(cr.get("players", {}))} players, {len(cr.get("unmatched", []))} unmatched'
        + (f', {len(cr["failed_teams"])} team pages failed' if cr.get('failed_teams') else '') if h is not None else 'missing', 'python3 ops/cap.py')
    if in_season:
        w = max_week(os.path.join(CACHE, 'ngs_receiving.csv.gz'), season)
        add('Tracking data (Next Gen Stats)', 'ok' if w is not None and w >= done else 'stale' if w is not None else 'missing',
            f'through week {w} (last closed week {done})', 'python3 ops/ngs.py (re-downloads every 12h)')
    h = hours(os.path.join(DATA, 'trending.json'))
    add('Sleeper trending adds / drops', 'ok' if h is not None and h <= (3 if GAME_DAY else 12) else 'stale' if h is not None else 'missing',
        f'{h:.1f}h old' if h is not None else 'missing', 'python3 ops/trending.py')
    add('Missing-starter effects (study)', 'ok' if os.path.exists(os.path.join(DATA, 'absence_effects.json')) else 'missing',
        'measured 2019-2025, holdout-tested' if os.path.exists(os.path.join(DATA, 'absence_effects.json')) else 'run ops/absence_study.py')
    np_ = os.path.join(DATA, 'news.json')
    n = json.load(open(np_)) if os.path.exists(np_) else None
    h = hours(np_)
    add('News radar (ESPN: injuries, suspensions, contracts, roles)',
        'ok' if n and h <= (3 if GAME_DAY else 12) and not n.get('failed') else 'stale' if n else 'missing',
        f'{h:.1f}h old, {n["stories_in_log"]} stories, {len(n["alerts"])} alerts' + (f', {len(n["failed"])} feeds failed' if n.get('failed') else '')
        if n else 'missing', 'python3 ops/news.py')

    # 4. hand-kept inputs that go stale quietly
    ov_p = os.path.join(DATA, 'news_overrides.json')
    ov = json.load(open(ov_p)) if os.path.exists(ov_p) else {}
    old = {k: v for k, v in ov.items() if v.get('week') is not None and v['week'] < cur}
    if old:
        json.dump({k: v for k, v in ov.items() if k not in old}, open(ov_p, 'w'), indent=1)
    add('News overrides (same-day reports)', 'ok', f'{len(ov) - len(old)} active' + (f'; removed {len(old)} from past weeks' if old else ''))
    tp = os.path.join(DATA, 'trade_plan.json')
    if os.path.exists(tp):
        upd = json.load(open(tp)).get('updated', '')
        age_d = (NOW - time.mktime(time.strptime(upd, '%Y-%m-%d'))) / 86400 if re.match(r'\d{4}-\d\d-\d\d$', upd) else 99
        add('Trade plan (data/trade_plan.json)', 'ok' if age_d <= 7 else 'stale', f'last re-checked {upd or "never"}',
            're-run the trade review; rosters, injuries and prices move weekly')
    src = open(os.path.join(ROOT, 'ops', 'league_dashboard.py')).read()
    m = re.search(r"OPEN_DECISIONS_DATE = '(\d{4}-\d\d-\d\d)'", src)
    if m:
        age_d = (NOW - time.mktime(time.strptime(m.group(1), '%Y-%m-%d'))) / 86400
        add('"On the clock" list (hand-written)', 'ok' if age_d <= 3 else 'stale', f'written {m.group(1)}',
            'rewrite OPEN_DECISIONS in ops/league_dashboard.py at each review')

    if fixed:
        print('freshness --fix: re-downloading ' + ', '.join(fixed) + ' this run (contents lagged the schedule)')
    if FIX:
        return
    bad = [c for c in checks if c['status'] != 'ok']
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'), 'game_day': GAME_DAY, 'checks': checks, 'stale': len(bad)},
              open(os.path.join(DATA, 'freshness.json'), 'w'), indent=1)
    print(f'freshness -> data/freshness.json: {len(checks) - len(bad)} of {len(checks)} sources current'
          + ('' if not bad else ' — STALE: ' + '; '.join(f"{c['source']} ({c['detail']})" for c in bad)))


if __name__ == '__main__':
    main()
