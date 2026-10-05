#!/usr/bin/env python3
"""Contract cut risk (added 2026-10-04): how cheap each rostered player is to release, season by season.

OverTheCap's 32 team salary-cap pages list every contracted player for each season (2026 onward) with his cap number
and, per scenario, the dead money and cap savings if he is cut before June 1. That is the question a dynasty owner
asks about a veteran: "if he slips, can his team walk away for nothing?" A player whose dead money next season is
small next to his cap number is easy to cut; one with big guarantees left is protected.

Tiers for NEXT season (the offseason decision point), from what a pre-June-1 cut saves vs leaves as dead money:
  easy cut     saves >= $2M and at least twice the dead money
  cuttable     saves more than the dead money
  protected    the dead money is as big as the savings or bigger (guarantees left)
  not signed   no contract next season (free agent; the contract-year model in contracts.py covers him)
This is a rule from the contract terms, NOT a measured cut probability: a free historical record of dead money by
season does not exist, so nothing here is fitted. contracts.py adds the tier to the contract calendar; a SELL flag
needs an easy-cut veteran (RB 28+, WR/TE 30+, QB 34+).

Writes data/cap_risk.json {sleeper_id: {team, seasons: {year: {cap, dead_cut, save_cut}}, next_tier, next_dead_pct}}.
Cache: each team page for 24 hours (cuts and extensions land daily in season).
"""
import html, json, os, re, subprocess, sys, time, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache', 'otc_cap')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
SLUG = {
    'ARI': 'arizona-cardinals', 'ATL': 'atlanta-falcons', 'BAL': 'baltimore-ravens', 'BUF': 'buffalo-bills',
    'CAR': 'carolina-panthers', 'CHI': 'chicago-bears', 'CIN': 'cincinnati-bengals', 'CLE': 'cleveland-browns',
    'DAL': 'dallas-cowboys', 'DEN': 'denver-broncos', 'DET': 'detroit-lions', 'GB': 'green-bay-packers',
    'HOU': 'houston-texans', 'IND': 'indianapolis-colts', 'JAX': 'jacksonville-jaguars', 'KC': 'kansas-city-chiefs',
    'LV': 'las-vegas-raiders', 'LAC': 'los-angeles-chargers', 'LAR': 'los-angeles-rams', 'MIA': 'miami-dolphins',
    'MIN': 'minnesota-vikings', 'NE': 'new-england-patriots', 'NO': 'new-orleans-saints', 'NYG': 'new-york-giants',
    'NYJ': 'new-york-jets', 'PHI': 'philadelphia-eagles', 'PIT': 'pittsburgh-steelers', 'SF': 'san-francisco-49ers',
    'SEA': 'seattle-seahawks', 'TB': 'tampa-bay-buccaneers', 'TEN': 'tennessee-titans', 'WAS': 'washington-commanders',
}
VET_AGE = {'RB': 28, 'WR': 30, 'TE': 30, 'QB': 34}


def norm(n):
    n = unicodedata.normalize('NFKD', n or '').encode('ascii', 'ignore').decode().lower()
    n = re.sub(r"[.,'\-]", '', n)
    n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def money(s):
    s = (s or '').replace('$', '').replace(',', '').strip()
    neg = s.startswith('(') or s.startswith('-')
    s = s.strip('()-')
    return (-1 if neg else 1) * int(s) if s.isdigit() else 0


def page(team):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f'{team}.html')
    if not (os.path.exists(p) and os.path.getsize(p) > 50000 and time.time() - os.path.getmtime(p) < 86400):
        r = subprocess.run(['curl', '-sL', '--max-time', '60', '-A', UA, f'https://overthecap.com/salary-cap/{SLUG[team]}'],
                           capture_output=True, text=True)
        if r.returncode or 'contracted-players' not in r.stdout:
            return open(p).read() if os.path.exists(p) else ''          # keep yesterday's copy over nothing
        open(p, 'w').write(r.stdout)
    return open(p).read()


