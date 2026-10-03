#!/usr/bin/env python3
"""College production for the prospect board, from the CollegeFootballData.com API.

Adds real college numbers (this season's passing / rushing / receiving lines and
usage share) to every player on the KTC devy board in data/prospects.json, and lists
transfer-portal moves. Writes data/college_stats.json, re-writes data/prospects.json
with a `stats` line per matched player, and appends a production table to
research/PROSPECTS.md. Run after ops/prospects.py (update.sh does).

The API needs a free key (Bearer token). It is read from $CFBD_API_KEY or from
~/.config/dynasty-scout/cfbd_key, never from the repo. Save it with
ops/set_cfbd_key.sh. With no key this script says so and exits 0, so the weekly
pipeline keeps working. Added 2026-10-02; endpoints checked against the API's own
OpenAPI document (v5.32.0) that day.
"""
import json, os, re, subprocess, sys, urllib.parse
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
API = 'https://api.collegefootballdata.com'
KEY_FILE = os.path.expanduser('~/.config/dynasty-scout/cfbd_key')


def api_key():
    k = os.environ.get('CFBD_API_KEY', '').strip()
    if not k and os.path.exists(KEY_FILE):
        k = open(KEY_FILE).read().strip()
    return k


def get(path, key, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    # key passed via a header file on stdin so it never appears in the process list
    r = subprocess.run(['curl', '-s', '-m', '60', '-w', '\n%{http_code}', '-H', '@-', url],
                       input=f'Authorization: Bearer {key}\nAccept: application/json\n',
                       capture_output=True, text=True)
    body, _, code = r.stdout.rpartition('\n')
    if code != '200':
        raise RuntimeError(f'{path} returned HTTP {code}')
    return json.loads(body)


# KTC name -> CFBD name, where they differ (verified with /player/search on 2026-10-02)
ALIASES = {'Hollywood Smothers': 'Daylan Smothers', 'Ryan Coleman-Williams': 'Ryan Williams'}


def norm(name):
    """'Mark Fletcher Jr.' and 'Mark Fletcher' match; punctuation and case ignored."""
    n = re.sub(r"[^a-z ]", '', name.lower().replace('.', '').replace('-', ' '))
    return ' '.join(w for w in n.split() if w not in ('jr', 'sr', 'ii', 'iii', 'iv'))


def collect(key, season):
    """{normalized name: {'name','team','pos', 'passing':{...}, 'rushing':{...}, 'receiving':{...}, 'usage':x}}"""
    players = {}
    for cat in ('passing', 'rushing', 'receiving'):
        for row in get('/stats/player/season', key, year=season, category=cat):
            k = norm(row['player'])
            p = players.setdefault((k, row['team']), {'name': row['player'], 'team': row['team'],
                                                     'pos': row.get('position')})
            try:
                p.setdefault(cat, {})[row['statType']] = float(row['stat'])
            except (TypeError, ValueError):
                pass
    for row in get('/player/usage', key, year=season):
        p = players.get((norm(row['name']), row['team']))
        if p and (row.get('usage') or {}).get('overall') is not None:
            p['usage'] = row['usage']['overall']
    return players


def line(p):
    out = []
    pa, ru, re_ = p.get('passing', {}), p.get('rushing', {}), p.get('receiving', {})
    if pa.get('YDS'):
        out.append(f"{int(pa.get('YDS', 0)):,} pass yds, {int(pa.get('TD', 0))} TD, {int(pa.get('INT', 0))} INT")
    if ru.get('YDS') and ru.get('CAR', 0) >= 10:
        out.append(f"{int(ru.get('CAR', 0))} car, {int(ru['YDS']):,} yds, {int(ru.get('TD', 0))} TD")
    if re_.get('REC'):
        out.append(f"{int(re_['REC'])} rec, {int(re_.get('YDS', 0)):,} yds, {int(re_.get('TD', 0))} TD")
    if p.get('usage') is not None:
        out.append(f"{p['usage'] * 100:.0f}% usage")
    return ' · '.join(out)


def main():
    key = api_key()
    if not key:
        print(f'cfbd.py: no CollegeFootballData API key yet ({KEY_FILE}) — college stats skipped. '
              f'Save one with ops/set_cfbd_key.sh')
        return
    season = max(json.load(open(os.path.join(DATA, 'seasons.json'))))
    try:
        players = collect(key, season)
        portal = get('/player/portal', key, year=season)
    except RuntimeError as e:
        print(f'cfbd.py: API call failed ({e}) — college stats NOT refreshed (a 401 means the key is wrong or expired)')
        return
    pros_path = os.path.join(DATA, 'prospects.json')
    pros = json.load(open(pros_path))
    by_name = {}
    for (k, _team), p in players.items():
        by_name.setdefault(k, []).append(p)
    matched, missing = 0, []
    for b in pros['board']:
        cands = by_name.get(norm(ALIASES.get(b['name'], b['name'])), [])
        if not cands:
            b.pop('stats', None)
            missing.append(b['name'])
            continue
        # same name at two schools: take the one with more production
        best = max(cands, key=lambda p: sum((p.get(c) or {}).get('YDS', 0) for c in ('passing', 'rushing', 'receiving')))
        b['stats'] = line(best)
        b['college_team'] = best['team']
        matched += 1
    json.dump(pros, open(pros_path, 'w'))
    keep_pos = {'QB', 'RB', 'WR', 'TE'}
    moves = [t for t in portal if t.get('position') in keep_pos]
    json.dump({'date': date.today().isoformat(), 'season': season, 'matched': matched,
               'unmatched': missing, 'portal': moves}, open(os.path.join(DATA, 'college_stats.json'), 'w'))
    L = ['', f'## College production ({season} season, CollegeFootballData.com, {date.today().isoformat()})', '',
         '| Player | Pos | KTC class | Team | This season |', '|---|---|---|---|---|']
    for b in pros['board']:
        if b.get('stats') and (b['cls'] or 0) >= 2027:
            L.append(f"| {b['name']} | {b['pos']} | {b['cls']} | {b.get('college_team', '')} | {b['stats']} |")
    if missing:
        L += ['', f'_No CFBD match for {len(missing)} board names (name spelling or no stats yet): '
              + ', '.join(missing[:25]) + ('…' if len(missing) > 25 else '') + '_']
    md = os.path.join(ROOT, 'research', 'PROSPECTS.md')
    base = open(md).read().split('\n## College production')[0].rstrip('\n')   # replace, never stack
    open(md, 'w').write(base + '\n' + '\n'.join(L) + '\n')
    print(f'cfbd -> college stats for {matched}/{len(pros["board"])} prospects; '
          f'{len(moves)} QB/RB/WR/TE portal moves ({season})')


if __name__ == '__main__':
    main()
