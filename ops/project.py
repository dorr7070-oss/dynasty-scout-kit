#!/usr/bin/env python3
"""Projected 2026 standings from Sleeper's own player projections.

Sleeper publishes per-week pts_ppr projections (PPR 1.0 = league scoring). We
sum each roster's best legal lineup per week over the set schedule
(data/<season>/matchups.json) to project wins, then rank -> projected finish.
This is the finish proxy that sets rookie-pick slots in trade_grades.py; it
predicts actual W-L far better than dynasty trade value does.

Two artifacts:
  data/projected_standings.json — {roster_id: place} (1 = best). The stable
    contract picks.py reads; do not change its shape.
  data/projection.json — the full working: per-player weekly points, each
    roster's week-by-week lineup total, and every matchup's margin. advise.py
    uses this to score moves by GAMES FLIPPED against the real schedule
    instead of by dynasty value alone (a +1,200-value TE that adds 1.2
    pts/week flips nothing, and the briefing should say so).

Caching: only the Sleeper FETCH is cached (data/sleeper_projections.json, 3
days) — those per-player numbers move slowly. The standings are recomputed on
every run, because they depend on rosters that change with every trade. Caching
them silently grades new trades against a pre-trade league: on 2026-08-16 a
2-day-old cache still had one team at 3-11, tiering their 2027 1st as an Early
1st (4,230) instead of a Mid (2,720) and mis-grading the James Cook trade by
1,510. Pass --refetch to force a fresh pull. Stdlib only (curl for the fetch,
per AGENTS rule 2). Part of ./update.sh, before trade_grades.py and advise.py.
"""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))
UA = 'Mozilla/5.0'
API = 'https://api.sleeper.com/projections/nfl'
OUT = os.path.join(DATA, 'projected_standings.json')
OUT_FULL = os.path.join(DATA, 'projection.json')
CACHE = os.path.join(DATA, 'sleeper_projections.json')   # network cache only
CACHE_TTL = 3 * 86400

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_format as LF  # noqa: E402  league shape from its own settings
POS = LF.POS
REG_WEEKS = LF.REG_WEEKS          # regular season, from playoff_week_start
STARTERS = list(LF.CORE.items())
FLEX = len(LF.FLEX_SLOTS)


def fetch(url):
    r = subprocess.run(['curl', '-sL', '--max-time', '60', '-A', UA, url],
                       capture_output=True, text=True, check=True)
    return r.stdout


def weekly_projections(season):
    proj = {}
    q = '&'.join(f'position[]={p}' for p in POS)
    for wk in REG_WEEKS:
        data = json.loads(fetch(f'{API}/{season}/{wk}?season_type=regular&{q}&order_by=ppr'))
        for x in data:
            st = x['stats']
            # league scoring: full / half / no PPR, plus any TE premium per catch
            pts = st.get('pts_ppr') if LF.PPR >= 1 else st.get('pts_half_ppr') if LF.PPR >= 0.5 else st.get('pts_std')
            if pts is not None and LF.TE_PREMIUM and (x.get('player') or {}).get('position') == 'TE':
                pts += LF.TE_PREMIUM * (st.get('rec') or 0)
            if pts is not None:
                proj.setdefault(str(x['player_id']), {})[wk] = pts
    return proj


def cached_projections(season, refetch=False):
    """Sleeper's per-week projections, cached for CACHE_TTL.

    ONLY the network fetch is cached. Callers must still recompute standings
    from the current rosters on every run — see the module docstring for why.
    """
    if not refetch and os.path.exists(CACHE) \
            and time.time() - os.path.getmtime(CACHE) < CACHE_TTL:
        blob = json.load(open(CACHE))
        if blob.get('season') == season and blob.get('scoring', [1.0, 0.0]) == [LF.PPR, LF.TE_PREMIUM]:
            print(f'  sleeper projections cached (<3d, {len(blob["proj"])} players)')
            return {pid: {int(w): v for w, v in wks.items()}
                    for pid, wks in blob['proj'].items()}
    proj = weekly_projections(season)
    json.dump({'season': season, 'scoring': [LF.PPR, LF.TE_PREMIUM],
               'proj': {pid: {str(w): v for w, v in wks.items()}
                        for pid, wks in proj.items()}}, open(CACHE, 'w'))
    print(f'  sleeper projections fetched ({len(proj)} players)')
    return proj