def parse(h):
    """{season: {normalized name: {cap, dead_cut, save_cut}}} from one team page."""
    out = {}
    for m in re.finditer(r'<table[^>]*contracted-players[^>]*>(.*?)</table>', h, re.S):
        yrs = re.findall(r'(?:id|data-year|class)="[^"]*?(20[2-4]\d)[^"]*"', h[max(0, m.start() - 3000):m.start()])
        if not yrs:
            continue
        season = int(yrs[-1])
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S):
            tds = re.findall(r'<td([^>]*)>(.*?)</td>', tr, re.S)
            if len(tds) < 10:
                continue
            name = html.unescape(re.sub(r'<[^>]+>', '', tds[0][1])).strip()
            cell = lambda cls: next((c for a, c in tds if cls in a), '')
            div = lambda c, k: (re.search(r'<div class="' + k + r'"[^>]*>(.*?)</div>', c, re.S) or [None, ''])[1]
            dead, save = cell('player-dead-money'), cell('player-cap-savings')
            cap_cells = [html.unescape(re.sub(r'<[^>]+>', '', c)).strip() for a, c in tds if 'cap-number' in a or 'player-cap' in a and 'savings' not in a]
            cap = money(cap_cells[0]) if cap_cells else 0
            if not cap:   # fall back to the largest plain money cell before the dead-money block
                plain = [money(html.unescape(re.sub(r'<[^>]+>', '', c))) for a, c in tds[:-2]]
                cap = max(plain) if plain else 0
            out.setdefault(season, {})[norm(name)] = {'name': name, 'cap': cap,
                                                      'dead_cut': money(div(dead, 'cut')), 'save_cut': money(div(save, 'cut'))}
    # injured reserve / PUP / suspended lists: this season's cap number only (their later seasons, if any, are in the
    # contracted tables above)
    cur = min(out) if out else None
    for m in re.finditer(r'<table[^>]*salary-cap-table non-active[^>]*>(.*?)</table>', h, re.S):
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S):
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
            if len(tds) == 2 and '/player/' in tds[0] and cur:
                name = html.unescape(re.sub(r'<[^>]+>', '', tds[0])).strip()
                out[cur].setdefault(norm(name), {'name': name, 'cap': money(re.sub(r'<[^>]+>', '', tds[1])), 'dead_cut': 0, 'save_cut': 0,
                                                 'list': True})
    return out


def find(rows_by_year, nm):
    """Seasons for one player: exact name, else unique last name + first initial (Matt / Matthew, Mike / Michael)."""
    hit = {y: rows[nm] for y, rows in rows_by_year.items() if nm in rows}
    if hit or ' ' not in nm:
        return hit
    first, last = nm[0], nm.split(' ')[-1]
    keys = {k for rows in rows_by_year.values() for k in rows if k.split(' ')[-1] == last and k[:1] == first}
    if len(keys) == 1:
        k = keys.pop()
        return {y: rows[k] for y, rows in rows_by_year.items() if k in rows}
    return {}


def tier(row):
    """Cutting him frees save_cut and leaves dead_cut on the books: teams cut when the first clearly beats the second."""
    if not row:
        return 'not signed', None
    pct = row['dead_cut'] / row['cap'] if row['cap'] > 0 else 1.0
    if row['save_cut'] >= 2_000_000 and row['save_cut'] >= 2 * row['dead_cut']:
        return 'easy cut', pct
    return ('cuttable' if row['save_cut'] > row['dead_cut'] else 'protected'), pct


def main():
    P = json.load(open(os.path.join(DATA, 'players.json')))
    latest = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))[-1]
    rosters = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
    rostered = {p for r in rosters for p in (r['players'] or [])}
    season = int(latest)
    by_team, failed = {}, []
    for t in SLUG:
        h = page(t)
        if not h:
            failed.append(t)
            continue
        by_team[t] = parse(h)
    out, unmatched = {}, []
    for pid in rostered:
        p = P.get(pid) or {}
        if p.get('position') not in VET_AGE or not p.get('team'):
            continue
        team = 'WAS' if p['team'] == 'WSH' else p['team']
        nm = norm(p.get('full_name'))
        seasons = find(by_team.get(team) or {}, nm)
        if not seasons:      # teams can differ between the two sites right after a move: unique match across the league
            hits = [t for t, yrs in by_team.items() if find(yrs, nm)]
            if len(hits) == 1:
                team = hits[0]
                seasons = find(by_team[team], nm)
        if not seasons:
            unmatched.append(p.get('full_name'))
            continue
        nt, pct = tier(seasons.get(season + 1))
        age = p.get('age')
        sell = nt == 'easy cut' and age is not None and age >= VET_AGE[p['position']]
        out[pid] = {'name': p.get('full_name'), 'pos': p['position'], 'team': team, 'age': age,
                    'seasons': {str(y): {k: v for k, v in r.items() if k != 'name'} for y, r in sorted(seasons.items())
                                if r['cap'] or r['dead_cut'] or r['save_cut']},     # $0 rows are void placeholder years
                    'next_tier': nt, 'next_dead_pct': None if pct is None else round(pct, 3), 'vet_easy_cut': sell}
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'), 'next_season': season + 1, 'players': out,
               'unmatched': sorted(unmatched), 'failed_teams': failed}, open(os.path.join(DATA, 'cap_risk.json'), 'w'), indent=1)
    from collections import Counter
    c = Counter(x['next_tier'] for x in out.values())
    print(f'cap risk -> data/cap_risk.json: {len(out)} rostered skill players matched to OverTheCap ({len(unmatched)} unmatched, '
          f'{len(failed)} team pages failed); {season + 1}: ' + ', '.join(f'{k} {v}' for k, v in c.most_common())
          + f'; veteran easy cuts {sum(x["vet_easy_cut"] for x in out.values())}')


if __name__ == '__main__':
    main()
