#!/usr/bin/env python3
"""Read the league's own settings from whatever platform it lives on -> data/league_profile.json + LEAGUE.md

    python3 ops/league_profile.py                      # uses config.json (league_url / platform + league_id)
    python3 ops/league_profile.py <league link or id>  # detect platform, save to config.json, read settings

Supported: Sleeper (public, no login), ESPN (public leagues; private leagues need the owner's
espn_s2 + SWID cookies, saved with set_platform_login.py), Yahoo (needs the owner's Yahoo
developer app + one-time consent, saved with set_platform_login.py).

Everything downstream reads the NEUTRAL profile this writes (via ops/league_format.py), so
no analysis assumes Sleeper, a lineup, a scoring system or a draft rule. What no platform
exposes (the rookie draft-order rule, league bylaws) is listed under "unknowns" so onboarding
asks the owner once. Field-by-field review: docs/LEAGUE_SETTINGS.md (2026-10-02).
"""
import json, os, re, subprocess, sys, time, urllib.parse
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CFG_PATH = os.path.join(ROOT, 'config.json')
if not os.path.exists(CFG_PATH) and os.path.exists(os.path.join(ROOT, 'config.template.json')):
    import shutil  # kit clones ship config.template.json; config.json is personal and git-ignored
    shutil.copy(os.path.join(ROOT, 'config.template.json'), CFG_PATH)
LOGIN_DIR = os.path.join(os.path.expanduser('~'), '.config', 'dynasty-scout')
OUT = os.path.join(DATA, 'league_profile.json')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/128'

FLEX_NAMES = {   # neutral flex name -> eligible positions
    'FLEX': ['RB', 'WR', 'TE'], 'WRRB_FLEX': ['RB', 'WR'], 'REC_FLEX': ['WR', 'TE'],
    'SUPER_FLEX': ['QB', 'RB', 'WR', 'TE'],
}


# ----------------------------------------------------------------- detection
def detect(ref):
    """League link or id -> (platform, league_id)."""
    ref = (ref or '').strip()
    if m := re.search(r'sleeper\.(?:com|app)/leagues/(\d+)', ref):
        return 'sleeper', m.group(1)
    if 'espn.com' in ref and (m := re.search(r'leagueId=(\d+)', ref)):
        return 'espn', m.group(1)
    if m := re.search(r'fantasysports\.yahoo\.com/(?:f1|nfl)/(\d+)', ref):
        return 'yahoo', m.group(1)
    if re.fullmatch(r'\d{15,20}', ref):
        return 'sleeper', ref                       # Sleeper ids are long numbers
    raise SystemExit(f'league_profile: cannot tell which platform "{ref}" is. Paste the league link '
                     f'from your browser (sleeper.com/leagues/..., fantasy.espn.com/...leagueId=..., '
                     f'football.fantasysports.yahoo.com/f1/...)')


def curl_json(url, headers=None):
    hdr = ''.join(f'{k}: {v}\n' for k, v in (headers or {}).items())
    r = subprocess.run(['curl', '-s', '-m', '40', '-A', UA, '-w', '\n%{http_code}', '-H', '@-', url],
                       input=hdr, capture_output=True, text=True)
    body, _, code = r.stdout.rpartition('\n')
    return int(code or 0), (json.loads(body) if body.strip().startswith(('{', '[')) else None)


