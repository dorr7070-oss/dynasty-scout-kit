#!/usr/bin/env python3
"""The analyst (added 2026-10-04): player lookup, trade analyzer and an ask-anything box -> dashboards/analyst.html,
folded into the one dashboard by hub_dashboard.py (lookup in Players, analyzer in Trades, the box in its own Ask tab).

Everything runs in the page from one embedded bundle built here from every source the pipeline has:
  per player   blended / our / Sleeper projections by week (our_projection.json), injury + practice status, usage
               (snaps, targets, routes, red zone), tracking-data lift (ngs.json), contract + cut risk, market,
               contract-adjusted and plan-window values, 7/30-day value trend, news (21 days) and Sleeper trending
  per team     roster, record, points, remaining schedule, owned picks with values
  league       lineup slots, playoff spots, this week's already-decided scores (decided.py)
The trade analyzer re-runs the season simulation in the browser (same engine as lottery.py: best legal lineup per
week, normal noise SD 22, top-N make it) for every team, before and after the trade, with the SAME random draws
both times so the difference is the trade and not luck. Values are neutral market values (no premium rules).
The ask box hands Claude four page functions (find_player, team, evaluate_trade, league) and answers from them; it
works only once the dashboard is published with the `sample` capability, and each question uses the VIEWER's own
Claude usage. Locally it says so instead of failing.
"""
import html, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import dynasty_value as DV  # noqa: E402
import picks as PK  # noqa: E402

jl = lambda f, d=None: json.load(open(os.path.join(DATA, f))) if os.path.exists(os.path.join(DATA, f)) else d
esc = html.escape


