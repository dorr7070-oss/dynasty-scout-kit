#!/usr/bin/env python3
"""Matchups already decided inside the week in progress (added 2026-10-04).

Sleeper only posts a week's wins and losses to the standings after the week closes (Tuesday), so on Sunday night a
season simulation would still give a team a chance to win a game it has already lost. decided(week) returns
{roster_id: final points} for every team whose matchup is over: every starter on both sides plays for an NFL team
whose game Sleeper's schedule marks "complete". The simulations use these scores instead of random draws for that
week. Any network failure returns {} (the simulation then falls back to drawing the whole week, as before).
"""
import json, os, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))


def _get(url):
    # api.sleeper.com answers 403 to Python's default User-Agent (seen 2026-10-04), so send an ordinary one
    req = urllib.request.Request(url + ('&' if '?' in url else '?') + f't={int(time.time())}', headers={'User-Agent': 'Mozilla/5.0'})
    return json.load(urllib.request.urlopen(req, timeout=20))


def decided(week, season=None):
    try:
        league = CFG['league_id']
        season = season or _get('https://api.sleeper.app/v1/state/nfl')['season']
        sched = _get(f'https://api.sleeper.com/schedule/nfl/regular/{season}')
        matchups = _get(f'https://api.sleeper.app/v1/league/{league}/matchups/{week}')
    except Exception:
        return {}
    games = [g for g in sched if g.get('week') == week]
    playing = {t for g in games for t in (g['home'], g['away'])}
    done = {t for g in games if g.get('status') == 'complete' for t in (g['home'], g['away'])}
    P = json.load(open(os.path.join(DATA, 'players.json')))

    def finished(pid):
        team = pid if pid.isalpha() and pid.isupper() else (P.get(pid) or {}).get('team')
        return team is None or team not in playing or team in done      # free agent / bye / game over

    by_mid = {}
    for m in matchups:
        if m.get('matchup_id') is not None:
            by_mid.setdefault(m['matchup_id'], []).append(m)
    out = {}
    for pair in by_mid.values():
        if len(pair) == 2 and all(finished(s) for m in pair for s in (m.get('starters') or []) if s and s != '0'):
            for m in pair:
                out[m['roster_id']] = float(m.get('points') or 0)
    return out


def result(locked, rid, opp, wk, cur_wk):
    """1.0 / 0.0 if this game is already decided, else None (caller uses its win probability)."""
    if wk == cur_wk and rid in locked and opp in locked:
        return 1.0 if locked[rid] > locked[opp] else 0.0
    return None


if __name__ == '__main__':
    import sys
    print(decided(int(sys.argv[1])))
