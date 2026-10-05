#!/usr/bin/env python3
"""Our own player and team projections — independent of Sleeper's (owner's ask, 2026-10-04).

Per player, per game:
  form     this season's PPR points, exponentially weighted toward recent games (half-life H games),
           shrunk toward the player's anchor by n / (n + K) games
  opp      expected points from opportunity: EWMA targets, carries and pass attempts per game, priced
           at points-per-opportunity rates fitted (least squares, by position) on the PREVIOUS season
  anchor   last season's points per game (4+ games); for players with no NFL history, an estimate
           from market value fitted on current players
  pred     = wF * form + wX * opp + (1 - wF - wX) * anchor
           x (team implied points / team's season-average implied) ^ BETA      (Vegas, nflverse lines)
           x measured extreme-weather / backup-QB multipliers                   (ops/weekly_study.py)
           x 0 for byes and for games an injured player is expected to miss     (ops/injuries.py)
Parameters (H, K, wF, wX, BETA) are fitted on 2024 and TESTED on 2025 against Sleeper's own weekly
projections for the same player-weeks — so the comparison is out of sample and honest.

Then the season: every roster's best legal lineup each remaining week from these projections, a Monte
Carlo of the rest of the regular season (same engine as ops/lottery.py) -> playoff odds, expected wins
and projected finish per team, side by side with the Sleeper-based numbers in data/pick_odds.json.

  python3 ops/our_projections.py --fit    fit on 2024, test on 2025 -> data/our_model.json
  python3 ops/our_projections.py          live: data/our_projection.json + OUR_PROJECTIONS.md
"""
import csv, json, math, os, random, statistics, sys, time
from collections import defaultdict
from itertools import product

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
HIST = os.path.join(CACHE, 'weekly_hist')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import weekly as W  # noqa: E402

POS = ('QB', 'RB', 'WR', 'TE')
MODEL = os.path.join(DATA, 'our_model.json')


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def week_rows(season):
    """All regular-season player-games for a season (gsis ids)."""
    p = os.path.join(HIST, f'week_{season}.csv')
    if not os.path.exists(p):
        p = os.path.join(CACHE, f'stats_player_week_{season}.csv')
    if not os.path.exists(p):                  # a new install has no history yet: fetch that season once
        from usage import grab
        p = grab(f'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv',
                 p, max_age=10**9)
        if not p:
            return []
    out = []
    for r in csv.DictReader(open(p, encoding='utf-8')):
        if r['season_type'] == 'REG' and r['position'] in POS:
            out.append({'pid': r['player_id'], 'pos': r['position'], 'week': int(r['week']), 'team': r['team'],
                        'gid': r['game_id'], 'pts': num(r['fantasy_points_ppr']), 'tgt': num(r['targets']),
                        'car': num(r['carries']), 'att': num(r['attempts'])})
    return out


def solve(A, b):
    """Gaussian elimination for a small dense system."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-9:
            continue
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-9 else 0.0 for i in range(n)]


def fit_rates(rows):
    """Per position: pts ~ a + bT*targets + bC*carries + bA*attempts (least squares)."""
    rates = {}
    for pos in POS:
        X = [(1.0, r['tgt'], r['car'], r['att']) for r in rows if r['pos'] == pos]
        y = [r['pts'] for r in rows if r['pos'] == pos]
        k = 4
        A = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
        bb = [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(k)]
        rates[pos] = solve(A, bb)
    return rates


def priors(rows):
    g = defaultdict(list)
    for r in rows:
        g[r['pid']].append(r['pts'])
    return {pid: sum(v) / len(v) for pid, v in g.items() if len(v) >= 4}


class Hist:
    """A player's games so far this season, for EWMA features."""

    def __init__(self, rows):
        self.by = defaultdict(list)
        for r in sorted(rows, key=lambda r: r['week']):
            self.by[r['pid']].append(r)

    def feats(self, pid, week, H):
        games = [r for r in self.by.get(pid, []) if r['week'] < week]
        if not games:
            return 0, None, None
        lam = 0.5 ** (1 / H)
        ws = [lam ** (len(games) - 1 - i) for i in range(len(games))]
        tw = sum(ws)
        ew = lambda k: sum(w * g[k] for w, g in zip(ws, games)) / tw
        return len(games), ew('pts'), (ew('tgt'), ew('car'), ew('att'))


