#!/usr/bin/env python3
"""Contract-year weighting + contract calendar (after values.py and context.py).

Decided 2026-10-02 (owner's answers): sort contract years by type, weight them by position
and age, MEASURE the weights from history (ops/contract_study.py -> data/contract_effects.json),
and adjust FUTURE seasons only: this season's production stays at full value; the share of a
player's dynasty value that comes from seasons after his contract ends is scaled by the measured
next-season effect for players like him.

    adjusted = market x (1 - future_share x (1 - effect))

Writes back into data/values/consensus.json: `mean` becomes the contract-adjusted value every
analysis uses; the untouched market number is kept as `mean_market`, and `contract` records the
class, effect and multiplier. Idempotent: always recomputes from `mean_market`.
Also writes data/contract_calendar.json (league-wide contract-year list with buy/sell signals and
a salary-based role-security tag) for the dashboards and advice.

Classes for players whose contract ends after THIS season:
  team_control   restricted / exclusive-rights FA — the team controls him; no adjustment
  depth          signed-future / minimum depth players, or value < 300 — ignored
  rookie_deal    still on his rookie contract (<= 4 years in the league): extension or tag is
                 common; measured effect for rookie deals at his position
  veteran        everyone else: measured effect for veterans at his position and age band
Small cells are shrunk toward their position's result (weight n / (n + 20)).
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402

SHRINK = 20
MIN_VALUE = 300
ROOKIE_APY = 6e6   # above this he is on a tag or a veteran deal, not his rookie scale


def future_share(age):
    """Rough share of a dynasty value that comes from seasons after this one (judgement, by age)."""
    if age is None:
        return 0.7
    return 0.85 if age <= 24 else 0.78 if age <= 26 else 0.68 if age <= 28 else 0.55 if age <= 30 else 0.4


def band(age):
    return '<=25' if (age or 27) <= 25 else '26-28' if (age or 27) <= 28 else '29+'


def effect_for(cells, pos, deal, age):
    """Measured effect, shrunk from the narrowest cell up to position level."""
    est = cells.get(pos, {}).get('effect', 1.0)
    for key in (f'{pos}|{deal}', f'{pos}|{deal}|{band(age)}'):
        c = cells.get(key, {})
        if 'effect' in c:
            n = c['walk']['n']
            w = n / (n + SHRINK)
            est = w * c['effect'] + (1 - w) * est
    return min(1.0, est)


def main():
    players = json.load(open(os.path.join(DATA, 'players.json')))
    vpath = os.path.join(DATA, 'values', 'consensus.json')
    cons = json.load(open(vpath))
    ctx = json.load(open(os.path.join(DATA, 'context.json')))
    epath = os.path.join(DATA, 'contract_effects.json')
    if not os.path.exists(epath):
        print('contracts.py: no data/contract_effects.json — run ops/contract_study.py once; values left unadjusted')
        return
    cells = json.load(open(epath))['cells']
    seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
    season = int(seasons[-1])

    # salary rank at position = role security
    apys = {}
    for pid, c in ctx.items():
        con = c.get('contract') or {}
        pos = players.get(pid, {}).get('position')
        if con.get('apy') and pos in LF.POS:
            apys.setdefault(pos, []).append(con['apy'])
    starter_line = {p: sorted(v, reverse=True)[min(len(v), LF.NUM_TEAMS * max(1, LF.CORE.get(p, 1))) - 1]
                    for p, v in apys.items() if v}

    adjusted, cal = 0, []
    for pid, v in cons.items():
        market = v.get('mean_market', v.get('mean', 0))
        v['mean_market'] = market
        v['mean'] = market
        v.pop('contract', None)
        p = players.get(pid, {})
        pos, age, exp = p.get('position'), p.get('age'), p.get('years_exp')
        con = (ctx.get(pid) or {}).get('contract') or {}
        if pos not in LF.POS or not con:
            continue
        role = 'paid like a starter' if con.get('apy', 0) >= starter_line.get(pos, 9e9) else (
               'cheap veteran — replaceable' if (age or 0) >= 27 and con.get('apy', 0) < 3e6 else '')
        if con.get('fa_year') != season + 1:
            if role:
                v['contract'] = {'class': 'signed', 'fa_year': con.get('fa_year'), 'role': role, 'mult': 1.0}
            continue
        ftype = con.get('fa_type', 'UFA')
        if ftype in ('RFA', 'ERFA'):
            cls, eff = 'team_control', 1.0
        elif ftype == 'SFA' or market < MIN_VALUE:
            cls, eff = 'depth', 1.0
        elif exp is not None and exp <= 4 and con.get('apy', 0) < ROOKIE_APY:
            cls, eff = 'rookie_deal', effect_for(cells, pos, 'rookie', age)
        else:
            cls, eff = 'veteran', effect_for(cells, pos, 'veteran', age)
        mult = round(1 - future_share(age) * (1 - eff), 3)
        v['mean'] = round(market * mult, 1)
        v['contract'] = {'class': cls, 'fa_year': con['fa_year'], 'fa_type': ftype, 'effect': round(eff, 3),
                         'mult': mult, 'role': role}
        if mult < 1:
            adjusted += 1
        if cls in ('rookie_deal', 'veteran') and market >= 800:
            cal.append({'pid': pid, 'name': p.get('full_name'), 'pos': pos, 'age': age, 'team': p.get('team'),
                        'class': cls, 'market': round(market), 'adjusted': round(market * mult),
                        'mult': mult, 'effect': round(eff, 3), 'apy': con.get('apy'), 'role': role})
    json.dump(cons, open(vpath, 'w'))

    # who owns them -> buy / sell signal relative to the configured owner
    R = json.load(open(os.path.join(DATA, str(season), 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, str(season), 'users.json')))}
    owner = {pid: U.get(r.get('owner_id')) for r in R for pid in (r.get('players') or [])}
    me = json.load(open(os.path.join(ROOT, 'config.json'))).get('my_username')
    dl = (LF.PROFILE.get('trade_deadline_week') or None)
    for c in cal:
        c['owner'] = owner.get(c['pid'])
        mine = c['owner'] == me
        if c['owner'] is None:
            c['signal'] = 'free agent'
        elif mine and c['class'] == 'veteran':
            c['signal'] = f'SELL window: before the week-{dl} deadline' if dl else 'SELL window: before your trade deadline'
        elif mine:
            c['signal'] = 'HOLD: rookie-deal player, extension or tag is likely'
        elif c['class'] == 'rookie_deal':
            c['signal'] = f"BUY if offered at more than {round((1 - c['mult']) * 100)}% below market (the measured contract-year cut)"
        else:
            c['signal'] = f"DON'T pay full price: worth ~{round((1 - c['mult']) * 100)}% less until his March landing spot is known"
    cal.sort(key=lambda c: -c['market'])
    json.dump({'season': season, 'free_agency': f'NFL league year opens mid-March {season + 1} (exact date set by the NFL)',
               'trade_deadline_week': dl, 'players': cal}, open(os.path.join(DATA, 'contract_calendar.json'), 'w'), indent=1)
    big = sorted(cal, key=lambda c: c['adjusted'] - c['market'])[:5]
    print(f'contracts -> {adjusted} contract-year players adjusted (future seasons only); calendar: {len(cal)} players >= 800'
          + ('; biggest cuts: ' + ', '.join(f"{c['name']} {c['market']:,}->{c['adjusted']:,}" for c in big) if big else ''))


if __name__ == '__main__':
    main()
