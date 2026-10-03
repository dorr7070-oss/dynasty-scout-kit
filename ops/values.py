#!/usr/bin/env python3
"""Multi-source dynasty value consensus (rank-normalized).

Every source is reduced to an ordering, then mapped through ONE shared
rank->value curve anchored to FantasyCalc (real-trade magnitudes). Plain
magnitude normalization (v/max) preserves each source's curve SHAPE, and KTC's
fat tail badly inflates depth players (at rank 200 KTC pays 28% of the #1 value
vs FantasyCalc 10%, DynastyProcess 0.9%). Ranking every source onto the
FantasyCalc curve keeps their orderings but prices them at what players
actually trade for, so the consensus mean is trade-realistic at every depth
and `spread` reflects genuine cross-source *rank* disagreement, not scale.

Sources (each one vote):
  FantasyCalc   - computed from real league trades (API)
  KeepTradeCut  - crowdsourced values (scraped from rankings page)
  ExpertRank    - DynastyProcess + FantasyPros folded together. DP's
                  value_1qb is strictly monotone in FP ECR, so post-ranking
                  they are near-duplicates; averaged into one vote to avoid
                  giving expert ranks double weight.
  ETR (optional)- drop a subscriber CSV at data/values/etr.csv with
                  Rank + Player columns; auto-included as a rank source

Deliberately excluded: Dynasty Daddy (its player values duplicate KTC),
DraftSharks (top-25 only without login).

Writes data/values/consensus.json: {sleeper_id: {mean, n, spread, vals, raw}}
  vals - rank-normalized per-source values; drive mean / spread / n.
  raw  - magnitude-normalized FantasyCalc / KTC / DynastyProcess, kept so the
         sell-high logic in advise.py can still quote the real FC-vs-KTC gap
         (quote FantasyCalc when buying, KTC when selling).
"""
import csv, json, os, re, statistics, subprocess, sys, time, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_format as LF  # noqa: E402  1QB vs superflex, team count, PPR -> which value format to pull

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
VDIR = os.path.join(DATA, 'values')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'


FETCHED_AT = {}


def fetch(url):
    # curl instead of urllib: macOS system Python's LibreSSL is too old for
    # some hosts (KTC rejects its TLS handshake).
    # No-cache headers are deliberate. Nothing here is written to data/cache/ —
    # every source is pulled live on every run — but an intermediary CDN will
    # happily serve a stale copy that looks identical. On 2026-09-28 Sleeper's
    # own rosters endpoint served a stale field for minutes after a write while
    # returning HTTP 200, so ask for a fresh copy explicitly rather than
    # trusting the default.
    r = subprocess.run(['curl', '-sL', '--max-time', '60', '-A', UA,
                        '-H', 'Cache-Control: no-cache', '-H', 'Pragma: no-cache',
                        url],
                       capture_output=True, text=True, check=True)
    FETCHED_AT[url] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    return r.stdout


def norm(n):
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode()
    n = n.lower().replace('.', '').replace("'", '').replace('-', ' ')
    n = re.sub(r'\s+(jr|sr|ii|iii|iv|v)$', '', n.strip())
    return re.sub(r'\s+', ' ', n)


