#!/usr/bin/env python3
"""Dynasty value scored against YOUR long-term plan (owner's ask, 2026-10-04: "not just season-helpful —
options for dynasty, in terms of the long-term plan").

window_value(asset) = market value averaged over the plan window (config "plan_window", default 3 seasons:
2026-2028 for "Contend 2026-28"), each later season shrunk by the measured year-over-year retention for the
player's position and age (data/age_curve.json; TE uses the WR curve, ages past the curve use its last step).
Picks keep their tier value (they turn into players inside the window).

plan_fit(asset, side) — small, explicit bonuses for what the plan says to do (research/DRAFT_PLAN.md):
  + acquiring a starting RB2 or TE now (holes "now"), a WR 25 or younger (the 2028 WR1 successor)
  + spending 2027 picks; - giving up 2028 picks (the target class)
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


def plan_fit(asset_key, pos, age, value, side, starter_need=('RB', 'TE')):
    """side = 'get' or 'give'. Returns (points, reason or '')."""
    if asset_key.startswith('pick:'):
        _, season, rnd, _ = asset_key.split(':')
        if side == 'give' and season == '2027':
            return 150, 'spends a 2027 pick (plan: spend 2027)'
        if side == 'give' and season == '2028':
            return -250 * (2 if rnd == '1' else 1), 'gives a 2028 pick (plan: keep the 2028 class)'
        if side == 'get' and season == '2028':
            return 200, 'adds a 2028 pick (target class)'
        return 0, ''
    if side == 'get':
        if pos in starter_need and value >= 1500:
            return 300, f'fills the {pos} hole now'
        if pos == 'WR' and age is not None and age <= 25 and value >= 1500:
            return 250, 'young WR (2028 WR1 successor)'
    return 0, ''
