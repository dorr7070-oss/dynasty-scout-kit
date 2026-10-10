#!/usr/bin/env python3
"""Hot corners vs hot receivers -> data/coverage.json (read by ops/weekly.py).

Owner's request 2026-10-09: rate receivers against the cornerbacks they face, not just the defense as a whole
(the week-5 Thursday game: Bucs held CeeDee Lamb to 2 catches for 9 yards on 5 targets).

Source: Pro Football Reference per-defender coverage, weekly (nflverse pfr_advstats/advstats_week_def_<season>.csv):
targets, yards allowed and passer rating allowed for every defender. Positions come from the nflverse roster (pfr_id).

  corner grade  a CB's yards allowed per target to date, shrunk toward the league CB mean (k = 30 targets), so one
                good afternoon on 4 targets doesn't make a lockdown corner. Last 3 weeks shown beside it ("hot").
  defense       its best CB (min 15 targets to date) and its weakest regular CB: 'lockdown' when the best CB grades
                in the league's top fifth, 'soft' when even its best CB grades in the bottom fifth, else 'average'.
  receiver      WR1 = his team's top WR by target share to date (>= 20%); everyone else WR2+.
  effect        MEASURED, never assumed: on last season, actual PPR points / Sleeper's projection for each
                (receiver role, defense tier) bucket, divided by the same ratio for all WRs. Applied in weekly.py
                like every other condition: 1 + (effect - 1) x n / (n + 300).

  python3 ops/coverage.py           study last season + grade this season's corners -> data/coverage.json
"""
import csv, json, os, statistics, sys, time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
from weekly import BASE, fetch, num, sleeper_week  # noqa: E402

ADV = 'https://github.com/nflverse/nflverse-data/releases/download/pfr_advstats/advstats_week_def_{}.csv'
K_CB, MIN_TGT, TOP_SHARE, HOT_YPT = 30, 15, 0.20, 5.0
# HOT_YPT chosen on 2025 (swept 4.5-6.0; 5.0 sharpest), then checked out of sample on 2024 — see data/coverage.json 'study'


def nv(kind, season):
    """Local path to an nflverse roster/stats file, downloading it if missing (a fresh kit install has none)."""
    url = {'roster': f'{BASE}/rosters/roster_{season}.csv', 'stats': f'{BASE}/stats_player/stats_player_week_{season}.csv'}[kind]
    name = {'roster': f'roster_{season}.csv', 'stats': f'stats_player_week_{season}.csv'}[kind]
    current = season >= int(time.strftime('%Y'))
    return fetch(url, os.path.join(CACHE, name), 6 * 3600 if current else 365 * 86400)


def load(season):
    p = fetch(ADV.format(season), os.path.join(CACHE, f'advstats_def_{season}.csv'), 6 * 3600)
    rows = list(csv.DictReader(open(p, encoding='utf-8'))) if p else []
    pos = {}
    rp = nv('roster', season)
    for r in csv.DictReader(open(rp, encoding='utf-8')) if rp else []:
        if r.get('pfr_id'):
            pos[r['pfr_id']] = (r.get('depth_chart_position') or r.get('position') or '')
    return [r for r in rows if r.get('game_type', 'REG') == 'REG' and pos.get(r['pfr_player_id']) == 'CB'], pos


def grades(cb_rows, before_week):
    """pfr_id -> grade dict, from games before `before_week`."""
    tot = defaultdict(lambda: {'tgt': 0, 'yds': 0, 'w': [], 'team': None, 'name': None, 'last': 0})
    for r in cb_rows:
        w = int(r['week'])
        t = num(r['def_targets']) or 0
        if w >= before_week or not t:
            continue
        g = tot[r['pfr_player_id']]
        y = num(r['def_yards_allowed']) or 0
        g['tgt'] += t
        g['yds'] += y
        g['w'].append((w, t, y))
        if w >= g['last']:
            g['last'], g['team'], g['name'] = w, r['team'], r['pfr_player_name']
    allt = sum(g['tgt'] for g in tot.values())
    mean = sum(g['yds'] for g in tot.values()) / allt if allt else 7.5
    out = {}
    for pid, g in tot.items():
        rec = sorted(g['w'])[-3:]
        rt = sum(t for _, t, _ in rec)
        out[pid] = {'name': g['name'], 'team': g['team'], 'tgt': int(g['tgt']),
                    'ypt': round((g['yds'] + K_CB * mean) / (g['tgt'] + K_CB), 2),
                    'raw_ypt': round(g['yds'] / g['tgt'], 1),
                    'last3_ypt': round(sum(y for _, _, y in rec) / rt, 1) if rt else None, 'last3_tgt': int(rt)}
    return out, mean


