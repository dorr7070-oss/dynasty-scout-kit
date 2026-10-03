#!/usr/bin/env python3
"""Lottery tracker: where every next-year 1st and 2nd is headed, who owns it, and how that is
moving week to week -> data/lottery_history.json (dated snapshots), LOTTERY.md, dashboard.

Asked for 2026-10-02 ("a lottery tracker index — knowledge — brain"). ops/lottery.py already
simulates the rest of the season and the league's draft-order rule into data/pick_odds.json;
this keeps a running RECORD of it, so the question "is that pick getting better or worse?" has
an answer, and turns it into trade targets.

Per original team, each run records: Max PF so far (the lottery's weighting stat in Max-PF
leagues), playoff odds, P(lottery) = P(missing the playoffs), P(top 3 pick), expected slot,
and for round 1 and 2: the current owner and the pick's expected value (ops/picks.py, priced
over the slot odds, same numbers trade grades use). Then:
  movers    biggest change in P(top 3) and value since the previous snapshot
  targets   1sts with real top-3 odds owned by a team that is contending (likely to sell a
            future pick for help now) — the cheapest place to buy lottery tickets
  yours     where your own 1st and 2nd are headed, and who benefits
One snapshot per calendar day (a rerun the same day replaces it). Run after lottery.py.
"""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import picks as PK  # noqa: E402

HIST = os.path.join(DATA, 'lottery_history.json')


