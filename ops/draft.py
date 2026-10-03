#!/usr/bin/env python3
"""Draft prep for my team — enforce best-value-available + guard my WR bias.

Two modes (stdlib only, reuses data/values/consensus.json corrected values):

  --diagnose   Retrospective. For each of my past rookie picks, show the pick's
               current value vs the best player taken within the next N picks,
               and summarize the pattern (positions I draft vs value I leave on
               the board). My documented flaw: I over-draft WR and reach past
               TE/QB at my hole positions.

  --board      (default) Live draft board. Ranks every currently-available
               player (not on any roster) by corrected consensus value,
               annotated with my positional need and a BIAS FLAG when a WR I
               don't need sits above a comparable TE/QB at one of my holes.
               Writes DRAFT_BOARD.md. Part of ./update.sh.
"""
import json, os, sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))

players = json.load(open(os.path.join(DATA, 'players.json')))
seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
latest = seasons[-1]
rosters = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
users = json.load(open(os.path.join(DATA, latest, 'users.json')))
cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))

POS = ('QB', 'RB', 'WR', 'TE')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_format as LF  # noqa: E402
STARTERS = {p: max(n, 1) for p, n in LF.CORE.items()}   # this league's core lineup
NEAR = 300   # "comparable value" window for the bias guard

uid_name = {u['user_id']: u['display_name'] for u in users}
my_uid = next(u for u, n in uid_name.items() if n == CFG['my_username'])
my_roster = next(r for r in rosters if r.get('owner_id') == my_uid)
my_rid = my_roster['roster_id']


def pv(pid):
    return cons.get(str(pid), {}).get('mean', 0)


def pos_of(pid):
    return players.get(str(pid), {}).get('position')


def name_of(pid):
    return players.get(str(pid), {}).get('full_name', str(pid))


def age_of(pid):
    return players.get(str(pid), {}).get('age')


# --- my positional need (same starter/depth model as advise.py) ---------------
def team_pos_values():
    teams = {}
    for r in rosters:
        by = {p: [] for p in POS}
        for pid in r.get('players') or []:
            if pos_of(pid) in by:
                by[pos_of(pid)].append(pv(pid))
        for p in by:
            by[p].sort(reverse=True)
        teams[r['roster_id']] = by
    return teams


TEAMS = team_pos_values()


def starter_rank(pos):
    """My rank (1=best) in starter value at a position."""
    def sv(by):
        return sum(by[pos][:STARTERS[pos]])
    vals = sorted((sv(by) for by in TEAMS.values()), reverse=True)
    return vals.index(sv(TEAMS[my_rid])) + 1


