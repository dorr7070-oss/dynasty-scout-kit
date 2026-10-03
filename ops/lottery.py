#!/usr/bin/env python3
"""Next rookie draft's slot odds under THIS league's draft-order rule -> data/pick_odds.json

Monte Carlo of the rest of the regular season (data/projection.json weekly projections,
the shared lineup optimizer, SD 22) tracking wins, points and Max PF; then the league's
playoff bracket (any size, byes, fixed or reseeded); then the draft-order rule.
Output: {"season": "<next>", "slots": {rid: [p(slot 1) .. p(slot N)]}, "playoff": {...}, "pts_wk": {...}}.

The rule lives in config.json "draft_order" (asked during onboarding, since no platform
exposes it). Supported:
  reverse_record      non-playoff teams by record, worst first; playoff teams by playoff finish (default)
  reverse_max_pf      non-playoff teams by Max PF (best-possible-lineup points), lowest first
  max_pf_lottery      non-playoff teams draw, balls by Max PF rank ("balls": [7,5,4,...]),
                      optional "protect_rank1_at_pick": the lowest team falls no lower than that pick
  record_lottery      same, balls by record rank
  reverse_record_all  the whole draft by regular-season record, playoffs ignored
History: built 2026-10-01 for one league's Max PF lottery (commissioner's note); generalized
2026-10-02 so any league's rule and bracket work.
"""
import json, math, os, random, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
from project import lineup_points  # noqa: E402
import league_format as LF  # noqa: E402

SD, N = 22, 6000
OUT = os.path.join(DATA, 'pick_odds.json')
RULE = LF.DRAFT_ORDER
T = LF.NUM_TEAMS
P = min(LF.PLAYOFF_TEAMS, T)
NP = T - P                                   # non-playoff teams: slots 1..NP


def lottery_dist(balls, protect=None):
    """Exact P(slot) for each rank (0 = worst). Returns [[p slot1..n] per rank].
    protect: 1-based pick by which rank 0 must have been drawn (e.g. 3)."""
    n = len(balls)
    dist = [[0.0] * n for _ in range(n)]

    def draw(pool, slot, p, order):
        if slot == n:
            for s, r in enumerate(order):
                dist[r][s] += p
            return
        if protect and slot == protect - 1 and 0 in pool:
            draw([r for r in pool if r != 0], slot + 1, p, order + [0]); return
        tot = sum(balls[r] for r in pool) or 1
        for r in pool:
            draw([x for x in pool if x != r], slot + 1, p * balls[r] / tot, order + [r])

    draw(list(range(n)), 0, 1.0, [])
    return dist


def _balls():
    b = list(RULE.get('balls') or [])
    if len(b) != NP:   # missing or wrong length -> a simple descending default, flagged loudly
        if 'lottery' in RULE.get('rule', ''):
            print(f'  lottery.py: draft_order.balls has {len(b)} entries for {NP} non-playoff teams — using {list(range(NP, 0, -1))}')
        b = list(range(NP, 0, -1))
    return b


IS_LOTTERY = RULE.get('rule') in ('max_pf_lottery', 'record_lottery')
LOTTERY = lottery_dist(_balls(), RULE.get('protect_rank1_at_pick')) if IS_LOTTERY and NP else None


def nonplayoff_slots(rank):
    """rank 0 = worst non-playoff team (by the rule's ordering) -> P(slot) over slots 1..NP."""
    if LOTTERY:
        return LOTTERY[rank]
    out = [0.0] * NP
    out[rank] = 1.0
    return out


def place_slot_dist(place):
    """Slot distribution over 1..T from a projected finish alone (1 = best .. T = worst).
    Used for drafts beyond the simulated one."""
    out = [0.0] * T
    if RULE.get('rule') == 'reverse_record_all' or place <= P:
        out[T - place] = 1.0                      # place 1 -> slot T
    else:
        for s, p in enumerate(nonplayoff_slots(T - place)):   # place T -> rank 0
            out[s] = p
    return out


def bracket_order(n):
    """Standard fixed-bracket seat order for a bracket of size n (power of two): 1, n, n/2+1, ..."""
    order = [1]
    while len(order) < n:
        m = len(order) * 2
        order = [x for s in order for x in (s, m + 1 - s)]
    return order


