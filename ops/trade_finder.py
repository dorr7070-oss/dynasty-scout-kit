#!/usr/bin/env python3
"""Trade finder: concrete offers to every owner, ranked by wins added for you -> data/trade_finder.json,
TRADE_FINDER.md, dashboard (after project.py, contracts.py, lottery.py).

Owner's choice (2026-10-02): stop waiting for offers — generate them. For every other team, tests
1-for-1 and 2-for-1 packages (your players and future picks for one of theirs) and keeps the ones
that (a) add expected wins for you over the rest of the regular season and (b) the other owner has a
reason to accept.

  your side    expected wins added: your remaining schedule replayed with the swap (opponents fixed,
               Sleeper weekly projections, best legal lineup each week), each game's win chance =
               Phi(margin / 31); plus dynasty value change on neutral market value (same scale both sides)
  their side   market value change (consensus market value: what they and KTC see) and their own
               expected-wins change on their schedule. Acceptance by window:
                 contender (playoff odds >= 60%): won't lose real points (>= -0.15 wins) and gets
                   value back within 10%
                 rebuilder (<= 25%): gets market value back (>= 0); wins don't matter to them
                 middle: both, a little stricter on wins
Config "premium" {asset: multiplier} marks core assets (player ids or "pick:<season>:<round>:<orig roster>"):
they are left out of ordinary offers and priced separately as KING'S-RANSOM asks — the cheapest package of up
to 3 of each team's assets worth >= multiplier x his value (owner's rule 2026-10-02: no one is untouchable, the core
just costs a king's ransom). Config "untouchable" is still honoured as a hard no if anyone sets it.
A 2-for-1 that would overfill their active roster is flagged ("they must drop one").

--ransom-basis market|plan|season|auto (DRAFT, 2026-10-08, owner's ask: "for dynasty, the king's ransom should matter
for the owner's long-term plan; for redraft, for the current season"). Without the flag nothing changes (market).
  market  the package's MARKET value must beat the core piece's by the surplus (the 10-02 rule)
  plan    the package's LONG-TERM PLAN value (dynasty_value: window value + plan bonuses) must beat the core piece's
          by the surplus — older returns count for less, younger for more
  season  the trade must add at least {"wins": X} expected wins this season (default config "ransom_wins", 0.5)
  auto    plan for dynasty/keeper leagues, season for redraft
--out FILE writes the JSON there and skips TRADE_FINDER.md (so a draft run never touches the live report).
"""
import json, math, os, sys, time
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import picks as PK  # noqa: E402
from project import lineup_points  # noqa: E402
import dynasty_value as DV  # noqa: E402

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
    # Both sides on the same neutral market value (owner's instruction 2026-10-02: don't skew the
    # evaluation against your own team). Contract-year effects show up in expected wins and the calendar.
    adj = lambda pid: cons.get(pid, {}).get('mean_market', cons.get(pid, {}).get('mean', 0))
    mkt = lambda pid: cons.get(pid, {}).get('mean_market', cons.get(pid, {}).get('mean', 0))
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    me = cfg.get('my_username')
    fence = set(cfg.get('untouchable') or [])          # hard no (legacy / optional)
    # --as <username> (league edition, added 2026-10-05): the same search from another owner's side, NEUTRAL — none of
    # this owner's private settings (king's-ransom prices, untouchables, long-term plan bonuses) and no report files
    AS = sys.argv[sys.argv.index('--as') + 1] if '--as' in sys.argv else None
    if AS:
        me, fence = AS, set()
    # king's-ransom rules: a number = multiplier on our value; {"surplus": N} = the evaluation must favor you
    # by at least N on MARKET value (what a KTC-style calculator shows), e.g. +9,000
    premium = {} if AS else {str(k): v for k, v in (cfg.get('premium') or {}).items()}
    BASIS = sys.argv[sys.argv.index('--ransom-basis') + 1] if '--ransom-basis' in sys.argv else 'market'
    if BASIS == 'auto':
        BASIS = 'season' if str(LF.PROFILE.get('league_type') or '').lower() == 'redraft' else 'plan'
    OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
    rosters, names = PK.rosters, {r['roster_id']: PK.rid2user.get(r['roster_id']) for r in PK.rosters}
    my_rid = next(rid for rid, n in names.items() if n == me)
    po = json.load(open(os.path.join(DATA, 'pick_odds.json'))) if os.path.exists(os.path.join(DATA, 'pick_odds.json')) else {}
    playoff = {int(k): v for k, v in (po.get('playoff') or {}).items()}
    wk_now = (json.load(open(os.path.join(DATA, 'weekly.json'))).get('week') if os.path.exists(os.path.join(DATA, 'weekly.json')) else 1) or 1
    active_limit = sum(1 for s in json.load(open(os.path.join(DATA, PK.latest, 'league.json')))['roster_positions'] if s not in ('IR',))

    def active(r):
        return [p for p in (r.get('players') or []) if p not in (r.get('taxi') or []) and p not in (r.get('reserve') or [])]
    roster = {r['roster_id']: r for r in rosters}

    from decided import decided, result
    LOCK = decided(wk_now)               # games already over this week count as played, whatever the trade

    def exp_wins(rid, players_):
        sched = [g for g in proj['rosters'][str(rid)]['schedule'] if g['wk'] >= wk_now]
        out = 0.0
        for g in sched:
            r = result(LOCK, rid, g['opp'], g['wk'], wk_now)
            out += r if r is not None else phi((lineup_points(players_, g['wk'], PW, pos_of) - g['opp_pts']) / SD_MARGIN)
        return out

    base = {rid: exp_wins(rid, [p for p in active(r) if pos_of(p) in LF.POS]) for rid, r in roster.items()}

    # my give assets: players + owned future picks, minus the fence
    mine = [p for p in active(roster[my_rid]) if pos_of(p) in LF.POS and p not in fence and adj(p) >= GIVE_MIN]
    mine = sorted(mine, key=lambda p: -adj(p))[:MAX_GIVE + len(premium)]
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
    give_all = mine + [p['key'] for p in my_picks]
    give_assets = [a for a in give_all if a not in premium]     # premium assets only go in king's-ransom asks
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
                # dynasty value against the long-term plan (ops/dynasty_value.py): window value + plan bonuses
                ag = lambda a: (P.get(a) or {}).get('age')
                pk_ = lambda a: a.startswith('pick:')
                fit = (lambda *a: (0, '')) if AS else DV.plan_fit      # the plan bonuses are this owner's strategy, not theirs
                dyn = (DV.window_value(gmkt(get) if False else mkt(get), pos_of(get), ag(get)) + fit(get, pos_of(get), ag(get), mkt(get), 'get')[0]
                       - sum(DV.window_value(gmkt(a), None if pk_(a) else pos_of(a), None if pk_(a) else ag(a)) for a in give)
                       + sum(fit(a, None if pk_(a) else pos_of(a), None if pk_(a) else ag(a), gmkt(a), 'give')[0] for a in give))
                if dw < 0.15 and not (dw >= -0.2 and dyn >= 200):
                    continue                                   # neither a season upgrade nor a plan upgrade
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
                               'their_wins': round(tdw, 2), 'they_must_drop': full, 'dyn': round(dyn),
                               'score': round(10 * dw + my_val / 1000, 2)})
    offers.sort(key=lambda o: -o['score'])
    best_by_partner, seen_get = {}, set()
    for o in offers:
        if o['my_wins'] >= 0.15 and o['partner'] not in best_by_partner and o['get'] not in seen_get:
            best_by_partner[o['partner']] = o
            seen_get.add(o['get'])
    top = sorted(best_by_partner.values(), key=lambda o: -o['score'])
    # the same, ranked for the long-term plan: highest dynasty value that keeps the season (>= -0.2 wins)
    best_dyn, seen_d = {}, set()
    for o in sorted(offers, key=lambda o: (-o['dyn'], -o['my_wins'])):
        if o['partner'] not in best_dyn and o['get'] not in seen_d and o['dyn'] > 0:
            best_dyn[o['partner']] = o
            seen_d.add(o['get'])
    top_dyn = sorted(best_dyn.values(), key=lambda o: -o['dyn'])
    # ---- king's-ransom asks: what each premium asset would cost each team ----
    # A package qualifies when the value coming back (our contract-adjusted view; picks at pick_value)
    # is at least premium x the asset's value. Among qualifying 1-3 asset packages from each team
    # (their top players + their future picks): of the 30 they overpay least on, the one that adds the most
    # expected wins for you this season (ties -> the smaller overpay, the likelier to be heard).
    owned = PK.owned_future_picks()
    ransom = []
    for a in [x for x in give_all if x in premium]:
        rule = premium[a]
        surplus = rule.get('surplus') if isinstance(rule, dict) else None
        need = (gmkt(a) + surplus) if surplus is not None else float(rule) * gval(a)
        side = 2 if surplus is not None else 1          # compare on market (index 2) or our value (index 1)
        ag_ = lambda x: (P.get(x) or {}).get('age')
        def plan_val(x, s_):                            # value to the owner's plan seasons (dynasty_value.plan_value)
            if x.startswith('pick:'):                   # a pick counts only from its draft year inside the plan
                return DV.plan_value(gmkt(x) if s_ == 'give' else x_val.get(x, 0), None, None, x.split(':')[1]) \
                    + DV.plan_fit(x, None, None, 0, s_)[0] * (1 if s_ == 'get' else -1)
            return DV.plan_value(mkt(x), pos_of(x), ag_(x)) + (DV.plan_fit(x, pos_of(x), ag_(x), mkt(x), 'get')[0] if s_ == 'get' else 0)
        plan_given = plan_val(a, 'give')
        wins_need = (rule.get('wins') if isinstance(rule, dict) else None) or cfg.get('ransom_wins', 0.5)
        for rid, r in roster.items():
            if rid == my_rid:
                continue
            assets = [(p, adj(p), mkt(p), P[p].get('full_name')) for p in sorted(
                [p for p in active(r) if pos_of(p) in LF.POS and adj(p) >= GET_MIN], key=lambda p: -adj(p))[:8]]
            x_val = {}
            for season, rnd, orig in owned.get(rid, []):
                v, tier = PK.pick_value(season, rnd, orig)
                if v >= 500:
                    assets.append((f'pick:{season}:{rnd}:{orig}', v, v, f'{season} {tier} {PK._RN.get(rnd, rnd)} ({names.get(orig)})'))
                    x_val[f'pick:{season}:{rnd}:{orig}'] = v
            qual = []
            for k in (1, 2, 3, 4):
                for combo in combinations(assets, k):
                    if BASIS == 'market':
                        got = sum(x[side] for x in combo)
                        if got >= need:
                            qual.append((sum(x[2] for x in combo) - gmkt(a), combo, got))
                    elif BASIS == 'plan' and surplus is not None:
                        got = sum(plan_val(x[0], 'get') for x in combo)
                        if got - plan_given >= surplus:
                            qual.append((sum(x[2] for x in combo) - gmkt(a), combo, got))
                    elif BASIS == 'season':
                        if sum(x[2] for x in combo) >= 0.7 * gmkt(a):   # plausibly heard; wins decide below
                            qual.append((sum(x[2] for x in combo) - gmkt(a), combo, sum(x[2] for x in combo)))
            if not qual:
                continue
            # among the 30 qualifying packages they overpay least on, take the one that helps YOUR season
            # most (you are contending), ties broken by the smaller overpay — the likeliest to be heard
            scored = []
            for over, combo, got in sorted(qual, key=lambda q: q[0])[:(400 if BASIS == 'season' else 30)]:
                gp = [x[0] for x in combo if not x[0].startswith('pick:')]
                dw_ = exp_wins(my_rid, [p for p in my_act if p != a] + gp) - base[my_rid]
                if BASIS == 'season' and dw_ < wins_need:
                    continue                            # season basis: the 30 cheapest packages that clear the wins bar
                if BASIS == 'season' and len(scored) >= 30:
                    break
                # plan basis (owner 10-08: "show the likeliest first"): the smallest market overpay that clears the
                # plan ransom, ties -> more plan value; market/season: the most wins this season
                # (full tuple on the other bases so ties break exactly as before this change)
                key_ = (-round(over), round(got - plan_given)) if BASIS == 'plan' else (round(dw_, 2), -over, over, combo, got)
                scored.append((key_, round(dw_, 2), over, combo, got))
            if not scored:
                continue
            _, dw, over, combo, got = max(scored, key=lambda t: t[0])
            gp = [x[0] for x in combo if not x[0].startswith('pick:')]
            their_after = [p for p in active(r) if pos_of(p) in LF.POS and p not in gp] + ([a] if not a.startswith('pick:') else [])
            tdw = exp_wins(rid, their_after) - base[rid]
            ransom.append({'asset': a, 'asset_label': label(a), 'rule': (f'+{surplus:,.0f} in your favor' if surplus is not None
                                                                     else f'x{float(rule)}'), 'need': round(need), 'partner': names[rid],
                           'playoff': round(playoff.get(rid, 0.5), 3), 'get_labels': [x[3] for x in combo],
                           'value_back': round(got), 'value_given': round(gmkt(a) if surplus is not None else gval(a)), 'their_overpay': round(over),
                           'my_wins': round(dw, 2), 'their_wins': round(tdw, 2), 'basis': BASIS,
                           'plan_gain': round(sum(plan_val(x[0], 'get') for x in combo) - plan_given)})
    ransom.sort(key=lambda x: (x['asset_label'], x['their_overpay']))
    res_ = {'generated': time.strftime('%Y-%m-%d %H:%M'), 'from_week': wk_now, 'base_wins': round(base[my_rid], 2),
            'n_evaluated': len(offers), 'best_by_partner': top, 'best_by_partner_dynasty': top_dyn, 'top': offers[:25], 'ransom': ransom,
            'ransom_basis': BASIS}
    if OUT:
        json.dump(res_, open(OUT, 'w'))
        print(f'trade finder (ransom basis: {BASIS}) -> {OUT}: {len(ransom)} king\'s-ransom packages')
        return
    if AS:
        os.makedirs(os.path.join(DATA, 'trade_finder_by_team'), exist_ok=True)
        res_.pop('ransom')
        json.dump(res_, open(os.path.join(DATA, 'trade_finder_by_team', f'{my_rid}.json'), 'w'))
        print(f'trade finder (neutral, as {AS}) -> data/trade_finder_by_team/{my_rid}.json: {len(offers):,} offers, {len(top)} partners')
        return
    json.dump(res_, open(os.path.join(DATA, 'trade_finder.json'), 'w'), indent=1)

    why = {'contender': 'they keep their points while contending, and the value is close',
           'rebuilder': 'they gain market value while rebuilding', 'middle': 'value and points both hold for them'}
    M = [f'# Trade Finder — from week {wk_now}', '',
         f'_Expected wins rest of season now: {base[my_rid]:.2f}. Every 1-for-1 and 2-for-1 with each owner tested on both '
         f'schedules ({len(offers):,} passed the filters). Values: neutral market value on both sides. '
         f'Core assets are never in these: they only move for a king\'s ransom (below)._', '',
         '## Best offer to each owner', '',
         '| Owner | You give | You get | +Wins you | Your value | Their value | Their wins | Why they say yes |',
         '|---|---|---|---|---|---|---|---|']
    for o in top:
        M.append(f"| {o['partner']} ({o['playoff']:.0%}) | {' + '.join(o['give_labels'])} | {o['get_label']} ({o['get_pos']}) | "
                 f"+{o['my_wins']:.2f} | {o['my_value']:+,} | {o['their_value']:+,} | {o['their_wins']:+.2f} | "
                 f"{why[o['window']]}{' · they must drop one' if o['they_must_drop'] else ''} |")
    if not top:
        M.append('| — | no offer passes both sides right now | | | | | | |')
    M += ['', '## Best offer to each owner for the LONG-TERM plan (Contend 2026-28)', '',
          '_Dynasty value = market value averaged over 2026-28, aged with our measured age curves, plus plan bonuses (spend 2027 picks, '
          'keep 2028 picks, fill RB2/TE now, add a WR 25 or younger). Season must not drop more than 0.2 wins._', '',
          '| Owner | You give | You get | Dynasty | Season wins | Their value |', '|---|---|---|---|---|---|']
    M += [f"| {o['partner']} | {' + '.join(o['give_labels'])} | {o['get_label']} ({o['get_pos']}) | {o['dyn']:+,} | {o['my_wins']:+.2f} | {o['their_value']:+,} |" for o in top_dyn] or ['| — | | | | | |']
    M += ['', "## King's ransom — what each core asset would cost", '',
          '_No one is untouchable; the core just needs a king\'s ransom (config `premium`): for the core, the trade evaluation must '
          + ({'plan': 'beat what you give by the configured surplus (e.g. +3,000) in LONG-TERM PLAN value (dynasty: each piece valued '
                       'across your plan seasons, players aged, picks counted only from their draft year). Per team, the likeliest '
                       'qualifying package (smallest market overpay), likeliest first. See KINGS_RANSOM_GUIDE.md._',
              'season': 'add at least the configured wins THIS SEASON (redraft). Per team, among the 30 likeliest qualifying packages, '
                        'the one that adds the most wins._'}.get(BASIS,
             'favor you by the configured surplus (e.g. +3,000) or more on market value. Per team, among the cheapest qualifying packages of up to 4 of their assets, the one that helps your season most._')
             + ' "Their overpay" is how far above market they would have to go; the smaller, the likelier.'), '']
    for a in dict.fromkeys(x['asset'] for x in ransom):
        rows_ = [x for x in ransom if x['asset'] == a][:4]
        M += [f"**{rows_[0]['asset_label']}** (value {rows_[0]['value_given']:,}; rule {rows_[0]['rule']} = needs {rows_[0]['need']:,} back)", '',
              '| From | Package | Value back | Their overpay | Your wins | Their wins |', '|---|---|---|---|---|---|']
        M += [f"| {x['partner']} ({x['playoff']:.0%}) | {' + '.join(x['get_labels'])} | {x['value_back']:,} | {x['their_overpay']:+,} | "
              f"{x['my_wins']:+.2f} | {x['their_wins']:+.2f} |" for x in rows_]
        M.append('')
    open(os.path.join(ROOT, 'TRADE_FINDER.md'), 'w').write('\n'.join(M) + '\n')
    print(f'trade finder -> TRADE_FINDER.md: {len(offers):,} viable offers across {len(top)} owners'
          + (f"; best: {' + '.join(top[0]['give_labels'])} for {top[0]['get_label']} ({top[0]['partner']}), "
             f"+{top[0]['my_wins']:.2f} wins" if top else ''))


if __name__ == '__main__':
    main()
