#!/usr/bin/env python3
"""Next Gen Stats: does the NFL's player-tracking data see a breakout (or a fade) before the box score does?
(added 2026-10-04)

Source: nflverse's Next Gen Stats files (free; updated weekly in season, back to 2016) —
  receivers / TEs: avg_separation (yards of space at the catch point), avg_yac_above_expectation,
                   percent_share_of_intended_air_yards
  running backs:   rush_yards_over_expected_per_att (yards beyond what the blocking and defenders predicted)
  quarterbacks:    completion_percentage_above_expectation, avg_time_to_throw

Test, not trust, on two horizons, each season 2019-2025 held out in turn (the fit never sees the season it is scored on):
  rest of season  first K weeks' points per game (K = weeks played so far this season) -> weeks K+1..17
  next season     full-season points per game -> next season's (the dynasty question)
each with and without the volume-weighted metric (straight-line fit). A metric is used only if it cuts the held-out
error by at least 0.5%, on at least 200 held-out player-seasons. For this season's players the
kept metrics give a rest-of-season estimate; the gap between it and the points-only estimate is the "tracking lift".
A lift of +1 point a game or more = the tracking data says he's better than his box score (buy-low watch); -1 or worse
= worse than his box score (sell-high watch).

Writes data/ngs.json. Stdlib only (the fit is solved by hand).
"""
import csv, gzip, json, os, sys, time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
BASE = 'https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats'
SEASONS = list(range(2019, 2026))      # each held out in turn (leave-one-season-out); the fit never sees its test season
METRICS = {  # (file, column, volume column, positions)
    'separation': ('receiving', 'avg_separation', 'targets', ('WR', 'TE')),
    'yac_over_exp': ('receiving', 'avg_yac_above_expectation', 'receptions', ('WR', 'TE', 'RB')),
    'air_yards_share': ('receiving', 'percent_share_of_intended_air_yards', 'targets', ('WR', 'TE')),
    'ryoe_per_att': ('rushing', 'rush_yards_over_expected_per_att', 'rush_attempts', ('RB',)),
    'cpoe': ('passing', 'completion_percentage_above_expectation', 'attempts', ('QB',)),
    'time_to_throw': ('passing', 'avg_time_to_throw', 'attempts', ('QB',)),
}
LIFT = 1.0


def grab(kind):
    p = os.path.join(CACHE, f'ngs_{kind}.csv.gz')
    if not (os.path.exists(p) and os.path.getsize(p) > 10000 and time.time() - os.path.getmtime(p) < 12 * 3600):
        import subprocess
        subprocess.run(['curl', '-sL', '--max-time', '120', '-o', p + '.tmp', f'{BASE}/ngs_{kind}.csv.gz'], check=False)
        try:
            gzip.open(p + '.tmp', 'rt').readline()
            os.replace(p + '.tmp', p)
        except Exception:
            pass                                                  # keep the previous copy
    return [r for r in csv.DictReader(gzip.open(p, 'rt', encoding='utf-8'))
            if r['season_type'] == 'REG' and r['week'].isdigit() and int(r['week']) > 0] if os.path.exists(p) else []


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def solve(X, y):
    """Least squares via the normal equations (Gaussian elimination)."""
    k = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(k)] + [sum(r[i] * t for r, t in zip(X, y))] for i in range(k)]
    for c in range(k):
        piv = max(range(c, k), key=lambda r: abs(A[r][c]))
        A[c], A[piv] = A[piv], A[c]
        if abs(A[c][c]) < 1e-12:
            return [0.0] * k
        for r in range(k):
            if r != c:
                f = A[r][c] / A[c][c]
                A[r] = [a - f * b for a, b in zip(A[r], A[c])]
    return [A[i][k] / A[i][i] for i in range(k)]


def weekly_points(season):
    p = os.path.join(CACHE, f'stats_player_week_{season}.csv')
    out = defaultdict(dict)
    if not os.path.exists(p):         # a new install has no past seasons cached: fetch each once
        from usage import grab as grab_csv
        p = grab_csv(f'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv',
                     p, max_age=10**9) or p
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding='utf-8')):
            if r.get('season_type', 'REG') == 'REG' and r['week'].isdigit():
                out[r['player_id']][int(r['week'])] = (float(r['fantasy_points_ppr'] or 0), r['position'])
    return out


