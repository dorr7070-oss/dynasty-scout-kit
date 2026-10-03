#!/usr/bin/env python3
"""Measure what injuries actually cost -> data/injury_effects.json (one-off, like the other studies).

Owner's choice (2026-10-02): price injured players by evidence. Two questions, 2015-2025, QB/RB/WR/TE:

  1. Game-day odds: a player listed Questionable or Doubtful — how often does he actually play,
     by his practice status that week (Full / Limited / Did Not Participate)?
  2. Time missed: once a player is ruled OUT with injury X, how many of his team's games pass
     before he plays again? Measured from snap counts (any offensive or special-teams snap = played),
     counting the TEAM's games (byes excluded). No return that season = season-ending (censored at
     the season's end and counted separately), because IR'd players drop off the weekly report.
     Also: given he has already missed k games, how many more (the "already out 3 weeks" question).

Data (free, nflverse): injuries_<y>.csv (weekly report + practice status), stats_player_week_<y>.csv,
nfldata games.csv. Skips when the output exists unless --force.
"""
import csv, json, os, statistics, subprocess, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'data', 'cache', 'weekly_hist')
OUT = os.path.join(ROOT, 'data', 'injury_effects.json')
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
GAMES_URL = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
SEASONS = range(2015, 2026)
POS = ('QB', 'RB', 'WR', 'TE')

BUCKETS = [  # (bucket, keywords) — first match wins; order puts the specific before the general
    ('achilles', ('achilles',)), ('acl', ('acl', 'cruciate')), ('concussion', ('concussion', 'head')),
    ('hamstring', ('hamstring',)), ('high ankle', ('high ankle',)), ('ankle', ('ankle',)),
    ('knee', ('knee', 'mcl', 'meniscus', 'patella')), ('groin', ('groin', 'adductor')),
    ('quadriceps', ('quad', 'thigh')), ('calf', ('calf', 'shin', 'fibula', 'tibia')),
    ('foot', ('foot', 'toe', 'heel', 'plantar', 'lisfranc', 'arch')),
    ('hip', ('hip', 'glute', 'pelvis', 'abdom', 'oblique', 'core')),
    ('back', ('back', 'neck', 'spine')), ('ribs', ('rib', 'chest', 'pector', 'sternum')),
    ('shoulder', ('shoulder', 'collarbone', 'clavicle', 'ac joint')),
    ('arm/hand', ('elbow', 'forearm', 'wrist', 'hand', 'finger', 'thumb', 'arm', 'bicep', 'tricep')),
    ('illness', ('illness', 'covid', 'flu')),
]


def bucket(txt):
    t = (txt or '').lower()
    if not t or 'not injury' in t or 'personal' in t or 'rest' in t:
        return None
    for b, kws in BUCKETS:
        if any(k in t for k in kws):
            return b
    return 'other'


def practice(txt):
    t = (txt or '').lower()
    return 'DNP' if 'did not' in t else 'Limited' if 'limited' in t else 'Full' if 'full' in t else None


def grab(url, path):
    if not os.path.exists(path) or os.path.getsize(path) < 10000:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(['curl', '-sL', '-m', '300', '-o', path, url], check=True)
    return path