def predict(prm, pos, n, form, opp, anchor, rates):
    H, K, wF, wX, BETA = prm
    if anchor is None:
        anchor = form if form is not None else 0.0
    a, bT, bC, bA = rates[pos]
    xfp = (a + bT * opp[0] + bC * opp[1] + bA * opp[2]) if opp else anchor
    fs = (n * form + K * anchor) / (n + K) if form is not None else anchor
    xs = (n * xfp + K * anchor) / (n + K)
    return max(0.0, wF * fs + wX * xs + (1 - wF - wX) * anchor)


GRID = [g for g in product((2, 3, 4), (0.5, 1, 2), (0.3, 0.4, 0.5, 0.6), (0.3, 0.4, 0.5, 0.6), (0.0, 0.25, 0.5))
        if g[2] + g[3] <= 1.0]   # widened 10-04: the first grid's best sat on its edges (K=1, wF+wX=0.95)


def game_ctx(S, effects):
    """(gid, team) -> (implied ratio, extremes multiplier by position) for a season."""
    out = {}
    for g in S.games:
        for team in (g['home_team'], g['away_team']):
            imp = S.implied.get((g['game_id'], team))
            ratio = imp / S.team_mean[team] if imp and S.team_mean.get(team) else 1.0
            ctx = S.team_context(g, team)
            mult = {}
            for pos in POS:
                m = 1.0
                for f, buckets in W.EXTREME.items():
                    b = ctx.get(f)
                    if b in buckets and not (f == 'backup_qb' and pos == 'QB'):
                        m *= W.mult(effects, pos, f, b)
                mult[pos] = m
            out[(g['game_id'], team)] = (ratio, mult)
    return out


def evaluate(season, prm, rows, hist, pri, rates, ctx, filt=None):
    errs = []
    for r in rows:
        if not (4 <= r['week'] <= 17):
            continue
        if filt and (r['pid'], r['week']) not in filt:
            continue
        n, form, opp = hist.feats(r['pid'], r['week'], prm[0])
        if n == 0 and r['pid'] not in pri:
            continue
        ratio, mult = ctx.get((r['gid'], r['team']), (1.0, {}))
        p = predict(prm, r['pos'], n, form, opp, pri.get(r['pid']), rates) * ratio ** prm[4] * mult.get(r['pos'], 1.0)
        r['pred'] = p
        errs.append((abs(p - r['pts']), r))
    return errs