def metric_by_player(rows, col, vol, season, k):
    """Volume-weighted metric over weeks 1..k of one season: {gsis: value}."""
    acc = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        if r['season'] == str(season) and int(r['week']) <= k:
            v, w = num(r[col]), num(r[vol]) or 0
            if v is not None and w > 0:
                a = acc[r['player_gsis_id']]; a[0] += v * w; a[1] += w
    return {g: a[0] / a[1] for g, a in acc.items() if a[1] >= 5}


def samples(season, k, rows_by_kind, metric, only=None):
    kind, col, vol, poss = METRICS[metric]
    m = metric_by_player(rows_by_kind[kind], col, vol, season, k)
    pts = weekly_points(season)
    out = []
    for g, wk in pts.items():
        pos = next(iter(wk.values()))[1]
        if pos not in poss or g not in m or (only and pos != only):
            continue
        early = [v[0] for w, v in wk.items() if w <= k]
        late = [v[0] for w, v in wk.items() if k < w <= 17]
        if len(early) >= max(2, k - 1) and len(late) >= 4:
            out.append((sum(early) / len(early), m[g], sum(late) / len(late), pos))
    return out


def season_samples(season, rows_by_kind, metric, only=None):
    """Dynasty horizon: full-season PPG + full-season metric -> NEXT season's PPG (8+ games both years)."""
    kind, col, vol, poss = METRICS[metric]
    m = metric_by_player(rows_by_kind[kind], col, vol, season, 18)
    now, nxt = weekly_points(season), weekly_points(season + 1)
    out = []
    for g, wk in now.items():
        pos = next(iter(wk.values()))[1]
        if pos not in poss or g not in m or (only and pos != only) or len(wk) < 8 or len(nxt.get(g, {})) < 8:
            continue
        out.append((sum(v[0] for v in wk.values()) / len(wk), m[g], sum(v[0] for v in nxt[g].values()) / len(nxt[g]), pos))
    return out


def evaluate(by_season):
    """by_season: {season: samples}. Leave-one-season-out MAE, points-only vs points + metric."""
    res = {}
    seasons = [y for y, s in by_season.items() if s]
    err0 = err1 = n = 0
    for y in seasons:
        tr = [s for z in seasons if z != y for s in by_season[z]]
        te = by_season[y]
        if len(tr) < 60:
            continue
        b0 = solve([[1, e] for e, _, _, _ in tr], [l for _, _, l, _ in tr])
        b1 = solve([[1, e, x] for e, x, _, _ in tr], [l for _, _, l, _ in tr])
        err0 += sum(abs(l - (b0[0] + b0[1] * e)) for e, _, l, _ in te)
        err1 += sum(abs(l - (b1[0] + b1[1] * e + b1[2] * x)) for e, x, l, _ in te)
        n += len(te)
    if n < 60:
        return None
    allr = [s for y in seasons for s in by_season[y]]
    b0 = solve([[1, e] for e, _, _, _ in allr], [l for _, _, l, _ in allr])
    b1 = solve([[1, e, x] for e, x, _, _ in allr], [l for _, _, l, _ in allr])
    m0, m1 = err0 / n, err1 / n
    x_mean = sum(x for _, x, _, _ in allr) / len(allr)
    return {'n': n, 'x_mean': round(x_mean, 4), 'mae_points_only': round(m0, 3), 'mae_with_metric': round(m1, 3), 'gain_pct': round(100 * (m0 - m1) / m0, 2),
            'use': (m0 - m1) / m0 >= 0.005 and n >= 200,      # small samples can't carry a metric
            'coef_points_only': [round(c, 4) for c in b0], 'coef_with': [round(c, 4) for c in b1]}


