#!/usr/bin/env python3
"""Opportunity share: snaps, targets and air yards. The leading indicator.

Consensus value is a lagging measure - the market reprices a player weeks after
his role changed. Depth charts are worse: they are updated by hand and a team
will list a starter it has quietly stopped feeding. Snap share and target share
move FIRST, which is why they belong in a scouting tool. A WR3 whose snap share
went 45% -> 80% is a buy before the value sources notice; a "starter" at 55% of
snaps and an 11% target share is a sell whatever the depth chart claims.

Two sources, joined on nflverse's own id bridge rather than on names:
  stats_player_week_<season>.csv - targets, target_share, air_yards_share, PPR
  snap_counts_<season>.csv       - offense_pct (the honest playing-time number)
  roster_<season>.csv            - gsis_id <-> pfr_id <-> sleeper_id crosswalk,
                                   so everything binds to the league's own ids
                                   with no name matching at all.

Season choice: the CURRENT season once it has >=3 games of data, otherwise the
last completed one. In September that means you are reading last year's roles,
which is the right prior - and it flips to live data automatically by week 4.

Writes data/usage.json: {sleeper_id: {season, games, snap_pct, target_share,
air_yards_share, tgt_per_g, ppr_ppg}}. Shares are 0-1. Stdlib only.
"""
import csv, json, os, statistics, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
BASE = 'https://github.com/nflverse/nflverse-data/releases/download'
POS = ('QB', 'RB', 'WR', 'TE')
MIN_WEEKS = 3          # before this, the current season tells you nothing


def grab(url, path, max_age=86400):
    """Download unless a fresh copy is already cached. Returns None if absent
    upstream - an unplayed season 404s, and that is expected, not an error."""
    if os.path.exists(path) and os.path.getsize(path) > 1000 and _is_csv(path):
        import time
        if time.time() - os.path.getmtime(path) < max_age:
            return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = subprocess.run(['curl', '-sL', '-w', '%{http_code}', '--max-time', '180',
                        '-o', path, url], capture_output=True, text=True)
    if r.stdout.strip().endswith('404') or not os.path.exists(path) \
            or os.path.getsize(path) < 1000 or not _is_csv(path):
        # A size check alone is not enough: a transient upstream failure serves
        # a ~160KB HTML error page with a 200, which then sits in the cache for
        # a day and silently zeroes out snap share (seen 2026-09-10).
        if os.path.exists(path):
            os.remove(path)
        return None
    return path


def _is_csv(path):
    """A CSV, not an HTML error page served with a 200."""
    with open(path, 'rb') as f:
        head = f.read(400).lstrip()
    return not head[:1] == b'<' and b',' in head.split(b'\n')[0]


def rows(path):
    return list(csv.DictReader(open(path, encoding='utf-8', errors='replace')))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_season(season):
    """(stat rows, snap rows, sleeper crosswalk) or None if the season is unplayed."""
    sp = grab(f'{BASE}/stats_player/stats_player_week_{season}.csv',
              f'{CACHE}/stats_player_week_{season}.csv')
    if not sp:
        return None
    st = [r for r in rows(sp) if r.get('season_type') == 'REG'
          and r.get('position') in POS]
    if len({r['week'] for r in st}) < MIN_WEEKS:
        return None
    ro = grab(f'{BASE}/rosters/roster_{season}.csv', f'{CACHE}/roster_{season}.csv')
    sc = grab(f'{BASE}/snap_counts/snap_counts_{season}.csv',
              f'{CACHE}/snap_counts_{season}.csv')
    return st, (rows(sc) if sc else []), (rows(ro) if ro else [])


def main():
    latest = max(int(d) for d in os.listdir(DATA) if d.isdigit())
    got, season = None, None
    for s in (latest, latest - 1):
        got = load_season(s)
        if got:
            season = s
            break
    if not got:
        print('usage: no season with enough data — skipped')
        json.dump({}, open(os.path.join(DATA, 'usage.json'), 'w'))
        return
    st, snaps, roster = got
    print(f'  usage baseline season: {season} '
          f'({len({r["week"] for r in st})} weeks)')

    # id crosswalk from nflverse's own roster file — no name matching
    gsis_sleeper, pfr_sleeper = {}, {}
    for r in roster:
        sid = r.get('sleeper_id')
        if not sid:
            continue
        if r.get('gsis_id'):
            gsis_sleeper[r['gsis_id']] = sid
        if r.get('pfr_id'):
            pfr_sleeper[r['pfr_id']] = sid

    acc = {}
    for r in st:
        sid = gsis_sleeper.get(r.get('player_id'))
        if not sid:
            continue
        a = acc.setdefault(sid, {'g': 0, 'ppr': 0.0, 'tgt': 0.0,
                                 'ts': [], 'ays': [], 'snap': []})
        a['g'] += 1
        a['ppr'] += num(r.get('fantasy_points_ppr')) or 0.0
        a['tgt'] += num(r.get('targets')) or 0.0
        for key, col in (('ts', 'target_share'), ('ays', 'air_yards_share')):
            v = num(r.get(col))
            if v is not None:
                a[key].append(v)

    for r in snaps:
        sid = pfr_sleeper.get(r.get('pfr_player_id'))
        if not sid or sid not in acc:
            continue
        v = num(r.get('offense_pct'))
        if v is not None:
            acc[sid]['snap'].append(v)

    out = {}
    for sid, a in acc.items():
        if not a['g']:
            continue
        out[sid] = {
            'season': season, 'games': a['g'],
            'ppr_ppg': round(a['ppr'] / a['g'], 2),
            'tgt_per_g': round(a['tgt'] / a['g'], 2),
            'snap_pct': round(statistics.mean(a['snap']), 4) if a['snap'] else None,
            'target_share': round(statistics.mean(a['ts']), 4) if a['ts'] else None,
            'air_yards_share': round(statistics.mean(a['ays']), 4) if a['ays'] else None,
        }
    json.dump(out, open(os.path.join(DATA, 'usage.json'), 'w'))
    withsnap = sum(1 for v in out.values() if v['snap_pct'] is not None)
    print(f'usage written for {len(out)} players -> data/usage.json '
          f'({withsnap} with snap share)')


if __name__ == '__main__':
    sys.exit(main())
