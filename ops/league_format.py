#!/usr/bin/env python3
"""League format — ONE place that knows the league's shape, read from its own settings.

Every script used to hard-code this league (1QB, 2RB, 3WR, 1TE, 2 FLEX, 12 teams,
full PPR, 6-team playoff, a Max PF lottery). Made generic 2026-10-02 so the
framework works for any Sleeper league, and for ESPN/Yahoo leagues translated into
the same files by ops/adapters/. Reads data/<latest season>/league.json (Sleeper
shape) plus the optional "draft_order" rule in config.json.

    import league_format as LF
    LF.CORE            {'QB': 1, 'RB': 2, 'WR': 3, 'TE': 1}
    LF.FLEX_SLOTS      [{'RB','WR','TE'}, ...]   one set per flex slot, most restrictive first
    LF.best_lineup(values_by_pos)  -> total of the best legal lineup
    LF.SUPERFLEX, LF.NUM_TEAMS, LF.PPR, LF.TE_PREMIUM, LF.PLAYOFF_TEAMS, LF.REG_WEEKS
    LF.KTC_FORMAT (1 or 2), LF.ktc_value(p) -> the right KTC value for this league
    LF.DRAFT_ORDER     {'rule': ..., ...}
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
POS = ('QB', 'RB', 'WR', 'TE')

# Sleeper slot name -> positions it accepts. ESPN/Yahoo adapters write these same names.
FLEX_TYPES = {
    'FLEX': {'RB', 'WR', 'TE'},
    'WRRB_FLEX': {'RB', 'WR'},
    'REC_FLEX': {'WR', 'TE'},
    'SUPER_FLEX': {'QB', 'RB', 'WR', 'TE'},
}


def _load():
    """Neutral profile first (data/league_profile.json from ops/league_profile.py, any platform);
    fall back to Sleeper's league.json, then to a common 12-team 1QB PPR shape before the first read."""
    cfg_path = os.path.join(ROOT, 'config.json')
    cfg = json.load(open(cfg_path, encoding='utf-8')) if os.path.exists(cfg_path) else {}
    prof_path = os.path.join(DATA, 'league_profile.json')
    if os.path.exists(prof_path):
        return cfg, json.load(open(prof_path, encoding='utf-8'))
    try:
        seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
        lg = json.load(open(os.path.join(DATA, seasons[-1], 'league.json')))
        rp, st, sc = lg.get('roster_positions') or [], lg.get('settings') or {}, lg.get('scoring_settings') or {}
        return cfg, {'name': lg.get('name'), 'platform': 'sleeper', 'num_teams': st.get('num_teams'),
                     'slots': {p: rp.count(p) for p in ('QB', 'RB', 'WR', 'TE', 'K', 'DEF')},
                     'flex': [sorted(FLEX_TYPES[x]) for x in rp if x in FLEX_TYPES],
                     'scoring': {'rec': sc.get('rec', 1.0), 'te_premium': sc.get('bonus_rec_te', 0)},
                     'playoff': {'teams': st.get('playoff_teams'), 'start_week': st.get('playoff_week_start')}}
    except (OSError, ValueError, IndexError):
        return cfg, {}


CFG, PROFILE = _load()
_slots = PROFILE.get('slots') or {'QB': 1, 'RB': 2, 'WR': 3, 'TE': 1}
_flex = PROFILE.get('flex') if PROFILE.get('flex') is not None else [['RB', 'WR', 'TE']] * 2
_sc = PROFILE.get('scoring') or {}
_po = PROFILE.get('playoff') or {}

