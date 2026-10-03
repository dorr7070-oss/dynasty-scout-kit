#!/usr/bin/env python3
"""Generate ADVICE.md — a data-driven "best moves" briefing for my team.

Heuristics (all from consensus values + owner profiles):
  1. My holes  = positions where my starters rank in the league's bottom third, by dynasty
     VALUE and (separately) by projected POINTS. The two disagree often and
     the disagreement is the point: an aging QB room can be last in dynasty
     value while being the best-scoring slot on the roster this season.
  2. My surplus = positions where my non-starter depth ranks top-3, plus any
     age-29+ startable player (sell-window asset).
  3. Buy lanes = for each hole, teams carrying MORE startable value at that
     position than their lineup uses, ranked by how motivated they are to
     sell (rebuilders/pick-hoarders sell win-now; all-in teams don't).
  4. Sell lanes = my 29+ / sell-high players matched to all-in teams
     (low pick share = desperate, win-now buyers).
  5. Sell-high flags = players whose crowd value (KTC) far exceeds
     real-trade value (FantasyCalc).
  6. FAAB targets = best free agents at my hole positions.

Schedule awareness (data/projection.json from ops/project.py): every buy and
FAAB candidate is re-simulated through my actual 2026 schedule with opponent
scores held fixed, so each one reports GAMES FLIPPED, not just value added.
A big dynasty upgrade that adds ~1 pt/week flips nothing, and this file now
says so instead of implying otherwise. Degrades gracefully to value-only if
projection.json is missing.

Run after fetch/values/project/profiles. Part of ./update.sh.
"""
import collections, json, os, sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from project import lineup_points          # noqa: E402  (shared lineup rules)

players = json.load(open(os.path.join(DATA, 'players.json')))
seasons = sorted(json.load(open(os.path.join(DATA, 'seasons.json'))))
latest = seasons[-1]
rosters = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
users = json.load(open(os.path.join(DATA, latest, 'users.json')))
cons = json.load(open(os.path.join(DATA, 'values', 'consensus.json')))
profiles = json.load(open(os.path.join(ROOT, 'profiles', 'profiles.json')))
_cpath = os.path.join(DATA, 'context.json')
ctx = json.load(open(_cpath)) if os.path.exists(_cpath) else {}
_upath = os.path.join(DATA, 'usage.json')
usage = json.load(open(_upath)) if os.path.exists(_upath) else {}


def flags(pid, walk=True):
    """Short availability / contract tags for a player (ops/context.py).

    These are the facts the value sources price slowly or not at all: an ACL
    designation and a walk year both change what an asset is worth to ME
    without moving his consensus number this week."""
    c = ctx.get(pid)
    if not c:
        return []
    out = []
    if c.get('avail') not in (None, 'OK'):
        body = (c.get('injury') or {}).get('body_part')
        out.append(f"{c['avail']}" + (f" ({body})" if body else ''))
    ct = cons.get(str(pid), {}).get('contract') or {}
    if walk and ct.get('class') in ('rookie_deal', 'veteran'):
        out.append(f"contract yr −{round((1 - ct.get('mult', 1)) * 100)}%")
    if c.get('age_flag'):
        out.append(f"age {c['age_flag']['age']}")
    if c.get('new_hc'):
        out.append('new HC')
    return out

uid_user = {u['user_id']: u['display_name'] for u in users}
uid_team = {u['user_id']: ((u.get('metadata') or {}).get('team_name') or u['display_name'])
            for u in users}
import league_format as LF  # noqa: E402
STARTERS = {p: n for p, n in LF.CORE.items() if n}   # this league's core lineup; flex handled in depth


def pv(pid):
    return cons.get(pid, {}).get('mean', 0)


def srcval(pid, s):
    # raw = magnitude-normalized values; the sell-high gap needs the real
    # FC-vs-KTC magnitude difference, which the rank-normalized `vals` hides.
    return (cons.get(pid, {}).get('raw') or {}).get(s) or 0


