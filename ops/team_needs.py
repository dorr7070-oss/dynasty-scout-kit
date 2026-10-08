#!/usr/bin/env python3
"""Team needs: what every team actually lacks vs what it has -> data/team_needs.json (dashboard League tab "Team Needs").

Per team and position: the starters' rest-of-season points per week (our blended projection, data/our_projection.json), the
league rank of that unit, hurt starters (Out / IR / Doubtful / Questionable), and startable depth they can't use. A NEED is a
bottom-four unit or a hurt starter with no startable backup; a SURPLUS is a bench player who would start for at least half the
league at his position. For each team it then lists which of your spare players fill a need — skipping anyone who clashes with
a same-NFL-team player at the same position on their roster, unless the two are a starter/backup pair at RB or QB (the owner's
rule, 2026-10-08) — and the owner's own intel from config (`not_interested`).
Added 2026-10-08 (owner request: review every team's needs vs what it has, for better offers).
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402

SLOTS = {'QB': 1, 'RB': 2, 'WR': 3, 'TE': 1}
HURT = ('Out', 'IR', 'Doubtful', 'Questionable', 'PUP', 'Sus')


def main():
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    me = cfg.get('my_username')
    season = max(d for d in os.listdir(DATA) if d.isdigit())
    P = json.load(open(os.path.join(DATA, 'players.json')))
    R = json.load(open(os.path.join(DATA, season, 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, season, 'users.json')))}
    op = json.load(open(os.path.join(DATA, 'our_projection.json')))
    week = (json.load(open(os.path.join(DATA, 'weekly.json'))).get('week') or 1)
    teams = op.get('teams') or {}
    cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
    ppg = {}
    for pid, x in (op.get('players') or {}).items():
        wk = [v for w, v in (x.get('weekly') or {}).items() if int(w) >= week]
        ppg[pid] = sum(wk) / len(wk) if wk else 0.0
    pos_of = lambda p: (P.get(p) or {}).get('position')
    name = lambda p: (P.get(p) or {}).get('full_name') or p

    units, depth = {}, {}
    for r in R:
        o = U.get(r.get('owner_id'))
        active = [p for p in r.get('players') or [] if p not in (r.get('taxi') or [])]
        units[o], depth[o] = {}, {}
        for pos, n in SLOTS.items():
            ps = sorted([p for p in active if pos_of(p) == pos], key=lambda p: -ppg.get(p, 0))
            units[o][pos] = ps[:n]
            depth[o][pos] = ps[n:]
    score = {o: {pos: sum(ppg.get(p, 0) for p in u[pos]) for pos in SLOTS} for o, u in units.items()}
    rank = {o: {pos: 1 + sum(1 for x in score if score[x][pos] > score[o][pos]) for pos in SLOTS} for o in score}
    # what a starter at each position looks like league-wide (the median of every team's last starter there)
    last_starter = {pos: sorted(ppg.get(units[o][pos][-1], 0) if units[o][pos] else 0 for o in units)[len(units) // 2] for pos in SLOTS}

    snub = {u: set(map(str, v)) for u, v in (cfg.get('not_interested') or {}).items()}
    premium = set(map(str, cfg.get('premium') or {}))
    try:
        plan = json.load(open(os.path.join(ROOT, 'my_plan.json')))
        keep = set((plan.get('keep_starters') or {}).get('players') or [])
    except Exception:
        keep = set()

    def clash(g, roster):
        gp = P.get(g) or {}
        for q in roster:
            qp = P.get(q) or {}
            if q == g or not gp.get('team') or qp.get('team') != gp.get('team') or qp.get('position') != gp.get('position'):
                continue
            if gp.get('position') in ('RB', 'QB') and {gp.get('depth_chart_order'), qp.get('depth_chart_order')} == {1, 2}:
                return False, qp.get('full_name')
            return True, None
        return False, None

    my_r = next(r for r in R if U.get(r.get('owner_id')) == me)
    my_starters = {p for pos in SLOTS for p in units[me][pos]}
    spares = [p for p in my_r.get('players') or [] if pos_of(p) in SLOTS and p not in premium and name(p) not in keep and ppg.get(p, 0) > 0]
    out = {'week': week, 'teams': []}
    for r in R:
        o = U.get(r.get('owner_id'))
        roster = r.get('players') or []
        needs, surplus, hurt = [], [], []
        for pos in SLOTS:
            startable_backup = [p for p in depth[o][pos] if ppg.get(p, 0) >= last_starter[pos] * 0.85]
            hurt_here = [p for p in units[o][pos] if (P.get(p) or {}).get('injury_status') in HURT]
            hurt += [f'{name(p)} ({(P.get(p) or {}).get("injury_status")})' for p in hurt_here]
            if rank[o][pos] >= 9 or (hurt_here and not startable_backup):
                needs.append({'pos': pos, 'rank': rank[o][pos], 'why': f'#{rank[o][pos]} of 12' + (' and a hurt starter' if hurt_here else '')})
            for p in depth[o][pos]:
                if ppg.get(p, 0) >= last_starter[pos]:
                    surplus.append({'pos': pos, 'player': name(p), 'ppg': round(ppg.get(p, 0), 1)})
        pitch = []
        if o != me:
            for n_ in sorted(needs, key=lambda x: -x['rank']):
                for g in sorted([g for g in spares if pos_of(g) == n_['pos']], key=lambda g: -ppg.get(g, 0)):
                    if g in snub.get(o, set()):
                        continue
                    bad, hc = clash(g, roster)
                    if bad:
                        continue
                    upgrade = ppg.get(g, 0) - (ppg.get(units[o][n_['pos']][-1], 0) if units[o][n_['pos']] else 0)
                    if upgrade > 0.5 or (hc and n_['pos'] == 'RB'):
                        pitch.append({'player': name(g), 'pos': n_['pos'], 'upgrade': round(upgrade, 1), 'handcuff': hc,
                                      'starts_for_you': g in my_starters, 'value': round(cons.get(g, {}).get('mean_market', 0))})
        t = teams.get(str(r['roster_id']), {})
        out['teams'].append({'owner': o, 'record': t.get('record'), 'playoff': t.get('playoff'), 'needs': needs, 'surplus': surplus[:4],
                             'hurt': hurt, 'rank': rank[o], 'pitch': pitch[:4], 'me': o == me})
    out['teams'].sort(key=lambda x: -(x['playoff'] or 0))
    json.dump(out, open(os.path.join(DATA, 'team_needs.json'), 'w'), indent=1)
    print(f"team needs -> data/team_needs.json: {len(out['teams'])} teams; "
          + '; '.join(f"{t['owner']}: {','.join(n['pos'] for n in t['needs']) or '-'}" for t in out['teams'] if not t['me']))


if __name__ == '__main__':
    main()
