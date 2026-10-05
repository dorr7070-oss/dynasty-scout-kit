#!/usr/bin/env python3
"""Shared tier-based pick valuation — single source of truth for report.py and
trade_grades.py (so they can't drift).

A pick's worth is mostly its TIER (Early / Mid / Late), and tier = the original
owner's finish (rookie order is reverse of the prior season's standings). Each
tier is the average of the FantasyCalc slot curve (data/values/picks.json) over
that third of the round, x a year discount. Deliberately coarse — no false-precise
exact-slot claims pinned to a projection.

Finish inputs: 2026 picks -> 2025 actual standings; 2027+ -> Sleeper projected
standings (data/projected_standings.json from ops/project.py; falls back to a
strength proxy); 2028 nudged by owner trajectory reads (TRAJ_2028).
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

players = json.load(open(os.path.join(DATA, 'players.json')))
cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
picks_mkt = json.load(open(os.path.join(DATA, 'values', 'picks.json')))
seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
latest = seasons[-1]
rosters = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
users = json.load(open(os.path.join(DATA, latest, 'users.json')))
traded = json.load(open(os.path.join(DATA, latest, 'traded_picks.json')))

_uname = {u['user_id']: (u.get('metadata') or {}).get('team_name') or u['display_name']
          for u in users}
rid2owner = {r['roster_id']: _uname.get(r['owner_id']) for r in rosters}
# Team names are display strings an owner can change at any time (and do —
# an owner can rename at any time). Anything hand-keyed
# must hang off the username, which is also what profiles/*.md are named by.
_user = {u['user_id']: u['display_name'] for u in users}
rid2user = {r['roster_id']: _user.get(r['owner_id']) for r in rosters}

POS = ('QB', 'RB', 'WR', 'TE')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_format as LF  # noqa: E402  league shape (lineup, teams, rounds) from its settings
T = LF.NUM_TEAMS
ROUNDS = tuple(range(1, int(LF.PROFILE.get('rookie_draft_rounds') or 3) + 1))
_THIRD = T // 3                        # tiers: Early = first third of a round, Late = last third
FUTURE = [str(int(latest) + 1), str(int(latest) + 2)]     # tradeable future pick years

# 2028 finish trajectory (place delta; + = declines = worse finish = EARLIER, more
# valuable pick). YOUR reads on where each owner is headed, keyed by Sleeper
# username, e.g. {'someowner': +3}. Empty until you have a view.
TRAJ_2028 = {}

_my_cards = os.path.join(ROOT, 'my_cards.py')   # an owner's own reads (git-ignored) override the default
if os.path.exists(_my_cards):
    _ns = {}
    exec(compile(open(_my_cards, encoding='utf-8').read(), _my_cards, 'exec'), _ns)
    TRAJ_2028 = _ns.get('TRAJ_2028', TRAJ_2028)

_stale = set(TRAJ_2028) - set(rid2user.values())
if _stale:
    print(f'  WARNING picks.py: TRAJ_2028 keys match no current owner: '
          f'{sorted(_stale)} — their trajectory nudge is being silently ignored')

_RN = {n: f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}" for n in range(1, 41)}


def _V(pid):
    return cons.get(str(pid), {}).get('mean', 0)


# --- slot curve -> Early/Mid/Late tier averages -------------------------------
# The exact-slot keys ("2026 Pick 1.01") only exist while that rookie draft is
# still ahead. Once it is held the market drops them, the curve comes back empty
# and EVERY pick was valued at 0 — silently, in the power rankings and in every
# trade grade (found 2026-09-29). Anchor on the earliest season the market still
# slots; otherwise use its own Early/Mid/Late tier prices for the next draft.
_SLOT_SEASON = next((str(y) for y in range(2026, int(latest) + 3)
                     if f'{y} Pick 1.01' in picks_mkt), None)
BASE_SEASON = _SLOT_SEASON or FUTURE[0]


def _slot_curve():
    curve = {}
    if not _SLOT_SEASON:
        return curve
    for r in ROUNDS:
        last = None
        for s in range(1, T + 1):
            k = f'{_SLOT_SEASON} Pick {r}.{s:02d}'
            if k in picks_mkt:
                curve[(r, s)] = picks_mkt[k]; last = curve[(r, s)]
            elif last:
                last = round(last * 0.96); curve[(r, s)] = last
    return curve


_SLOT = _slot_curve()


def _tier_avg(rnd, lo, hi):
    vals = [_SLOT[(rnd, s)] for s in range(lo, hi + 1) if (rnd, s) in _SLOT]
    return sum(vals) / len(vals) if vals else 0


if _SLOT:
    TIER_VAL = {rnd: {'Early': _tier_avg(rnd, 1, _THIRD),
                      'Mid':   _tier_avg(rnd, _THIRD + 1, T - _THIRD),
                      'Late':  _tier_avg(rnd, T - _THIRD + 1, T)} for rnd in ROUNDS}
else:
    def _mkt(rnd, t):
        # the market prices rounds 1-4; deeper rounds decay from the 4th
        r = min(rnd, 4)
        return picks_mkt.get(f'{BASE_SEASON} {_RN[r]} ({t})', 0) * (0.8 ** (rnd - r))
    TIER_VAL = {rnd: {t: _mkt(rnd, t) for t in ('Early', 'Mid', 'Late')} for rnd in ROUNDS}

if not all(v for tiers in TIER_VAL.values() for v in tiers.values()):
    print(f'  *** WARNING picks.py: a pick tier is valued at 0 ({TIER_VAL}) — '
          f'data/values/picks.json no longer carries the keys this reads ***')


# --- league calibration: never price a round above what it actually yields here ---
# The market (FantasyCalc, and KTC far more) prices picks on hope. Checked on
# 2026-10-01 against this league's own 2025+2026 rookie drafts, the players taken
# were worth, on today's consensus, ~80% of the round-1 tier price, ~75% of round 2
# and ~60% of round 3. Overpriced picks inflated every pick-holder in the power
# rankings and every trade grade with a pick in it. So each round is scaled DOWN
# (never up) to the realized average of the players this league drafted in it.
# Recomputed every run from data/<season>/drafts.json, so it moves as drafts age.
def _league_calibration(min_n=8):
    realized = {r: [] for r in ROUNDS}
    for s in seasons:
        try:
            drafts = json.load(open(os.path.join(DATA, s, 'drafts.json')))
        except (OSError, ValueError):
            continue
        for dr in drafts:
            if (dr.get('settings') or {}).get('rounds', 99) > 5:   # skip the startup draft
                continue
            for pk in dr.get('picks') or []:
                if pk.get('round') in realized and pk.get('player_id'):
                    realized[pk['round']].append(_V(pk['player_id']))
    out = {}
    for rnd, vals in realized.items():
        priced = sum(TIER_VAL[rnd].values()) / 3
        if len(vals) >= min_n and priced:
            out[rnd] = min(1.0, (sum(vals) / len(vals)) / priced)
        else:
            out[rnd] = 1.0
    return out, {r: len(v) for r, v in realized.items()}


CALIBRATION, _CAL_N = _league_calibration()
for _r, _m in CALIBRATION.items():
    for _t in TIER_VAL[_r]:
        TIER_VAL[_r][_t] *= _m
print('  pick calibration vs this league\'s drafted outcomes: ' +
      ', '.join(f'R{r} x{m:.2f} (n={_CAL_N[r]})' for r, m in CALIBRATION.items()))


def year_discount(season, rnd):
    if int(season) <= int(BASE_SEASON):   # the anchor year, or a draft already held
        return 1.0
    base = picks_mkt.get(f'{BASE_SEASON} {_RN[rnd]}')
    fut = picks_mkt.get(f'{season} {_RN[rnd]}')
    if base and fut:
        return fut / base
    return 0.93 ** (int(season) - int(BASE_SEASON))


# --- finish standings that set rookie-draft slots -----------------------------
_PRIOR = {}
_HELD = {}


def _held_slots(draft_season, rnd=1):
    """{original roster_id: slot in round rnd} for a rookie draft already held, from the
    draft's own recorded order (Sleeper slot_to_roster_id). Snake drafts reverse the slot
    in even rounds. Empty if not recorded."""
    if draft_season not in _HELD:
        out, snake = {}, False
        try:
            for dr in json.load(open(os.path.join(DATA, draft_season, 'drafts.json'))):
                if (dr.get('settings') or {}).get('rounds', 99) <= 8 and dr.get('slot_to_roster_id'):
                    out = {int(r): int(sl) for sl, r in dr['slot_to_roster_id'].items() if sl and r}
                    snake = dr.get('type') == 'snake'
                    break
        except (OSError, ValueError):
            pass
        _HELD[draft_season] = (out, snake)
    out, snake = _HELD[draft_season]
    if snake and rnd % 2 == 0:
        return {r: T + 1 - sl for r, sl in out.items()}
    return out



def _places_prior(draft_season):
    """Final standings of the season BEFORE a held draft (they set its order).
    Empty when that season isn't on record (e.g. a startup year) — callers fall back to mid-pack."""
    key = str(int(draft_season) - 1)
    if key not in _PRIOR:
        try:
            rs = json.load(open(os.path.join(DATA, key, 'rosters.json')))
            order = sorted(rs, key=lambda x: (-x['settings']['wins'], -x['settings'].get('fpts', 0)))
            _PRIOR[key] = {x['roster_id']: i + 1 for i, x in enumerate(order)}
        except (OSError, ValueError):
            _PRIOR[key] = {}
    return _PRIOR[key]