teams = {}
for r in rosters:
    uid = r.get('owner_id')
    if not uid:
        continue
    by_pos = {p: [] for p in STARTERS}
    for pid in r.get('players') or []:
        pos = players.get(pid, {}).get('position')
        if pos in by_pos:
            by_pos[pos].append(pid)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: -pv(p))
    starter_val = {pos: sum(pv(p) for p in by_pos[pos][:n]) for pos, n in STARTERS.items()}
    depth_val = {pos: sum(pv(p) for p in by_pos[pos][n:]) for pos, n in STARTERS.items()}
    prof = profiles.get(uid_user.get(uid), {})
    teams[uid] = {'user': uid_user.get(uid), 'team': uid_team.get(uid),
                  'by_pos': by_pos, 'starter_val': starter_val, 'depth_val': depth_val,
                  'pick_share': prof.get('tendencies', {}).get('pick_share', 10),
                  'labels': prof.get('labels', [])}

me_uid = next(u for u, t in teams.items() if t['user'] == CFG['my_username'])
me = teams[me_uid]
me_rid = next(r['roster_id'] for r in rosters if r.get('owner_id') == me_uid)
my_players = [p for p in (next(r for r in rosters if r['roster_id'] == me_rid)
                          .get('players') or [])]


def rank(uid, key, pos):
    vals = sorted((t[key][pos] for t in teams.values()), reverse=True)
    return vals.index(teams[uid][key][pos]) + 1


# ---- schedule-aware layer (optional; value-only if projection.json absent) ----
_pp = os.path.join(DATA, 'projection.json')
PROJ = json.load(open(_pp)) if os.path.exists(_pp) else None
SWING = 5.0          # a game inside this margin is realistically flippable
PLAYOFF_SPOTS = LF.PLAYOFF_TEAMS

if PROJ:
    PW = {pid: {int(w): v for w, v in wks.items()}
          for pid, wks in PROJ['player_weekly'].items()}
    WEEKS = list(range(PROJ['weeks'][0], PROJ['weeks'][1] + 1))
    MYSCHED = PROJ['rosters'][str(me_rid)]['schedule']
    pos_of = lambda pid: (players.get(pid) or {}).get('position')

    def ppg(pid):
        """Projected points per game, averaged over the regular season.
        None = Sleeper publishes no projection for this player (rookie, injured,
        camp body) — distinct from a real 0.0, so callers can say 'unknown'."""
        wks = PW.get(str(pid))
        if not wks:
            return None
        return sum(wks.get(w, 0.0) for w in WEEKS) / len(WEEKS)

    def sim(add=(), drop=()):
        """My season re-run with roster changes, opponents held fixed.
        Returns (wins, [(week, my_pts, opp_pts, won)])."""
        pl = [p for p in my_players if p not in set(drop)] + [p for p in add]
        out, w = [], 0
        for g in MYSCHED:
            pts = lineup_points(pl, g['wk'], PW, pos_of)
            won = pts >= g['opp_pts']
            w += won
            out.append((g['wk'], pts, g['opp_pts'], won))
        return w, out

    BASE_W, BASE_GAMES = sim()

    _flip_cache = {}

    def flips(pid):
        """Games this player flips if acquired (nothing given up on my side).
        Memoized — every buy candidate is now scored, not just the shown ones."""
        if pid not in _flip_cache:
            _flip_cache[pid] = sim(add=[pid])[0] - BASE_W
        return _flip_cache[pid]

    def pos_pts(pids, pos, n):
        return sum(sorted((ppg(p) or 0.0 for p in pids if pos_of(p) == pos),
                          reverse=True)[:n])

    pts_rank = {}
    for pos, n in STARTERS.items():
        vals = sorted((pos_pts(t_r.get('players') or [], pos, n) for t_r in rosters),
                      reverse=True)
        mine = pos_pts(my_players, pos, n)
        pts_rank[pos] = (mine, vals.index(mine) + 1)