def login(name):
    p = os.path.join(LOGIN_DIR, f'{name}.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None


# ----------------------------------------------------------------- Sleeper
def read_sleeper(lid):
    code, lg = curl_json(f'https://api.sleeper.app/v1/league/{lid}')
    if code != 200 or not lg:
        raise SystemExit(f'league_profile: Sleeper returned HTTP {code} for league {lid} — check the id')
    st, sc, slots = lg.get('settings') or {}, lg.get('scoring_settings') or {}, lg.get('roster_positions') or []
    core = {p: slots.count(p) for p in ('QB', 'RB', 'WR', 'TE', 'K', 'DEF')}
    idp = sum(slots.count(p) for p in ('DL', 'LB', 'DB', 'IDP_FLEX'))
    return {
        'platform': 'sleeper', 'league_id': lid, 'season': lg.get('season'), 'name': lg.get('name'),
        'num_teams': st.get('num_teams') or lg.get('total_rosters'),
        'league_type': {0: 'redraft', 1: 'keeper', 2: 'dynasty'}.get(st.get('type'), 'unknown'),
        'slots': core, 'idp_slots': idp,
        'flex': [FLEX_NAMES[s] for s in slots if s in FLEX_NAMES],
        'bench': slots.count('BN'), 'ir_slots': st.get('reserve_slots', 0),
        'taxi': {'slots': st.get('taxi_slots', 0), 'years': st.get('taxi_years', 0)},
        'scoring': {'rec': sc.get('rec', 0), 'te_premium': sc.get('bonus_rec_te', 0), 'pass_td': sc.get('pass_td', 4),
                    'first_down': (sc.get('rush_fd', 0) or 0) + (sc.get('rec_fd', 0) or 0), 'carry': sc.get('rush_att', 0)},
        'playoff': {'teams': st.get('playoff_teams'), 'start_week': st.get('playoff_week_start'),
                    'reseed': bool(st.get('playoff_seed_type'))},
        'median_game': bool(st.get('league_average_match')),
        # Sleeper uses week 99 for 'no deadline'
        'trade_deadline_week': st.get('trade_deadline') if (st.get('trade_deadline') or 99) <= 18 else None,
        'pick_trading': bool(st.get('pick_trading', 1)),
        'waivers': {'faab': st.get('waiver_type') == 2, 'budget': st.get('waiver_budget')},
        'rookie_draft_rounds': st.get('draft_rounds'),
        'raw_ref': f'https://api.sleeper.app/v1/league/{lid}',
    }


# ----------------------------------------------------------------- ESPN
ESPN_SLOT = {0: 'QB', 2: 'RB', 4: 'WR', 6: 'TE', 16: 'DEF', 17: 'K'}
ESPN_FLEX = {23: 'FLEX', 3: 'WRRB_FLEX', 5: 'REC_FLEX', 7: 'SUPER_FLEX'}
ESPN_IDP = (8, 9, 10, 11, 12, 13, 14, 15)


def read_espn(lid, season):
    cookies = login('espn') or {}
    hdr = {'Cookie': f"espn_s2={cookies['espn_s2']}; SWID={cookies['swid']}"} if cookies else {}
    code, lg = curl_json(f'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}'
                         f'/segments/0/leagues/{lid}?view=mSettings&view=mTeam', hdr)
    if code == 401:
        raise SystemExit('league_profile: this ESPN league is private. Save your ESPN login cookies with '
                         '"python set_platform_login.py espn" (see ONBOARDING.md), then run this again.')
    if code != 200 or not lg:
        raise SystemExit(f'league_profile: ESPN returned HTTP {code} for league {lid} ({season})')
    s = lg['settings']
    counts = {int(k): v for k, v in (s['rosterSettings'].get('lineupSlotCounts') or {}).items()}
    core = {p: 0 for p in ('QB', 'RB', 'WR', 'TE', 'K', 'DEF')}
    flex = []
    for sid, n in counts.items():
        if sid in ESPN_SLOT:
            core[ESPN_SLOT[sid]] += n
        elif sid in ESPN_FLEX:
            flex += [FLEX_NAMES[ESPN_FLEX[sid]]] * n
    items = {i['statId']: i for i in s['scoringSettings'].get('scoringItems', [])}
    rec = items.get(53, {}).get('points', 0)
    te_rec = (items.get(53, {}).get('pointsOverrides') or {}).get('6')
    sched, acq = s.get('scheduleSettings', {}), s.get('acquisitionSettings', {})
    reg = sched.get('matchupPeriodCount')
    dl = s.get('tradeSettings', {}).get('deadlineDate')
    return {
        'platform': 'espn', 'league_id': lid, 'season': str(season), 'name': s.get('name'),
        'num_teams': s.get('size') or len(lg.get('teams', [])),
        'league_type': 'keeper' if s.get('draftSettings', {}).get('keeperCount') else 'redraft',
        'slots': core, 'idp_slots': sum(counts.get(i, 0) for i in ESPN_IDP), 'flex': flex,
        'bench': counts.get(20, 0), 'ir_slots': counts.get(21, 0), 'taxi': {'slots': 0, 'years': 0},
        'scoring': {'rec': rec, 'te_premium': (te_rec - rec) if te_rec is not None else 0,
                    'pass_td': items.get(4, {}).get('points', 4), 'first_down': 0, 'carry': 0},
        'playoff': {'teams': sched.get('playoffTeamCount'), 'start_week': (reg + 1) if reg else None,
                    'reseed': False},
        'median_game': s.get('scoringSettings', {}).get('scoringEnhancementType') == 'WIN_BONUS_TOP_HALF',
        'trade_deadline_date': time.strftime('%Y-%m-%d', time.gmtime(dl / 1000)) if dl else None,
        'pick_trading': False,
        'waivers': {'faab': bool(acq.get('isUsingAcquisitionBudget')), 'budget': acq.get('acquisitionBudget')},
        'rookie_draft_rounds': None,
        'raw_ref': f'ESPN league {lid} season {season}',
    }


# ----------------------------------------------------------------- Yahoo
YAHOO_FLEX = {'W/R/T': 'FLEX', 'W/R': 'WRRB_FLEX', 'W/T': 'REC_FLEX', 'Q/W/R/T': 'SUPER_FLEX'}


def yahoo_token():
    """Refresh the owner's Yahoo OAuth token (saved by set_platform_login.py yahoo)."""
    y = login('yahoo')
    if not y:
        raise SystemExit('league_profile: Yahoo needs a one-time login. Run "python set_platform_login.py yahoo" '
                         '(see ONBOARDING.md), then run this again.')
    if y.get('expires_at', 0) > time.time() + 60:
        return y['access_token']
    body = urllib.parse.urlencode({'grant_type': 'refresh_token', 'refresh_token': y['refresh_token'],
                                   'redirect_uri': 'oob'})
    import base64
    basic = base64.b64encode(f"{y['client_id']}:{y['client_secret']}".encode()).decode()
    r = subprocess.run(['curl', '-s', '-m', '40', '-X', 'POST', '-H', f'Authorization: Basic {basic}',
                        '-H', 'Content-Type: application/x-www-form-urlencoded', '--data-binary', '@-',
                        'https://api.login.yahoo.com/oauth2/get_token'], input=body, capture_output=True, text=True)
    tok = json.loads(r.stdout or '{}')
    if 'access_token' not in tok:
        raise SystemExit('league_profile: Yahoo token refresh failed — run "python set_platform_login.py yahoo" again')
    y.update(access_token=tok['access_token'], expires_at=time.time() + int(tok.get('expires_in', 3600)),
             refresh_token=tok.get('refresh_token', y['refresh_token']))
    json.dump(y, open(os.path.join(LOGIN_DIR, 'yahoo.json'), 'w', encoding='utf-8'))
    return y['access_token']


def read_yahoo(lid):
    tok = yahoo_token()
    code, d = curl_json(f'https://fantasysports.yahooapis.com/fantasy/v2/league/nfl.l.{lid}/settings?format=json',
                        {'Authorization': f'Bearer {tok}'})
    if code != 200 or not d:
        raise SystemExit(f'league_profile: Yahoo returned HTTP {code} for league {lid}')
    lg = d['fantasy_content']['league']
    meta, st = lg[0], lg[1]['settings'][0]
    core = {p: 0 for p in ('QB', 'RB', 'WR', 'TE', 'K', 'DEF')}
    flex, bench, ir, idp = [], 0, 0, 0
    for rp in st.get('roster_positions', []):
        pos, n = rp['roster_position']['position'], int(rp['roster_position'].get('count', 1))
        if pos in core:
            core[pos] += n
        elif pos in YAHOO_FLEX:
            flex += [FLEX_NAMES[YAHOO_FLEX[pos]]] * n
        elif pos == 'BN':
            bench += n
        elif pos == 'IR':
            ir += n
        elif pos in ('DL', 'LB', 'DB', 'D', 'DT', 'DE', 'CB', 'S'):
            idp += n
    mods = {int(m['stat']['stat_id']): float(m['stat']['value'])
            for m in (st.get('stat_modifiers') or {}).get('stats', [])}
    return {
        'platform': 'yahoo', 'league_id': lid, 'season': str(meta.get('season')), 'name': meta.get('name'),
        'num_teams': int(meta.get('num_teams') or 0),
        'league_type': 'keeper' if st.get('uses_keepers') else 'redraft',
        'slots': core, 'idp_slots': idp, 'flex': flex, 'bench': bench, 'ir_slots': ir,
        'taxi': {'slots': 0, 'years': 0},
        'scoring': {'rec': mods.get(11, 0), 'te_premium': 0, 'pass_td': mods.get(5, 4), 'first_down': 0, 'carry': 0},
        'playoff': {'teams': int(st.get('num_playoff_teams') or 0) or None,
                    'start_week': int(st.get('playoff_start_week') or 0) or None,
                    'reseed': st.get('uses_playoff_reseeding') in (1, '1')},
        'median_game': False,
        'trade_deadline_date': st.get('trade_end_date'),
        'pick_trading': st.get('can_trade_draft_picks') in (1, '1') or st.get('draft_pick_trading') in (1, '1'),
        'waivers': {'faab': st.get('uses_faab') in (1, '1'), 'budget': None},
        'rookie_draft_rounds': None,
        'raw_ref': f'Yahoo league nfl.l.{lid}',
    }


# ----------------------------------------------------------------- write
def finish(p, cfg):
    p['superflex'] = p['slots']['QB'] >= 2 or any('QB' in f for f in p['flex'])
    ppr = float(p['scoring']['rec'] or 0)
    p['format_label'] = (f"{p['num_teams']}-team {'superflex' if p['superflex'] else '1QB'} "
                         f"{'PPR' if ppr >= 1 else 'half-PPR' if ppr >= 0.5 else 'standard'}"
                         f"{' + TE premium' if p['scoring']['te_premium'] else ''}")
    p['draft_order'] = cfg.get('draft_order')
    p['read_at'] = date.today().isoformat()
    unknowns = []
    if not p['draft_order']:
        unknowns.append('How is the rookie draft order set? (reverse record / a lottery and how / Max PF / '
                        'playoff finish for playoff teams) — no platform exposes it; it decides every pick value')
    if p['platform'] == 'espn':
        unknowns.append('ESPN has no future-pick trading or taxi squad: pick values are informational only')
    if p['league_type'] == 'redraft':
        unknowns.append('The platform calls this a redraft league: dynasty values assume players carry over — confirm the league is dynasty/keeper')
    if p['idp_slots']:
        unknowns.append(f"{p['idp_slots']} IDP starting slots: dynasty values here cover offense only")
    if p['scoring']['first_down'] or p['scoring']['carry']:
        unknowns.append('Points per first down / carry: projections use standard PPR math and may undervalue RBs')
    p['unknowns'] = unknowns
    return p


def write_md(p):
    flex = ', '.join('/'.join(f) for f in p['flex']) or 'none'
    L = [f"# {p['name']}", '',
         f"_Read from {p['platform'].title()} on {p['read_at']} by `ops/league_profile.py`. Re-run it whenever the "
         f"commissioner changes settings._", '',
         f"**Format:** {p['format_label']}", '',
         '| Setting | Value |', '|---|---|',
         f"| Platform / league | {p['platform']} · {p['league_id']} · season {p['season']} |",
         f"| League type | {p['league_type']} |",
         f"| Starters | {', '.join(f'{k} {v}' for k, v in p['slots'].items() if v)} · flex: {flex} |",
         f"| Bench / IR / taxi | {p['bench']} / {p['ir_slots']} / {p['taxi']['slots']} (taxi years {p['taxi']['years']}) |",
         f"| Scoring | {p['scoring']['rec']:g} per catch · TE premium {p['scoring']['te_premium']:g} · pass TD {p['scoring']['pass_td']:g} |",
         f"| Playoffs | {p['playoff']['teams']} teams from week {p['playoff']['start_week']}{' (reseeded)' if p['playoff']['reseed'] else ''} |",
         f"| Median game | {'yes' if p['median_game'] else 'no'} |",
         f"| Trade deadline | {p.get('trade_deadline_week') and 'week ' + str(p['trade_deadline_week']) or p.get('trade_deadline_date') or 'none set'} |",
         f"| Draft-pick trading | {'yes' if p['pick_trading'] else 'no'} · rookie rounds {p['rookie_draft_rounds'] or 'n/a'} |",
         f"| Waivers | {'FAAB $' + str(p['waivers']['budget']) if p['waivers']['faab'] else 'priority'} |",
         f"| Draft order rule | {(p['draft_order'] or {}).get('rule', '**not set — ask the owner**')} |", '']
    if p['unknowns']:
        L += ['## Still needed from the owner', ''] + [f'- {u}' for u in p['unknowns']] + ['']
    open(os.path.join(ROOT, 'LEAGUE.md'), 'w', encoding='utf-8').write('\n'.join(L))


def main():
    cfg = json.load(open(CFG_PATH, encoding='utf-8')) if os.path.exists(CFG_PATH) else {}
    if len(sys.argv) > 1:
        plat, lid = detect(sys.argv[1])
        cfg.update(platform=plat, league_id=lid, league_url=sys.argv[1])
        json.dump(cfg, open(CFG_PATH, 'w', encoding='utf-8'), indent=2)
    else:
        plat = cfg.get('platform') or detect(cfg.get('league_url') or cfg.get('league_id', ''))[0]
        lid = cfg.get('league_id') or detect(cfg.get('league_url', ''))[1]
    season = cfg.get('season') or (date.today().year if date.today().month >= 3 else date.today().year - 1)
    p = {'sleeper': lambda: read_sleeper(lid), 'espn': lambda: read_espn(lid, season),
         'yahoo': lambda: read_yahoo(lid)}[plat]()
    p = finish(p, cfg)
    os.makedirs(DATA, exist_ok=True)
    json.dump(p, open(OUT, 'w', encoding='utf-8'), indent=2)
    write_md(p)
    print(f"league profile -> data/league_profile.json + LEAGUE.md: {p['name']} — {p['format_label']}"
          + (f" · {len(p['unknowns'])} question(s) for the owner" if p['unknowns'] else ''))


if __name__ == '__main__':
    main()