def _places_strength():
    strength = {}
    for r in rosters:
        by = {p: [] for p in POS}
        for pid in r.get('players') or []:
            pos = players.get(str(pid), {}).get('position')
            if pos in by:
                by[pos].append(_V(pid))
        for p in by:
            by[p].sort(reverse=True)
        strength[r['roster_id']] = LF.best_lineup(by)
    order = sorted(strength, key=lambda k: -strength[k])
    return {rid: i + 1 for i, rid in enumerate(order)}


def _places_projected():
    """Prefer Sleeper's points-based projected standings; fall back to strength."""
    path = os.path.join(DATA, 'projected_standings.json')
    if os.path.exists(path):
        return {int(k): v for k, v in json.load(open(path)).items()}
    return _places_strength()


P25 = _places_prior(latest)    # standings that set this year's draft
PPROJ = _places_projected()


# --- draft order: this league runs a LOTTERY (found 2026-10-01) ---------------------
# The commissioner's league note: the 6 non-playoff teams draw for slots 1-6, weighted
# by Max PF, not record; 7-12 follow the playoff finish. Until 2026-10-01 this file
# assumed reverse record. ops/lottery.py simulates the season + bracket + lottery
# for the next draft (data/pick_odds.json); later drafts use the same lottery applied
# to a projected finish. Value = probability-weighted tier price over the 12 slots.
from lottery import place_slot_dist   # noqa: E402

