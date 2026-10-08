#!/usr/bin/env python3
"""Trade paths: the owner's saved trade routes, re-scored on every refresh -> data/trade_paths.json (dashboard Trades tab).

Routes live in my_trade_paths.json at the folder root (the owner's own, written by Claude in a session; see the file's
"_how"). For every route this re-simulates the season after each step (ops/trade_sim.py: live Sleeper rosters, the same
lineup optimizer and Monte Carlo the rest of the tool uses), so the odds never go stale the way typed numbers do. It also
  * flags a step whose player is no longer where the route expects him (a trade elsewhere broke the route), and
  * re-checks the king's ransom whenever a core piece (config `premium`) leaves, on the same long-term plan value the
    Trade Finder uses (dynasty_value.plan_value + plan_fit; picks via picks.pick_value).
Picks don't change this season's odds, so the simulation moves players only. No my_trade_paths.json -> nothing to do.
Added 2026-10-08 (owner request after a session of route-building).
Steps are ORDERED BY RISK (owner, 2026-10-08): dependencies first, then standalone non-core deals (biggest solo gain first), then
deals that need earlier pieces, then deals that move a core piece — so each deal that lands still helps if later ones fall through.
"""
import json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))


def sim(moves, me):
    """-> {'playoff': float, 'pts': float, 'ros': 'W-L'} for my team after these moves (None if the sim fails)."""
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'ops', 'trade_sim.py'), *moves], capture_output=True, text=True, timeout=180)
    m = re.search(rf'^\s*{re.escape(me)}\s+\S+\s+([\d.]+)/wk\s+ROS\s+(\d+-\d+)\s+playoff\s+([\d.]+)%', r.stdout, re.M)
    return {'pts': float(m.group(1)), 'ros': m.group(2), 'playoff': float(m.group(3)) / 100} if m else None


SLOT_ORDER = [('QB', {'QB'}), ('RB', {'RB'}), ('RB', {'RB'}), ('WR', {'WR'}), ('WR', {'WR'}), ('WR', {'WR'}), ('TE', {'TE'}),
              ('FLEX', {'RB', 'WR', 'TE'}), ('FLEX', {'RB', 'WR', 'TE'})]


def best_lineup(players, P, pts):
    """Greedy best lineup by slot (flex last) for {pid: points}. -> list of slot dicts."""
    pool = sorted([p for p in players if (P.get(p) or {}).get('position') in ('QB', 'RB', 'WR', 'TE')], key=lambda p: -pts.get(p, 0))
    used, lineup = set(), []
    for slot, ok in SLOT_ORDER:
        pick = next((p for p in pool if p not in used and (P.get(p) or {}).get('position') in ok), None)
        if pick:
            used.add(pick)
        lineup.append((slot, pick))
    return lineup, used


def team_view(players, P, ppg, mkt, pick_keys, PK, names, ctx):
    """Everything the "your team after" panel shows for one roster state:
    rest-of-season lineup (ppg), this week's lineup (ctx['wk']), the same roster aged to 2027 and 2028 (age curves; picks not counted),
    market and plan value, picks, and a tag per player (core / keep / tradeable)."""
    import dynasty_value as DV
    tag = lambda p: 'core' if p in ctx['core'] else 'keep' if (P.get(p) or {}).get('full_name') in ctx['keep'] else ''
    def cell(slot, p, pts):
        q = P.get(p) or {}
        return {'slot': slot, 'pid': p, 'name': q.get('full_name') if p else None, 'pos': q.get('position') if p else None,
                'age': q.get('age') if p else None, 'ppg': round(pts.get(p, 0), 1) if p else 0, 'inj': q.get('injury_status') if p else None,
                'tag': tag(p) if p else ''}
    ros, used = best_lineup(players, P, ppg)
    lineup = [cell(sl, p, ppg) for sl, p in ros]
    wk_l, _ = best_lineup(players, P, ctx['wk'])
    week_lineup = [cell(sl, p, ctx['wk']) for sl, p in wk_l]
    # aged rest-of-season points: one and two seasons on, by the measured position/age retention
    aged = {}
    for yrs in (1, 2):
        pts = {}
        for p in players:
            q = P.get(p) or {}
            v, a = ppg.get(p, 0), q.get('age')
            for _ in range(yrs):
                v *= DV.retention(q.get('position'), a)
                a = (a or 27) + 1
            pts[p] = v
        al, _ = best_lineup(players, P, pts)
        aged[yrs] = round(sum(pts.get(p, 0) for _, p in al if p), 1)
    bench = [{'pid': p, 'name': (P.get(p) or {}).get('full_name'), 'pos': (P.get(p) or {}).get('position'), 'ppg': round(ppg.get(p, 0), 1),
              'tag': tag(p)} for p in sorted(players, key=lambda p: -ppg.get(p, 0))
             if p not in used and (P.get(p) or {}).get('position') in ('QB', 'RB', 'WR', 'TE')][:8]
    picks, plan_picks = [], 0.0
    for k in sorted(pick_keys):
        _, s_, r_, o_ = k.split(':')
        v, tier = PK.pick_value(s_, int(r_), int(o_))
        picks.append({'key': k, 'label': f'{s_} {tier} {PK._RN.get(int(r_), r_)} ({names.get(int(o_), o_)})', 'value': round(v)})
        plan_picks += DV.plan_value(v, None, None, s_)
    skill = [p for p in players if (P.get(p) or {}).get('position') in ('QB', 'RB', 'WR', 'TE')]
    starters = [x for x in lineup if x['pid']]
    return {'lineup': lineup, 'week_lineup': week_lineup, 'bench': bench, 'picks': picks,
            'total': round(sum(x['ppg'] for x in lineup), 1), 'week_total': round(sum(x['ppg'] for x in week_lineup), 1),
            'y2027': aged[1], 'y2028': aged[2],
            'avg_age': round(sum((x['age'] or 0) for x in starters) / max(1, len(starters)), 1),
            'value': round(sum(mkt(p) for p in skill) + sum(x['value'] for x in picks)),
            'plan_value': round(sum(DV.plan_value(mkt(p), (P.get(p) or {}).get('position'), (P.get(p) or {}).get('age')) for p in skill) + plan_picks)}


