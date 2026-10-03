#!/usr/bin/env python3
"""Tier-aware trade grades — who won the league's trades, by current value.

Prices players at corrected consensus value and PICKS by TIER (Early / Mid /
Late), because a pick's worth is mostly its tier, and tier = the original owner's
finish (rookie order is reverse of the prior season's standings). A pick from a
bad team is an early, valuable pick; from a good team, a late, cheap one. Each
tier is the average of the FantasyCalc slot curve (data/values/picks.json) over
that third of the round, x a year discount — deliberately coarse so it does not
pin a false-precise exact slot to a projection.

Pick valuation (tier model, finish standings, trajectory reads) lives in the
shared ops/picks.py so this and report.py can't drift. Outputs TRADE_GRADES.md
(owner net ranking + top-N most lopsided trades). Stdlib only. Part of ./update.sh
(after values.py writes picks.json and project.py writes projected_standings.json).
"""
import json, os, datetime
from picks import pick_value, rid2owner, _RN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

players = json.load(open(os.path.join(DATA, 'players.json')))
cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))

TOP_N = 10


def _owner(rid):
    return rid2owner.get(rid) or f'former team {rid}'   # teams that left the league


def V(pid):
    return cons.get(str(pid), {}).get('mean', 0)


def pname(pid):
    return players.get(str(pid), {}).get('full_name', str(pid))


# --- grade every completed trade ----------------------------------------------
def grade():
    net = {rid: 0.0 for rid in rid2owner}
    trades, seen = [], set()
    for s in seasons:
        path = os.path.join(DATA, s, 'transactions.json')
        if not os.path.exists(path):
            continue
        for t in json.load(open(path)):
            if t['type'] != 'trade' or t.get('status') != 'complete' \
                    or t['transaction_id'] in seen:
                continue
            seen.add(t['transaction_id'])
            dt = datetime.datetime.fromtimestamp(t['created'] / 1000).strftime('%Y-%m-%d')
            got = {rid: [] for rid in t['roster_ids']}
            recv = {rid: 0.0 for rid in t['roster_ids']}
            for pid, rc in (t.get('adds') or {}).items():
                if rc in got:
                    got[rc].append((pname(pid), V(pid))); recv[rc] += V(pid)
                    if rc in net:            # a team that has since left the league isn't ranked
                        net[rc] += V(pid)
            for pid, rc in (t.get('drops') or {}).items():
                if rc in net:
                    net[rc] -= V(pid)
            for dp in (t.get('draft_picks') or []):
                val, tier = pick_value(dp['season'], dp['round'], dp['roster_id'])
                lbl = f"{dp['season']} {tier} {_RN[dp['round']]}"
                o, pv = dp.get('owner_id'), dp.get('previous_owner_id')
                if o in got:
                    got[o].append((lbl, val)); recv[o] += val
                    if o in net:
                        net[o] += val
                if pv in net:
                    net[pv] -= val
            rids = list(t['roster_ids'])
            if len(rids) >= 2:
                w = max(rids, key=lambda k: recv[k]); l = min(rids, key=lambda k: recv[k])
                trades.append((recv[w] - recv[l], dt, w, l, got))
    return net, trades


def main():
    net, trades = grade()
    trades.sort(key=lambda x: -x[0])
    L = ['# Trade Grades — tier-aware pick values',
         '',
         f'_Generated {datetime.date.today().isoformat()}. Players at corrected consensus; '
         'picks by TIER (Early/Mid/Late = original owner projected bottom-4/middle-4/top-4), '
         'each the average of the FantasyCalc slot curve over that third of the round x year '
         'discount. Current values = hindsight. 2028 tiers use confirmed trajectory reads '
         '(set in TRAJ_2028 in ops/picks.py)._',
         '',
         '## Owner net trade value',
         '',
         '| # | owner | net |',
         '|---|---|---|']
    for i, rid in enumerate(sorted(net, key=lambda k: -net[k]), 1):
        L.append(f'| {i} | {_owner(rid)} | {round(net[rid]):+,} |')
    L += ['', f'## Top {TOP_N} most lopsided trades', '']
    for i, (mg, dt, w, l, got) in enumerate(trades[:TOP_N], 1):
        L.append(f'**{i}. {dt} — won by {_owner(w)} (+{round(mg):,})**')
        for rid in (w, l):
            items = ', '.join(f'{n} {round(v):,}' for n, v in sorted(got[rid], key=lambda x: -x[1])) or '(nothing)'
            mark = '→ ' if rid == w else '  '
            L.append(f'- {mark}**{_owner(rid)}** got: {items}')
        L.append('')
    open(os.path.join(ROOT, 'TRADE_GRADES.md'), 'w').write('\n'.join(L) + '\n')
    rank = sorted(net, key=lambda k: -net[k])
    print(f'trade grades written -> TRADE_GRADES.md ({len(trades)} trades graded)')
    print(f'  best: {_owner(rank[0])} ({round(net[rank[0]]):+,})  |  '
          f'worst: {_owner(rank[-1])} ({round(net[rank[-1]]):+,})')


if __name__ == '__main__':
    main()
