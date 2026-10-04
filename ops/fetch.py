#!/usr/bin/env python3
"""Fetch the full Sleeper history for the league in config.json.

Walks the previous_league_id chain (one league per season) and saves, per season:
  league.json, users.json, rosters.json, traded_picks.json, drafts.json
  (draft meta + picks), transactions.json (all weeks, deduped), matchups.json,
  winners_bracket.json
Also caches the NFL players DB at data/players.json (refreshed if >7 days old).

Stdlib only. Rerun any time; it always refetches league data (small) and is the
first step of every update: fetch -> values -> profiles -> report.
"""
import json, os, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))
API = 'https://api.sleeper.app/v1'


def get(url, retries=3):
    # cache-buster: Sleeper's CDN can serve a roster that is a minute or two old, which hid a lineup
    # swap made just before a game-day refresh (2026-10-04). The API ignores the extra parameter.
    url += ('&' if '?' in url else '?') + f'_={int(time.time())}'
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1 + i)


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, 'w'))


def fetch_season(lid, league):
    season = league['season']
    d = os.path.join(DATA, season)
    save(f'{d}/league.json', league)
    save(f'{d}/users.json', get(f'{API}/league/{lid}/users'))
    save(f'{d}/rosters.json', get(f'{API}/league/{lid}/rosters'))
    save(f'{d}/traded_picks.json', get(f'{API}/league/{lid}/traded_picks'))
    save(f'{d}/winners_bracket.json', get(f'{API}/league/{lid}/winners_bracket'))

    drafts = get(f'{API}/league/{lid}/drafts') or []
    for dr in drafts:
        dr['picks'] = get(f"{API}/draft/{dr['draft_id']}/picks") or []
        # the draft's actual order (slot -> original roster) lives only on the per-draft
        # endpoint; picks.py prices already-held drafts from it (2026-10-02)
        detail = get(f"{API}/draft/{dr['draft_id']}") or {}
        dr['slot_to_roster_id'] = detail.get('slot_to_roster_id')
        dr['draft_order'] = detail.get('draft_order')
    save(f'{d}/drafts.json', drafts)

    txns, seen = [], set()
    for wk in range(0, 19):
        for t in get(f'{API}/league/{lid}/transactions/{wk}') or []:
            if t['transaction_id'] not in seen:
                seen.add(t['transaction_id'])
                txns.append(t)
    save(f'{d}/transactions.json', txns)

    matchups = {}
    for wk in range(1, 18):
        m = get(f'{API}/league/{lid}/matchups/{wk}') or []
        if m:
            matchups[str(wk)] = m
    save(f'{d}/matchups.json', matchups)
    print(f'  {season}: {len(txns)} transactions, {len(drafts)} draft(s), '
          f'{len(matchups)} weeks of matchups')
    return season


def main():
    os.makedirs(DATA, exist_ok=True)
    platform = CFG.get('platform', 'sleeper')

    players_path = os.path.join(DATA, 'players.json')
    # ops/context.py reads live injury_status / depth_chart_order out of this
    # file, and those move midweek — so refresh it DAILY once the season is
    # live, and fall back to the cheap weekly cadence in the offseason.
    max_age = 7 * 86400
    try:
        if platform == 'sleeper':
            in_season = (get(f"{API}/league/{CFG['league_id']}") or {}).get('status') == 'in_season'
        else:
            in_season = (get(f'{API}/state/nfl') or {}).get('season_type') == 'regular'
        if in_season:
            max_age = 86400
    except Exception:
        pass
    if not os.path.exists(players_path) or time.time() - os.path.getmtime(players_path) > max_age:
        print(f'fetching players DB (~14MB, max age {max_age // 3600}h)...')
        save(players_path, get(f'{API}/players/nfl'))

    if platform != 'sleeper':
        # ESPN / Yahoo: translate into the same files (ops/adapters/), matched via the Sleeper player DB
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        prof_path = os.path.join(DATA, 'league_profile.json')
        if not os.path.exists(prof_path):
            sys.exit('fetch.py: run ops/league_profile.py first (it reads the league settings)')
        profile = json.load(open(prof_path, encoding='utf-8'))
        players = json.load(open(players_path, encoding='utf-8'))
        if platform == 'espn':
            from adapters import espn
            espn.fetch(DATA, CFG, profile, save, players)
        elif platform == 'yahoo':
            from adapters import yahoo
            import league_profile
            yahoo.fetch(DATA, CFG, profile, save, players, league_profile.yahoo_token())
        else:
            sys.exit(f'fetch.py: unknown platform "{platform}" in config.json')
        print('done -> data/')
        return

    lid = CFG['league_id']
    seasons = []
    print('walking league chain:')
    while lid:
        try:
            league = get(f'{API}/league/{lid}')
        except urllib.error.HTTPError as e:
            if seasons:      # an older season's league was deleted on Sleeper: history ends here
                print(f'  previous league {lid} not available (HTTP {e.code}) — history stops at {seasons[-1]}')
                break
            raise
        if not league:
            break
        seasons.append(fetch_season(lid, league))
        lid = league.get('previous_league_id')
        if str(lid) in ('0', 'None', ''):   # Sleeper uses '0' for no previous season
            break
    save(os.path.join(DATA, 'seasons.json'), seasons)
    print(f'done: {len(seasons)} seasons -> data/')


if __name__ == '__main__':
    main()
