#!/usr/bin/env python3
"""Missing starters study (added 2026-10-04): what a fantasy player loses or gains when regular starters are out —
his OWN offensive line, or the OPPOSING secondary and front seven.

Measured on 2019-2025 regular seasons from nflverse snap counts (who played, at what share) and weekly box scores:
  starter   = played >= 60% of his unit's snaps in most of his team's previous games (2 of 3, 3 of 4; needs 3+ games)
  absent    = a starter with no snaps in this game (inactive / didn't play — the case a pre-game report can forecast)
  groups    = own OL (T, G, C) · opposing DB (CB, S, FS, SS, DB) · opposing FRONT (DE, DT, NT, LB)
  buckets   = 0, 1, 2+ absent
For QB/RB/WR/TE player-games (players with 6+ games and 5+ PPR a game that season), expected points = the player's
average over his OTHER games that season; the effect of a bucket = actual/expected there, relative to the 0-absent
bucket, shrunk toward no effect by n/(n+300) like the weather study. Fit on 2019-2024, then tested on 2025: does
multiplying in the effects shrink the error? The verdict is saved, and ops/absence.py only applies effects that
passed (use: true).

Writes data/absence_effects.json. Skips when that file exists; rerun with --force once a season (or when a season
of data is added); ~1 minute, plus a one-time download of any season files not yet cached.
"""
import csv, json, os, sys, time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
SEASONS = list(range(2019, 2026))
FIT, TEST = SEASONS[:-1], SEASONS[-1:]
OL, DB, FRONT = {'T', 'G', 'C', 'OT', 'OG', 'OL'}, {'CB', 'S', 'FS', 'SS', 'DB'}, {'DE', 'DT', 'NT', 'LB', 'OLB', 'ILB', 'MLB', 'EDGE', 'DL'}
FIX = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA'}
SHRINK = 300
bucket = lambda n: '2+' if n >= 2 else str(n)
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usage import grab  # noqa: E402


def cached(kind, season):
    """Path to a past season's nflverse file, downloaded once if this machine doesn't have it yet."""
    name = f'{kind}_{season}.csv'
    folder = 'stats_player' if kind == 'stats_player_week' else kind
    p = grab(f'{REL}/{folder}/{name}', os.path.join(CACHE, name), max_age=10**9)
    if not p:
        sys.exit(f'absence_study: could not download {name} from nflverse')
    return p


