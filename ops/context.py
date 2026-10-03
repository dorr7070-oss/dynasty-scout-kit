#!/usr/bin/env python3
"""Player CONTEXT the value sources do not carry: availability, contract, depth.

Consensus values price a player's dynasty worth. They say nothing about whether
he is on IR this week, whether he is playing out the last year of his deal, or
whether the guy directly behind him on the depth chart is already on my roster.
Those three facts move real decisions:

  availability - an IR/PUP/Suspended starter is a lineup hole NOW, and a
                 Questionable tag on a thin-margin week is a start/sit call.
                 Sleeper carries live designations; they change midweek, so
                 fetch.py refreshes players.json daily during the season.
  contract     - the walk year is the dynasty tell. A 27-year-old WR entering
                 free agency can land anywhere; a just-extended one is locked
                 into a known offense. It cuts both ways, so this file only
                 FLAGS the walk year, it does not adjust value.
  handcuff     - who is directly behind my starter, and who owns him. Owning
                 your own RB1's backup converts an injury from a lost season
                 into a lateral move; a rival owning it is leverage against you.

Sources:
  Sleeper players.json  - injury_status / injury_body_part / injury_notes /
                          status / practice_participation / depth_chart_*
                          (already cached by fetch.py; no extra request)
  OverTheCap            - per-position contract tables, current through today.
                          The "Free Agency" column ("2029 UFA", "2031 Void") is
                          the walk-year signal: walk year == fa_year - 1.

Deliberately NOT used: nflverse historical_contracts. Its release timestamp
updates daily but the DATA stops at contracts signed in 2022 - no player who
signed after that appears at all (recent signings are missing),
so it cannot answer "is this a contract year". Re-check before re-adding it.

Suspensions: Sleeper flags SERVED suspensions (injury_status 'Sus'/'NA') and
those are captured here. There is no free structured feed for PENDING or
threatened discipline - that stays a manual note in profiles/.

Also team-level context, attached to every player on that team:
  bye         - the week his team does not play (from the nflverse schedule).
                Two starters sharing a bye is a real, knowable roster hole.
  playoff SOS - weeks 15-17 are this league's playoffs. Those opponents are
                already known, so how hard they are at HIS position is knowable
                today. Defensive strength is measured as PPR points allowed per
                game to that position, from last season's box scores.
  new_hc      - a new head coach rewrites the offense, and that moves value
                more than most injuries. Parsed from the Wikipedia season page.
                NOTE: coordinator-only changes are NOT here - no free source
                publishes a league-wide OC table - so an OC swap under a
                retained head coach still needs a manual profile note.
  age_flag    - set when a player is at or past the age where his position
                historically starts losing production, per data/age_curve.json
                (derived by ops/age_curve.py from real year-over-year retention,
                NOT from folklore). Only RB currently qualifies: the data shows
                a hard 27->28 break and no defensible cliff for WR/TE/QB.

Writes data/context.json: {sleeper_id: {avail, injury, contract, depth,
handcuff, bye, sos, new_hc, age_flag}}
Stdlib only. Runs after values.py, before profiles/advise.
"""
import csv, html, json, os, re, subprocess, unicodedata
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
POS = {'QB': 'quarterback', 'RB': 'running-back',
       'WR': 'wide-receiver', 'TE': 'tight-end'}
MIN_DEF_WEEKS = 3      # weeks of box scores before the current season is usable
MIN_DEF_TEAMS = 28     # ...and it must cover nearly every defense

# Sleeper designations that mean "not available to start right now", worst first.
OUT = {'IR': 'IR', 'PUP': 'PUP', 'Sus': 'SUSPENDED', 'NA': 'NA', 'DNR': 'DNR'}

# DOWNSIDE multipliers -> the optional `adj` value. Read the name carefully:
# `adj` is NOT an expected value and it never replaces `mean`. It answers one
# question — "what is this asset worth if the risks I can see break badly?" —
# so it is only ever a haircut, and it is deliberately kept as a separate
# number. Baking these into the consensus would push a guess into the power
# rankings, the trade grades and every buy lane at once, where you could no
# longer see it, and would quietly argue against you when SELLING, because the
# rival quoting KTC has no such discount in his number.
#
# These are judgement, not measurement. One dict, tune freely.
RISK_MULT = {
    'out': 0.70,        # IR / PUP / suspended / NA — cannot play now
    'questionable': 0.92,
    'age_decline': 0.85,   # past the empirical break for his position
    'new_hc': 0.95,     # new offense, genuinely two-sided — a light touch only
}