MY_RANK = {p: starter_rank(p) for p in POS}
MY_COUNT = {p: len(TEAMS[my_rid][p]) for p in POS}
HOLES = {p for p in POS if MY_RANK[p] >= LF.HOLE_RANK}   # bottom third of the league
DEEP = {p for p in POS if MY_RANK[p] <= LF.NUM_TEAMS // 4 or MY_COUNT[p] >= 6}


def need_tag(pos):
    if pos in HOLES:
        return 'HOLE'
    if pos in DEEP:
        return 'deep'
    return 'ok'


# --- diagnose -----------------------------------------------------------------
def diagnose(window=5, threshold=300):
    print('=== DRAFT SELF-SCOUT (my rookie picks vs value left on the board) ===')
    print(f'my current need: ' + ', '.join(f'{p} #{MY_RANK[p]}' for p in POS))
    print(f'holes: {sorted(HOLES) or "none"} | deep: {sorted(DEEP) or "none"}\n')
    drafted_pos, left_pos, total_left = {}, {}, 0
    # rookie drafts = every season after the startup (first season)
    for season in seasons[1:]:
        path = os.path.join(DATA, season, 'drafts.json')
        if not os.path.exists(path):
            continue
        for dr in json.load(open(path)):
            picks = sorted(dr.get('picks') or [], key=lambda x: x.get('pick_no', 0))
            if not picks:
                continue
            mine = [p for p in picks if p.get('roster_id') == my_rid]
            if not mine:
                continue
            print(f'-- {season} rookie draft --')
            for mp in mine:
                pno, pid = mp['pick_no'], mp['player_id']
                drafted_pos[pos_of(pid)] = drafted_pos.get(pos_of(pid), 0) + 1
                after = [p for p in picks if pno < p['pick_no'] <= pno + window]
                alts = sorted(after, key=lambda x: -pv(x['player_id']))
                best = alts[0] if alts else None
                miss = ''
                if best and pv(best['player_id']) - pv(pid) > threshold:
                    d = round(pv(best['player_id']) - pv(pid))
                    bp = best['player_id']
                    miss = (f"  <= LEFT {name_of(bp)} ({pos_of(bp)} {round(pv(bp))}) "
                            f"on the board [-{d}]")
                    left_pos[pos_of(bp)] = left_pos.get(pos_of(bp), 0) + 1
                    total_left += d
                print(f"  R{mp.get('round')} p{pno}: {name_of(pid)} "
                      f"({pos_of(pid)} {round(pv(pid))}){miss}")
            print()
    print('=== pattern ===')
    print(f'  positions I drafted:      {drafted_pos}')
    print(f'  positions I passed (hit): {left_pos}')
    print(f'  total value left on board: {round(total_left):,}')
    if left_pos:
        worst = max(left_pos, key=left_pos.get)
        print(f'  most-often missed position: {worst} '
              f'(and {"a hole" if worst in HOLES else "not a current hole"})')
    if drafted_pos.get('WR', 0) >= max(drafted_pos.values() or [0]) and 'WR' in DEEP:
        print('  FLAG: WR is my most-drafted position AND I am already WR-deep — '
              'the same bias as my trade ledger.')


# --- board --------------------------------------------------------------------
def board(top=40):
    rostered = {str(pid) for r in rosters for pid in (r.get('players') or [])}
    avail = []
    for pid, p in players.items():
        # require an active NFL player: filters out name-collision ghosts, where
        # a retired player (team=None, active=False) inherits a rostered
        # namesake's value through the name-matched value sources.
        if (p.get('position') in POS and pid not in rostered and pv(pid) > 0
                and p.get('active') and p.get('team')):
            avail.append(pid)
    avail.sort(key=lambda pid: -pv(pid))

    def best_hole_alt(i):
        """Best HOLE-position player ranked below row i, within NEAR value."""
        base = pv(avail[i])
        for j in range(i + 1, len(avail)):
            if base - pv(avail[j]) > NEAR:
                break
            if pos_of(avail[j]) in HOLES:
                return avail[j]
        return None

    lines = [f'# Draft Board — {CFG["my_username"]} ({latest})', '',
             f'_Generated {date.today().isoformat()} from corrected consensus values. '
             f'Best-value-available; my holes: {sorted(HOLES) or "none"}, '
             f'deep: {sorted(DEEP) or "none"}._', '',
             '| # | player | pos | age | value | my need | flag |',
             '|---|---|---|---|---|---|---|']
    for i, pid in enumerate(avail[:top]):
        pos = pos_of(pid)
        flag = ''
        if pos in DEEP:
            alt = best_hole_alt(i)
            if alt:
                flag = f'⚠ BIAS: you are {pos}-deep — {name_of(alt)} ({pos_of(alt)}, ' \
                       f'{round(pv(alt))}) fills a hole for ~same value'
        lines.append(f'| {i+1} | {name_of(pid)} | {pos} | {age_of(pid)} | '
                     f'{round(pv(pid)):,} | {need_tag(pos)} | {flag} |')
    out = os.path.join(ROOT, 'DRAFT_BOARD.md')
    open(out, 'w').write('\n'.join(lines) + '\n')
    print(f'draft board written -> DRAFT_BOARD.md ({len(avail)} available, top {top} listed)')
    flagged = sum(1 for i, pid in enumerate(avail[:top])
                  if pos_of(pid) in DEEP and best_hole_alt(i))
    print(f'  holes: {sorted(HOLES) or "none"} | bias flags in top {top}: {flagged}')


if __name__ == '__main__':
    if '--diagnose' in sys.argv:
        diagnose()
    else:
        board()