def build_bundle(edition='owner'):
    """The page's data. edition='league' (ops/league_edition.py) drops everything private to this owner: the trade plan,
    their news alerts, which team is theirs, and contract signals phrased from their side."""
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    me = cfg.get('my_username')
    latest = sorted(jl('seasons.json'))[-1]
    P = jl('players.json')
    R = json.load(open(os.path.join(DATA, latest, 'rosters.json')))
    users = json.load(open(os.path.join(DATA, latest, 'users.json')))
    U = {u['user_id']: u['display_name'] for u in users}
    TN = {u['user_id']: ((u.get('metadata') or {}).get('team_name') or u['display_name']).strip() for u in users}
    league = json.load(open(os.path.join(DATA, latest, 'league.json')))
    done = (league.get('settings') or {}).get('last_scored_leg', 0)
    weeks = list(range(done + 1, LF.PLAYOFF_START))
    cons = jl('values/consensus.json', {})
    op = jl('our_projection.json', {'players': {}, 'teams': {}})
    usage = jl('usage.json', {})
    ngs = (jl('ngs.json', {}) or {}).get('players', {})
    cal = jl('contract_calendar.json', {'players': [], 'cut_risk': []})
    ctr = {c['pid']: c for c in cal.get('players', [])}
    cap = (jl('cap_risk.json', {}) or {}).get('players', {})
    news = (jl('news.json', {}) or {}).get('players', {})
    trend = (jl('trending.json', {}) or {}).get('players', {})
    wk = (jl('weekly.json', {}) or {}).get('players', {})
    # value trend for every player (not just flagged movers): today's market vs the dated snapshots ~7 and ~30 days back
    import value_trends as VT
    snaps = sorted(f[:-5] for f in os.listdir(VT.HDIR) if f.endswith('.json') and f[:-5] != time.strftime('%Y-%m-%d')) \
        if os.path.isdir(VT.HDIR) else []
    hist = {k: json.load(open(os.path.join(VT.HDIR, f'{d}.json'))) for k, d in
            ((k, VT.nearest(n, snaps)) for k, n in (('7d', 7), ('30d', 30))) if d}
    def chg(pid, now_v, k):
        old = (hist.get(k) or {}).get(pid)
        return round((now_v - old) / old, 3) if old and old >= 100 and now_v else None
    wv = jl('waivers.json', {}) or {}
    owner = {pid: U.get(r['owner_id']) for r in R for pid in (r['players'] or [])}

    ids = set(owner) | {x['pid'] for k in ('start', 'rising', 'stash') for x in wv.get(k, [])} \
        | {pid for pid, t in trend.items() if t.get('add_24h', 0) >= 20000}
    out = {}
    for pid in ids:
        p = P.get(pid) or {}
        pos = p.get('position')
        if pos not in LF.POS:
            continue
        c = cons.get(pid) or {}
        mkt = round(c.get('mean_market') or c.get('mean') or 0)
        pr = op['players'].get(pid) or {}
        blend = {int(k): v for k, v in (pr.get('weekly') or {}).items()}
        games = [v for w, v in blend.items() if v > 0]
        u = usage.get(pid) or {}
        n = ngs.get(pid) or {}
        cp = cap.get(pid) or {}
        nxt = (cp.get('seasons') or {}).get(str(int(latest) + 1))
        t = trend.get(pid) or {}
        out[pid] = {
            'n': p.get('full_name'), 'p': pos, 't': p.get('team'), 'a': p.get('age'), 'o': owner.get(pid),
            'inj': p.get('injury_status'), 'injp': p.get('injury_body_part'), 'prac': p.get('practice_participation'),
            'mkt': mkt, 'adj': round(c.get('mean') or 0), 'win': round(DV.window_value(mkt, pos, p.get('age'))),
            'tr7': chg(pid, mkt, '7d'), 'tr30': chg(pid, mkt, '30d'),
            'proj': {str(w): blend.get(w, 0) for w in weeks},
            'projO': {str(w): (pr.get('weekly_ours') or {}).get(str(w), (pr.get('weekly_ours') or {}).get(w)) for w in weeks},
            'projS': {str(w): (pr.get('weekly_sleeper') or {}).get(str(w), (pr.get('weekly_sleeper') or {}).get(w)) for w in weeks},
            'ros': round(sum(games) / len(games), 1) if games else 0,
            'ppg': u.get('ppr_ppg'), 'gp': u.get('games'),
            'use': {k: u.get(k) for k in ('snap_pct', 'target_share', 'route_pct_est', 'rz_tgt_share', 'rz_carry_share', 'air_yards_share')},
            'ngs': {'lift': n.get('lift'), 'next': n.get('lift_next'), 'watch': n.get('watch')} if n else None,
            'ctr': {k: (ctr.get(pid) or {}).get(k) for k in ('class', 'signal')} if pid in ctr else None,
            'fa': ((cons.get(pid) or {}).get('contract') or {}).get('fa_year'),
            'cut': {'tier': cp.get('next_tier'), 'save': (nxt or {}).get('save_cut'), 'dead': (nxt or {}).get('dead_cut')} if cp else None,
            'news': [{'k': x['kind'], 'h': x['headline'], 'ago': x['hours_ago'], 'u': x.get('url')} for x in (news.get(pid) or [])[:5]],
            'trn': {'add': t.get('add_24h', 0), 'drop': t.get('drop_24h', 0), 'add7': t.get('add_7d', 0)} if t else None,
            'flags': (wk.get(pid) or {}).get('flags', []), 'wk': (wk.get(pid) or {}).get('proj'),
        }

    sched = {int(k): v['schedule'] for k, v in (jl('projection.json', {}) or {}).get('rosters', {}).items()}
    teams = {}
    owned = PK.owned_future_picks()
    for r in R:
        rid = r['roster_id']
        st = r.get('settings') or {}
        act = [x for x in (r['players'] or []) if x not in (r.get('reserve') or []) and x not in (r.get('taxi') or [])]
        pk = []
        for season, rnd, orig in owned.get(rid, []):
            v, tier = PK.pick_value(season, rnd, orig)
            pk.append({'k': f'pick:{season}:{rnd}:{orig}', 'l': f'{season} {tier} {PK._RN.get(rnd, rnd)} ({U.get(next((x["owner_id"] for x in R if x["roster_id"] == orig), ""), "?")})',
                       'v': round(v)})
        tp = (op.get('teams') or {}).get(str(rid)) or {}
        teams[rid] = {'owner': U.get(r['owner_id']), 'name': TN.get(r['owner_id']), 'players': act,
                      'all': list(r['players'] or []),          # incl. IR / taxi: tradeable, but not in the lineup
                      'w': st.get('wins', 0), 'l': st.get('losses', 0),
                      'pf': round(st.get('fpts', 0) + st.get('fpts_decimal', 0) / 100, 2),
                      'sched': [{'wk': g['wk'], 'opp': g['opp']} for g in sched.get(rid, []) if g['wk'] in weeks],
                      'picks': pk, 'po': tp.get('playoff'), 'xw': tp.get('exp_wins')}
    from decided import decided
    locked = decided(weeks[0]) if weeks else {}
    my_rid = next(r['roster_id'] for r in R if U.get(r['owner_id']) == me)
    om = jl('our_model.json', {}) or {}
    fr = jl('freshness.json', {}) or {}
    bundle = {
        'generated': time.strftime('%Y-%m-%d %H:%M'), 'league': LF.LEAGUE_NAME, 'season': latest, 'me': me, 'my_rid': my_rid,
        'weeks': weeks, 'core': LF.CORE, 'flex': [sorted(f) for f in LF.FLEX_SLOTS], 'playoff_teams': LF.PLAYOFF_TEAMS,
        'median': LF.MEDIAN_GAME, 'locked': {str(k): v for k, v in locked.items()}, 'sd': 22,
        'players': out, 'teams': {str(k): v for k, v in teams.items()},
        'plan': jl('trade_plan.json', {}), 'alerts': (jl('news.json', {}) or {}).get('alerts', [])[:12],
        'fresh': {'checked': fr.get('generated'), 'stale': [c['source'] for c in fr.get('checks', []) if c['status'] != 'ok']},
        'model': {'blend': om.get('blend'), 'test': (om.get('blend_test') or {}).get('ours'), 'test_sleeper': (om.get('blend_test') or {}).get('sleeper'),
                  'test_blend': (om.get('blend_test') or {}).get('blend')},
    }
    if edition == 'league':
        for k in ('plan', 'alerts', 'me', 'my_rid'):
            bundle.pop(k, None)
        for x in bundle['players'].values():
            if x.get('ctr'):
                x['ctr'] = {'class': x['ctr'].get('class')}          # the signal text is written from this owner's side
    return bundle