def fetch(url):
    # curl, per values.py: system Python's LibreSSL fails TLS on some hosts
    r = subprocess.run(['curl', '-sL', '--max-time', '60', '-A', UA, url],
                       capture_output=True, text=True, check=True)
    return r.stdout


def norm(n):
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode()
    n = n.lower().replace('.', '').replace("'", '').replace('-', ' ')
    n = re.sub(r'\s+(jr|sr|ii|iii|iv|v)$', '', n.strip())
    return re.sub(r'\s+', ' ', n)


# Wikipedia team article titles -> the abbreviations Sleeper uses.
WIKI_TEAM = {
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL',
    'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI',
    'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL',
    'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX',
    'Kansas City Chiefs': 'KC', 'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC',
    'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
    'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
    'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT',
    'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB',
    'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS',
}
NFLVERSE = 'https://github.com/nflverse/nflverse-data/releases/download'

# nflverse spells the Rams 'LA'; Sleeper spells them 'LAR'. This is the only
# disagreement between the two vocabularies, and left unmapped it silently
# drops every Ram from byes and playoff SOS rather than erroring — so normalize
# every nflverse team code through here.
NV_TEAM = {'LA': 'LAR'}


def nv(t):
    return NV_TEAM.get(t, t)


def money(s):
    d = re.sub(r'[^0-9]', '', s or '')
    return int(d) if d else None


def otc_contracts():
    """Scrape OverTheCap's position tables -> {normalized name: contract}."""
    out = {}
    for pos, slug in POS.items():
        try:
            page = fetch(f'https://overthecap.com/position/{slug}')
        except Exception as e:
            print(f'  OverTheCap {pos}: FAILED ({e}) - contracts skipped for {pos}')
            continue
        n = 0
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', page, re.S):
            c = [html.unescape(re.sub(r'<[^>]+>', '', x)).strip()
                 for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]
            if len(c) < 8 or c[0] == 'Player':
                continue
            m = re.match(r'(\d{4})\s*(\w+)?', c[7] or '')
            if not m:
                continue
            out[norm(c[0])] = {
                'pos': pos, 'team': c[1],
                'value': money(c[3]), 'apy': money(c[4]),
                'guaranteed': money(c[5]), 'fully_guaranteed': money(c[6]),
                'fa_year': int(m.group(1)), 'fa_type': m.group(2) or 'UFA',
            }
            n += 1
        print(f'  OverTheCap {pos}: {n} contracts')
    return out


def _ok(path):
    """Exists, non-trivial, and actually CSV — not an HTML error page served
    with a 200. Upstream does that on a transient failure, and a size-only
    check caches the error page for a day (seen 2026-09-10, snap share)."""
    if not (os.path.exists(path) and os.path.getsize(path) > 1000):
        return False
    with open(path, 'rb') as f:
        head = f.read(400).lstrip()
    return head[:1] != b'<' and b',' in head.split(b'\n')[0]


def _cached(url, path, max_age=86400):
    import time
    if _ok(path) and time.time() - os.path.getmtime(path) < max_age:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = subprocess.run(['curl', '-sL', '-w', '%{http_code}', '--max-time', '180',
                        '-o', path, url], capture_output=True, text=True)
    if r.stdout.strip().endswith('404') or not _ok(path):
        return None
    return path


def schedule(season):
    """(bye week by team, {team: {week: opponent}}) for one season."""
    path = _cached(f'{NFLVERSE}/schedules/games.csv',
                   os.path.join(DATA, 'cache', 'games.csv'))
    if not path:
        print('  schedule: unavailable - byes and SOS skipped')
        return {}, {}
    opp, weeks = {}, set()
    for r in csv.DictReader(open(path, encoding='utf-8', errors='replace')):
        if r.get('season') != str(season) or r.get('game_type') != 'REG':
            continue
        w = int(r['week'])
        weeks.add(w)
        home, away = nv(r['home_team']), nv(r['away_team'])
        opp.setdefault(home, {})[w] = away
        opp.setdefault(away, {})[w] = home
    byes = {t: next((w for w in sorted(weeks) if w not in sched), None)
            for t, sched in opp.items()}
    return byes, opp