def absences(season):
    """{(team, week): {'ol': n, 'db': n, 'front': n}} for one regular season."""
    rows = [r for r in csv.DictReader(open(cached('snap_counts', season), encoding='utf-8'))
            if r['game_type'] == 'REG' and r['week'].isdigit()]
    by_team = defaultdict(lambda: defaultdict(dict))          # team -> week -> {pfr_id: (pos, off_pct, def_pct)}
    for r in rows:
        t = FIX.get(r['team'], r['team'])
        by_team[t][int(r['week'])][r['pfr_player_id']] = (r['position'], float(r['offense_pct'] or 0), float(r['defense_pct'] or 0))
    out = {}
    for t, weeks in by_team.items():
        order = sorted(weeks)
        for i, w in enumerate(order):
            prev = order[max(0, i - 4):i]
            if len(prev) < 3:
                continue
            cnt = {'ol': 0, 'db': 0, 'front': 0}
            seen = defaultdict(int)
            pos_of = {}
            for pw in prev:
                for pid, (pos, op, dp) in weeks[pw].items():
                    pct = op if pos in OL else dp
                    if pct >= 0.6:
                        seen[pid] += 1; pos_of[pid] = pos
            for pid, k in seen.items():
                if k >= -(-3 * len(prev) // 5) and pid not in weeks[w]:     # 60%+ in most recent games: 2 of 3, 3 of 4
                    g = 'ol' if pos_of[pid] in OL else 'db' if pos_of[pid] in DB else 'front' if pos_of[pid] in FRONT else None
                    if g:
                        cnt[g] += 1
            out[(t, w)] = cnt
    return out


def player_games(season):
    rows = [r for r in csv.DictReader(open(cached('stats_player_week', season), encoding='utf-8'))
            if r.get('season_type', 'REG') == 'REG' and r['position'] in ('QB', 'RB', 'WR', 'TE')]
    by_p = defaultdict(list)
    for r in rows:
        by_p[r['player_id']].append((int(r['week']), FIX.get(r['team'], r['team']), FIX.get(r['opponent_team'], r['opponent_team']),
                                     r['position'], float(r['fantasy_points_ppr'] or 0)))
    out = []
    for pid, g in by_p.items():
        if len(g) < 6:
            continue
        tot = sum(x[4] for x in g)
        if tot / len(g) < 5:
            continue
        for w, t, o, pos, pts in g:
            out.append((w, t, o, pos, pts, (tot - pts) / (len(g) - 1)))
    return out


def fit(seasons):
    acc = defaultdict(lambda: [0.0, 0.0, 0])                   # (pos, group, bucket) -> [actual, expected, n]
    for s in seasons:
        ab = absences(s)
        for w, t, o, pos, pts, exp in player_games(s):
            own, opp = ab.get((t, w)), ab.get((o, w))
            if own is None or opp is None:
                continue
            for grp, n in (('own_ol', own['ol']), ('opp_db', opp['db']), ('opp_front', opp['front'])):
                a = acc[(pos, grp, bucket(n))]
                a[0] += pts; a[1] += exp; a[2] += 1
    eff = {}
    for pos in ('QB', 'RB', 'WR', 'TE'):
        for grp in ('own_ol', 'opp_db', 'opp_front'):
            base = acc[(pos, grp, '0')]
            if not base[1]:
                continue
            r0 = base[0] / base[1]
            for b in ('1', '2+'):
                a = acc[(pos, grp, b)]
                if not a[1]:
                    continue
                raw = (a[0] / a[1]) / r0
                k = a[2] / (a[2] + SHRINK)
                eff.setdefault(pos, {}).setdefault(grp, {})[b] = {'mult': round(1 + k * (raw - 1), 4), 'raw': round(raw, 4), 'n': a[2]}
    return eff


def mult(eff, pos, own_ol, opp_db, opp_front, use=None):
    m = 1.0
    for grp, n in (('own_ol', own_ol), ('opp_db', opp_db), ('opp_front', opp_front)):
        if n and (use is None or use.get(grp)):
            m *= (((eff.get(pos) or {}).get(grp) or {}).get(bucket(n)) or {}).get('mult', 1.0)
    return m


def test(eff, seasons):
    """MAE of expected vs expected x effect, per group, on held-out seasons."""
    res = defaultdict(lambda: [0.0, 0.0, 0])
    for s in seasons:
        ab = absences(s)
        for w, t, o, pos, pts, exp in player_games(s):
            own, opp = ab.get((t, w)), ab.get((o, w))
            if own is None or opp is None:
                continue
            for grp, args in (('own_ol', (own['ol'], 0, 0)), ('opp_db', (0, opp['db'], 0)), ('opp_front', (0, 0, opp['front']))):
                if not any(args):
                    continue
                r = res[grp]
                r[0] += abs(pts - exp); r[1] += abs(pts - exp * mult(eff, pos, *args)); r[2] += 1
    return {g: {'n': r[2], 'mae_without': round(r[0] / r[2], 4), 'mae_with': round(r[1] / r[2], 4),
                'use': r[1] < r[0]} for g, r in res.items() if r[2]}


def main():
    if os.path.exists(os.path.join(DATA, 'absence_effects.json')) and '--force' not in sys.argv:
        print('missing-starters study: data/absence_effects.json already built (historical, fixed) — skip; --force to redo')
        return
    t0 = time.time()
    eff_fit = fit(FIT)
    verdict = test(eff_fit, TEST)
    eff_all = fit(SEASONS)                      # final effects use every season; the use flags come from the holdout
    use = {g: v['use'] for g, v in verdict.items()}
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'), 'seasons': [SEASONS[0], SEASONS[-1]], 'fit': FIT, 'test': TEST,
               'shrink': SHRINK, 'effects': eff_all, 'holdout': verdict, 'use': use},
              open(os.path.join(DATA, 'absence_effects.json'), 'w'), indent=1)
    print(f'missing-starters study -> data/absence_effects.json ({time.time() - t0:.0f}s)')
    for pos, g in eff_all.items():
        print('  ' + pos + ': ' + ' · '.join(f'{grp} ' + ', '.join(f'{b}: {v["mult"]:.3f} (n={v["n"]})' for b, v in bs.items()) for grp, bs in g.items()))
    for g, v in verdict.items():
        print(f'  holdout {TEST[0]} {g}: MAE {v["mae_without"]} -> {v["mae_with"]} on {v["n"]} player-games -> {"USE" if v["use"] else "do not use"}')


if __name__ == '__main__':
    main()
