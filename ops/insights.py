#!/usr/bin/env python3
"""Six analysis feeds for the Analysis page (owner's ask, 2026-10-04) -> data/insights.json

  sos        rest-of-season and fantasy-playoff (weeks 15-17) schedule strength per position: each defense's
             PPR allowed per game to the position this season, ranked 1 = softest; averaged over each player's
             remaining opponents
  efficiency every owner's lineup efficiency and points left on the bench (ops/manager_skill.py)
  values     market value over time per player on your roster (daily snapshots, ops/value_trends.py)
  calculator for every player worth 800+ on another roster: the cheapest packages of yours (1-3 assets,
             players and picks) that clear both sides' rules — market value back to them (rebuilder >= 0,
             contender within 10%), core assets only at the king's-ransom rule — with your expected-wins change
  accuracy   week by week: our projection vs Sleeper's vs actual points (backfilled for finished weeks;
             our projection rebuilt "as of" each week from data available before it)
  capital    every team's 2027-2029 pick capital: count of 1sts, total value, best pick, and 2027 1st odds over time
Run after our_projections.py and trade_finder.py; analysis_dashboard.py renders it.
"""
import csv, json, math, os, statistics, sys
from collections import defaultdict
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import picks as PK  # noqa: E402
import our_projections as OP  # noqa: E402
from project import lineup_points  # noqa: E402
import dynasty_value as DV  # noqa: E402

NV = {'LA': 'LAR'}


def jl(name, default=None):
    p = os.path.join(DATA, name)
    return json.load(open(p)) if os.path.exists(p) else default