def main():
    po_path = os.path.join(DATA, 'pick_odds.json')
    if not os.path.exists(po_path):
        print('lottery_tracker: no data/pick_odds.json (run ops/lottery.py) — skipped')
        return
    po = json.load(open(po_path))
    season = po['season']
    rosters = PK.rosters
    names = {r['roster_id']: PK.rid2user.get(r['roster_id']) for r in rosters}
    me = json.load(open(os.path.join(ROOT, 'config.json'))).get('my_username')
    owned = PK.owned_future_picks()
    owner_of = {(s, rnd, orig): rid for rid, lst in owned.items() for s, rnd, orig in lst}
    NP = PK.T - min(LF.PLAYOFF_TEAMS, PK.T)

    teams = {}
    for r in rosters:
        rid = r['roster_id']
        st = r.get('settings') or {}
        dist = po['slots'].get(str(rid)) or [0] * PK.T
        exp_slot = sum((i + 1) * p for i, p in enumerate(dist))
        row = {'team': names[rid], 'record': f"{st.get('wins', 0)}-{st.get('losses', 0)}",
               'max_pf': round((st.get('ppts') or 0) + (st.get('ppts_decimal') or 0) / 100, 1),
               'pf': round((st.get('fpts') or 0) + (st.get('fpts_decimal') or 0) / 100, 1),
               'playoff': round(po['playoff'].get(str(rid), 0), 3),
               'p_lottery': round(sum(dist[:NP]), 3), 'p_top3': round(sum(dist[:3]), 3),
               'p_1': round(dist[0], 3), 'exp_slot': round(exp_slot, 2)}
        for rnd in (1, 2):
            if rnd in PK.ROUNDS:
                val, tier = PK.pick_value(season, rnd, rid)
                ow = owner_of.get((season, rnd, rid), rid)
                row[f'r{rnd}'] = {'owner': names.get(ow), 'value': round(val), 'tier': tier}
        teams[str(rid)] = row

    hist = json.load(open(HIST)) if os.path.exists(HIST) else {'season': season, 'snapshots': []}
    if hist.get('season') != season:
        hist = {'season': season, 'snapshots': []}
    today = time.strftime('%Y-%m-%d')
    hist['snapshots'] = [s for s in hist['snapshots'] if s['date'] != today]
    prev = hist['snapshots'][-1] if hist['snapshots'] else None
    snap = {'date': today, 'weeks_left': po.get('weeks'), 'teams': teams}
    hist['snapshots'].append(snap)
    json.dump(hist, open(HIST, 'w'), indent=1)

    # movers vs previous snapshot
    movers = []
    if prev:
        for rid, t in teams.items():
            p = prev['teams'].get(rid)
            if p:
                movers.append((t['p_top3'] - p['p_top3'], t['r1']['value'] - p['r1']['value'], rid))
        movers.sort(key=lambda m: -abs(m[0]))

    # targets: real top-3 odds, owned by a contender (playoff odds >= 60%) who is not me
    play = {names[int(k)]: v for k, v in po['playoff'].items()}
    targets = sorted([(t['p_top3'], rid) for rid, t in teams.items()
                      if t['p_top3'] >= 0.15 and t['r1']['owner'] != me and play.get(t['r1']['owner'], 0) >= 0.6],
                     reverse=True)

    order = sorted(teams, key=lambda k: teams[k]['exp_slot'])
    L = [f'# Lottery Tracker — {season} rookie draft', '',
         f'_Updated {today}. Rule: `{po.get("rule")}` ({json.dumps(LF.DRAFT_ORDER.get("balls")) if isinstance(LF.DRAFT_ORDER, dict) and LF.DRAFT_ORDER.get("balls") else "see config draft_order"}). '
         f'{po.get("sims", 0):,} simulated seasons from ops/lottery.py; history in data/lottery_history.json '
         f'({len(hist["snapshots"])} snapshot{"s" if len(hist["snapshots"]) != 1 else ""})._', '',
         '| Exp. slot | Original team | Record | Max PF | Playoff | Lottery | Top 3 | #1 | 1st owned by | 1st value | 2nd owned by |',
         '|---|---|---|---|---|---|---|---|---|---|---|']
    for k in order:
        t = teams[k]
        L.append(f"| {t['exp_slot']:.1f} | {t['team']} | {t['record']} | {t['max_pf']:.0f} | {t['playoff']:.0%} | "
                 f"{t['p_lottery']:.0%} | {t['p_top3']:.0%} | {t['p_1']:.0%} | {t['r1']['owner']} | {t['r1']['value']:,} | "
                 f"{t.get('r2', {}).get('owner', '—')} |")
    L += ['', '## Movers since last snapshot', '']
    if movers:
        for d3, dv, rid in movers[:5]:
            L.append(f"- {teams[rid]['team']}: top-3 odds {d3:+.0%}, 1st value {dv:+,} (owned by {teams[rid]['r1']['owner']})")
    else:
        L.append('- First snapshot — movement shows from the next run.')
    L += ['', '## Lottery tickets to buy (top-3 odds 15%+, owned by a contender)', '']
    L += [f"- {teams[rid]['team']}'s 1st — top 3 {p:.0%}, #1 {teams[rid]['p_1']:.0%}, value {teams[rid]['r1']['value']:,}; "
          f"owner {teams[rid]['r1']['owner']} is {play.get(teams[rid]['r1']['owner'], 0):.0%} to make the playoffs"
          for p, rid in targets] or ['- None right now.']
    mine = next((k for k, t in teams.items() if t['team'] == me), None)
    if mine:
        t = teams[mine]
        L += ['', f'## Your own picks ({me})', '',
              f"- 1st: expected slot {t['exp_slot']:.1f}, top 3 {t['p_top3']:.0%} — owned by **{t['r1']['owner']}**"
              + (' (you)' if t['r1']['owner'] == me else ' — your losses help them, not you'),
              f"- 2nd: owned by **{t.get('r2', {}).get('owner', '—')}**"]
    open(os.path.join(ROOT, 'LOTTERY.md'), 'w').write('\n'.join(L) + '\n')
    top = teams[order[0]]
    print(f'lottery tracker -> LOTTERY.md + data/lottery_history.json ({len(hist["snapshots"])} snapshots); '
          f"likeliest #1: {top['team']}'s 1st ({top['p_1']:.0%}, owned by {top['r1']['owner']}); "
          f'{len(targets)} buy target(s)')


if __name__ == '__main__':
    main()