def lineup_points(pl, wk, proj, pos_of):
    """Best legal lineup total for one week. `pos_of` maps player_id -> position;
    `proj` is {player_id: {week: pts}}. Shared with advise.py so the two agree
    on what a lineup is worth."""
    by = {p: [] for p in POS}
    for pid in pl:
        pos = pos_of(str(pid))
        if pos in by:
            by[pos].append(proj.get(str(pid), {}).get(wk, 0.0) or 0.0)
    return LF.best_lineup(by)


def main(refetch=False):
    players = json.load(open(os.path.join(DATA, 'players.json')))
    seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
    latest = seasons[-1]
    rosters = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
    matchups = json.load(open(os.path.join(DATA, latest, 'matchups.json')))
    pos_of = lambda pid: (players.get(pid) or {}).get('position')

    proj = cached_projections(latest, refetch)
    roster = {r['roster_id']: r['players'] or [] for r in rosters}
    wins = {rid: 0 for rid in roster}
    weekly = {rid: {} for rid in roster}      # rid -> {week: lineup pts}
    schedule = {rid: [] for rid in roster}    # rid -> [{wk, opp, pts, opp_pts}]

    for wk in REG_WEEKS:
        entries = matchups.get(str(wk), [])
        pts = {e['roster_id']: lineup_points(roster.get(e['roster_id'], []), wk, proj, pos_of)
               for e in entries if e['roster_id'] in roster}
        for rid, v in pts.items():
            weekly[rid][wk] = round(v, 2)
        seen = set()
        for e in entries:
            mid, rid = e['matchup_id'], e['roster_id']
            if mid in seen or rid not in roster:
                continue
            opp = next((x for x in entries
                        if x['matchup_id'] == mid and x['roster_id'] != rid), None)
            if not opp or opp['roster_id'] not in roster:
                continue
            seen.add(mid)
            orid = opp['roster_id']
            a, b = pts[rid], pts[orid]
            wins[rid if a >= b else orid] += 1
            schedule[rid].append({'wk': wk, 'opp': orid, 'pts': round(a, 2),
                                  'opp_pts': round(b, 2)})
            schedule[orid].append({'wk': wk, 'opp': rid, 'pts': round(b, 2),
                                   'opp_pts': round(a, 2)})

    order = sorted(wins, key=lambda k: -wins[k])
    place = {rid: i + 1 for i, rid in enumerate(order)}
    json.dump({str(k): v for k, v in place.items()}, open(OUT, 'w'))

    n = len(REG_WEEKS)
    # keep only players with a real projection, so the artifact stays small
    slim = {pid: {str(w): round(v, 2) for w, v in wks.items() if v}
            for pid, wks in proj.items() if any(wks.values())}
    json.dump({
        'season': latest,
        'weeks': [REG_WEEKS.start, REG_WEEKS.stop - 1],
        'starters': dict(STARTERS), 'flex': FLEX,
        'player_weekly': slim,
        'rosters': {str(rid): {'wins': wins[rid], 'losses': n - wins[rid],
                               'place': place[rid], 'weekly': weekly[rid],
                               'schedule': sorted(schedule[rid], key=lambda x: x['wk'])}
                    for rid in roster},
    }, open(OUT_FULL, 'w'))

    print(f'projected standings written -> {os.path.basename(OUT)} '
          f'(top: roster {order[0]} {wins[order[0]]}-{n - wins[order[0]]})')
    print(f'full projection written -> {os.path.basename(OUT_FULL)} '
          f'({len(slim)} players x {n} weeks)')


if __name__ == '__main__':
    main(refetch='--refetch' in sys.argv)