def main():
    path = os.path.join(ROOT, 'my_trade_paths.json')
    out_path = os.path.join(DATA, 'trade_paths.json')
    if not os.path.exists(path):
        json.dump({'paths': [], 'note': 'no my_trade_paths.json'}, open(out_path, 'w'))
        print('trade paths: no my_trade_paths.json — nothing to score')
        return
    spec = json.load(open(path))
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    me = cfg.get('my_username')
    season = max(d for d in os.listdir(DATA) if d.isdigit())
    P = json.load(open(os.path.join(DATA, 'players.json')))
    cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
    R = json.load(open(os.path.join(DATA, season, 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, season, 'users.json')))}
    owner_of = {}
    for r in R:
        for p in r.get('players') or []:
            owner_of[p] = U.get(r.get('owner_id'))
    by_name = {}
    for pid in owner_of:
        n = (P.get(pid) or {}).get('full_name')
        if n:
            by_name.setdefault(n, pid)
    import dynasty_value as DV
    import picks as PK
    premium = {str(k): v for k, v in (cfg.get('premium') or {}).items()}
    mkt = lambda pid: cons.get(pid, {}).get('mean_market', cons.get(pid, {}).get('mean', 0))

    def plan_player(pid, side):
        p = P.get(pid) or {}
        v = DV.plan_value(mkt(pid), p.get('position'), p.get('age'))
        return v + (DV.plan_fit(pid, p.get('position'), p.get('age'), mkt(pid), 'get')[0] if side == 'get' else 0)

    def plan_pick(key, side):
        _, s, rnd, orig = key.split(':')
        v = PK.pick_value(s, int(rnd), int(orig))[0]
        fit = DV.plan_fit(key, None, None, 0, side)[0]
        return DV.plan_value(v, None, None, s) + (fit if side == 'get' else -fit)

    base = sim([], me)
    rid_me = next((r['roster_id'] for r in R if U.get(r.get('owner_id')) == me), None)
    my_picks = {f'pick:{s_}:{r_}:{o_}' for s_, r_, o_ in PK.owned_future_picks().get(rid_me, [])}

    def order_by_risk(steps):
        """Owner's rule (owner, 2026-10-08): list a route lowest-risk first, so each deal that lands still helps if the later ones
        don't. A step that needs a player or pick another step brings in goes after it; among the rest, steps that don't move a
        core piece and don't depend on anything come first, then by what they add on their own."""
        info = []
        for i, st in enumerate(steps):
            gives_p = {n for n, f, t in st.get('players') or [] if f == me}
            gets_p = {n for n, f, t in st.get('players') or [] if t == me}
            needs = {n for n in gives_p if owner_of.get(by_name.get(n)) != me} | {k for k in st.get('give_picks') or [] if k not in my_picks}
            core = [n for n in gives_p if by_name.get(n) in premium] + [k for k in st.get('give_picks') or [] if k in premium]
            info.append({'i': i, 'st': st, 'gets': gets_p | set(st.get('get_picks') or []), 'needs': needs, 'core': core})
        for x in info:
            x['deps'] = {y['i'] for y in info if y is not x and x['needs'] & y['gets']}
            alone = None
            if not x['deps']:
                moves = [f'{n}>{t}' for n, f, t in x['st'].get('players') or []]
                r_ = sim(moves, me)
                alone = (r_['playoff'] - base['playoff']) if (r_ and base) else None
            x['alone'] = alone
            x['risk'] = ('high' if x['core'] else 'medium' if x['deps'] else 'low')
            x['why'] = ('moves a core piece — your call' if x['core'] else
                        'needs pieces from an earlier step' if x['deps'] else 'stands alone')
        done, ordered = set(), []
        rank = {'low': 0, 'medium': 1, 'high': 2}
        while len(ordered) < len(info):
            ready = [x for x in info if x['i'] not in done and x['deps'] <= done] or [x for x in info if x['i'] not in done]
            nxt = min(ready, key=lambda x: (rank[x['risk']], -(x['alone'] or 0)))
            ordered.append(nxt); done.add(nxt['i'])
        return ordered

    # rest-of-season points per week (our blended projection) and league position ranks, for the "your team after" view
    week = (json.load(open(os.path.join(DATA, 'weekly.json'))).get('week') or 1)
    ppg = {}
    for pid_, x in (json.load(open(os.path.join(DATA, 'our_projection.json'))).get('players') or {}).items():
        wk = [v for w, v in (x.get('weekly') or {}).items() if int(w) >= week]
        ppg[pid_] = sum(wk) / len(wk) if wk else 0.0
    rid_name = {r['roster_id']: U.get(r.get('owner_id')) for r in R}
    my_now = [p for p in next(r for r in R if U.get(r.get('owner_id')) == me).get('players') or []]

    def pos_ranks(holdings):
        """League rank (1 = best) of each team's starting unit by position, for a {owner: [pids]} map."""
        n_ = {'QB': 1, 'RB': 2, 'WR': 3, 'TE': 1}
        sc = {o: {pos: sum(sorted([ppg.get(p, 0) for p in ps if (P.get(p) or {}).get('position') == pos], reverse=True)[:n_[pos]]) for pos in n_}
              for o, ps in holdings.items()}
        return {pos: 1 + sum(1 for o in sc if sc[o][pos] > sc[me][pos]) for pos in n_}

    wkd = json.load(open(os.path.join(DATA, 'weekly.json'))).get('players') or {}
    try:
        keep_ = set(((json.load(open(os.path.join(ROOT, 'my_plan.json'))).get('keep_starters') or {}).get('players')) or [])
    except Exception:
        keep_ = set()
    ctx = {'wk': {p: (x.get('proj') or 0) for p, x in wkd.items()}, 'core': set(premium), 'keep': keep_}
    holdings_now = {}
    for pid_, o in owner_of.items():
        holdings_now.setdefault(o, []).append(pid_)
    before = team_view(my_now, P, ppg, mkt, my_picks, PK, rid_name, ctx)
    before['ranks'] = pos_ranks(holdings_now)
    out = {'generated': time.strftime('%Y-%m-%d %H:%M'), 'base': base, 'paths': [], 'before': before}
    for route in spec.get('paths') or []:
        ordered = order_by_risk(route.get('steps') or [])
        where = dict(owner_of)                         # who holds each player as the route plays out
        dest, steps = {}, []
        for ox in ordered:
            st = ox['st']
            issues = []
            for name, frm, to in st.get('players') or []:
                pid = by_name.get(name)
                if not pid:
                    issues.append(f'{name} is not on any roster')
                    continue
                if where.get(pid) != frm:
                    issues.append(f'{name} is on {where.get(pid) or "no roster"}, not {frm}')
                if frm == me and to != me:              # Owner's rule: no same-NFL-team + position clash, unless an RB/QB starter-backup pair
                    gp = P.get(pid) or {}
                    for q, qo in where.items():
                        qp = P.get(q) or {}
                        if qo == to and q != pid and gp.get('team') and qp.get('team') == gp.get('team') and qp.get('position') == gp.get('position'):
                            if not (gp.get('position') in ('RB', 'QB') and {gp.get('depth_chart_order'), qp.get('depth_chart_order')} == {1, 2}):
                                issues.append(f'{name} clashes with {to}\'s {qp.get("full_name")} (same NFL team and position)')
                            break
                where[pid] = to
                dest[name] = to
            # king's ransom: if a core piece leaves, does the return clear the plan-value surplus?
            ransom = None
            gives = [by_name.get(n) for n, f, t in st.get('players') or [] if f == me and by_name.get(n)]
            core_out = [g for g in gives if g in premium] + [k for k in st.get('give_picks') or [] if k in premium]
            if core_out:
                need = sum((premium[c].get('surplus', 0) if isinstance(premium[c], dict) else 0) for c in core_out)
                gets = [by_name.get(n) for n, f, t in st.get('players') or [] if t == me and by_name.get(n)]
                got = sum(plan_player(g, 'get') for g in gets) + sum(plan_pick(k, 'get') for k in st.get('get_picks') or [])
                gave = sum(plan_player(g, 'give') for g in gives) + sum(plan_pick(k, 'give') for k in st.get('give_picks') or [])
                ransom = {'core': [(P.get(c) or {}).get('full_name', c) for c in core_out], 'gain': round(got - gave), 'need': need,
                          'clears': got - gave >= need}
            moves = [f'{n}>{t}' for n, t in dest.items() if owner_of.get(by_name.get(n)) != t]
            res = sim(moves, me) if not issues else None
            mine_after = [p for p, o in where.items() if o == me]
            picks_after = (set(my_picks) | {k for ox2 in ordered[:len(steps) + 1] for k in ox2['st'].get('get_picks') or []}) \
                - {k for ox2 in ordered[:len(steps) + 1] for k in ox2['st'].get('give_picks') or []}
            hold_after = {}
            for pid_, o in where.items():
                hold_after.setdefault(o, []).append(pid_)
            view = team_view(mine_after, P, ppg, mkt, picks_after, PK, rid_name, ctx)
            view['ranks'] = pos_ranks(hold_after)
            view['in'] = [name for name, f, t in (n for ox2 in ordered[:len(steps) + 1] for n in ox2['st'].get('players') or []) if t == me and f != me]
            view['out'] = [name for name, f, t in (n for ox2 in ordered[:len(steps) + 1] for n in ox2['st'].get('players') or []) if f == me and t != me]
            view['in'] = [x for x in view['in'] if x not in view['out']]
            view['out'] = [x for x in view['out'] if x not in [n for n, f, t in (n for ox2 in ordered[:len(steps) + 1] for n in ox2['st'].get('players') or []) if t == me and f != me]]
            steps.append({'label': st.get('label'), 'issues': issues, 'ransom': ransom, 'after': res, 'team': view,
                          'risk': ox['risk'], 'risk_why': ox['why'], 'alone': ox['alone']})
        for st_ in steps:                                  # idea 1: one-line verdict per step
            t_ = st_.get('team')
            if not t_:
                continue
            bits = []
            dp = t_['total'] - before['total']
            bits.append(('Stronger now' if dp > 0.5 else 'Weaker now' if dp < -0.5 else 'About the same now') + f' ({dp:+.1f} pts/wk')
            moves_r = [f'{pos} #{before["ranks"][pos]}→#{t_["ranks"][pos]}' for pos in ('QB', 'RB', 'WR', 'TE') if before['ranks'][pos] != t_['ranks'][pos]]
            bits[-1] += (', ' + ', '.join(moves_r) if moves_r else '') + ')'
            d28 = t_['y2028'] - before['y2028']
            bits.append(('better' if d28 > 0.5 else 'worse' if d28 < -0.5 else 'about the same') + f' in 2028 ({d28:+.1f} pts/wk)')
            dv = t_['plan_value'] - before['plan_value']
            bits.append(f'plan value {dv:+,}')
            newp = [x['label'] for x in t_['picks'] if x['key'] not in {y['key'] for y in before['picks']}]
            gone = [x['label'] for x in before['picks'] if x['key'] not in {y['key'] for y in t_['picks']}]
            if newp:
                bits.append('gains ' + ', '.join(newp))
            if gone:
                bits.append('gives up ' + ', '.join(gone))
            t_['verdict'] = '; '.join(bits) + '.'
        out['paths'].append({'name': route.get('name'), 'why': route.get('why'), 'decision': route.get('decision'), 'steps': steps,
                             'max_risk': max((s_.get('risk') for s_ in steps), key=lambda r_: {'low': 0, 'medium': 1, 'high': 2}.get(r_, 0), default=None),
                             'final': next((s['after'] for s in reversed(steps) if s['after']), None),
                             'broken': any(s['issues'] for s in steps)})
    json.dump(out, open(out_path, 'w'), indent=1)
    best = max((p for p in out['paths'] if p['final']), key=lambda p: p['final']['playoff'], default=None)
    print(f"trade paths -> data/trade_paths.json: {len(out['paths'])} routes, base {base['playoff']:.0%}" if base else 'trade paths: base sim failed',
          (f"; best {best['name']} {best['final']['playoff']:.0%}" if best else ''),
          (f"; BROKEN: {[p['name'] for p in out['paths'] if p['broken']]}" if any(p['broken'] for p in out['paths']) else ''))


if __name__ == '__main__':
    main()