_ODDS_PATH = os.path.join(DATA, 'pick_odds.json')
PICK_ODDS = json.load(open(_ODDS_PATH)) if os.path.exists(_ODDS_PATH) else {}
_SLOT_TIER = ['Early'] * _THIRD + ['Mid'] * (T - 2 * _THIRD) + ['Late'] * _THIRD


def slot_dist(season, orig_rid):
    """P(slot 1..12) for a future pick, by original owner."""
    if PICK_ODDS.get('season') == season and str(orig_rid) in PICK_ODDS.get('slots', {}):
        return PICK_ODDS['slots'][str(orig_rid)]
    place = PPROJ.get(orig_rid, T // 2 + 1)
    if int(season) > int(FUTURE[0]):
        place += TRAJ_2028.get(rid2user.get(orig_rid), 0)
    return place_slot_dist(min(T, max(1, place)))


def pick_value(season, rnd, orig_rid):
    """Expected value of a pick over its slot odds. Returns (value, tier) where tier is
    the Early/Mid/Late band it most likely lands in (display + KTC lookups)."""
    if int(season) <= int(latest):     # a draft already held: priced by last season's finish
        if rnd not in TIER_VAL:
            last = max(TIER_VAL)
            return TIER_VAL[last]['Mid'] * (0.6 ** (rnd - last)), 'Mid'
        slot = _held_slots(season, rnd).get(orig_rid)
        if slot:                                   # the draft's real order
            tier = 'Early' if slot <= _THIRD else ('Late' if slot > T - _THIRD else 'Mid')
        else:                                      # else last season's finish (reverse record)
            place = min(T, max(1, _places_prior(season).get(orig_rid, T // 2 + 1)))
            tier = 'Early' if place > T - _THIRD else ('Late' if place <= _THIRD else 'Mid')
        return TIER_VAL[rnd][tier] * year_discount(season, rnd), tier
    if rnd not in TIER_VAL:   # e.g. a round-17 startup-draft pick in an old trade: near-zero, never a crash
        last = max(TIER_VAL)
        return TIER_VAL[last]['Mid'] * (0.6 ** (rnd - last)) * year_discount(season, last), 'Mid'
    dist = slot_dist(season, orig_rid)
    mass = {t: 0.0 for t in ('Early', 'Mid', 'Late')}
    for s, p in enumerate(dist):
        mass[_SLOT_TIER[s]] += p
    val = sum(mass[t] * TIER_VAL[rnd][t] for t in mass)
    return val * year_discount(season, rnd), max(mass, key=mass.get)


def owned_future_picks():
    """{roster_id: [(season, round, original_roster_id), ...]} — reconstruct current
    ownership of every future rookie pick (default = original owner; traded_picks
    overrides). Keeps the original owner so callers can tier-value each pick."""
    override = {(t['season'], t['round'], t['roster_id']): t['owner_id']
                for t in traded if t['season'] in FUTURE}
    owned = {r['roster_id']: [] for r in rosters}
    for season in FUTURE:
        for rnd in ROUNDS:
            for orig in owned:
                owner = override.get((season, rnd, orig), orig)
                if owner in owned:
                    owned[owner].append((season, rnd, orig))
    return owned