def fit():
    effects = json.load(open(os.path.join(DATA, 'weekly_effects.json')))['effects']
    res = {}
    # train: 2024 (priors + rates from 2023)
    tr = week_rows(2024)
    S24 = W.Season(2024, live=False)
    ctx24 = game_ctx(S24, effects)
    pri24, rates24, h24 = priors(week_rows(2023)), fit_rates(week_rows(2023)), Hist(tr)
    best = min(GRID, key=lambda prm: statistics.mean(e for e, _ in evaluate(2024, prm, tr, h24, pri24, rates24, ctx24)))
    # test: 2025 vs Sleeper on identical rows
    te = week_rows(2025)
    S25 = W.Season(2025, live=False)
    ctx25 = game_ctx(S25, effects)
    pri25, rates25, h25 = priors(tr), fit_rates(tr), Hist(te)
    sl, filt = {}, set()
    for w in range(4, 18):
        for sid, v in W.sleeper_week(2025, w).items():
            sl[(sid, w)] = v
    gs = S25.gs
    for r in te:
        sid = gs.get(r['pid'])
        if sid and sl.get((sid, r['week']), 0) >= 5:
            filt.add((r['pid'], r['week']))
    ours = evaluate(2025, best, te, h25, pri25, rates25, ctx25, filt)
    slp = [abs(sl[(gs[r['pid']], r['week'])] - r['pts']) for _, r in ours]
    by_pos = {pos: (round(statistics.mean(e for e, r in ours if r['pos'] == pos), 3),
                    round(statistics.mean(abs(sl[(gs[r['pid']], r['week'])] - r['pts']) for _, r in ours if r['pos'] == pos), 3))
              for pos in POS}
    res = {'params': dict(zip(('H', 'K', 'wF', 'wX', 'BETA'), best)), 'test_season': 2025, 'weeks': '4-17',
           'n': len(ours), 'ours_mae': round(statistics.mean(e for e, _ in ours), 3), 'sleeper_mae': round(statistics.mean(slp), 3),
           'by_pos_ours_vs_sleeper': by_pos}
    # blend with Sleeper (added 2026-10-04): the two models miss in different places. Weight per position chosen on
    # 2025 weeks 4-10, judged ONLY on weeks 11-17 (never used to choose it).
    slv = lambda r: sl[(gs[r['pid']], r['week'])]
    blend, bt = {}, {}
    for pos in POS:
        tr_ = [r for _, r in ours if r['pos'] == pos and r['week'] <= 10]
        te_ = [r for _, r in ours if r['pos'] == pos and r['week'] > 10]
        if len(tr_) < 50 or len(te_) < 50:
            continue
        mae = lambda rs, w: statistics.mean(abs(w * r['pred'] + (1 - w) * slv(r) - r['pts']) for r in rs)
        w = min((i / 10 for i in range(11)), key=lambda w: mae(tr_, w))
        blend[pos] = w
        bt[pos] = {'w_ours': w, 'n_test': len(te_), 'ours': round(mae(te_, 1), 3), 'sleeper': round(mae(te_, 0), 3), 'blend': round(mae(te_, w), 3)}
    for pos, b in bt.items():   # a blend that lost on the held-out weeks is not used: keep the better single model
        if b['blend'] > min(b['ours'], b['sleeper']):
            blend[pos] = 1.0 if b['ours'] <= b['sleeper'] else 0.0
            b['kept'] = 'ours only' if blend[pos] == 1.0 else 'sleeper only'
    allte = [r for _, r in ours if r['week'] > 10 and r['pos'] in blend]

    res['blend'] = blend
    res['blend_test'] = {'weeks': '11-17 (weights chosen on 4-10)', 'by_pos': bt,
                         'ours': round(statistics.mean(abs(r['pred'] - r['pts']) for r in allte), 3),
                         'sleeper': round(statistics.mean(abs(slv(r) - r['pts']) for r in allte), 3),
                         'blend': round(statistics.mean(abs(blend[r['pos']] * r['pred'] + (1 - blend[r['pos']]) * slv(r) - r['pts']) for r in allte), 3)}
    json.dump(res, open(MODEL, 'w'), indent=1)
    bt_ = res['blend_test']
    print(f"blend test (2025 weeks 11-17, weights from 4-10): ours {bt_['ours']} · sleeper {bt_['sleeper']} · BLEND {bt_['blend']}  weights {blend}")
    print(f"our model: params {res['params']} (fitted on 2024)")
    print(f"2025 test, weeks 4-17, {res['n']:,} player-weeks Sleeper projected 5+: OURS MAE {res['ours_mae']} vs SLEEPER {res['sleeper_mae']}")
    for pos, (o, s) in by_pos.items():
        print(f'  {pos}: ours {o} vs sleeper {s}')