def main():
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    me = cfg.get('my_username')
    premium = cfg.get('premium') or {}
    P = json.load(open(os.path.join(DATA, 'players.json')))
    season = PK.latest
    R = PK.rosters
    names = {r['roster_id']: PK.rid2user.get(r['roster_id']) for r in R}
    my_rid = next(rid for rid, n in names.items() if n == me)
    pos_of = lambda s: (P.get(s) or {}).get('position')
    nm = lambda s: (P.get(s) or {}).get('full_name') or s
    cons = jl('values/consensus.json', {})
    mkt = lambda s: (cons.get(s) or {}).get('mean_market', (cons.get(s) or {}).get('mean', 0))
    op = jl('our_projection.json', {})
    proj = op.get('players') or {}
    league = json.load(open(os.path.join(DATA, season, 'league.json')))
    done = (league.get('settings') or {}).get('last_scored_leg', 0)
    out = {}

    # ---- 1. schedule strength ----
    rows = OP.week_rows(int(season))
    allowed = defaultdict(list)                       # (def team, pos) -> PPR per game allowed (team totals)
    tot = defaultdict(float)
    for r in rows:
        tot[(r['gid'], r['team'], r['pos'])] += r['pts']
    opp_of = {}
    gpath = os.path.join(CACHE, 'games.csv')
    games = [g for g in csv.DictReader(open(gpath, encoding='utf-8')) if g['season'] == season and g['game_type'] == 'REG'] if os.path.exists(gpath) else []
    for g in games:
        opp_of[(g['game_id'], g['home_team'])] = g['away_team']
        opp_of[(g['game_id'], g['away_team'])] = g['home_team']
    for (gid, team, pos), v in tot.items():
        d = opp_of.get((gid, team))
        if d:
            allowed[(d, pos)].append(v)
    rank = {}
    for pos in LF.POS:
        teams = sorted({d for d, p in allowed if p == pos}, key=lambda d: -statistics.mean(allowed[(d, pos)]))
        for i, d in enumerate(teams):
            rank[(d, pos)] = i + 1
    sched = defaultdict(dict)
    for g in games:
        w = int(g['week'])
        sched[g['home_team']][w] = g['away_team']
        sched[g['away_team']][w] = g['home_team']
    reg_end = LF.PLAYOFF_START - 1
    sos = []
    for s in (next(r for r in R if r['roster_id'] == my_rid)['players'] or []):
        pos = pos_of(s)
        team = {'LAR': 'LA'}.get((P.get(s) or {}).get('team'), (P.get(s) or {}).get('team'))
        if pos not in LF.POS or not team:
            continue
        ros = [rank.get((sched[team][w], pos)) for w in range(done + 1, reg_end + 1) if w in sched[team]]
        po = [(w, NV.get(sched[team][w], sched[team][w]), rank.get((sched[team][w], pos))) for w in (15, 16, 17) if w in sched[team]]
        ros = [x for x in ros if x]
        sos.append({'name': nm(s), 'pos': pos, 'team': P[s].get('team'), 'ros': round(statistics.mean(ros), 1) if ros else None,
                    'playoffs': [{'wk': w, 'opp': o, 'rank': rk} for w, o, rk in po],
                    'po_mean': round(statistics.mean([rk for _, _, rk in po if rk]), 1) if any(rk for _, _, rk in po) else None,
                    'value': round(mkt(s))})
    sos.sort(key=lambda x: -x['value'])
    out['sos'] = {'players': sos, 'n_teams': len({d for d, _ in allowed}), 'weeks_used': done}

    # ---- 2. lineup efficiency ----
    ms = jl('manager_skill.json', {})
    out['efficiency'] = sorted([{'owner': k, 'eff': v.get('efficiency'), 'left_pg': v.get('left_per_game'), 'weeks': v.get('weeks')}
                                for k, v in ms.items() if isinstance(v, dict) and v.get('efficiency') is not None], key=lambda x: -x['eff'])

    # ---- 3. value history ----
    hd = os.path.join(DATA, 'value_history')
    days = sorted(f[:-5] for f in os.listdir(hd) if f.endswith('.json')) if os.path.isdir(hd) else []
    snaps = {d: json.load(open(os.path.join(hd, f'{d}.json'))) for d in days}
    mine = [s for s in (next(r for r in R if r['roster_id'] == my_rid)['players'] or []) if pos_of(s) in LF.POS]
    out['values'] = {'days': days, 'players': sorted([{'name': nm(s), 'pos': pos_of(s), 'series': [snaps[d].get(s) for d in days]} for s in mine],
                                                     key=lambda x: -(x['series'][-1] or 0))}

    # ---- 4. "what it would take" calculator ----
    po_odds = {int(k): v for k, v in ((jl('pick_odds.json', {}) or {}).get('playoff') or {}).items()}
    proj_w = {s: {int(w): v for w, v in (x.get('weekly') or {}).items()} for s, x in proj.items()}
    sch = {int(k): v['schedule'] for k, v in (jl('projection.json', {}).get('rosters') or {}).items()}
    act = {r['roster_id']: [s for s in (r['players'] or []) if s not in (r.get('reserve') or []) and s not in (r.get('taxi') or [])] for r in R}
    phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def ew(rid, pl):
        return sum(phi((lineup_points(pl, g['wk'], proj_w, pos_of) - g['opp_pts']) / 31) for g in sch.get(rid, []) if g['wk'] > done)
    base_me = ew(my_rid, act[my_rid])
    give = [s for s in act[my_rid] if pos_of(s) in LF.POS and mkt(s) >= 250]
    gpick = []
    for sea, rnd, orig in PK.owned_future_picks().get(my_rid, []):
        v, tier = PK.pick_value(sea, rnd, orig)
        if v >= 250:
            gpick.append((f'pick:{sea}:{rnd}:{orig}', v, f'{sea} {tier} {PK._RN.get(rnd, rnd)} ({names.get(orig)})'))
    assets = [(s, mkt(s), nm(s)) for s in give] + gpick

    def rule_ok(combo, target_v):
        for a, v, _ in combo:
            r = premium.get(a)
            if r is None:
                continue
            need = (v + r['surplus']) if isinstance(r, dict) else float(r) * v
            if target_v < need:          # a core piece only moves at its ransom
                return False
        return True
    calc = []
    for rid, ss in act.items():
        if rid == my_rid:
            continue
        window = 'contender' if po_odds.get(rid, 0.5) >= 0.6 else 'rebuilder' if po_odds.get(rid, 0.5) <= 0.25 else 'middle'
        for t in ss:
            tv = mkt(t)
            if pos_of(t) not in LF.POS or tv < 800:
                continue
            floor = tv if window == 'rebuilder' else tv * (0.95 if window == 'middle' else 0.9)
            qual = []
            for k in (1, 2, 3):
                for c in combinations(assets, k):
                    gv = sum(v for _, v, _ in c)
                    if floor <= gv <= tv * 1.5 and rule_ok(c, tv):
                        qual.append((gv - tv, c))
            qual.sort(key=lambda q: q[0])
            age = lambda a: (P.get(a) or {}).get('age')
            tw = DV.window_value(tv, pos_of(t), age(t))
            tfit, treason = DV.plan_fit(t, pos_of(t), age(t), tv, 'get')
            pk = []
            for over, c in qual[:14]:             # the 14 cheapest, scored both ways
                gp = [a for a, _, _ in c if not a.startswith('pick:')]
                dw = ew(my_rid, [s for s in act[my_rid] if s not in gp] + [t]) - base_me
                gw = sum(DV.window_value(v, None if a.startswith('pick:') else pos_of(a), None if a.startswith('pick:') else age(a)) for a, v, _ in c)
                fits = [DV.plan_fit(a, None if a.startswith('pick:') else pos_of(a), None if a.startswith('pick:') else age(a), v, 'give') for a, v, _ in c]
                dyn = tw - gw + tfit + sum(f for f, _ in fits)
                why = [r for _, r in fits if r] + ([treason] if treason else [])
                pk.append({'give': [lbl for _, _, lbl in c], 'give_value': round(sum(v for _, v, _ in c)), 'over': round(over),
                           'my_wins': round(dw, 2), 'dyn': round(dyn), 'why': why})
            season_best = sorted(pk, key=lambda x: (-x['my_wins'], x['over']))[:3]
            dyn_best = sorted([x for x in pk if x['my_wins'] >= -0.25], key=lambda x: (-x['dyn'], -x['my_wins']))[:3]
            calc.append({'name': nm(t), 'pos': pos_of(t), 'team': P[t].get('team'), 'owner': names[rid], 'window': window,
                         'value': round(tv), 'packages': season_best, 'dynasty': dyn_best})
    calc.sort(key=lambda x: -x['value'])
    out['calculator'] = calc

    # ---- 5. projection accuracy (finished weeks) ----
    m = jl('our_model.json', {})
    acc = []
    if m:
        prm = tuple(m['params'][k] for k in ('H', 'K', 'wF', 'wX', 'BETA'))
        prev = OP.week_rows(int(season) - 1)
        pri, rates = OP.priors(prev), OP.fit_rates(prev)
        hist = OP.Hist(rows)
        import weekly as WK
        gs = WK.Season(int(season), live=True).gs
        slp = (jl('sleeper_projections.json', {}) or {}).get('proj') or {}
        for w in range(1, done + 1):
            e_o, e_s, by = [], [], defaultdict(lambda: [[], []])
            for r in rows:
                if r['week'] != w:
                    continue
                sid = gs.get(r['pid'])
                sv = (slp.get(sid) or {}).get(str(w)) if sid else None
                if sv is None or sv < 5:
                    continue
                n, form, opp = hist.feats(r['pid'], w, prm[0])
                if n == 0 and r['pid'] not in pri:
                    continue
                ours = OP.predict(prm, r['pos'], n, form, opp, pri.get(r['pid']), rates)
                e_o.append(abs(ours - r['pts']))
                e_s.append(abs(sv - r['pts']))
                by[r['pos']][0].append(abs(ours - r['pts']))
                by[r['pos']][1].append(abs(sv - r['pts']))
            if e_o:
                acc.append({'week': w, 'n': len(e_o), 'ours': round(statistics.mean(e_o), 2), 'sleeper': round(statistics.mean(e_s), 2),
                            'by_pos': {p: [round(statistics.mean(a), 2), round(statistics.mean(b), 2)] for p, (a, b) in by.items() if a}})
    out['accuracy'] = {'weeks': acc, 'backtest_2025': {'ours': m.get('ours_mae'), 'sleeper': m.get('sleeper_mae')}}

    # ---- 6. draft capital ----
    owned = PK.owned_future_picks()
    lh = jl('lottery_history.json', {}) or {}
    cap = []
    for rid in sorted(owned):
        lst = owned[rid]
        vals = [(PK.pick_value(s, r, o)[0], s, r, o) for s, r, o in lst]
        firsts = [x for x in vals if x[2] == 1]
        best = max(vals, default=None)
        own27 = next((t for t in (lh.get('snapshots') or [{}])[-1].get('teams', {}).values() if t['team'] == names[rid]), None) if lh.get('snapshots') else None
        trend = [((s.get('teams') or {}).get(str(rid)) or {}).get('p_top3') for s in (lh.get('snapshots') or [])]
        cap.append({'owner': names[rid], 'total': round(sum(v for v, *_ in vals)), 'n': len(vals), 'firsts': len(firsts),
                    'firsts_by_year': {y: sum(1 for x in firsts if x[1] == y) for y in sorted({x[1] for x in vals})},
                    'best': (f'{best[1]} {PK._RN.get(best[2], best[2])} ({names.get(best[3])})', round(best[0])) if best else None,
                    'own_1st_top3_trend': trend, 'own_1st_owner': (own27 or {}).get('r1', {}).get('owner')})
    cap.sort(key=lambda x: -x['total'])
    out['capital'] = {'teams': cap, 'snap_days': [s['date'] for s in (lh.get('snapshots') or [])]}

    # ---- 7. long-term plan check: 2026-28 window strength per team + the trade plan scored both ways ----
    def window_total(rid, roster=None):
        r = next(x for x in R if x['roster_id'] == rid)
        ss = roster if roster is not None else (r['players'] or [])
        pl = sorted([DV.window_value(mkt(x), pos_of(x), (P.get(x) or {}).get('age')) for x in ss if pos_of(x) in LF.POS], reverse=True)[:16]
        pk = sum(PK.pick_value(se, rn, o)[0] for se, rn, o in owned.get(rid, []) if int(se) <= int(season) + 2)
        return round(sum(pl)), round(pk)
    win = sorted(({'owner': names[rid], 'players': window_total(rid)[0], 'picks': window_total(rid)[1]} for rid in names),
                 key=lambda x: -(x['players'] + x['picks']))
    plan = jl('trade_plan.json', {}) or {}
    after = list(next(r for r in R if r['roster_id'] == my_rid)['players'] or [])
    for t in plan.get('trades', []):
        after = [x for x in after if x not in t['give']] + list(t['get'])
    out['plan'] = {'window_rank': win, 'my_rank': next(i for i, x in enumerate(win, 1) if x['owner'] == me),
                   'after_players': window_total(my_rid, after)[0], 'trades': plan.get('trades', []),
                   'dynasty_total': plan.get('dynasty_total'), 'window_years': DV.WINDOW}

    json.dump(out, open(os.path.join(DATA, 'insights.json'), 'w'))
    print(f"insights -> data/insights.json: sos {len(sos)} players; efficiency {len(out['efficiency'])} owners; values {len(days)} days; "
          f"calculator {len(calc)} targets; accuracy {len(acc)} weeks; capital {len(cap)} teams")


if __name__ == '__main__':
    main()
