#!/usr/bin/env python3
"""Rest-of-season playoff odds for hypothetical trades.

    python3 ops/trade_sim.py                          # current rosters
    python3 ops/trade_sim.py "Some Player>yourname" "Other Player>theirname"

Each move is "<Full Name>><username>": the player leaves whoever rosters him and joins
that owner. Uses LIVE Sleeper rosters (not the data/ cache, so a trade made minutes
ago counts), data/projection.json for weekly Sleeper projections, the same lineup
optimizer as project.py, the real schedule, current W-L, and a Monte Carlo with
weekly scoring noise (SD 22). Prints pts/wk, deterministic record and playoff odds for
every team. Built 2026-09-30 after the same model was rebuilt by hand a dozen times in
one trade-negotiation session. Stdlib only; fetch via curl (AGENTS rule 2).
"""
import json, os, random, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ops'))
from project import lineup_points  # noqa: E402
import league_format as LF  # noqa: E402

CFG = json.load(open(os.path.join(ROOT, 'config.json')))
L = CFG['league_id']
SD, N = 22, 8000


def get(url):
    return json.loads(subprocess.run(['curl', '-s', '-H', 'Cache-Control: no-cache', url],
                                     capture_output=True, text=True, check=True).stdout)


def main(moves):
    P = json.load(open(os.path.join(ROOT, 'data', 'players.json')))
    d = json.load(open(os.path.join(ROOT, 'data', 'projection.json')))
    league = get(f'https://api.sleeper.app/v1/league/{L}')
    playoff_teams = LF.PLAYOFF_TEAMS
    rosters = get(f'https://api.sleeper.app/v1/league/{L}/rosters')
    users = {u['user_id']: u['display_name'] for u in get(f'https://api.sleeper.app/v1/league/{L}/users')}
    name = {r['roster_id']: users.get(r['owner_id'], '?') for r in rosters}
    rid_of = {v: k for k, v in name.items()}
    proj = {pid: {int(w): v for w, v in wk.items()} for pid, wk in d['player_weekly'].items()}
    pos_of = lambda p: P.get(p, {}).get('position')
    act = {r['roster_id']: [p for p in r['players'] if p not in (r.get('reserve') or [])
                            and p not in (r.get('taxi') or [])] for r in rosters}
    byname = {P[p].get('full_name'): p for r in rosters for p in r['players'] if p in P}
    for m in moves:
        who, to = m.rsplit('>', 1)
        p = byname.get(who.strip())
        if not p or to.strip() not in rid_of:
            sys.exit(f'cannot parse move {m!r} (player must be rostered; owner = Sleeper username)')
        for k in act:
            if p in act[k]:
                act[k].remove(p)
        act[rid_of[to.strip()]].append(p)
    sched = {int(k): v['schedule'] for k, v in d['rosters'].items()}
    done_wk = league['settings'].get('last_scored_leg', 0)
    weeks = [w for w in range(done_wk + 1, LF.PLAYOFF_START)]
    W0 = {r['roster_id']: r['settings']['wins'] for r in rosters}
    PF0 = {r['roster_id']: r['settings'].get('fpts', 0) + r['settings'].get('fpts_decimal', 0) / 100 for r in rosters}
    pts = {r: {w: lineup_points(act[r], w, proj, pos_of) for w in weeks} for r in act}
    det = {r: sum(1 for g in sched[r] if g['wk'] in weeks and pts[r][g['wk']] > pts[g['opp']][g['wk']]) for r in act}
    random.seed(7)
    made = {r: 0 for r in act}
    for _ in range(N):
        W, PF = dict(W0), dict(PF0)
        for w in weeks:
            s = {r: random.gauss(pts[r][w], SD) for r in act}
            seen = set()
            for r in act:
                for g in sched[r]:
                    if g['wk'] == w and (r, g['opp']) not in seen:
                        o = g['opp']; seen |= {(r, o), (o, r)}
                        W[r if s[r] > s[o] else o] += 1
            if LF.MEDIAN_GAME:
                for r in sorted(act, key=lambda r: -s[r])[:len(act) // 2]:
                    W[r] += 1
            for r in act:
                PF[r] += s[r]
        for r in sorted(act, key=lambda r: (-W[r], -PF[r]))[:playoff_teams]:
            made[r] += 1
    print(f'weeks {weeks[0]}-{weeks[-1]} · top {playoff_teams} make playoffs · moves: {moves or "none"}')
    for r in sorted(act, key=lambda r: -made[r]):
        g = len(weeks)
        print(f'  {name[r]:16} {W0[r]}-{len(weeks) and (league["settings"].get("last_scored_leg",0)-W0[r])}'
              f'  {sum(pts[r].values())/g:6.1f}/wk  ROS {det[r]}-{g-det[r]}  playoff {100*made[r]/N:5.1f}%')


if __name__ == '__main__':
    main(sys.argv[1:])
