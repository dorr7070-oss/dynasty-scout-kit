#!/usr/bin/env python3
"""Waiver / FAAB engine -> data/waivers.json, WAIVERS.md, dashboard (after weekly.py).

Owner's choice (2026-10-02). Every free agent at QB/RB/WR/TE scored three ways:
  start now   Sleeper's projections for the next 3 weeks vs the weakest starter he would replace
              in YOUR best lineup -> points per week gained (0 = would not start)
  rising      usage moving before the market: snap share trend (last 3 vs season), route share,
              red-zone / goal-line share, target share — the leading indicators from usage_adv.py
  stash       dynasty market value, age 24 or younger first
Bid guide from THIS league's FAAB history (every winning bid over $0 on record): a would-start add
-> the league's 75th-percentile winning bid, a stash -> the median, depth -> $0-1, all capped by
your remaining budget and the share of the season left. Names the drop that costs least
(lowest value + projection on your active roster, never a starter or a config "premium"/"untouchable" asset).
"""
import json, os, statistics, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import weekly as W  # noqa: E402


def main():
    P = json.load(open(os.path.join(DATA, 'players.json')))
    season = max(d for d in os.listdir(DATA) if d.isdigit())
    R = json.load(open(os.path.join(DATA, season, 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, season, 'users.json')))}
    L = json.load(open(os.path.join(DATA, season, 'league.json')))
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    me = cfg.get('my_username')
    fence = set(cfg.get('untouchable') or []) | set((cfg.get('premium') or {}).keys())   # never suggested as a drop
    rostered = {pid for r in R for pid in (r.get('players') or [])}
    my = next(r for r in R if U.get(r.get('owner_id')) == me)
    cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
    usage = json.load(open(os.path.join(DATA, 'usage.json'))) if os.path.exists(os.path.join(DATA, 'usage.json')) else {}
    wk = json.load(open(os.path.join(DATA, 'weekly.json'))) if os.path.exists(os.path.join(DATA, 'weekly.json')) else {}
    week = wk.get('week') or 1
    reg_end = (LF.PROFILE.get('playoff_week_start') or 15) - 1

    # next-3-week Sleeper projections (all players), byes excluded from the average
    proj = {}
    for w in range(week, min(week + 3, reg_end + 1)):
        for pid, v in W.sleeper_week(int(season), w).items():
            proj.setdefault(pid, []).append(v)
    ros = {pid: statistics.mean(v) for pid, v in proj.items() if v}
    val = lambda pid: round(cons.get(pid, {}).get('mean_market', cons.get(pid, {}).get('mean', 0)))

    # my lineup baseline on the same projections
    active = [p for p in my['players'] if p not in (my.get('taxi') or []) and p not in (my.get('reserve') or [])
              and P.get(p, {}).get('position') in LF.POS]
    base, starters = LF.best_lineup_ids((ros.get(p, 0), p, P[p]['position']) for p in active)

    def gain(pid):
        pos = P[pid]['position']
        tot, _ = LF.best_lineup_ids([(ros.get(p, 0), p, P[p]['position']) for p in active] + [(ros.get(pid, 0), pid, pos)])
        return tot - base

    _tp = os.path.join(DATA, 'trending.json')
    TR = json.load(open(_tp)).get('players', {}) if os.path.exists(_tp) else {}
    fa = []
    for pid, p in P.items():
        if pid in rostered or p.get('position') not in LF.POS or not p.get('team') or p.get('status') not in ('Active', None):
            continue
        if ros.get(pid, 0) < 3 and val(pid) < 300:
            continue
        u = usage.get(pid) or {}
        rise = 0.0
        if p['position'] != 'QB' or LF.SUPERFLEX:                     # a free-agent QB only matters in superflex
            rise += max(0, (u.get('snap_trend') or 0)) * 10            # +10 pts of snap share = 1
            rise += (u.get('target_share') or 0) * 8                   # 15% of targets = 1.2
            rise += ((u.get('rz_tgt_share') or 0) + (u.get('rz_carry_share') or 0) + (u.get('gl_carry_share') or 0)) * 3
            rise += max(0, (u.get('route_pct_est') or 0) - 0.5) * 2    # a real route role, not just snaps
        fa.append({'pid': pid, 'name': p.get('full_name'), 'pos': p['position'], 'team': p['team'], 'age': p.get('age'),
                   'ros': round(ros.get(pid, 0), 1), 'gain': round(gain(pid), 1), 'value': val(pid),
                   'snap': u.get('snap_pct'), 'snap_trend': u.get('snap_trend'), 'tgt_share': u.get('target_share'),
                   'route': u.get('route_pct_est'), 'rz': (u.get('rz_tgt_share') or 0) + (u.get('rz_carry_share') or 0),
                   'rise': round(rise, 2), 'injury': p.get('injury_status'),
                   'adds_24h': (TR.get(pid) or {}).get('add_24h', 0), 'drops_24h': (TR.get(pid) or {}).get('drop_24h', 0)})

    # this league's FAAB market
    bids = []
    for y in sorted(d for d in os.listdir(DATA) if d.isdigit()):
        tp = os.path.join(DATA, y, 'transactions.json')
        for t in json.load(open(tp)) if os.path.exists(tp) else []:
            b = (t.get('settings') or {}).get('waiver_bid')
            if t['type'] == 'waiver' and t['status'] == 'complete' and b:
                add = next(iter(t.get('adds') or {}), None)
                bids.append((b, y, P.get(add, {}).get('full_name', add)))
    amounts = sorted(b for b, _, _ in bids)
    pctl = lambda q: amounts[min(len(amounts) - 1, int(len(amounts) * q))] if amounts else 1
    budget = (L['settings'].get('waiver_budget') or 100) - (my['settings'].get('waiver_budget_used') or 0)
    season_left = max(0.15, (reg_end - week + 1) / reg_end)

    def bid(x):
        # 100k+ Sleeper adds in 24h = the whole fantasy world saw the news; expect competition here too (a rule:
        # there is no history of trending counts to measure it against) -> one tier up
        hot = x.get('adds_24h', 0) >= 100_000
        if x['gain'] >= 2:
            b = pctl(0.9 if hot else 0.75)
        elif x['gain'] > 0 or x['value'] >= 1500:
            b = pctl(0.75 if hot else 0.5)
        elif hot:
            b = pctl(0.5)
        else:
            return 0
        return int(min(budget * 0.5, max(1, round(b * (0.6 + 0.4 * season_left)))))

    start = sorted([x for x in fa if x['gain'] > 0.3], key=lambda x: -x['gain'])[:10]
    rising = sorted([x for x in fa if x['rise'] >= 1.2 and x not in start], key=lambda x: -x['rise'])[:10]
    stash = sorted([x for x in fa if x['value'] >= 600 and (x['age'] or 30) <= 24], key=lambda x: -x['value'])[:8]
    for x in start + rising + stash:
        x['bid'] = bid(x)
    keep = set(starters) | fence
    drops = sorted([p for p in active if p not in keep],
                   key=lambda p: val(p) + 60 * ros.get(p, 0))[:3]
    out = {'week': week, 'generated': time.strftime('%Y-%m-%d %H:%M'), 'budget_left': budget,
           'faab': {'n': len(amounts), 'median': pctl(0.5), 'p75': pctl(0.75), 'p90': pctl(0.9),
                    'max': amounts[-1] if amounts else 0, 'top': sorted(bids, reverse=True)[:5]},
           'start': start, 'rising': rising, 'stash': stash,
           'drop': [{'pid': p, 'name': P[p].get('full_name'), 'value': val(p), 'ros': round(ros.get(p, 0), 1)} for p in drops]}
    json.dump(out, open(os.path.join(DATA, 'waivers.json'), 'w'), indent=1)

    f = lambda v: '—' if v is None else f'{v:.0%}'
    trend = lambda x: '—' if x['snap_trend'] is None else f"{round(x['snap_trend'] * 100):+d}" 
    M = [f'# Waivers & FAAB — week {week}', '',
         f"_Budget left: ${budget}. This league's winning bids over $0 ({len(amounts)} on record): median ${pctl(0.5)}, "
         f"75th pct ${pctl(0.75)}, 90th ${pctl(0.9)}, max ${out['faab']['max']}. Biggest: "
         + ', '.join(f'{n} ${b} ({y})' for b, y, n in out['faab']['top']) + '._', '',
         '## Would start for you (next 3 weeks, Sleeper projections)', '',
         '| Player | Proj/wk | Gain/wk | Snap | Trend | Value | Bid |', '|---|---|---|---|---|---|---|']
    M += [f"| {x['name']} ({x['pos']} {x['team']}){' — ' + x['injury'] if x['injury'] else ''} | {x['ros']} | +{x['gain']} | "
          f"{f(x['snap'])} | {trend(x)} | {x['value']:,} | ${x['bid']} |"
          for x in start] or ['| None — no free agent beats your current starters | | | | | | |']
    M += ['', '## Rising usage (leading indicators — buy before the market does)', '',
          '| Player | Snap | Trend | Routes | Tgt share | RZ share | Proj/wk | Bid |', '|---|---|---|---|---|---|---|---|']
    M += [f"| {x['name']} ({x['pos']} {x['team']}) | {f(x['snap'])} | {trend(x)} | "
          f"{f(x['route'])} | {f(x['tgt_share'])} | {f(x['rz'])} | {x['ros']} | ${x['bid']} |" for x in rising] or ['| — | | | | | | | |']
    M += ['', '## Dynasty stashes (24 and under)', '', '| Player | Age | Value | Proj/wk | Bid |', '|---|---|---|---|---|']
    M += [f"| {x['name']} ({x['pos']} {x['team']}) | {x['age']} | {x['value']:,} | {x['ros']} | ${x['bid']} |" for x in stash] or ['| — | | | | |']
    M += ['', '## If you need a roster spot, cheapest drops', '']
    M += [f"- {d['name']} (value {d['value']:,}, {d['ros']} proj/wk)" for d in out['drop']]
    open(os.path.join(ROOT, 'WAIVERS.md'), 'w').write('\n'.join(M) + '\n')
    print(f"waivers -> WAIVERS.md: {len(start)} would-start adds"
          + (f" (best {start[0]['name']} +{start[0]['gain']}/wk, bid ${start[0]['bid']})" if start else '')
          + f", {len(rising)} rising, {len(stash)} stashes; budget ${budget}; league median bid ${pctl(0.5)}")


if __name__ == '__main__':
    main()
