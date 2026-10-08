#!/usr/bin/env python3
"""Dynasty value scored against YOUR long-term plan (owner's ask, 2026-10-04: "not just season-helpful —
options for dynasty, in terms of the long-term plan").

window_value(asset) = market value averaged over the plan window (config "plan_window", default 3 seasons:
2026-2028 for "Contend 2026-28"), each later season shrunk by the measured year-over-year retention for the
player's position and age (data/age_curve.json; TE uses the WR curve, ages past the curve use its last step).
Picks keep their tier value (they turn into players inside the window).

plan_fit(asset, side) — small, explicit bonuses for what the plan says to do:
  + acquiring a starting RB2 or TE now (holes "now"), a WR 25 or younger (a future WR1)
  picks follow the owner's my_plan.json "picks" (since 2026-10-08): + spending a "Spend" year, - giving a held round,
  + adding a pick in a "target" class. No plan file -> no pick bonuses.
Values are market-scale points, so they add to window_value. Both shown separately so nothing is hidden.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

_AC = json.load(open(os.path.join(DATA, 'age_curve.json'))) if os.path.exists(os.path.join(DATA, 'age_curve.json')) else {}
_CFG = json.load(open(os.path.join(ROOT, 'config.json')))
WINDOW = int(_CFG.get('plan_window', 3))


def retention(pos, age):
    pc = ((_AC.get('positions') or {}).get(pos if pos != 'TE' else 'WR') or {}).get('curve') or []
    if not pc or age is None:
        return 0.85
    by = {c['age']: c['retention'] for c in pc}
    a = int(age)
    if a in by:
        return min(1.0, by[a])
    return min(1.0, by[max(by)] if a > max(by) else by[min(by)])


def window_value(value, pos, age):
    """Average market value across the plan window, aged with the measured curve."""
    if pos is None:                       # a pick
        return value
    tot, v, a = 0.0, value, age
    for _ in range(WINDOW):
        tot += v
        v *= retention(pos, a)
        a = (a or 27) + 1
    return tot / WINDOW


def _pick_policy():
    """The owner's pick policy from my_plan.json "picks" (2026-10-08): {year: {"text": "Spend" | "Hold ..." | "...target...",
    "hold_rounds": [1, ...]}} or {year: "Hold"}. No plan -> {} -> no pick bonuses (they used to be one owner's plan, hard-coded)."""
    try:
        return json.load(open(os.path.join(ROOT, 'my_plan.json'))).get('picks') or {}
    except Exception:
        return {}


def plan_fit(asset_key, pos, age, value, side, starter_need=('RB', 'TE')):
    """side = 'get' or 'give'. Returns (points, reason or '')."""
    if asset_key.startswith('pick:'):
        _, season, rnd, _ = asset_key.split(':')
        pol = _pick_policy().get(season)
        if pol is None:
            return 0, ''
        text = (pol.get('text') if isinstance(pol, dict) else str(pol)) or ''
        hold = set(pol.get('hold_rounds') or []) if isinstance(pol, dict) else ({1, 2, 3, 4, 5} if text.lower().startswith('hold') else set())
        if side == 'give' and text.lower().startswith('spend'):
            return 150, f'spends a {season} pick (plan: spend {season})'
        if side == 'give' and int(rnd) in hold:
            return -250 * (2 if rnd == '1' else 1), f'gives a {season} round-{rnd} pick (plan: hold)'
        if side == 'get' and 'target' in text.lower():
            return 200, f'adds a {season} pick (target class)'
        return 0, ''
    if side == 'get':
        if pos in starter_need and value >= 1500:
            return 300, f'fills the {pos} hole now'
        if pos == 'WR' and age is not None and age <= 25 and value >= 1500:
            return 250, 'young WR (2028 WR1 successor)'
    return 0, ''


def plan_years():
    """The seasons the owner's plan covers: my_plan.json "goals" years (2026-10-08), else this season + plan_window."""
    try:
        g = json.load(open(os.path.join(ROOT, 'my_plan.json'))).get('goals') or {}
        ys = sorted(int(y) for y in g if str(y).isdigit())
        if ys:
            return ys
    except Exception:
        pass
    s = int(max(d for d in os.listdir(DATA) if d.isdigit()))
    return list(range(s, s + WINDOW))


def plan_value(value, pos, age, draft_year=None, years=None):
    """Value to THIS owner's plan: the asset's worth in each plan season, averaged over the plan's seasons. A player
    ages along the measured curve; a pick is worth nothing before its draft year (it can't play yet) and its tier
    value from then on. So a contend-now window discounts picks, and a rebuild window that runs later counts them."""
    years = years or plan_years()
    tot, v, a = 0.0, value, age
    first = years[0]
    for y in years:
        if pos is None:                         # a pick
            tot += value if (draft_year is None or y >= int(draft_year)) else 0.0
        else:
            tot += v
            v *= retention(pos, a)
            a = (a or 27) + 1
    return tot / len(years)