def main():
    if os.path.exists(OUT) and '--force' not in sys.argv:
        print('injury study: data/injury_effects.json already built (historical, fixed) — skip; --force to redo')
        return
    games = list(csv.DictReader(open(grab(GAMES_URL, os.path.join(CACHE, 'games.csv')), encoding='utf-8')))
    team_weeks = defaultdict(list)                         # (season, team) -> sorted REG weeks played
    for g in games:
        if g['game_type'] == 'REG' and g['season'].isdigit() and int(g['season']) in SEASONS:
            for t in (g['home_team'], g['away_team']):
                team_weeks[(int(g['season']), t)].append(int(g['week']))
    for k in team_weeks:
        team_weeks[k].sort()

    gameday = Counter()                                    # (status, practice) -> [played, listed]
    played_n, listed_n = Counter(), Counter()
    spells = defaultdict(list)                             # bucket -> [(games_missed, censored)]
    for y in SEASONS:
        # "played" = any snap (offense or special teams) in the snap counts, mapped pfr -> gsis via the
        # roster file. A stat line alone misses players who were on the field but never touched the
        # ball, which made Questionable players look like they sat (checked 10-02: Q+Full read 70%).
        played = defaultdict(set)                          # gsis -> weeks he took a snap
        pfr_gsis = {}
        for r in csv.DictReader(open(grab(f'{REL}/rosters/roster_{y}.csv', os.path.join(CACHE, f'roster_{y}.csv')),
                                     encoding='utf-8')):
            if r.get('pfr_id') and r.get('gsis_id'):
                pfr_gsis[r['pfr_id']] = r['gsis_id']
        for r in csv.DictReader(open(grab(f'{REL}/snap_counts/snap_counts_{y}.csv', os.path.join(CACHE, f'snaps_{y}.csv')),
                                     encoding='utf-8')):
            g = pfr_gsis.get(r['pfr_player_id'])
            if g and r['game_type'] == 'REG' and (float(r['offense_snaps'] or 0) + float(r['st_snaps'] or 0)) > 0:
                played[g].add(int(r['week']))
        for r in csv.DictReader(open(grab(f'{REL}/stats_player/stats_player_week_{y}.csv',
                                          os.path.join(CACHE, f'week_{y}.csv')), encoding='utf-8')):
            if r['season_type'] == 'REG':
                played[r['player_id']].add(int(r['week']))   # belt and braces
        inj = defaultdict(dict)                            # gsis -> week -> row
        for r in csv.DictReader(open(grab(f'{REL}/injuries/injuries_{y}.csv',
                                          os.path.join(CACHE, f'injuries_{y}.csv')), encoding='utf-8')):
            if r.get('game_type', 'REG') == 'REG' and r['position'] in POS and r['week'].isdigit():
                inj[r['gsis_id']][int(r['week'])] = r
        for gid, weeks in inj.items():
            for w, r in weeks.items():
                st = r['report_status']
                if st in ('Questionable', 'Doubtful'):
                    k = (st, practice(r['practice_status']) or 'none')
                    listed_n[k] += 1
                    played_n[k] += w in played[gid]
            # OUT spells: first Out week after having played (or week 1), then count team games until he plays
            out_weeks = sorted(w for w, r in weeks.items() if r['report_status'] == 'Out')
            done = set()
            for w in out_weeks:
                if w in done:
                    continue                                   # still inside an earlier spell
                if w != 1 and not (played[gid] & set(range(1, w))):
                    continue                                   # never active yet: a camp injury carried in
                b = bucket(weeks[w]['report_primary_injury'] or weeks[w]['practice_primary_injury'])
                tw = [x for x in team_weeks.get((y, weeks[w]['team']), []) if x >= w]
                back = next((x for x in tw if x in played[gid]), None)
                missed = tw.index(back) if back else len(tw)
                done.update(tw[:missed])
                if b and tw:
                    spells[b].append((missed, back is None))

    out = {'window': f'{min(SEASONS)}-{max(SEASONS)} regular seasons', 'gameday': {}, 'missed': {}}
    for k in sorted(listed_n):
        if listed_n[k] >= 30:
            out['gameday'][f'{k[0]}|{k[1]}'] = {'n': listed_n[k], 'p_play': round(played_n[k] / listed_n[k], 3)}
    for b, sp in sorted(spells.items(), key=lambda kv: -len(kv[1])):
        if len(sp) < 25:
            continue
        g = [m for m, _ in sp]
        cond = {}
        for k in (1, 2, 3, 4, 6):                          # already missed k -> median more
            rest = [m - k for m in g if m > k]
            if len(rest) >= 15:
                cond[str(k)] = round(statistics.median(rest), 1)
        out['missed'][b] = {'n': len(sp), 'median': statistics.median(g), 'mean': round(statistics.mean(g), 1),
                            'p75': sorted(g)[int(len(g) * 0.75)], 'p_season_ending': round(sum(c for _, c in sp) / len(sp), 3),
                            'p_back_in_1': round(sum(m <= 1 for m in g) / len(g), 3),
                            'more_given_missed': cond}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'injury study -> data/injury_effects.json ({sum(len(v) for v in spells.values()):,} OUT spells, '
          f'{sum(listed_n.values()):,} Q/D listings)')
    for k, v in out['gameday'].items():
        print(f'  plays when {k:28} {v["p_play"]:.0%} (n={v["n"]})')
    for b, v in out['missed'].items():
        print(f"  {b:12} n={v['n']:4}  median {v['median']} games, p75 {v['p75']}, back next game {v['p_back_in_1']:.0%}, "
              f"season-ending {v['p_season_ending']:.0%}")


if __name__ == '__main__':
    main()
