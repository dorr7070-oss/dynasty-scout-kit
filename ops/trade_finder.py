#!/usr/bin/env python3
"""Trade finder: concrete offers to every owner, ranked by wins added for you -> data/trade_finder.json,
TRADE_FINDER.md, dashboard (after project.py, contracts.py, lottery.py).

Owner's choice (2026-10-02): stop waiting for offers — generate them. For every other team, tests
1-for-1 and 2-for-1 packages (your players and future picks for one of theirs) and keeps the ones
that (a) add expected wins for you over the rest of the regular season and (b) the other owner has a
reason to accept.

  your side    expected wins added: your remaining schedule replayed with the swap (opponents fixed,
               Sleeper weekly projections, best legal lineup each week), each game's win chance =
               Phi(margin / 31); plus dynasty value change on OUR contract-adjusted consensus
  their side   market value change (consensus market value: what they and KTC see) and their own
               expected-wins change on their schedule. Acceptance by window:
                 contender (playoff odds >= 60%): won't lose real points (>= -0.15 wins) and gets
                   value back within 10%
                 rebuilder (<= 25%): gets market value back (>= 0); wins don't matter to them
                 middle: both, a little stricter on wins
Never offers anything in config "untouchable" or "keep" (player ids, or "pick:<season>:<round>:<orig roster>").
A 2-for-1 that would overfill their active roster is flagged ("they must drop one").
"""
import json, math, os, sys, time
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import picks as PK  # noqa: E402
from project import lineup_points  # noqa: E402