def defense_allowed(season):
    """PPR points allowed per game to each position, by defense.

    Aggregated straight from box scores: every skill player's PPR output is
    charged to the defense he faced. Rank 1 = allows the most, i.e. the softest
    matchup. Falls back a season if the current one has not been played.

    "Has not been played" means FEWER THAN MIN_WEEKS weeks, not zero. At week 1
    the current season's file already exists with a single Thursday game in it,
    and ranking 32 defenses off two teams produced an SOS table where 30 teams
    ranked `None` (2026-09-10). Require real coverage before switching over."""
    for yr in (season, season - 1):
        path = _cached(f'{NFLVERSE}/stats_player/stats_player_week_{yr}.csv',
                       os.path.join(DATA, 'cache', f'stats_player_week_{yr}.csv'))
        if not path:
            continue
        tot, gms = {}, {}
        for r in csv.DictReader(open(path, encoding='utf-8', errors='replace')):
            d, pos = r.get('opponent_team'), r.get('position')
            if r.get('season_type') != 'REG' or pos not in POS or not d:
                continue
            d = nv(d)
            try:
                fp = float(r.get('fantasy_points_ppr') or 0)
            except ValueError:
                fp = 0.0
            tot[(d, pos)] = tot.get((d, pos), 0.0) + fp
            gms.setdefault((d, pos), set()).add(r.get('week'))
        weeks = {w for s_ in gms.values() for w in s_}
        teams = {k[0] for k in tot}
        if not tot or (yr == season
                       and (len(weeks) < MIN_DEF_WEEKS or len(teams) < MIN_DEF_TEAMS)):
            continue
        allowed = {k: v / max(1, len(gms[k])) for k, v in tot.items()}
        rank = {}
        for pos in POS:
            vals = sorted(((v, k[0]) for k, v in allowed.items() if k[1] == pos),
                          reverse=True)
            for i, (_, team) in enumerate(vals, 1):
                rank[(team, pos)] = i
        print(f'  defense strength baseline: {yr}')
        return allowed, rank, yr
    return {}, {}, None


def head_coach_changes(season):
    """{team: {'incoming','departing'}} from the Wikipedia season article.

    Wikipedia keeps a clean sortable table of head-coach changes per season.
    There is no equivalent league-wide table for coordinators, so this is head
    coaches only - stated plainly rather than silently implied."""
    import urllib.parse
    url = ('https://en.wikipedia.org/w/api.php?action=parse&format=json&'
           'prop=wikitext&page=' + urllib.parse.quote(f'{season} NFL season'))
    try:
        w = json.loads(fetch(url))['parse']['wikitext']['*']
    except Exception as e:
        print(f'  head coaches: unavailable ({e})')
        return {}
    i = w.find('===Head coaches===')
    if i < 0:
        print('  head coaches: no head-coach section on the page')
        return {}
    # STOP at the General managers subsection. The parent section is titled
    # "Head coaching AND general manager changes" and the GM table has the same
    # shape, so reading past this point silently overwrites a team's real
    # coaching change with its front-office one.
    j = w.find('===General managers===', i)
    block = w[i:j if j > 0 else i + 14000]
    out = {}
    for row in block.split('|-'):
        m = re.search(r'\[\[([A-Z][^\]|]+?)\]\]', row)
        if not m or m.group(1) not in WIKI_TEAM:
            continue
        names = re.findall(r'\{\{sortname\|([^|}]+)\|([^|}]+)', row)
        if len(names) < 2:
            continue
        out[WIKI_TEAM[m.group(1)]] = {
            'departing': ' '.join(names[0]), 'incoming': ' '.join(names[-1])}
    print(f'  head coaches: {len(out)} teams changed for {season}')
    return out


