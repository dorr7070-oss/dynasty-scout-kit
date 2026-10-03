#!/usr/bin/env python3
"""Injury outlook for every injured rostered player -> data/injury_outlook.json, INJURIES.md, dashboard.

Uses the measured history in data/injury_effects.json (ops/injury_study.py):
  Questionable / Doubtful -> P(plays this week) by his latest practice status (Full / Limited / DNP)
  Out / IR / PUP          -> expected further games missed for that injury type, CONDITIONAL on the
                             games he has already missed (from snap counts this season), the
                             expected return week, and the season-ending rate for the injury type
Value read: the share of his remaining regular season expected to be lost, set against how far his
market value has moved (data/value_trends.json). A big market drop on a short expected absence is a
BUY-LOW; a small drop on a long one means the market has not priced it yet (SELL before it does).
Run after usage_adv.py and value_trends.py; weekly.py reads p_play from here.
"""
import csv, json, os, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import injury_study as IS  # noqa: E402

OUT_STATUSES = ('Out', 'IR', 'PUP', 'Sus', 'NA', 'DNR')


def main():
    ep = os.path.join(DATA, 'injury_effects.json')
    if not os.path.exists(ep):
        print('injuries.py: no data/injury_effects.json (run ops/injury_study.py) — skipped')
        return
    eff = json.load(open(ep))
    P = json.load(open(os.path.join(DATA, 'players.json')))
    season = max(d for d in os.listdir(DATA) if d.isdigit())
    R = json.load(open(os.path.join(DATA, season, 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, season, 'users.json')))}
    owner = {pid: U.get(r.get('owner_id')) for r in R for pid in (r.get('players') or [])}
    usage = json.load(open(os.path.join(DATA, 'usage.json'))) if os.path.exists(os.path.join(DATA, 'usage.json')) else {}
    cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
    vt = json.load(open(os.path.join(DATA, 'value_trends.json'))) if os.path.exists(os.path.join(DATA, 'value_trends.json')) else {}
    moved = {m['pid']: (m['w'] if m['w'] is not None else m['m']) for m in vt.get('movers', [])}
    me = json.load(open(os.path.join(ROOT, 'config.json'))).get('my_username')

    import weekly as W   # shares its 6-hour cache of nfldata games.csv (first run downloads it here)
    W.fetch(W.GAMES_URL, os.path.join(CACHE, 'games.csv'), 6 * 3600)
    games = [g for g in csv.DictReader(open(os.path.join(CACHE, 'games.csv'), encoding='utf-8'))
             if g['season'] == season and g['game_type'] == 'REG'] if os.path.exists(os.path.join(CACHE, 'games.csv')) else []
    played_wk = {}            # team -> sorted weeks already played
    left = {}                 # team -> remaining regular-season games
    for g in games:
        for t in (g['home_team'], g['away_team']):
            t = {'LA': 'LAR'}.get(t, t)
            (played_wk.setdefault(t, []) if g['home_score'] else left.setdefault(t, [])).append(int(g['week']))
    reg_end = LF.PROFILE.get('playoff_week_start') or 15

    # latest practice status this season (gsis -> row), mapped to sleeper ids via the roster crosswalk
    gs = {}
    rp = os.path.join(CACHE, f'roster_{season}.csv')
    if os.path.exists(rp):
        gs = {r['gsis_id']: r['sleeper_id'] for r in csv.DictReader(open(rp, encoding='utf-8')) if r.get('sleeper_id')}
    prac = {}
    ip = os.path.join(CACHE, f'injuries_{season}.csv')
    for r in csv.DictReader(open(ip, encoding='utf-8')) if os.path.exists(ip) else []:
        sid = gs.get(r['gsis_id'])
        if sid and r['week'].isdigit() and int(r['week']) >= prac.get(sid, {}).get('week', 0):
            prac[sid] = {'week': int(r['week']), 'practice': IS.practice(r['practice_status']),
                         'report': r['report_status'], 'injury': r['report_primary_injury'] or r['practice_primary_injury']}

    rows = []
    for pid, own in owner.items():
        p = P.get(pid, {})
        st = p.get('injury_status')
        pr = prac.get(pid, {})
        if p.get('position') not in LF.POS or not (st or pr.get('report') in ('Out', 'Doubtful', 'Questionable')):
            continue
        st = st or pr.get('report')
        team = p.get('team')
        inj_txt = p.get('injury_body_part') or pr.get('injury') or ''
        b = IS.bucket(inj_txt)
        val = round(cons.get(pid, {}).get('mean_market', cons.get(pid, {}).get('mean', 0)))
        row = {'pid': pid, 'name': p.get('full_name'), 'pos': p.get('position'), 'team': team, 'owner': own,
               'status': st, 'injury': inj_txt or '—', 'bucket': b, 'value': val, 'practice': pr.get('practice')}
        if st in ('Questionable', 'Doubtful'):
            k = f"{st}|{pr.get('practice') or 'none'}"
            g = eff['gameday'].get(k) or eff['gameday'].get(f'{st}|none') or {}
            row['p_play'] = g.get('p_play')
            row['read'] = f"plays {row['p_play']:.0%} of the time with that practice status" if row['p_play'] is not None else ''
        elif st in OUT_STATUSES:
            wk = (usage.get(pid) or {}).get('wk') or {}
            snapped = sorted(int(w) for w, x in wk.items() if (x.get('snap') or 0) > 0)
            tp = played_wk.get(team, [])
            last = snapped[-1] if snapped else 0
            missed = sum(1 for w in tp if w > last) if tp else 0
            m = eff['missed'].get(b or '', {})
            more = (m.get('more_given_missed') or {}).get(str(missed)) if missed else m.get('median')
            if more is None and m:
                ks = [int(x) for x in (m.get('more_given_missed') or {}) if int(x) <= missed]
                more = m['more_given_missed'][str(max(ks))] if ks else m.get('median')
            rem = [w for w in left.get(team, []) if w < reg_end]
            row.update(missed=missed, exp_more=more, p_season_ending=m.get('p_season_ending'),
                       return_week=(rem[int(round(more))] if more is not None and int(round(more)) < len(rem) else None),
                       season_share_lost=round(min(1.0, (more or 0) / len(rem)), 2) if rem else None,
                       n=m.get('n'))
            if st == 'IR' and missed < 4:
                row['note'] = 'on IR: at least 4 games by rule'
            if not m and b in ('acl', 'achilles'):
                # Too few OUT spells to measure (these players go straight to IR and drop off the weekly
                # report), but a torn ACL or Achilles normally ends the season — never price it as short.
                row.update(exp_more=None, return_week=None, season_share_lost=1.0, p_season_ending=None)
            mv = moved.get(pid)
            row['market_move'] = mv
            share = row['season_share_lost'] or 0
            row['read'] = (f"~{more:g} more game{'s' if more != 1 else ''} expected"
                           + (f" (back about week {row['return_week']})" if row['return_week'] else ' (likely beyond the regular season)')
                           + f"; {m.get('p_season_ending', 0):.0%} of {b} OUT spells ended the season" if m else 'no history for this injury type')
            if not m:
                row['read'] = ('torn ACL/Achilles: normally season-ending (not modelled — too few OUT spells on the weekly reports)'
                               if b in ('acl', 'achilles') else 'no measured history for this injury type')
            elif mv is not None and own != me and mv <= -0.15 and share <= 0.35:
                row['signal'] = 'BUY-LOW: market fell further than the expected absence'
            elif own == me and (mv is None or mv > -0.10) and share >= 0.5:
                row['signal'] = 'market has not priced the absence yet — sell before it does'
        rows.append(row)
    rows.sort(key=lambda r: (r['owner'] != me, -r['value']))
    json.dump({'season': season, 'players': rows}, open(os.path.join(DATA, 'injury_outlook.json'), 'w'), indent=1)

    L = ['# Injury Outlook', '', f"_Measured on {eff['window']} (ops/injury_study.py). Game-day odds come from how often "
         'players with that status and practice level actually took a snap; time missed counts the team\'s games until he '
         'played again, conditional on games already missed._', '',
         '| Player | Owner | Status | Injury | Outlook | Signal |', '|---|---|---|---|---|---|']
    for r in rows:
        if r['value'] >= 500 or r['owner'] == me:
            L.append(f"| {r['name']} ({r['pos']} {r['team']}) | {r['owner']} | {r['status']}{' · ' + r['practice'] if r.get('practice') else ''} | "
                     f"{r['injury']} | {r.get('read', '')}{' · ' + r['note'] if r.get('note') else ''} | {r.get('signal', '')} |")
    open(os.path.join(ROOT, 'INJURIES.md'), 'w').write('\n'.join(L) + '\n')
    mine = [r for r in rows if r['owner'] == me]
    print(f"injuries -> INJURIES.md: {len(rows)} injured rostered players; yours: "
          + '; '.join(f"{r['name']} {r['status']} ({r.get('read', '')[:60]})" for r in mine[:4]))


if __name__ == '__main__':
    main()