def live():
    m = json.load(open(MODEL))
    prm = tuple(m['params'][k] for k in ('H', 'K', 'wF', 'wX', 'BETA'))
    effects = json.load(open(os.path.join(DATA, 'weekly_effects.json')))['effects']
    season = max(int(d) for d in os.listdir(DATA) if d.isdigit())
    S = W.Season(season, live=True)
    rows = week_rows(season)
    hist = Hist(rows)
    prev = week_rows(season - 1)
    pri, rates = priors(prev), fit_rates(prev)
    gs = S.gs
    sg = {v: k for k, v in gs.items()}
    P = json.load(open(os.path.join(DATA, 'players.json')))
    cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
    R = json.load(open(os.path.join(DATA, str(season), 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, str(season), 'users.json')))}
    league = json.load(open(os.path.join(DATA, str(season), 'league.json')))
    done = (league.get('settings') or {}).get('last_scored_leg', 0)
    weeks = list(range(done + 1, LF.PLAYOFF_START))
    io = json.load(open(os.path.join(DATA, 'injury_outlook.json'))) if os.path.exists(os.path.join(DATA, 'injury_outlook.json')) else {'players': []}
    out_until = {}
    for x in io['players']:
        if x.get('status') in W.__dict__.get('OUT_STATUSES', ('Out', 'IR', 'PUP', 'Sus', 'NA', 'DNR')) or x.get('exp_more') is not None:
            more = x.get('exp_more')
            out_until[x['pid']] = 99 if (x.get('season_share_lost') or 0) >= 1.0 else (done + 1 + math.ceil(more) if more else done + 1)

    # market-value anchor for players with no NFL history: ppg ~ c * sqrt(value), per position, fitted now
    fitv = defaultdict(list)
    for sid in {sid for r in R for sid in (r.get('players') or [])}:
        g = sg.get(sid)
        if g in pri and P.get(sid, {}).get('position') in POS:
            v = cons.get(sid, {}).get('mean_market', 0)
            if v > 0:
                fitv[P[sid]['position']].append((math.sqrt(v), pri[g]))
    cv = {pos: (sum(x * y for x, y in v) / sum(x * x for x, y in v)) if v else 0.08 for pos, v in fitv.items()}

    games_by = defaultdict(dict)    # team -> week -> game row
    for g in S.games:
        for t in (g['home_team'], g['away_team']):
            games_by[t][int(g['week'])] = g
    ctx_cache = {}

    def gctx(g, team):
        k = (g['game_id'], team)
        if k not in ctx_cache:
            imp = S.implied.get(k)
            ratio = imp / S.team_mean[team] if imp and S.team_mean.get(team) else 1.0
            c = S.team_context(g, team) if int(g['week']) == weeks[0] else {}
            ctx_cache[k] = (ratio, c)
        return ctx_cache[k]

    team_played = defaultdict(int)
    for g in S.games:
        if g['home_score']:
            team_played[g['home_team']] += 1
            team_played[g['away_team']] += 1
    injured = {x['pid'] for x in io['players']}
    proj = {}
    for r in R:
        for sid in r.get('players') or []:
            p = P.get(sid, {})
            pos, team = p.get('position'), W.SLEEPER_TO_NV.get(p.get('team'), p.get('team'))
            if pos not in POS or not team:
                continue
            g_id = sg.get(sid)
            n, form, opp = hist.feats(g_id, 99, prm[0]) if g_id else (0, None, None)
            anchor = pri.get(g_id)
            if anchor is None and n == 0:
                anchor = cv.get(pos, 0.08) * math.sqrt(max(0, cons.get(sid, {}).get('mean_market', 0)))
            base = predict(prm, pos, n, form, opp, anchor, rates)
            # Hasn't played this season although his team has (2+ games), and isn't on the injury list:
            # a backup/inactive, not a starter — last season's line must not carry him (Richardson 7.2 -> ~0).
            if n == 0 and team_played.get(team, 0) >= 2 and sid not in injured:
                base *= 0.1
            wk = {}
            for w in weeks:
                g = games_by.get(team, {}).get(w)
                if not g or out_until.get(sid, 0) > w:
                    wk[w] = 0.0
                    continue
                ratio, c = gctx(g, team)
                mlt = 1.0
                for f, buckets in W.EXTREME.items():
                    b = c.get(f)
                    if b in buckets and not (f == 'backup_qb' and pos == 'QB'):
                        mlt *= W.mult(effects, pos, f, b)
                wk[w] = round(base * ratio ** prm[4] * mlt, 2)
            proj[sid] = {'name': p.get('full_name'), 'pos': pos, 'team': p.get('team'), 'base': round(base, 2),
                         'n': n, 'weekly': wk}

    # BLEND with Sleeper where the held-out test said it helps (m['blend'] = weight on ours, per position; 1.0 = ours
    # only). Injury zeros stay zero: Sleeper's number for a player we know is out is not evidence he plays.
    bw = m.get('blend') or {}
    slw = {}
    for w in weeks:
        try:
            slw[w] = W.sleeper_week(season, w)
        except Exception:
            slw[w] = {}
    for sid, x in proj.items():
        x['weekly_ours'] = dict(x['weekly'])
        x['weekly_sleeper'] = {w: round(slw[w][sid], 2) for w in weeks if sid in slw.get(w, {})}
        b = bw.get(x['pos'], 1.0)
        for w in weeks:
            o, sv = x['weekly'].get(w, 0.0), x['weekly_sleeper'].get(w)
            if o > 0 and sv is not None:
                x['weekly'][w] = round(b * o + (1 - b) * sv, 2)

    # season simulation with the BLENDED projections (same engine as lottery.py)
    from project import lineup_points
    PW = {sid: {int(w): v for w, v in x['weekly'].items()} for sid, x in proj.items()}
    pos_of = lambda s: P.get(s, {}).get('position')
    act = {r['roster_id']: [s for s in (r['players'] or []) if s not in (r.get('reserve') or []) and s not in (r.get('taxi') or [])] for r in R}
    sched = {int(k): v['schedule'] for k, v in json.load(open(os.path.join(DATA, 'projection.json')))['rosters'].items()}
    numf = lambda rr, k: rr['settings'].get(k, 0) + rr['settings'].get(k + '_decimal', 0) / 100
    W0 = {rr['roster_id']: rr['settings']['wins'] for rr in R}
    F0 = {rr['roster_id']: numf(rr, 'fpts') for rr in R}
    pts = {rid: {w: lineup_points(act[rid], w, PW, pos_of) for w in weeks} for rid in act}
    from decided import decided
    locked = decided(weeks[0]) if weeks else {}   # matchups already over in the week in progress (see decided.py)
    random.seed(11)
    N = 6000
    made, wins, place = defaultdict(int), defaultdict(float), defaultdict(float)
    for _ in range(N):
        Wn, Fp = dict(W0), dict(F0)
        for w in weeks:
            s = {rid: random.gauss(pts[rid][w], 22) for rid in act}
            if w == weeks[0]:
                s.update({rid: v for rid, v in locked.items() if rid in s})
            seen = set()
            for rid in act:
                for g in sched[rid]:
                    if g['wk'] == w and (rid, g['opp']) not in seen:
                        o = g['opp']; seen |= {(rid, o), (o, rid)}
                        Wn[rid if s[rid] > s[o] else o] += 1
            for rid in act:
                Fp[rid] += s[rid]
        seed = sorted(act, key=lambda rid: (-Wn[rid], -Fp[rid]))
        for i, rid in enumerate(seed):
            place[rid] += i + 1
            wins[rid] += Wn[rid]
            made[rid] += i < LF.PLAYOFF_TEAMS
    po = json.load(open(os.path.join(DATA, 'pick_odds.json'))) if os.path.exists(os.path.join(DATA, 'pick_odds.json')) else {}
    teams = {}
    for rid in act:
        teams[str(rid)] = {'owner': U.get(next(rr for rr in R if rr['roster_id'] == rid).get('owner_id')),
                           'record': f"{W0[rid]}-{next(rr for rr in R if rr['roster_id'] == rid)['settings']['losses']}",
                           'pts_wk': round(sum(pts[rid].values()) / max(1, len(weeks)), 1),
                           'exp_wins': round(wins[rid] / N, 2), 'exp_place': round(place[rid] / N, 2),
                           'playoff': round(made[rid] / N, 3),
                           'sleeper_playoff': (po.get('playoff') or {}).get(str(rid)),
                           'sleeper_pts_wk': (po.get('pts_wk') or {}).get(str(rid))}
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'), 'season': season, 'weeks': [weeks[0], weeks[-1]] if weeks else [],
               'model': m, 'teams': teams, 'players': proj}, open(os.path.join(DATA, 'our_projection.json'), 'w'))
    order = sorted(teams, key=lambda k: teams[k]['exp_place'])
    L = ['# Our projections (independent of Sleeper)', '',
         f"_Model fitted on 2024, tested on 2025 weeks 4-17 ({m['n']:,} player-weeks): our error {m['ours_mae']} PPR per player-week "
         f"vs Sleeper's {m['sleeper_mae']} on the same games. Remaining weeks {weeks[0]}-{weeks[-1]}, {N:,} simulated seasons._", '',
         '| Proj. finish | Team | Record | Our pts/wk | Exp. wins | Our playoff odds | Sleeper-based odds |', '|---|---|---|---|---|---|---|']
    for k in order:
        t = teams[k]
        sp = t['sleeper_playoff']
        L.append(f"| {t['exp_place']:.1f} | {t['owner']} | {t['record']} | {t['pts_wk']} | {t['exp_wins']:.1f} | {t['playoff']:.0%} | "
                 f"{'—' if sp is None else f'{sp:.0%}'} |")
    open(os.path.join(ROOT, 'OUR_PROJECTIONS.md'), 'w').write('\n'.join(L) + '\n')
    me = json.load(open(os.path.join(ROOT, 'config.json'))).get('my_username')
    mt = next((t for t in teams.values() if t['owner'] == me), None)
    print(f"our projections -> OUR_PROJECTIONS.md ({len(proj)} players, weeks {weeks[0]}-{weeks[-1]})"
          + (f"; {me}: {mt['playoff']:.0%} playoff (Sleeper-based {mt['sleeper_playoff']:.0%}), exp. finish {mt['exp_place']:.1f}" if mt and mt['sleeper_playoff'] is not None else ''))


if __name__ == '__main__':
    fit() if '--fit' in sys.argv else live()
