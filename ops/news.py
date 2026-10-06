#!/usr/bin/env python3
"""News radar (added 2026-10-04, owner's rule: always work off the most current information — injuries, contracts,
suspensions, anything off the field).

Sleeper's player feed carries injury status, practice participation and SERVED suspensions, but nothing about what is
still developing: an announced suspension, an arrest, an extension or holdout, a release, a benching, a beat writer
saying a player is "unlikely to play". This reads ESPN's free public news feed (no key): the league-wide latest 50
plus each team's latest 25 and the official transactions log (signings, releases, IR,
practice-squad elevations, trades — matched by full name + team), every run, into a rolling 21-day log (data/news_feed.json), then ties stories to rostered
players by name.

A story counts for a player only when ESPN tags him AND the headline or summary names him (game recaps tag a dozen
players and mention none). Each story is sorted by keywords into suspension / injury / contract / role. Output
data/news.json: per rostered player, his last 21 days of stories, plus `alerts` = last 72 hours for your roster and
the players in data/trade_plan.json. Nothing here changes a projection on its own: a story that should move a
start/sit call goes into data/news_overrides.json for that week (see AGENTS.md "Freshest data").
"""
import hashlib, json, os, re, sys, time, unicodedata, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, 'cache')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))
BASE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'
KEEP_DAYS, ALERT_HOURS = 21, 72
TEAM_FIX = {'WSH': 'WAS', 'LA': 'LAR', 'JAC': 'JAX'}     # ESPN / nflverse codes -> Sleeper's (WSH silently dropped WAS news)

KINDS = [  # first match wins; order = how much it can change a decision
    ('suspension', r'suspen|banned|reinstat|conduct policy|arrest|charged|indict|lawsuit|investigat|exempt list|commissioner.?s list'),
    ('injury', r'injur|torn|\bacl\b|achilles|surgery|\bir\b|injured reserve|out for (the )?season|season.ending|concussion|hamstring|'
               r'ankle|knee|groin|quad|ruled out|questionable|doubtful|inactive|limited|did not practice|\bdnp\b|activated|designated to return|'
               r'return(s|ing)? (to|from)|week.to.week|day.to.day|mri|x.rays?'),
    ('contract', r'extension|contract|re.?sign|holdout|hold.in|trade request|franchise tag|restructur|released|waived|\bcut\b|'
                 r'signs?\b|signed|traded|trade to|acquire|free agen|option|guarantee'),
    ('role', r'bench(ed)?|named (the )?start|starting job|depth chart|demot|promot|elevat|snap count|workload|role|first.team|'
             r'take over|lead back|bell.?cow|committee'),
]


def get(url):
    # this Mac's system Python (LibreSSL) intermittently fails ESPN's TLS handshake (seen 2026-10-05: one team feed of
    # 33); retry once, then fetch with curl, the same workaround context.py and values.py use
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            return json.load(urllib.request.urlopen(req, timeout=20))
        except Exception:
            time.sleep(1)
    import subprocess
    r = subprocess.run(['curl', '-sL', '--max-time', '30', '-A', 'Mozilla/5.0', url], capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        raise RuntimeError(f'curl failed ({r.returncode})')
    return json.loads(r.stdout)


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r"[.'\-]", '', s)
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def teams():
    p = os.path.join(CACHE, 'espn_teams.json')
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 30 * 86400:
        return json.load(open(p))
    t = {x['team']['id']: x['team']['abbreviation'] for x in get(f'{BASE}/teams')['sports'][0]['leagues'][0]['teams']}
    os.makedirs(CACHE, exist_ok=True)
    json.dump(t, open(p, 'w'))
    return t