def main():
    bundle = build_bundle()
    out, teams, weeks, locked = bundle['players'], bundle['teams'], bundle['weeks'], bundle['locked']
    js = open(os.path.join(ROOT, 'ops', 'analyst.js')).read()
    css = open(os.path.join(ROOT, 'ops', 'analyst.css')).read()
    body = f'''<meta charset="utf-8"><title>Analyst</title><style>{css}</style><div class="wrap">
<section id="lookup"><div class="kicker">Analyst</div><h2 class="disp">Player Lookup</h2>
<p class="lede">Type any player in the league, or a free agent people are adding. One card: projections (ours, Sleeper's and the
blend that beat both in testing), injuries and practice, usage, tracking data, contract and cut risk, value and trend, news.</p>
<div class="an-search"><input id="an-q" type="search" placeholder="Player name…" autocomplete="off" aria-label="Player name"><div id="an-sug" class="an-sug" role="listbox"></div></div>
<div id="an-card"></div></section>
<section id="analyzer"><div class="kicker">Analyst</div><h2 class="disp">Trade Analyzer</h2>
<p class="lede">Build any trade between two teams. It re-runs the whole season for every team, before and after, with the same
random draws both times, so the change you see is the trade, not luck. Values are neutral market values.</p>
<div class="an-trade"><div class="an-side" id="an-a"></div><div class="an-side" id="an-b"></div></div>
<button class="an-btn" id="an-go" type="button">Evaluate trade</button><div id="an-out" aria-live="polite"></div></section>
<section id="ask"><div class="kicker">Analyst</div><h2 class="disp">Ask the Analyst</h2>
<p class="lede">Ask anything about your team, a player, a trade or the league in plain English. Claude answers from this
dashboard's data (it can look players up, open any team, run the trade analyzer) and says when something isn't in it.
Each question uses the viewer's own Claude usage.</p>
<div class="an-ask"><textarea id="an-in" rows="3" placeholder="e.g. Should I trade Smith and a 3rd for McMillan? Who's my best waiver add this week?"></textarea>
<div class="an-row"><button class="an-btn" id="an-ask" type="button">Ask</button><button class="an-btn ghost" id="an-stop" type="button" hidden>Stop</button>
<span id="an-note" class="an-note"></span></div><div id="an-ans" class="an-ans" aria-live="polite"></div></div></section>
<script type="application/json" id="ad">{json.dumps(bundle, separators=(",", ":")).replace("</", "<" + chr(92) + "/")}</script>
<script>{js}</script></div>'''
    open(os.path.join(ROOT, 'dashboards', 'analyst.html'), 'w').write(body)
    print(f'analyst -> dashboards/analyst.html ({len(body) // 1024} KB): {len(out)} players, {len(teams)} teams, weeks {weeks[0]}-{weeks[-1]}, '
          f'{len(locked)} decided this week')


if __name__ == '__main__':
    main()