def play_bracket(po, win, reseed):
    """po: playoff teams in seed order. Returns teams in finish order (1st first)."""
    size = 2 ** math.ceil(math.log2(len(po))) if len(po) > 1 else 1
    seed_of = {r: i for i, r in enumerate(po)}
    seats = [po[s - 1] if s <= len(po) else None for s in bracket_order(size)]
    finish_rounds = []                            # losers per round, earliest first
    while len(seats) > 1:
        if reseed and finish_rounds:             # byes play out in round 1; reseed after
            alive = sorted([x for x in seats if x is not None], key=seed_of.get)
            seats = [x for i in range(len(alive) // 2) for x in (alive[i], alive[-1 - i])] + \
                    ([alive[len(alive) // 2]] if len(alive) % 2 else [])
        nxt, losers = [], []
        for a, b in zip(seats[::2], seats[1::2]):
            if a is None or b is None:
                nxt.append(a or b)
            else:
                w = win(a, b); nxt.append(w); losers.append(b if w == a else a)
        finish_rounds.append(losers)
        seats = nxt
        if len(seats) == 1:
            break
    champ = seats[0]
    order = [champ]
    for losers in reversed(finish_rounds):        # later rounds finish higher
        if len(losers) == 2:                      # placement game between the two
            w = win(losers[0], losers[1]); order += [w, losers[1] if w == losers[0] else losers[0]]
        else:
            order += sorted(losers, key=seed_of.get)
    return order


def main():
    Pl = json.load(open(os.path.join(DATA, 'players.json')))
    d = json.load(open(os.path.join(DATA, 'projection.json')))
    seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
    latest = seasons[-1]
    rosters = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
    league = json.load(open(os.path.join(DATA, latest, 'league.json')))
    done = (league.get('settings') or {}).get('last_scored_leg', 0)
    proj = {pid: {int(w): v for w, v in wk.items()} for pid, wk in d['player_weekly'].items()}
    pos_of = lambda p: Pl.get(p, {}).get('position')
    act = {r['roster_id']: [p for p in r['players'] or [] if p not in (r.get('reserve') or [])
                            and p not in (r.get('taxi') or [])] for r in rosters}
    sched = {int(k): v['schedule'] for k, v in d['rosters'].items()}
    weeks = list(range(done + 1, LF.PLAYOFF_START))
    num = lambda r, k: r['settings'].get(k, 0) + r['settings'].get(k + '_decimal', 0) / 100
    W0 = {r['roster_id']: r['settings']['wins'] for r in rosters}
    F0 = {r['roster_id']: num(r, 'fpts') for r in rosters}
    M0 = {r['roster_id']: num(r, 'ppts') for r in rosters}
    pts = {r: {w: lineup_points(act[r], w, proj, pos_of) for w in weeks} for r in act}
    avg = {r: (sum(pts[r].values()) / len(weeks)) if weeks else 120 for r in act}
    by_maxpf = RULE.get('rule') in ('max_pf_lottery', 'reverse_max_pf')

    random.seed(11)
    cnt = {r: [0.0] * T for r in act}
    made = {r: 0 for r in act}
    for _ in range(N):
        W, F, M = dict(W0), dict(F0), dict(M0)
        for w in weeks:
            s = {r: random.gauss(pts[r][w], SD) for r in act}
            seen = set()
            for r in act:
                for g in sched[r]:
                    if g['wk'] == w and (r, g['opp']) not in seen:
                        o = g['opp']; seen |= {(r, o), (o, r)}
                        W[r if s[r] > s[o] else o] += 1
            if LF.MEDIAN_GAME:                    # extra win for a top-half score each week
                for r in sorted(act, key=lambda r: -s[r])[:len(act) // 2]:
                    W[r] += 1
            for r in act:
                F[r] += s[r]; M[r] += s[r]
        seed = sorted(act, key=lambda r: (-W[r], -F[r]))
        po, out = seed[:P], seed[P:]
        for r in po:
            made[r] += 1
        if RULE.get('rule') == 'reverse_record_all':
            for i, r in enumerate(reversed(seed)):    # worst record -> slot 1
                cnt[r][i] += 1
            continue
        g = lambda r: random.gauss(avg[r], SD)
        win = lambda a, b: a if g(a) > g(b) else b
        for place, r in enumerate(play_bracket(po, win, LF.PLAYOFF_RESEED)):
            cnt[r][T - 1 - place] += 1             # champion picks last
        ranked = sorted(out, key=(lambda r: M[r]) if by_maxpf else (lambda r: (W[r], F[r])))
        for rank, r in enumerate(ranked):
            for s_, p in enumerate(nonplayoff_slots(rank)):
                cnt[r][s_] += p
    slots = {str(r): [round(c / N, 4) for c in cnt[r]] for r in act}
    json.dump({'season': str(int(latest) + 1), 'sims': N, 'rule': RULE.get('rule'),
               'weeks': [weeks[0], weeks[-1]] if weeks else [], 'slots': slots,
               'playoff': {str(r): round(made[r] / N, 4) for r in act},
               'pts_wk': {str(r): round(avg[r], 1) for r in act}}, open(OUT, 'w'))
    users = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, latest, 'users.json')))}
    nm = {r['roster_id']: users.get(r['owner_id'], '?') for r in rosters}
    third = T // 3
    print(f'draft-order odds for the {int(latest) + 1} draft ({RULE.get("rule")}) -> {os.path.basename(OUT)}  '
          f'(slots 1-{third} / {third + 1}-{2 * third} / {2 * third + 1}-{T}, %)')
    for r in sorted(act, key=lambda r: -sum(i * p for i, p in enumerate(slots[str(r)]))):
        v = slots[str(r)]
        print(f'  {nm[r]:16} Max PF {M0[r]:6.1f}  early {100*sum(v[:third]):5.1f}  mid {100*sum(v[third:2*third]):5.1f}  '
              f'late {100*sum(v[2*third:]):5.1f}  #1 {100*v[0]:4.1f}')


if __name__ == '__main__':
    main()