CORE = {p: int(_slots.get(p, 0) or 0) for p in POS}
FLEX_SLOTS = sorted((set(f) for f in _flex), key=len)          # most restrictive first
SUPERFLEX = CORE['QB'] >= 2 or any('QB' in f for f in FLEX_SLOTS)
NUM_TEAMS = int(PROFILE.get('num_teams') or 12)
PPR = float(_sc.get('rec', 1.0) if _sc.get('rec') is not None else 1.0)
TE_PREMIUM = float(_sc.get('te_premium') or 0)
PLAYOFF_TEAMS = int(_po.get('teams') or 6)
PLAYOFF_START = int(_po.get('start_week') or 15)
PLAYOFF_RESEED = bool(_po.get('reseed'))
REG_WEEKS = range(1, PLAYOFF_START)
MEDIAN_GAME = bool(PROFILE.get('median_game'))
LEAGUE_NAME = (PROFILE.get('name') or CFG.get('league_name') or 'Dynasty League').strip()
PLATFORM = PROFILE.get('platform') or CFG.get('platform', 'sleeper')
PICK_TRADING = PROFILE.get('pick_trading', True)
# bottom third of the league = a positional "hole" (was a hard-coded rank >= 9 of 12)
HOLE_RANK = NUM_TEAMS - NUM_TEAMS // 3 + 1
KTC_FORMAT = 2 if SUPERFLEX else 1
DRAFT_ORDER = CFG.get('draft_order') or PROFILE.get('draft_order') or {'rule': 'reverse_record'}


def ktc_value(p):
    """KTC player/pick object -> value on this league's format (superflex or 1QB)."""
    key = 'superflexValues' if SUPERFLEX else 'oneQBValues'
    return (p.get(key) or {}).get('value')


def fantasycalc_url():
    ppr = 1 if PPR >= 1 else (0.5 if PPR >= 0.5 else 0)
    return (f'https://api.fantasycalc.com/values/current?isDynasty=true&numQbs={2 if SUPERFLEX else 1}'
            f'&numTeams={NUM_TEAMS}&ppr={ppr}')


def best_lineup(by_pos):
    """by_pos: {'QB': [v, ...], ...} (any order). Sum of the best legal lineup:
    core slots first, then each flex slot (most restrictive first) takes the best
    remaining eligible player."""
    pools = {p: sorted(by_pos.get(p, []), reverse=True) for p in POS}
    total = 0.0
    for p, n in CORE.items():
        total += sum(pools[p][:n])
        pools[p] = pools[p][n:]
    for elig in FLEX_SLOTS:
        best = max((p for p in elig if pools[p]), key=lambda p: pools[p][0], default=None)
        if best:
            total += pools[best].pop(0)
    return total


def best_lineup_ids(items):
    """items: iterable of (value, player_id, position). Returns (total, [player ids used])
    for the best legal lineup: core slots, then flex slots most restrictive first."""
    items = list(items)                       # may be a generator; it is read once per position
    pools = {p: sorted([(v, pid) for v, pid, ps in items if ps == p], reverse=True) for p in POS}
    total, used = 0.0, []
    for p, n in CORE.items():
        for v, pid in pools[p][:n]:
            total += v; used.append(pid)
        pools[p] = pools[p][n:]
    for elig in FLEX_SLOTS:
        best = max((p for p in elig if pools[p]), key=lambda p: pools[p][0][0], default=None)
        if best:
            v, pid = pools[best].pop(0); total += v; used.append(pid)
    return total, used


def fill_slots(slots, by_pos):
    """Max points for an explicit slot list (e.g. one season's roster_positions) from
    {position: [points, ...]}. Fixed slots first, then flex slots most restrictive first."""
    pools = {p: sorted(v, reverse=True) for p, v in by_pos.items()}
    total = 0.0
    flex = []
    for slot in slots:
        if slot in FLEX_TYPES:
            flex.append(FLEX_TYPES[slot]); continue
        if pools.get(slot):
            total += pools[slot].pop(0)
    for elig in sorted(flex, key=len):
        best = max((p for p in elig if pools.get(p)), key=lambda p: pools[p][0], default=None)
        if best:
            total += pools[best].pop(0)
    return total


def describe():
    flex = ', '.join('/'.join(sorted(f)) for f in FLEX_SLOTS)
    return (f'{LEAGUE_NAME}: {NUM_TEAMS} teams, {"superflex" if SUPERFLEX else "1QB"}, '
            f'{PPR:g} PPR{f" + {TE_PREMIUM:g} TE premium" if TE_PREMIUM else ""}, '
            f'lineup {CORE} + flex [{flex or "none"}], {PLAYOFF_TEAMS}-team playoff from week {PLAYOFF_START}, '
            f'draft order: {DRAFT_ORDER.get("rule")}')


if __name__ == '__main__':
    print(describe())