def main():
    feed_p = os.path.join(DATA, 'news_feed.json')
    feed = json.load(open(feed_p)) if os.path.exists(feed_p) else {}
    pulled, failed = 0, []
    urls = [f'{BASE}/news?limit=50'] + [f'{BASE}/news?team={tid}&limit=25' for tid in teams()]
    for u in urls:
        try:
            for a in get(u).get('articles', []):
                feed[str(a['id'])] = {
                    'headline': a.get('headline', ''), 'description': a.get('description', ''),
                    'published': a.get('published', ''), 'url': ((a.get('links') or {}).get('web') or {}).get('href', ''),
                    'athletes': [c.get('description', '') for c in a.get('categories', []) if c.get('type') == 'athlete'],
                    'teams': [TEAM_FIX.get(x, x) for x in ((c.get('team') or {}).get('abbreviation', '') for c in a.get('categories', []) if c.get('type') == 'team')]}
                pulled += 1
        except Exception as e:
            failed.append(f'{u.split("?")[-1]}: {e}')
    # official transactions (signings, releases, IR, practice-squad elevations, trades): ESPN's daily log, ~2.5 weeks
    try:
        for t in get(f'{BASE}/transactions?limit=200').get('transactions', []):
            team = (t.get('team') or {}).get('abbreviation', '')
            d = t.get('description', '')
            key = 'tx:' + t.get('date', '')[:10] + ':' + team + ':' + hashlib.md5(d.encode()).hexdigest()[:10]
            feed[key] = {'headline': f'{team}: {d}', 'description': '', 'published': t.get('date', '').replace('Z', ':00Z') if t.get('date', '').count(':') == 1 else t.get('date', ''),
                         'url': '', 'athletes': [], 'teams': [TEAM_FIX.get(team, team)], 'transaction': True}
            pulled += 1
    except Exception as e:
        failed.append(f'transactions: {e}')
    now = datetime.now(timezone.utc)
    age_h = lambda a: (now - datetime.fromisoformat(a['published'].replace('Z', '+00:00'))).total_seconds() / 3600 if a['published'] else 1e9
    feed = {k: a for k, a in feed.items() if age_h(a) <= KEEP_DAYS * 24}
    json.dump(feed, open(feed_p, 'w'))

    # rostered players in this league, keyed by normalized name (team breaks ties)
    P = json.load(open(os.path.join(DATA, 'players.json')))
    latest = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))[-1]
    rosters = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
    users = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, latest, 'users.json')))}
    owner = {p: users.get(r['owner_id'], '?') for r in rosters for p in (r['players'] or [])}
    byname = {}
    for pid in owner:
        p = P.get(pid) or {}
        if p.get('full_name'):
            byname.setdefault(norm(p['full_name']), []).append(pid)
    me = CFG.get('my_username')
    plan_p = os.path.join(DATA, 'trade_plan.json')
    plan = json.load(open(plan_p)) if os.path.exists(plan_p) else {'trades': []}
    watch = {p for p, o in owner.items() if o == me} | {p for t in plan['trades'] for p in t.get('get', []) + t.get('give', [])}

    out = {}
    for aid, a in sorted(feed.items(), key=lambda kv: kv[1]['published'], reverse=True):
        text = (a['headline'] + ' ' + a['description'])
        ntext = norm(text)
        kind = next((k for k, rx in KINDS if re.search(rx, text, re.I)), None)
        per_kind = {}
        if a.get('transaction'):
            # no player tags: match any rostered player whose full name appears, on the transacting team, and classify
            # him by HIS sentence (one line often holds several moves: "Waived X. Signed Y. Placed Z on IR.")
            athletes = []
            for sent in re.split(r'(?<=[.;])\s+', text):
                ns = norm(sent)
                k = 'injury' if re.search(r'injured reserve|\bIR\b|physically unable|non.football injury', sent, re.I) else \
                    'suspension' if re.search(r'suspen|exempt|reinstat', sent, re.I) else 'transaction'
                for n, ids in byname.items():
                    if len(n.split()) >= 2 and re.search(r'\b' + re.escape(n) + r'\b', ns) \
                            and any((P.get(i) or {}).get('team') in {TEAM_FIX.get(x, x) for x in a['teams']} for i in ids):
                        athletes.append(n); per_kind[n] = k
        else:
            athletes = a['athletes']
        for ath in athletes:
            n = norm(ath)
            ids = byname.get(n, [])
            # same name, different player (QB Josh Allen vs the Jaguars' Josh Allen): when the story names teams, the
            # player's team must be one of them
            teams_ = {TEAM_FIX.get(x, x) for x in a['teams']}
            if teams_:
                ids = [i for i in ids if (P.get(i) or {}).get('team') in teams_]
            last = n.split(' ')[-1] if n else ''
            if not ids or not last or last not in ntext:
                continue
            for pid in ids:
                out.setdefault(pid, []).append({'id': aid, 'kind': per_kind.get(n, kind), 'headline': a['headline'],
                                                'summary': a['description'], 'published': a['published'], 'url': a['url'],
                                                'hours_ago': round(age_h(a), 1)})
    alerts = []
    for pid, items in out.items():
        for it in items:
            if pid in watch and it['kind'] and it['hours_ago'] <= ALERT_HOURS:
                alerts.append({'player': (P.get(pid) or {}).get('full_name'), 'pid': pid, 'owner': owner.get(pid),
                               'mine': owner.get(pid) == me, **it})
    alerts.sort(key=lambda x: x['hours_ago'])
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'), 'stories_in_log': len(feed), 'pulled_this_run': pulled,
               'failed': failed, 'players': out, 'alerts': alerts}, open(os.path.join(DATA, 'news.json'), 'w'))
    print(f'news -> data/news.json: {len(feed)} stories in the {KEEP_DAYS}-day log ({pulled} pulled now, {len(failed)} feeds failed); '
          f'{len(out)} rostered players with news; {len(alerts)} alerts (your roster + trade plan, last {ALERT_HOURS}h)')
    for a in alerts[:8]:
        print(f"  [{a['kind']}] {a['player']} ({a['owner']}), {a['hours_ago']:.0f}h ago: {a['headline']}")


if __name__ == '__main__':
    main()