def main():
    latest = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))[-1]
    league = json.load(open(os.path.join(DATA, latest, 'league.json')))
    done = (league.get('settings') or {}).get('last_scored_leg', 0)
    season = int(latest)
    rows = {k: grab(k) for k in ('receiving', 'rushing', 'passing')}
    k = max(2, min(done or 2, 8))
    ev, ev_next = {}, {}
    for metric, (_, _, _, poss) in METRICS.items():
        for pos in poss:      # one fit per position: a TE's normal air-yards share is not a WR's
            e = evaluate({y: samples(y, k, rows, metric, pos) for y in SEASONS})
            if e:
                ev[f'{metric}|{pos}'] = e
            e = evaluate({y: season_samples(y, rows, metric, pos) for y in SEASONS[:-1]})
            if e:
                ev_next[f'{metric}|{pos}'] = e

    # this season: rostered players, points-only vs tracking-informed rest-of-season estimate
    P = json.load(open(os.path.join(DATA, 'players.json')))
    R = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, latest, 'users.json')))}
    owner = {pid: U.get(r['owner_id']) for r in R for pid in (r['players'] or [])}
    # Sleeper carries the NFL (gsis) id for only a fraction of players; nflverse's roster file maps them all
    by_gsis = {p.get('gsis_id'): pid for pid, p in P.items() if p.get('gsis_id') and pid in owner}
    rp = os.path.join(CACHE, f'roster_{season}.csv')
    if os.path.exists(rp):
        for r in csv.DictReader(open(rp, encoding='utf-8')):
            if r.get('gsis_id') and r.get('sleeper_id') in owner:
                by_gsis.setdefault(r['gsis_id'], r['sleeper_id'])
    pts = weekly_points(season)
    players = {}
    for key, e in ev.items():
        metric, only = key.split('|')
        kind, col, vol, poss = METRICS[metric]
        m = metric_by_player(rows[kind], col, vol, season, done)
        for g, val in m.items():
            pid = by_gsis.get(g)
            wk = pts.get(g) or {}
            if not pid or not wk:
                continue
            pos = next(iter(wk.values()))[1]
            if pos != only:
                continue
            early = [v[0] for w, v in wk.items() if w <= done]
            if len(early) < max(2, done - 1):
                continue
            ppg = sum(early) / len(early)
            row = players.setdefault(pid, {'name': P[pid].get('full_name'), 'pos': pos, 'team': P[pid].get('team'), 'owner': owner[pid],
                                           'ppg': round(ppg, 2), 'metrics': {}, 'lift': 0.0, 'lift_next': 0.0})
            b0, b1 = e['coef_points_only'], e['coef_with']
            lift = (b1[0] + b1[1] * ppg + b1[2] * val) - (b0[0] + b0[1] * ppg)
            en = ev_next.get(key)
            ln = None
            if en:
                c0, c1 = en['coef_points_only'], en['coef_with']
                # the next-season fit learned from FULL seasons; a few weeks of tracking data is noisier, so pull this
                # season's value toward the position average by games played (half weight at 8 games)
                vs = en['x_mean'] + (val - en['x_mean']) * len(early) / (len(early) + 8)
                ln = (c1[0] + c1[1] * ppg + c1[2] * vs) - (c0[0] + c0[1] * ppg)
            row['metrics'][metric] = {'value': round(val, 3), 'lift': round(lift, 2), 'used': e['use'],
                                      'lift_next': None if ln is None else round(ln, 2), 'used_next': bool(en and en['use'])}
            if e['use']:
                row['lift'] = round(row['lift'] + lift, 2)
            if en and en['use']:
                row['lift_next'] = round(row['lift_next'] + ln, 2)
    for r in players.values():
        best = r['lift'] if abs(r['lift']) >= abs(r['lift_next']) else r['lift_next']
        r['watch'] = 'buy-low' if best >= LIFT else 'sell-high' if best <= -LIFT else ''
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'), 'weeks_used': done, 'k_tested': k, 'seasons': SEASONS,
               'evaluation': ev, 'evaluation_next_season': ev_next, 'lift_threshold': LIFT, 'players': players},
              open(os.path.join(DATA, 'ngs.json'), 'w'), indent=1)
    used = [m for m, e in ev.items() if e['use']] + [m + ' (next season)' for m, e in ev_next.items() if e['use']]
    print(f'next gen stats -> data/ngs.json: rest of season tested at {k} weeks + next season, each season held out; kept {used or "none"}; '
          f'{len(players)} rostered players scored; {sum(1 for r in players.values() if r["watch"] == "buy-low")} buy-low, '
          f'{sum(1 for r in players.values() if r["watch"] == "sell-high")} sell-high')
    for lab, E in (('rest of season', ev), ('next season', ev_next)):
        for m, e in E.items():
            print(f'  {lab} · {m}: MAE {e["mae_points_only"]} -> {e["mae_with_metric"]} ({e["gain_pct"]:+.1f}%, n={e["n"]}) {"USE" if e["use"] else "no"}')


if __name__ == '__main__':
    main()