def main():
    players = json.load(open(os.path.join(DATA, 'players.json')))
    season = int(json.load(open(os.path.join(
        DATA, CFG.get('season', max(d for d in os.listdir(DATA)
                                    if d.isdigit())), 'league.json')))['season'])

    contracts = otc_contracts()
    byes, opp = schedule(season)
    allowed, drank, dseason = defense_allowed(season)
    new_hc = head_coach_changes(season)
    _ac = os.path.join(DATA, 'age_curve.json')
    decline = ({k: v.get('decline_age') for k, v in
                json.load(open(_ac))['positions'].items()}
               if os.path.exists(_ac) else {})
    # this league's playoff weeks — the only games that decide anything
    lg = json.load(open(os.path.join(DATA, str(season), 'league.json')))
    pstart = int((lg.get('settings') or {}).get('playoff_week_start') or 15)
    PLAYOFF = list(range(pstart, pstart + 3))

    by_name = {}
    for pid, p in players.items():
        if p.get('active') and p.get('position') in POS and p.get('full_name'):
            by_name.setdefault(norm(p['full_name']), pid)

    # depth chart: team + charted position -> [(order, pid)]
    chart = {}
    for pid, p in players.items():
        o, t = p.get('depth_chart_order'), p.get('team')
        dpos = p.get('depth_chart_position')
        if o is not None and t and dpos and p.get('active'):
            chart.setdefault((t, dpos), []).append((o, pid))
    for k in chart:
        chart[k].sort()

    ctx, matched = {}, 0
    for pid, p in players.items():
        if not p.get('active') or p.get('position') not in POS:
            continue
        inj, st = p.get('injury_status'), p.get('status')
        avail = OUT.get(inj) or ('IR' if st == 'Injured Reserve' else None) \
            or ('Q' if inj == 'Questionable' else None) or 'OK'

        rec = {'avail': avail}
        if inj or p.get('injury_body_part'):
            rec['injury'] = {k: v for k, v in {
                'status': inj, 'body_part': p.get('injury_body_part'),
                'notes': p.get('injury_notes'), 'since': p.get('injury_start_date'),
                'practice': p.get('practice_participation'),
            }.items() if v}

        con = contracts.get(norm(p['full_name'] or ''))
        if con:
            matched += 1
            rec['contract'] = dict(con, walk_year=con['fa_year'] == season + 1,
                                   years_left=max(0, con['fa_year'] - season))

        t, dpos, o = p.get('team'), p.get('depth_chart_position'), p.get('depth_chart_order')
        if t and dpos and o is not None:
            rec['depth'] = {'team': t, 'pos': dpos, 'order': o}
            room = chart.get((t, dpos), [])
            ahead = [q for (n_, q) in room if n_ < o]
            behind = [q for (n_, q) in room if n_ > o]
            hc = {}
            if behind:
                hc['handcuff'] = behind[0]     # the guy who inherits the job
            if ahead:
                hc['backup_of'] = ahead[-1]    # the guy whose job he inherits
            if hc:
                rec['handcuff'] = hc

        pos_ = p['position']
        if t:
            if byes.get(t):
                rec['bye'] = byes[t]
            if t in new_hc:
                rec['new_hc'] = new_hc[t]
            # playoff-weeks matchup difficulty at HIS position. rank 1 = the
            # defense that gave up the most, i.e. the softest draw.
            games = [(w, opp[t][w]) for w in PLAYOFF
                     if w in (opp.get(t) or {})]
            rks = [drank.get((o, pos_)) for _, o in games]
            rks = [r for r in rks if r]
            if rks:
                rec['sos'] = {
                    'weeks': [{'wk': w, 'opp': o, 'rank': drank.get((o, pos_))}
                              for w, o in games],
                    'mean_rank': round(sum(rks) / len(rks), 1),
                    'baseline': dseason,
                }
        d_age = decline.get(pos_)
        if d_age and (p.get('age') or 0) >= d_age:
            rec['age_flag'] = {'age': p.get('age'), 'decline_age': d_age,
                               'pos': pos_}

        mult, why = 1.0, []
        if rec['avail'] in ('IR', 'PUP', 'SUSPENDED', 'NA', 'DNR'):
            mult *= RISK_MULT['out']; why.append(rec['avail'])
        elif rec['avail'] == 'Q':
            mult *= RISK_MULT['questionable']; why.append('questionable')
        # contract years are now weighted in the main value by ops/contracts.py (measured, future seasons
        # only, 2026-10-02) — not applied again here, which would count them twice
        if rec.get('age_flag'):
            mult *= RISK_MULT['age_decline']; why.append('age')
        if rec.get('new_hc'):
            mult *= RISK_MULT['new_hc']; why.append('new HC')
        if why:
            rec['risk'] = {'mult': round(mult, 3), 'why': why}
        ctx[pid] = rec

    json.dump(ctx, open(os.path.join(DATA, 'context.json'), 'w'))
    flagged = sum(1 for r in ctx.values() if r['avail'] != 'OK')
    walk = sum(1 for r in ctx.values() if r.get('contract', {}).get('walk_year'))
    aged = sum(1 for r in ctx.values() if r.get('age_flag'))
    print(f'context written for {len(ctx)} players -> data/context.json')
    print(f'  contracts matched: {matched} · walk years ({season}): {walk} · '
          f'availability flags: {flagged} · age flags: {aged}')
    risky = sum(1 for r in ctx.values() if r.get('risk'))
    print(f'  byes for {len(byes)} teams · playoff weeks {PLAYOFF} · '
          f'new head coaches: {len(new_hc)} · downside-adjusted: {risky}')


if __name__ == '__main__':
    main()