def main():
    os.makedirs(VDIR, exist_ok=True)
    players = json.load(open(os.path.join(DATA, 'players.json')))

    # Map normalized name -> the most relevant sleeper_id so the name-matched
    # value sources (KTC / DynastyProcess / FantasyPros) bind to the real active
    # player, not a retired namesake sharing the name. Without this, a ghost like
    # the retired WR "Kenneth Walker" (team=None, search_rank=9999999) wins the
    # join and inherits the RB's crowd value. Prefer active, then has-team, then
    # Sleeper's search_rank (lower = more prominent).
    # Position is NOT a filter, only a preference. Sleeper lists Travis Hunter
    # as a DB; every value source ranks him as a WR, so filtering the map to
    # QB/RB/WR/TE dropped a top-200 asset on every run (found 2026-09-29).
    SKILL = ('QB', 'RB', 'WR', 'TE')

    def _relevance(pid):
        p = players[pid]
        sr = p.get('search_rank')
        return (0 if p.get('position') in SKILL else 1,
                0 if p.get('active') else 1,
                0 if p.get('team') else 1,
                sr if isinstance(sr, int) else 10 ** 9)

    name_sid = {}
    alias_sid = {}          # (last name, position, team) -> sid
    for pid, p in players.items():
        if not p.get('full_name'):
            continue
        nm = norm(p['full_name'])
        if nm not in name_sid or _relevance(pid) < _relevance(name_sid[nm]):
            name_sid[nm] = pid
        pos, team = p.get('position'), p.get('team')
        if pos in SKILL and team:
            key = (nm.split()[-1], pos, team)
            if key not in alias_sid or _relevance(pid) < _relevance(alias_sid[key]):
                alias_sid[key] = pid

    # Sources spell names their own way: Sleeper says "Kenny Gainwell" and
    # "Chig Okonkwo" where KTC says "Kenneth Gainwell" and "Chigoziem Okonkwo".
    # Fall back to last name + position + team, which is specific enough not to
    # collide, and normalize the handful of team codes the sources disagree on.
    TEAM_FIX = {'JAC': 'JAX', 'TBB': 'TB', 'GBP': 'GB', 'KCC': 'KC', 'NOS': 'NO',
                'SFO': 'SF', 'NEP': 'NE', 'LVR': 'LV', 'ARZ': 'ARI', 'BLT': 'BAL',
                'CLV': 'CLE', 'HST': 'HOU', 'WSH': 'WAS', 'LA': 'LAR'}

    def resolve(name, pos=None, team=None):
        """sleeper_id for a source's player name, or None."""
        nm = norm(name or '')
        sid = name_sid.get(nm)
        if sid:
            return sid
        if nm and pos and team:
            t = TEAM_FIX.get(team.upper(), team.upper())
            return alias_sid.get((nm.split()[-1], pos, t))
        return None

    src = {}

    # FantasyCalc
    fc_raw = json.loads(fetch(LF.fantasycalc_url()))
    fc = {}
    fc_picks = {}
    for v in fc_raw:
        p = v['player']
        if p['position'] == 'PICK':
            # keep slot-aware pick values (e.g. "2026 Pick 1.01", "2027 1st") for
            # trade_grades.py; players use them via data/values/picks.json
            fc_picks[p['name']] = v['value']
            continue
        sid = str(p.get('sleeperId') or '') or name_sid.get(norm(p['name']), '')
        if sid:
            fc[sid] = v['value']
    src['FantasyCalc'] = fc
    json.dump(fc_picks, open(os.path.join(VDIR, 'picks.json'), 'w'))

    # KeepTradeCut. The page used to inline `var playersArray = [...]`; as of
    # 2026-09 it ships the same array as JSON in a <script id="ktc-players">
    # element and parses it at runtime. Read the element first, keep the old
    # inline form as a fallback — and if BOTH miss, say so instead of silently
    # dropping a source from the consensus.
    html = fetch(f'https://keeptradecut.com/dynasty-rankings?format={LF.KTC_FORMAT}')
    m = (re.search(r'<script[^>]*id="ktc-players"[^>]*>(.*?)</script>', html, re.S)
         or re.search(r'var playersArray = (\[.*?\]);', html, re.S))
    ktc = {}
    ktc_missed = []
    if not m:
        print('  KeepTradeCut: PARSE FAILED (page markup changed) - source skipped')
    if m:
        for p in json.loads(m.group(1)):
            nm = p.get('playerName') or ''
            # Draft picks are identified by their STRUCTURED fields, never by a
            # substring of the name. The old test was `'Pick' in nm`, and
            # "George PICKens" matched it — KTC's #23 dynasty asset was dropped
            # from the consensus on every run until 2026-09-29, silently,
            # because a skipped row looks exactly like a player KTC does not
            # rank. Substring tests on human names are a trap: Rounds, Pickett
            # and Pickering are all real football surnames too.
            # 'RDP' = rookie draft pick, 'PI' = the older pick marker. NOT
            # pickRound/pickNum — those carry a real player's own NFL draft
            # slot, so testing them drops almost the entire board.
            if p.get('position') in ('PI', 'RDP'):
                continue
            val = LF.ktc_value(p)
            sid = resolve(nm, p.get('position'), p.get('team'))
            if sid and val:
                ktc[sid] = val
            elif val:
                ktc_missed.append((nm, (p.get('superflexValues' if LF.SUPERFLEX else 'oneQBValues') or {}).get('rank')))
    src['KeepTradeCut'] = ktc
    # A name we cannot bind is invisible in the output, so name the expensive
    # ones out loud. Deep rows failing to match is normal; a top-300 player
    # failing to match is a bug worth seeing on the day it starts.
    loud = sorted([x for x in ktc_missed if isinstance(x[1], int) and x[1] <= 300],
                  key=lambda x: x[1])
    if loud:
        print('  KeepTradeCut: UNMATCHED inside the top 300 - ' +
              ', '.join(f'{n} (KTC #{r})' for n, r in loud))

    # DynastyProcess
    dp = {}
    txt = fetch('https://raw.githubusercontent.com/dynastyprocess/data/master/files/values.csv')
    dp_scraped = ''
    for row in csv.DictReader(txt.splitlines()):
        sid = resolve(row['player'], row.get('pos'), row.get('team'))
        col = 'value_2qb' if LF.SUPERFLEX else 'value_1qb'
        if sid and row.get(col):
            dp[sid] = float(row[col])
        dp_scraped = row.get('scrape_date') or dp_scraped
    src['DynastyProcess'] = dp
    # DynastyProcess publishes the date it last scraped. It is a file in a git
    # repo, not a live API, so it can sit unchanged for days — say how old it is
    # rather than letting a stale file pass as today's number.
    if dp_scraped:
        FETCHED_AT['DynastyProcess.scrape_date'] = dp_scraped
        age = (time.time() - time.mktime(time.strptime(dp_scraped, '%Y-%m-%d'))) / 86400
        note = f'  DynastyProcess: source data scraped {dp_scraped} ({age:.0f}d old)'
        print(note + ('  <- STALE, check upstream' if age > 10 else ''))

    # magnitude-normalize value sources (kept as `raw` for sell-high quoting)
    raw = {k: {sid: v / max(d.values()) * 10000 for sid, v in d.items()}
           for k, d in src.items() if d}

    # rank->value curve anchored to FantasyCalc (real-trade magnitudes): every
    # source contributes its ORDERING, but the value scale is what players
    # actually trade for, so the consensus reads trade-realistic at every depth
    # instead of inheriting KTC's inflated tail. Fall back to the cross-source
    # average shape only if FantasyCalc is unavailable.
    if raw.get('FantasyCalc'):
        curve = sorted(raw['FantasyCalc'].values(), reverse=True)
    else:
        curves = [sorted(d.values(), reverse=True) for d in raw.values()]
        maxlen = max(len(c) for c in curves)
        curve = [statistics.mean([c[i] for c in curves if i < len(c)]) for i in range(maxlen)]

    def rank_to_val(r):
        i = max(0, int(round(r)) - 1)
        if i >= len(curve):
            return max(0.0, curve[-1] * (0.98 ** (i - len(curve) + 1)))
        return curve[i]

    def rankify(d):
        # map a source's players onto the shared curve by their rank in it
        order = sorted(d, key=lambda sid: -d[sid])
        return {sid: rank_to_val(i + 1) for i, sid in enumerate(order)}

    # rank-normalized sources drive the consensus (FP joins as ranks below)
    normed = {k: rankify(d) for k, d in raw.items()}

    # FantasyPros ECR -> rank-values (already a ranking source)
    fpr = {}
    html = fetch('https://www.fantasypros.com/nfl/rankings/'
                 + ('dynasty-superflex.php' if LF.SUPERFLEX else 'dynasty-overall.php'))
    m = re.search(r'var ecrData = (\{.*?\});', html, re.S)
    if m:
        for p in json.loads(m.group(1)).get('players', []):
            sid = resolve(p['player_name'], p.get('player_position_id'),
                          p.get('player_team_id'))
            r = p.get('rank_ecr') or p.get('rank_ave')
            if sid and r:
                fpr[sid] = rank_to_val(float(r))

    # Fold DynastyProcess + FantasyPros into one ExpertRank vote: DP's values
    # are monotone in FP ECR, so post-ranking they are near-duplicates and
    # would otherwise give expert ranks 2 of 4 votes.
    dp_ranked = normed.pop('DynastyProcess', {})
    expert = {}
    for sid in set(dp_ranked) | set(fpr):
        vs = [x for x in (dp_ranked.get(sid), fpr.get(sid)) if x is not None]
        if vs:
            expert[sid] = statistics.mean(vs)
    if expert:
        normed['ExpertRank'] = expert

    # Establish The Run (optional subscriber CSV)
    etr_path = os.path.join(ROOT, 'data', 'values', 'etr.csv')
    if os.path.exists(etr_path):
        etr = {}
        for row in csv.DictReader(open(etr_path)):
            r = {k.lower().strip(): v for k, v in row.items() if k}
            nm = r.get('player') or r.get('name') or r.get('player name')
            rk = r.get('rank') or r.get('overall') or r.get('1qb rank')
            if not (nm and rk):
                continue
            sid = resolve(nm, r.get('pos') or r.get('position'), r.get('team'))
            try:
                rk = float(rk)
            except ValueError:
                continue
            if sid and sid not in etr:
                etr[sid] = rank_to_val(rk)
        if etr:
            normed['EstablishTheRun'] = etr
            print(f'  EstablishTheRun: {len(etr)} players from etr.csv')

    out = {}
    all_sids = set().union(*[set(d) for d in normed.values()])
    for sid in all_sids:
        vals = {s: d.get(sid) for s, d in normed.items()}
        have = {s: v for s, v in vals.items() if v is not None}
        if not have:
            continue
        vs = list(have.values())
        out[sid] = {'mean': statistics.mean(vs), 'n': len(vs),
                    'spread': (max(vs) - min(vs)) if len(vs) > 1 else 0,
                    'vals': vals,
                    'raw': {s: d.get(sid) for s, d in raw.items()}}
    # Compare this run's coverage with the last one BEFORE overwriting it. A
    # source that half-fails still prints a plausible-looking count, and nobody
    # audits a number they have nothing to compare it to. AGENTS.md says to
    # check the per-source counts by eye; this checks them.
    prev_path = os.path.join(VDIR, 'sources.json')
    prev = {}
    if os.path.exists(prev_path):
        try:
            prev = json.load(open(prev_path)).get('counts', {})
        except (ValueError, OSError):
            prev = {}
    counts = {s: len(d) for s, d in normed.items()}
    warnings = []
    for s, n in counts.items():
        was = prev.get(s)
        if was and n < was * 0.9:
            warnings.append(f'{s} {was} -> {n} players ({100 * n / was:.0f}% of last run)')
    for s in prev:
        if s not in counts:
            warnings.append(f'{s} produced NOTHING this run (had {prev[s]})')

    json.dump(out, open(os.path.join(VDIR, 'consensus.json'), 'w'))
    json.dump({'counts': counts, 'fetched_at': FETCHED_AT,
               'run_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')},
              open(prev_path, 'w'), indent=1)
    for s, d in normed.items():
        was = prev.get(s)
        delta = f'  (last run {was})' if was and was != len(d) else ''
        print(f'  {s}: {len(d)} players (rank-normalized){delta}')
    print(f'consensus written for {len(out)} players -> data/values/consensus.json')
    if warnings:
        print('\n  *** SOURCE COVERAGE DROPPED ***')
        for w in warnings:
            print(f'    {w}')
        print('    A source that quietly shrinks is the failure mode this guards.'
              '\n    Check the source before trusting today\'s values.\n')


if __name__ == '__main__':
    main()