SD_MARGIN = 31.0          # SD of a weekly score difference (22 per team, as in lottery.py)
GIVE_MIN, GET_MIN = 300, 800
MAX_GIVE, MAX_GET = 16, 12


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def main():
    proj = json.load(open(os.path.join(DATA, 'projection.json')))
    PW = {pid: {int(w): v for w, v in wks.items()} for pid, wks in proj['player_weekly'].items()}
    P = json.load(open(os.path.join(DATA, 'players.json')))
    pos_of = lambda pid: (P.get(pid) or {}).get('position')
    cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
    adj = lambda pid: cons.get(pid, {}).get('mean', 0)
    mkt = lambda pid: cons.get(pid, {}).get('mean_market', cons.get(pid, {}).get('mean', 0))
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    me, fence = cfg.get('my_username'), set(cfg.get('untouchable') or []) | set(cfg.get('keep') or [])
    rosters, names = PK.rosters, {r['roster_id']: PK.rid2user.get(r['roster_id']) for r in PK.rosters}
    my_rid = next(rid for rid, n in names.items() if n == me)
    po = json.load(open(os.path.join(DATA, 'pick_odds.json'))) if os.path.exists(os.path.join(DATA, 'pick_odds.json')) else {}
    playoff = {int(k): v for k, v in (po.get('playoff') or {}).items()}
    wk_now = (json.load(open(os.path.join(DATA, 'weekly.json'))).get('week') if os.path.exists(os.path.join(DATA, 'weekly.json')) else 1) or 1
    active_limit = sum(1 for s in json.load(open(os.path.join(DATA, PK.latest, 'league.json')))['roster_positions'] if s not in ('IR',))

    def active(r):
        return [p for p in (r.get('players') or []) if p not in (r.get('taxi') or []) and p not in (r.get('reserve') or [])]
    roster = {r['roster_id']: r for r in rosters}

    def exp_wins(rid, players_):
        sched = [g for g in proj['rosters'][str(rid)]['schedule'] if g['wk'] >= wk_now]
        return sum(phi((lineup_points(players_, g['wk'], PW, pos_of) - g['opp_pts']) / SD_MARGIN) for g in sched)

    base = {rid: exp_wins(rid, [p for p in active(r) if pos_of(p) in LF.POS]) for rid, r in roster.items()}

    # my give assets: players + owned future picks, minus the fence
    mine = [p for p in active(roster[my_rid]) if pos_of(p) in LF.POS and p not in fence and adj(p) >= GIVE_MIN]
    mine = sorted(mine, key=lambda p: -adj(p))[:MAX_GIVE]
    my_picks = []
    for season, rnd, orig in PK.owned_future_picks().get(my_rid, []):
        key = f'pick:{season}:{rnd}:{orig}'
        if key in fence:
            continue
        v, tier = PK.pick_value(season, rnd, orig)
        if v >= GIVE_MIN:
            my_picks.append({'key': key, 'label': f'{season} {tier} {PK._RN.get(rnd, rnd)} ({names.get(orig)})', 'value': v})
    pick_val = {p['key']: p['value'] for p in my_picks}
    label = lambda a: (next(x['label'] for x in my_picks if x['key'] == a) if a.startswith('pick:') else P[a].get('full_name'))
    give_assets = mine + [p['key'] for p in my_picks]
    gval = lambda a: pick_val[a] if a.startswith('pick:') else adj(a)
    gmkt = lambda a: pick_val[a] if a.startswith('pick:') else mkt(a)
    gives = [(a,) for a in give_assets] + list(combinations(give_assets, 2))

    my_act = [p for p in active(roster[my_rid]) if pos_of(p) in LF.POS]
    offers = []
    for rid, r in roster.items():
        if rid == my_rid:
            continue
        theirs_act = [p for p in active(r) if pos_of(p) in LF.POS]
        gets = sorted([p for p in theirs_act if adj(p) >= GET_MIN], key=lambda p: -mkt(p))[:MAX_GET]
        po_ = playoff.get(rid, 0.5)
        window = 'contender' if po_ >= 0.6 else 'rebuilder' if po_ <= 0.25 else 'middle'
        for get in gets:
            for give in gives:
                gm = sum(gmkt(a) for a in give)
                if not (0.75 * mkt(get) <= gm <= 1.6 * mkt(get)):
                    continue                                   # not in the same value neighbourhood
                their_val = gm - mkt(get)
                if window == 'rebuilder' and their_val < 0:
                    continue                                   # a rebuilder wants value back, not a haircut
                if window == 'middle' and their_val < -0.05 * mkt(get):
                    continue
                if window == 'contender' and their_val < -0.10 * mkt(get):
                    continue
                gp = [a for a in give if not a.startswith('pick:')]
                my_after = [p for p in my_act if p not in gp] + [get]
                dw = exp_wins(my_rid, my_after) - base[my_rid]
                if dw < 0.15:
                    continue
                their_after = [p for p in theirs_act if p != get] + gp
                tdw = exp_wins(rid, their_after) - base[rid]
                if window == 'contender' and tdw < -0.15:
                    continue
                if window == 'middle' and tdw < -0.25:
                    continue
                my_val = adj(get) - sum(gval(a) for a in give)
                if my_val < -0.20 * sum(gval(a) for a in give) and dw < 0.6:
                    continue                                   # overpaying for a small bump
                full = len(gp) == 2 and len(active(r)) + 1 > active_limit
                offers.append({'partner': names[rid], 'rid': rid, 'window': window, 'playoff': round(po_, 3),
                               'give': list(give), 'give_labels': [label(a) for a in give], 'get': get,
                               'get_label': P[get].get('full_name'), 'get_pos': pos_of(get),
                               'my_wins': round(dw, 2), 'my_value': round(my_val), 'their_value': round(their_val),
                               'their_wins': round(tdw, 2), 'they_must_drop': full,
                               'score': round(10 * dw + my_val / 1000, 2)})
    offers.sort(key=lambda o: -o['score'])
    best_by_partner, seen_get = {}, set()
    for o in offers:
        if o['partner'] not in best_by_partner and o['get'] not in seen_get:
            best_by_partner[o['partner']] = o
            seen_get.add(o['get'])
    top = sorted(best_by_partner.values(), key=lambda o: -o['score'])
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'), 'from_week': wk_now, 'base_wins': round(base[my_rid], 2),
               'n_evaluated': len(offers), 'best_by_partner': top, 'top': offers[:25]},
              open(os.path.join(DATA, 'trade_finder.json'), 'w'), indent=1)

    why = {'contender': 'they keep their points while contending, and the value is close',
           'rebuilder': 'they gain market value while rebuilding', 'middle': 'value and points both hold for them'}
    M = [f'# Trade Finder — from week {wk_now}', '',
         f'_Expected wins rest of season now: {base[my_rid]:.2f}. Every 1-for-1 and 2-for-1 with each owner tested on both '
         f'schedules ({len(offers):,} passed the filters). Values: yours = contract-adjusted consensus, theirs = market. '
         f'Untouchable: {", ".join(label(a) if not a.startswith("pick:") else a for a in fence) or "none"}._', '',
         '## Best offer to each owner', '',
         '| Owner | You give | You get | +Wins you | Your value | Their value | Their wins | Why they say yes |',
         '|---|---|---|---|---|---|---|---|']
    for o in top:
        M.append(f"| {o['partner']} ({o['playoff']:.0%}) | {' + '.join(o['give_labels'])} | {o['get_label']} ({o['get_pos']}) | "
                 f"+{o['my_wins']:.2f} | {o['my_value']:+,} | {o['their_value']:+,} | {o['their_wins']:+.2f} | "
                 f"{why[o['window']]}{' · they must drop one' if o['they_must_drop'] else ''} |")
    if not top:
        M.append('| — | no offer passes both sides right now | | | | | | |')
    open(os.path.join(ROOT, 'TRADE_FINDER.md'), 'w').write('\n'.join(M) + '\n')
    print(f'trade finder -> TRADE_FINDER.md: {len(offers):,} viable offers across {len(top)} owners'
          + (f"; best: {' + '.join(top[0]['give_labels'])} for {top[0]['get_label']} ({top[0]['partner']}), "
             f"+{top[0]['my_wins']:.2f} wins" if top else ''))


if __name__ == '__main__':
    main()