holes_val = [pos for pos in STARTERS if rank(me_uid, 'starter_val', pos) >= LF.HOLE_RANK]
holes_pts = ([pos for pos in STARTERS if pts_rank[pos][1] >= LF.HOLE_RANK] if PROJ else [])
# lanes cover both views: dynasty-value gaps AND this-season scoring gaps
holes = [pos for pos in STARTERS if pos in holes_val or pos in holes_pts]
surplus = [pos for pos in STARTERS if rank(me_uid, 'depth_val', pos) <= LF.NUM_TEAMS // 4]

lines = [f'# Move Briefing — {me["team"]} ({latest})', '',
         f'_Generated {date.today().isoformat()} from consensus values '
         f'(FC/KTC/DP/FP) + owner profiles. Heuristic, not gospel — cross-check '
         f'the manual notes in `profiles/`._', '']

lines += ['## Positional standing', '']
if PROJ:
    lines += ['| Pos | Starters value | Value rank | Proj pts/gm | Points rank | Depth rank |',
              '|---|---|---|---|---|---|']
    for pos in STARTERS:
        pts, prk = pts_rank[pos]
        lines.append(f"| {pos} | {me['starter_val'][pos]:,.0f} | "
                     f"#{rank(me_uid, 'starter_val', pos)} of {LF.NUM_TEAMS} | {pts:.1f} | "
                     f"#{prk} of {LF.NUM_TEAMS} | #{rank(me_uid, 'depth_val', pos)} |")
    lines += ['', f"**Dynasty-value holes:** {', '.join(holes_val) or 'none'} · "
              f"**This-season scoring holes:** {', '.join(holes_pts) or 'none'} · "
              f"**Tradeable depth:** {', '.join(surplus) or 'none'}", '']
    only_val = [p for p in holes_val if p not in holes_pts]
    if only_val:
        lines += [f"> {', '.join(only_val)} reads as a hole on dynasty value but not on 2026 "
                  f"points — that's an age/asset gap, not a lineup gap. Don't pay win-now "
                  f"prices to fix it.", '']
else:
    lines += ['| Pos | Starters value | League rank | Depth rank |', '|---|---|---|---|']
    for pos in STARTERS:
        lines.append(f"| {pos} | {me['starter_val'][pos]:,.0f} | "
                     f"#{rank(me_uid, 'starter_val', pos)} of {LF.NUM_TEAMS} | "
                     f"#{rank(me_uid, 'depth_val', pos)} |")
    lines += ['', f"**Holes:** {', '.join(holes) or 'none'} · "
              f"**Tradeable depth:** {', '.join(surplus) or 'none'}", '']

# schedule reality
if PROJ:
    mine = PROJ['rosters'][str(me_rid)]
    place, losses = mine['place'], len(WEEKS) - BASE_W
    cut = 'in the playoff field' if place <= PLAYOFF_SPOTS else 'outside the playoff field'
    swing = [(wk, a, b) for wk, a, b, won in BASE_GAMES if abs(a - b) <= SWING]
    close_l = sorted((b - a, wk) for wk, a, b, won in BASE_GAMES if not won and b - a <= SWING)
    lines += ['## Schedule reality (Sleeper weekly projections over the set schedule)', '',
              f'**Projected {BASE_W}-{losses}, finish #{place} of {LF.NUM_TEAMS} — {cut}** '
              f'(top {PLAYOFF_SPOTS} make it).', '']
    if swing:
        lines.append(f'{len(swing)} of {len(WEEKS)} games project inside {SWING:.0f} points — '
                     f'that band is where roster moves actually change your record:')
        lines.append('')
        for wk, a, b in swing:
            opp_rid = next(g['opp'] for g in MYSCHED if g['wk'] == wk)
            opp_uid = next((r.get('owner_id') for r in rosters
                            if r['roster_id'] == opp_rid), None)
            lines.append(f"- Week {wk} vs {uid_team.get(opp_uid, '?')}: "
                         f"{a:.1f}–{b:.1f} ({a - b:+.1f})")
        lines.append('')
    if close_l:
        need = close_l[0][0]
        lines += [f'**Cheapest win available:** +{need:.1f} pts/week flips week {close_l[0][1]}. '
                  f'Flipping all {len(close_l)} close losses needs +{close_l[-1][0]:.1f}/week.', '']
    lines += ['_Deterministic point estimate — no variance, and preseason projections '
              'compress TE/QB. Read the record as the center of a ~±2 win band._', '']

# buy lanes
lines += ['## Buy lanes', '']
if PROJ:
    lines += ['_`Δ` = projected pts/gm this player adds to my best lineup · '
              '`flips` = games that swings on the real schedule (opponents fixed, '
              'nothing given back). A high-value name with `flips 0` is an asset '
              'play, not a 2026 fix._', '']
SELLER_SHARE = 15        # same threshold the lane text calls "likely seller"


def is_seller(t):
    """Rebuilders sell STARTERS, not just bench. Their best player at a position
    is usually the one worth having, so don't filter it out of their lane —
    price it as a premium instead."""
    return t['pick_share'] >= SELLER_SHARE or \
        any('accumulating' in lab for lab in t['labels'])


for pos in holes:
    lanes = []
    for uid, t in teams.items():
        if uid == me_uid:
            continue
        seller = is_seller(t)
        pool = t['by_pos'][pos] if seller else t['by_pos'][pos][STARTERS[pos]:]
        cand = [p for p in pool if pv(p) >= 1200]
        if not cand and not seller and STARTERS[pos] == 1 and len(t['by_pos'][pos]) > 1:
            cand = [p for p in t['by_pos'][pos][1:] if pv(p) >= 1200]
        if not cand:
            continue
        # rank within the team by what the player actually does for me, not by
        # what he is worth in the abstract
        cand.sort(key=(lambda p: (flips(p), ppg(p) or 0.0, pv(p))) if PROJ
                  else (lambda p: pv(p)), reverse=True)
        top = cand[:2]
        starters = set(t['by_pos'][pos][:STARTERS[pos]])
        key = ((max(flips(p) for p in top), sum(pv(p) for p in top)) if PROJ
               else (sum(pv(p) for p in top),))
        lanes.append((key, t['pick_share'], uid, top, starters, seller))
    lanes.sort(key=lambda x: x[0], reverse=True)
    why = ''
    if PROJ:
        tags = (['dynasty value'] if pos in holes_val else []) + \
               (['2026 points'] if pos in holes_pts else [])
        why = f" — hole on {' + '.join(tags)}"
    lines.append(f'### {pos}{why}')
    # the player a new starter would displace = my marginal (worst) starter here
    marginal = (pos_pts(my_players, pos, STARTERS[pos])
                - pos_pts(my_players, pos, STARTERS[pos] - 1)) if PROJ else 0
    for _, mot, uid, top, starters, seller in lanes[:4]:
        t = teams[uid]
        parts = []
        for p in top:
            s = f"{players[p].get('full_name')} ({players[p].get('age')}, {pv(p):,.0f}"
            if PROJ:
                g = ppg(p)
                s += (f", Δ{g - marginal:+.1f}/gm, flips {flips(p)}" if g is not None
                      else ', no 2026 projection')
            if p in starters:
                s += ', THEIR STARTER'
            for f in flags(p):
                s += f', {f}'
            parts.append(s + ')')
        will = ('likely seller' if mot >= SELLER_SHARE else
                'possible seller' if mot >= 9 else 'reluctant — will charge a premium')
        lines.append(f"- **{t['team']}** ({t['user']}): {', '.join(parts)} — {will} "
                     f"({mot}% of assets in picks)")
    lines.append('')
if any(is_seller(t) for u, t in teams.items() if u != me_uid):
    lines += ['_`THEIR STARTER` = the player that team actually starts. Only shown for '
              'rebuilders and pick-hoarders, who do sell starters — expect to pay a '
              'premium, but this is where the real upgrades live._', '']

# sell lanes
allin = sorted(((t['pick_share'], uid) for uid, t in teams.items() if uid != me_uid))
buyers = [uid for _, uid in allin[:3]]
oldies = [p for pos in STARTERS for p in me['by_pos'][pos]
          if (players[p].get('age') or 0) >= 29 and pv(p) >= 1200]
lines += ['## Sell lanes (my aging/sell-high assets → all-in buyers)', '']
if oldies:
    for p in sorted(oldies, key=lambda x: -pv(x)):
        pl = players[p]
        lines.append(f"- **{pl.get('full_name')}** ({pl.get('age')}, {pv(p):,.0f}) — "
                     f"buyers: " + ', '.join(teams[b]['team'] for b in buyers))
else:
    lines.append('- No obvious age-29+ sell candidates.')
lines.append('')

# sell-high flags (crowd >> trades)
flags = []
for pos in STARTERS:
    for p in me['by_pos'][pos]:
        fc, ktc = srcval(p, 'FantasyCalc'), srcval(p, 'KeepTradeCut')
        if fc and ktc and ktc - fc >= 1500 and pv(p) >= 1500:
            flags.append((ktc - fc, p, fc, ktc))
flags.sort(reverse=True)
lines += ['## Sell-high flags (crowd values these far above real trades — quote KTC)', '']
for gap, p, fc, ktc in flags[:6]:
    lines.append(f"- {players[p].get('full_name')}: trades say {fc:,.0f}, "
                 f"crowd says {ktc:,.0f} (gap {gap:,.0f})")
if not flags:
    lines.append('- none right now')
lines.append('')

# FAAB
rostered = set()
for r in rosters:
    rostered.update(r.get('players') or [])
fas = sorted(((pv(p), p) for p in cons
              if p not in rostered and players.get(p, {}).get('position') in holes),
             reverse=True)[:8]
lines += [f"## FAAB targets at hole positions ({', '.join(holes) or '—'})", '']
if PROJ:
    # a free agent costs only money, so rank these by what they actually do to the
    # record, not by dynasty value
    scored = sorted(((flips(p), ppg(p) or -1, v, p) for v, p in fas), reverse=True)
    for f, g, v, p in scored:
        pl = players[p]
        rate = f'{g:.1f} pts/gm' if g >= 0 else 'no 2026 projection'
        lines.append(f"- {pl['position']} {pl.get('full_name')} ({pl.get('team') or 'FA'}) — "
                     f"value {v:,.0f}, {rate}, **flips {f}**")
    if scored and scored[0][0] == 0:
        lines.append('')
        lines.append('> No free agent flips a game on projection — spend FAAB on '
                     'injury insurance and upside stashes, not on chasing wins.')
else:
    for v, p in fas:
        pl = players[p]
        lines.append(f"- {pl['position']} {pl.get('full_name')} ({pl.get('team') or 'FA'}) — {v:,.0f}")
# ---------------------------------------------------------------- risk board
# Availability, contract year and handcuff ownership for MY roster. None of
# this is in the consensus number; all of it changes what I should do.
if ctx:
    lines += ['## Roster risk board (availability · contract · handcuff)', '']
    owner_of = {p: uid_user.get(r['owner_id'], '?') for r in rosters
                for p in (r.get('players') or [])}
    hurt, walks, hc_rows = [], [], []
    for p in sorted(my_players, key=lambda x: -pv(x)):
        c, pl = ctx.get(p), players.get(p) or {}
        if not c:
            continue
        body = (c.get('injury') or {}).get('body_part')
        note = (c.get('injury') or {}).get('notes')
        if c.get('avail') not in (None, 'OK'):
            hurt.append(f"- **{pl.get('full_name')}** ({pl.get('position')}, "
                        f"{pv(p):,.0f}) — {c['avail']}"
                        + (f", {body}" if body else '')
                        + (f" ({note})" if note else ''))
        con = c.get('contract') or {}
        if con.get('walk_year'):
            walks.append(f"- **{pl.get('full_name')}** ({pl.get('position')}, "
                         f"{pl.get('age')}, {pv(p):,.0f}) — free agent "
                         f"{con['fa_year']} ({con['fa_type']}), "
                         f"${(con.get('apy') or 0) / 1e6:.1f}M/yr")
        h = (c.get('handcuff') or {}).get('handcuff')
        if h and pl.get('position') in ('RB', 'QB', 'TE') and pv(p) >= 1200:
            hn = (players.get(h) or {}).get('full_name', h)
            who = owner_of.get(h)
            hc_rows.append(f"- **{pl.get('full_name')}** ({pv(p):,.0f}) → "
                           f"handcuff **{hn}** — "
                           + ('**mine**' if who == uid_user.get(me_uid) else
                              f'held by {who}' if who else 'FREE AGENT'))
    lines += (['### Not fully available', ''] + hurt + ['']) if hurt else []
    lines += (['### Playing out the last year of the deal', ''] + walks
              + ['', '_A walk year cuts both ways — a new team can raise or '
                 'wreck the projection. It is a reason to decide, not a reason '
                 'to sell._', '']) if walks else []
    if hc_rows:
        lines += ['### Handcuffs on my key men', ''] + hc_rows + ['']

    aged = [p for p in my_players if ctx.get(p, {}).get('age_flag')]
    if aged:
        lines += ['### Past the positional decline age', '']
        for p in sorted(aged, key=lambda x: -pv(x)):
            a = ctx[p]['age_flag']
            lines.append(f"- **{players[p].get('full_name')}** "
                         f"({a['pos']}, {a['age']}, {pv(p):,.0f}) — "
                         f"{a['pos']}s break at {a['decline_age']} in the "
                         f"2019-25 retention data")
        lines += ['', '_Only RB is flagged. Measured year-over-year with '
                  'washouts counted as zero, RBs keep 81% of production through '
                  'age 26-27 and 60% from 27-28. **The same test finds no WR '
                  'cliff at all through 31** (80-84% every year), which cuts '
                  'against reading the Nico/Smith/Higgins cohort as one asset '
                  'that expires together. Re-run `ops/age_curve.py` as seasons '
                  'accumulate._', '']

    nhc = [p for p in my_players if ctx.get(p, {}).get('new_hc')]
    if nhc:
        lines += ['### New head coach (offense being rewritten)', '']
        for p in sorted(nhc, key=lambda x: -pv(x)):
            h = ctx[p]['new_hc']
            lines.append(f"- **{players[p].get('full_name')}** "
                         f"({players[p].get('team')}, {pv(p):,.0f}) — "
                         f"{h['departing']} -> **{h['incoming']}**")
        lines += ['', '_Head coaches only — no free source publishes a '
                  'league-wide coordinator table, so an OC change under a '
                  'retained head coach still needs a manual note._', '']

    bye_of = collections.defaultdict(list)
    for p in my_players:
        b = ctx.get(p, {}).get('bye')
        if b and pv(p) >= 1000:
            bye_of[b].append(p)
    stacked = {w: ps for w, ps in bye_of.items() if len(ps) >= 2}
    if stacked:
        lines += ['### Bye-week stacking', '']
        for w in sorted(stacked):
            names = ', '.join(f"{players[p].get('full_name')} "
                              f"({players[p].get('position')})"
                              for p in sorted(stacked[w], key=lambda x: -pv(x)))
            lines.append(f'- **Week {w}** — {len(stacked[w])} of my assets off: {names}')
        lines += ['', '_Only players worth 1,000+ are counted. Two starters on '
                  'the same bye is a loss you can see in September._', '']

    sos_rows = []
    for p in my_players:
        c = ctx.get(p) or {}
        if c.get('sos') and pv(p) >= 1400:
            sos_rows.append((c['sos']['mean_rank'], p, c['sos']))
    if sos_rows:
        wk = ', '.join(str(x['wk']) for x in sos_rows[0][2]['weeks'])
        lines += [f'### Fantasy-playoff matchups (weeks {wk})', '',
                  '_Rank is the opponent defense at HIS position, out of 32, on '
                  'PPR points allowed per game. **Rank 1 = softest draw**, 32 = '
                  'toughest. Low mean rank is good._', '']
        for mr, p, sd in sorted(sos_rows):
            det = ' · '.join(f"wk{x['wk']} {x['opp']} (#{x['rank']})"
                             for x in sd['weeks'])
            lines.append(f"- **{players[p].get('full_name')}** "
                         f"({players[p].get('position')}) — mean **#{mr}** — {det}")
        lines += ['', f"_Defensive baseline: {sos_rows[0][2]['baseline']} box "
                  'scores. Personnel turns over, so treat this as a tiebreaker, '
                  'not a projection._', '']

    if usage:
        role = [(pv(p), p, usage[p]) for p in my_players
                if usage.get(p) and pv(p) >= 1000]
        if role:
            lines += ['### Role check — snap and target share',
                      f"(last completed season: {role[0][2]['season']})", '',
                      '| Player | Pos | Value | G | Snap% | Tgt share | Air yds share | PPR/gm |',
                      '|---|---|---|---|---|---|---|---|']
            for v, p, u in sorted(role, reverse=True):
                pos_ = players[p].get('position')
                pct = lambda x: f'{x * 100:.0f}%' if x is not None else '—'
                ts = pct(u['target_share']) if pos_ != 'QB' else '—'
                ay = pct(u['air_yards_share']) if pos_ in ('WR', 'TE') else '—'
                lines.append(f"| {players[p].get('full_name')} | {pos_} | "
                             f"{v:,.0f} | {u['games']} | {pct(u['snap_pct'])} | "
                             f"{ts} | {ay} | {u['ppr_ppg']:.1f} |")
            lines += ['', '_Usage moves before value does. A high value with a '
                      'falling snap share is the sell the market has not made '
                      'yet; the reverse is the buy._', '']

    radj = [(pv(p), p, ctx[p]['risk']) for p in my_players
            if ctx.get(p, {}).get('risk') and pv(p) >= 1000]
    if radj:
        lines += ['### Downside-adjusted value (`adj`)', '',
                  '_What each asset is worth **if the visible risks break '
                  'badly** — not an expected value, and it never replaces the '
                  'consensus number. Kept separate on purpose: folded into '
                  '`mean` it would silently bias the power rankings and argue '
                  'against you when selling, since the rival quoting KTC has no '
                  'such haircut. Multipliers live in `RISK_MULT` in '
                  '`ops/context.py`._', '',
                  '| Player | Consensus | Adjusted | Δ | Why |', '|---|---|---|---|---|']
        for v, p, r in sorted(radj, reverse=True):
            adj = v * r['mult']
            lines.append(f"| {players[p].get('full_name')} | {v:,.0f} | "
                         f"{adj:,.0f} | {adj - v:+,.0f} | {', '.join(r['why'])} |")
        lines.append('')

lines += ['', '---', '_Standing rules: quote FantasyCalc when buying, KTC when selling. '
          'Check profiles/<owner>.md manual notes before any offer._']

open(os.path.join(ROOT, 'ADVICE.md'), 'w').write('\n'.join(lines) + '\n')
print(f"ADVICE.md written — holes: {holes or 'none'}, depth to trade: {surplus or 'none'}")