def defenses(gr):
    """team -> {'tier', 'best', 'weak'}; tiers cut at the league's top/bottom fifth of qualified CBs."""
    by = defaultdict(list)
    for x in gr.values():
        if x['tgt'] >= MIN_TGT:
            by[x['team']].append(x)
    if len(by) < 20:
        return {}
    q = sorted(min(x['ypt'] for x in cbs) for cbs in by.values())     # each defense's BEST corner
    lo, hi = q[len(q) // 5 - 1], q[-(len(q) // 5)]
    out = {}
    for t, cbs in by.items():
        best, weak = min(cbs, key=lambda x: x['ypt']), max(cbs, key=lambda x: x['ypt'])
        tier = 'lockdown' if best['ypt'] <= lo else 'soft' if best['ypt'] >= hi else 'average'
        # hot = the best corner's last 3 games allowed under HOT_YPT yards per target on 8+ targets
        hot = best['last3_ypt'] is not None and best['last3_tgt'] >= 8 and best['last3_ypt'] < HOT_YPT
        out[t] = {'tier': tier, 'hot': hot, 'best': best, 'weak': weak if weak is not best else None}
    return out


def wr_roles(stats, before_week):
    """(gsis player_id) -> 'WR1'/'WR2+', by target share to date among his team's WRs."""
    sh = defaultdict(lambda: [0.0, 0])
    team = {}
    for r in stats:
        if r['position'] != 'WR' or int(r['week']) >= before_week:
            continue
        s = num(r.get('target_share'))
        if s is None:
            continue
        sh[r['player_id']][0] += s
        sh[r['player_id']][1] += 1
        team[r['player_id']] = r['team']
    avg = {p: s / n for p, (s, n) in sh.items() if n >= 2}
    top = {}
    for p, a in avg.items():
        t = team[p]
        if a >= TOP_SHARE and a > top.get(t, (None, 0))[1]:
            top[t] = (p, a)
    return {p: ('WR1' if top.get(team[p], (None,))[0] == p else 'WR2+') for p in avg}, avg


def hot_wr(by_week, week):
    """A receiver is hot when his last 3 games average 20%+ above his season to date (4+ games)."""
    prev = [by_week[w] for w in sorted(by_week) if w < week]
    return len(prev) >= 4 and sum(prev[-3:]) / 3 >= 1.2 * sum(prev) / len(prev)


def study(season):
    cb, _ = load(season)
    sp, rp = nv('stats', season), nv('roster', season)
    if not sp or not rp:
        return {'season': season, 'error': 'nflverse files unavailable', 'effects': {}, 'n': 0, 'all_wr_actual_vs_sleeper': 0}
    stats = list(csv.DictReader(open(sp, encoding='utf-8')))
    gs = {r['gsis_id']: r['sleeper_id'] for r in csv.DictReader(open(rp, encoding='utf-8')) if r.get('sleeper_id')}
    buckets = defaultdict(lambda: [0.0, 0.0, 0])
    allw = [0.0, 0.0, 0]
    ppr = defaultdict(dict)
    for r in stats:
        if r['position'] == 'WR':
            ppr[r['player_id']][int(r['week'])] = num(r['fantasy_points_ppr']) or 0
    for week in range(4, 18):
        D = defenses(grades(cb, week)[0])
        roles, _ = wr_roles(stats, week)
        sl = sleeper_week(season, week)
        for r in stats:
            if int(r['week']) != week or r['position'] != 'WR' or r.get('season_type', 'REG') != 'REG':
                continue
            sid = gs.get(r['player_id'])
            proj = sl.get(sid) if sid else None
            if not proj or proj < 5 or r['player_id'] not in roles or r['opponent_team'] not in D:
                continue
            act = num(r['fantasy_points_ppr']) or 0
            d = D[r['opponent_team']]
            role = roles[r['player_id']]
            hc = 'hot corner' if d['hot'] else 'no hot corner'
            ks = [f"{role}|{d['tier']}", f"{role}|{hc}"]
            if hot_wr(ppr[r['player_id']], week):
                ks.append(f"hot WR|{hc}")
            for b in [buckets[k] for k in ks] + [allw]:
                b[0] += act
                b[1] += proj
                b[2] += 1
    base = allw[0] / allw[1] if allw[1] else 1.0
    eff = {k: {'effect': round((a / p) / base, 3) if p else 1.0, 'n': n, 'actual_vs_sleeper': round(a / p, 3) if p else None} for k, (a, p, n) in buckets.items()}
    return {'season': season, 'weeks': '4-17', 'all_wr_actual_vs_sleeper': round(base, 3), 'n': allw[2], 'effects': eff}


def main():
    seasons = sorted(int(d) for d in os.listdir(DATA) if d.isdigit())
    cur = seasons[-1]
    st = study(cur - 1)
    st['out_of_sample'] = study(cur - 2)
    cb, _ = load(cur)
    last = max((int(r['week']) for r in cb), default=0)
    gr, mean = grades(cb, last + 1)
    D = defenses(gr)
    sp = nv('stats', cur)
    stats = list(csv.DictReader(open(sp, encoding='utf-8'))) if sp else []
    roles, share = wr_roles(stats, 99)
    rp = nv('roster', cur)
    gs = {r['gsis_id']: r['sleeper_id'] for r in csv.DictReader(open(rp, encoding='utf-8')) if r.get('sleeper_id')} if rp else {}
    hot_cbs = sorted([x for x in gr.values() if x['tgt'] >= MIN_TGT], key=lambda x: x['ypt'])
    out = {'season': cur, 'through_week': last, 'league_cb_ypt': round(mean, 2), 'study': st,
           'defenses': D, 'top_corners': hot_cbs[:15],
           'roles': {gs[p]: {'role': r, 'target_share': round(share[p], 3)} for p, r in roles.items() if p in gs}}
    json.dump(out, open(os.path.join(DATA, 'coverage.json'), 'w'), indent=1)
    print(f"coverage -> data/coverage.json: {len(gr)} CBs graded through wk {last}; "
          f"{sum(1 for d in D.values() if d['tier'] == 'lockdown')} lockdown / {sum(1 for d in D.values() if d['tier'] == 'soft')} soft defenses")
    print(f"  study {st['season']} (n={st['n']} WR games, WRs score {st['all_wr_actual_vs_sleeper']:.2f}x Sleeper overall):")
    oos = st['out_of_sample']['effects']
    for k, e in sorted(st['effects'].items()):
        o = oos.get(k, {})
        print(f"    {k:24} {st['season']} {e['effect']:.3f} n={e['n']:<4}  {st['out_of_sample']['season']} {o.get('effect', 0):.3f} n={o.get('n', 0)}")


if __name__ == '__main__':
    main()
