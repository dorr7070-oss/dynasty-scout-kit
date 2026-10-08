#!/usr/bin/env python3
"""THE one dashboard -> dashboards/hub.html (live since 2026-10-08; replaced hub_dashboard.py's layout, whose helpers it reuses).

Same content as hub.html, reorganised so it reads summary-first:
  * a short header: team, tiles (with "since your last visit" changes), key dates, a search button;
  * This Week opens on "Do this now" — action cards computed from the data (lineup fix, game-time calls,
    injuries, waivers, news, trade deadline, value movers) — then your opponent, then the live matchup;
  * five tabs (This Week · Trades · My Season · League · Picks); the old Players tab's deep dives live under
    My Season, Player Lookup + Ask the Analyst move behind the search button;
  * every detailed section is folded behind its heading and a one-line description, except each tab's lead view.

Generic like hub.html: everything comes from the owner's own config and data, so every kit user gets it for
their own team. Run after hub_dashboard.py's inputs exist (league/analysis/gameday/assets/analyst.html).
"""
import html, json, math, os, re, sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'dashboards')
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
import hub_dashboard as H   # noqa: E402  (parts / scope_css / heading / drop_links)

esc = html.escape
TABS = [('week', 'This Week', 'Week'), ('trades', 'Trades', 'Trades'), ('season', 'My Plan', 'Plan'),
        ('league', 'League', 'League'), ('picks', 'Picks', 'Picks')]
DEEP = 100   # My Season items at or past this order sit under "Your players in depth"
ROUTE = [  # (heading starts with, tab, order, open?, one-line description shown on the folded heading)
    ('Start / Sit', 'week', 30, False, 'Every lineup slot with our projection, kickoff, weather and the backup plan'),
    ('Waivers, Injuries', 'week', 40, False, 'Free agents worth a bid, injury reads for every roster, and players the market is moving on'),
    ('News & Data Check', 'week', 50, False, 'Recent news on rostered players, and whether every data source refreshed'),
    ('Trade Analyzer', 'trades', 10, True, 'Build any trade and see how it changes your playoff odds and dynasty value'),
    ('Plan Check', 'trades', 20, False, 'How your written trade plan scores right now'),
    ('Trade Finder', 'trades', 30, False, 'Offers each owner is likely to accept, ranked by how much they help you'),
    ('What Would It Take', 'trades', 40, False, 'What it would cost to pry a specific player loose'),
    ('My Team', 'trades', 50, False, 'Your roster by position, holes, depth to trade, and standing advice'),
    ('Contract Calendar', 'trades', 60, False, 'Players whose real-life contract status should change when you buy or sell'),
    ('Playoff Race', 'season', 10, True, ''),
    ('Your Remaining Schedule', 'season', 20, False, 'Each remaining week: opponent, projected score, win odds'),
    ('Our Projections vs Sleeper', 'season', 30, False, 'Where our model and Sleeper disagree about each team'),
    ('Projection Accuracy', 'season', 35, False, 'How close our weekly projections have been so far this season'),
    ('Starters vs the League', 'season', 100, False, 'Your starters compared with every team at each position'),
    ('Your Players, Week by Week', 'season', 110, False, 'Points and projections for each of your players, week by week'),
    ('Value History', 'season', 120, False, 'How trade values have moved over the last month'),
    ('Availability, Contracts', 'season', 130, False, 'Injury history, contract years and handcuffs'),
    ('Strength of Schedule', 'season', 140, False, 'Which of your players have easy or hard schedules ahead'),
    ('Tracking Data', 'season', 150, False, 'Players whose tracking stats say they are better or worse than their box score'),
    ('Scheme Change', 'season', 160, False, 'New head coaches and players with downside risk'),
    ('The WR Cliff', 'season', 170, False, 'Why receiver value drops off sharply past a certain age'),
    ('Power Rankings', 'league', 10, True, ''),
    ('Every Owner at a Glance', 'league', 20, False, 'Each owner: window, needs, trade habits'),
    ('Lineup Efficiency', 'league', 30, False, 'Points each owner left on the bench'),
    ('Trade Grades', 'league', 40, False, 'Every trade in league history, graded'),
    ('Owner Board', 'league', 50, False, 'Scouting notes on each owner'),
    ('Lottery Tracker', 'picks', 10, True, ''),
    ('Draft Capital', 'picks', 20, False, 'Who holds the most pick value, by year'),
    ('Player Lookup', 'find', 10, True, ''),
    ('Ask the Analyst', 'find', 20, True, ''),
]


def J(name, default=None):
    try:
        return json.load(open(os.path.join(DATA, name)))
    except Exception:
        return default if default is not None else {}


def slug(s):
    return 'sec-' + re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:40]


def fold(title, blurb, frag, opened=False):
    return (f'<details class="fold" id="{slug(title)}"{" open" if opened else ""}><summary><span class="ft">{esc(title)}</span>'
            + (f'<span class="fb">{esc(blurb)}</span>' if blurb else '') + f'</summary><div class="fold-body">{frag}</div></details>')


# ------------------------------------------------------------------ "Do this now" — computed, never typed
def action_cards():
    cfg = LF.CFG
    me = cfg.get('my_username')
    wk = J('weekly.json')
    players = wk.get('players', {})
    name = lambda pid: (players.get(pid) or {}).get('name') or pid
    my_rid = next((r for r, t in wk.get('teams', {}).items() if t.get('owner') == me), None)
    team = wk.get('teams', {}).get(my_rid, {}) if my_rid else {}
    week = wk.get('week')
    cards = []   # (tag, css, title, detail, go)

    mine = [p for p in players.values() if p.get('owner') == me and p.get('ko')]
    first_ko = min(mine, key=lambda p: p['ko'])['kickoff'] if mine else None
    if team:
        if team.get('gain', 0) >= 0.5:
            ins = ', '.join(name(p) for p in team.get('swap_in', []))
            outs = ', '.join(name(p) for p in team.get('swap_out', []))
            cards.append(('Lineup', 'crit', f'Start {ins} over {outs}',
                          f'About +{team["gain"]:.1f} points ({team["set_total"]:.1f} → {team["best_total"]:.1f} projected).'
                          + (f' First lock: {first_ko}.' if first_ko else ''), 'sec-start-sit'))
        else:
            cards.append(('Lineup', 'good', 'Your lineup is already the best one we can find',
                          f'{team.get("set_total", 0):.1f} projected points.', 'sec-start-sit'))
        calls = [g for g in team.get('gametime_plans', []) if g.get('p_play', 1) < 0.8]
        if calls:
            cards.append(('Game-time', 'warn', 'Game-time calls: ' + ', '.join(name(g['pid']) for g in calls),
                          '\n'.join(f'{name(g["pid"])} plays ~{g["p_play"] * 100:.0f}%'
                                     + (f', backup {name(g["fallback"])}' if g.get('fallback') else '')
                                     + f' (locks {g["lock"]})' for g in calls), 'sec-start-sit'))
    out = [p for p in J('injury_outlook.json').get('players', []) if p.get('owner') == me
           and p.get('status') in ('Out', 'IR', 'Doubtful', 'PUP', 'Suspended')]
    if out:
        cards.append(('Injury', 'warn', 'Hurt: ' + ', '.join(p['name'] for p in out),
                      '\n'.join(f'{p["name"]}: {p.get("read") or p.get("status")}' for p in out), 'sec-waivers-injuries-market-movers'))
    wv = J('waivers.json')
    if wv:
        bud = wv.get('budget_left')
        if wv.get('start'):
            w = wv['start'][0]
            cards.append(('Waivers', 'crit', f'Claim {w["name"]} ({w.get("pos", "")}, {w.get("team", "")})',
                          f'Would start for you. Suggested bid ${w.get("bid", 0)}' + (f' of ${bud} left.' if bud is not None else '.'),
                          'sec-waivers-injuries-market-movers'))
        else:
            stash = wv.get('stash') or wv.get('rising') or []
            cards.append(('Waivers', '', 'No free agent would start for you this week',
                          (f'Worth a stash: {", ".join(s["name"] for s in stash[:2])}. ' if stash else '')
                          + (f'${bud} budget left.' if bud is not None else ''), 'sec-waivers-injuries-market-movers'))
    for a in [a for a in J('news.json').get('alerts', []) if a.get('mine')][:2]:
        cards.append(('News', '', a['headline'], f'{a["player"]} · {a.get("kind", "")} · {a.get("hours_ago", 0):.0f}h ago',
                      'sec-news-data-check'))
    dl = LF.PROFILE.get('trade_deadline_week')
    tf = J('trade_finder.json')
    best = (tf.get('top') or [None])[0]
    if dl and week:
        left = dl - week
        line = (f'{left} week{"s" if left != 1 else ""} until the trade deadline (week {dl}).' if left > 0 else
                'Trade deadline is this week.' if left == 0 else f'The trade deadline (week {dl}) has passed.')
        if best and left >= 0:
            cards.append(('Trade', '', f'Best offer found: {" + ".join(best["give_labels"])} to {best["partner"]} for {best["get_label"]}',
                          f'{line} Adds about {best["my_wins"]:+.1f} wins this season.', 'sec-trade-finder'))
        else:
            cards.append(('Trade', '', line, '', 'sec-trade-finder'))
    vt = [m for m in J('value_trends.json').get('movers', []) if m.get('owner') == me]
    if vt:
        up = sorted(vt, key=lambda m: -m.get('w', 0))[:2]
        dn = sorted(vt, key=lambda m: m.get('w', 0))[:2]
        f = lambda m: f'{m["name"]} {(m.get("w", 0)) * 100:+.0f}%'
        cards.append(('Value', '', 'Your biggest value moves this week',
                      'Up: ' + ', '.join(f(m) for m in up if m.get('w', 0) > 0) +
                      ('. Down: ' + ', '.join(f(m) for m in dn if m.get('w', 0) < 0) if any(m.get('w', 0) < 0 for m in dn) else ''),
                      'sec-value-history'))
    return cards, my_rid, week


def opponent_card(my_rid, week):
    wk = J('weekly.json')
    mu = (J(os.path.join(str(LF.PROFILE.get('season') or wk.get('season')), 'matchups.json')) or {}).get(str(week)) or []
    mine = next((m for m in mu if str(m.get('roster_id')) == str(my_rid)), None)
    if not mine:
        return ''
    opp = next((m for m in mu if m.get('matchup_id') == mine.get('matchup_id') and m is not mine), None)
    if not opp:
        return ''
    teams = wk.get('teams', {})
    me_t, op_t = teams.get(str(my_rid), {}), teams.get(str(opp['roster_id']), {})
    ours = [p for p in J('injury_outlook.json').get('players', []) if p.get('owner') == op_t.get('owner')
            and p.get('pid') in (op_t.get('set') or [])]
    gap = me_t.get('set_total', 0) - op_t.get('set_total', 0)
    inj = (' Their hurt starters: ' + ', '.join(f'{p["name"]} ({p["status"]})' for p in ours) + '.') if ours else ' No injury tags on their starters.'
    return (f'<div class="opp"><div class="kicker">Week {week} opponent</div><div class="opp-row"><b>{esc(op_t.get("owner", "?"))}</b>'
            f'<span class="num">{me_t.get("set_total", 0):.1f} – {op_t.get("set_total", 0):.1f}</span></div>'
            f'<div class="fb">Projected with both lineups as set: you are {"ahead" if gap >= 0 else "behind"} by {abs(gap):.1f}.{esc(inj)}</div></div>')


def key_dates(week):
    dl = LF.PROFILE.get('trade_deadline_week')
    ps = LF.PLAYOFF_START
    wv = J('waivers.json')
    bits = [f'Week {week}' if week else None,
            f'Trade deadline: week {dl}' if dl else None,
            f'Playoffs: weeks {ps}–{ps + 2}' if ps else None,
            f'FAAB: ${wv["budget_left"]} left' if wv.get('budget_left') is not None else None]
    return '<div class="dates">' + ''.join(f'<span>{esc(b)}</span>' for b in bits if b) + '</div>'


# ------------------------------------------------------------------ king's ransom: what it is, and this league's own numbers
def league_trade_margins():
    """How lopsided this league's trades have been (winner's value edge, today's market values) — every league gets its
    own reference points for choosing a ransom."""
    try:
        import trade_grades as TG
        _, trades = TG.grade()
        m = sorted(t[0] for t in trades)
    except Exception:
        return None
    if not m:
        return None
    return {'n': len(m), 'median': m[len(m) // 2], 'p90': m[min(len(m) - 1, int(len(m) * 0.9))], 'max': m[-1]}


def ransom_explainer(cdef):
    prem = LF.CFG.get('premium') or {}
    surplus = sorted({v.get('surplus') for v in prem.values() if isinstance(v, dict) and v.get('surplus')})
    mine = cdef.get('ransom') or (surplus[0] if surplus else None)
    M = league_trade_margins()
    yours = (f'Yours is <b>+{mine:,}</b>.' if mine else 'You haven\'t set one yet, so the Trade Finder treats every player the same.')
    bench = ''
    if M:
        bench = (f'<p>In this league ({M["n"]} trades so far, valued at today\'s prices) the typical winner came out about '
                 f'<b>+{M["median"]:,.0f}</b> ahead, 1 trade in 10 cleared <b>+{M["p90"]:,.0f}</b>, and the most lopsided ever was '
                 f'<b>+{M["max"]:,.0f}</b>.' + (f' At +{mine:,} a core piece only moves for '
                 + ('a deal as lopsided as the biggest this league has ever seen.' if mine >= M['max'] * 0.9 else
                    'one of this league\'s most lopsided deals.' if mine >= M['p90'] else 'a clearly lopsided, but not unheard-of, deal.')
                 if mine else '') + '</p>')
    return ('<details class="explain"><summary>What\'s a king\'s ransom, and how do I set mine?</summary>'
            '<p>A king\'s ransom is the price tag on your core. No one is untouchable, but a core player (or pick) only moves '
            'when the trade clearly pays you back. What "pays you back" means depends on your league:</p>'
            '<p><b>Dynasty / keeper:</b> measured against <b>your long-term plan</b>. Each piece is valued across the seasons your '
            'plan covers: players age along measured curves, and a draft pick counts only from the year it can play. A '
            'contend-now plan therefore discounts far-off picks and older players; a rebuild plan that runs later counts them. '
            'The package must beat what you give by your number.</p>'
            '<p><b>Redraft:</b> measured on <b>this season</b>: the trade must add at least a set number of expected wins '
            '(default +0.5).</p>'
            f'<p>The Trade Finder enforces it and lists the best qualifying package from each team. {yours}</p>' + bench +
            '<p><b>Choosing a number:</b> higher means your core almost never moves; lower means you\'ll see more offers for '
            'them. A good starting point is just above your league\'s biggest-ever trade win, so a core piece only moves for '
            'the best deal anyone here has made. Rebuilding teams often set it lower, so their veterans are easier to sell.</p>'
            '<p><b>Changing it:</b> tell Claude "change my king\'s ransom to +4,000" or "add Jalen Coker to my core". Claude '
            'updates your plan and the Trade Finder together (KINGS_RANSOM_GUIDE.md), and this page warns you if the two '
            'ever disagree.</p></details>')


# ------------------------------------------------------------------ Trade Finder offers, checked against the plan
def offer_flags(o, ctx, nm):
    """-> list of (css, text). crit = breaks the plan, warn = allowed but needs a reason, good = fits."""
    if not ctx:
        return []
    F = []
    give_names = list(o.get('give_labels') or [])
    give_picks = [g for g in o.get('give') or [] if str(g).startswith('pick:')]
    get_names = [o['get_label']] if o.get('get_label') else list(o.get('get_labels') or [])
    get_only_picks = all(re.match(r'^20\d\d ', g or '') for g in get_names) and bool(get_names)
    core_out = [n for n in give_names if n in ctx['core']] + ([o['asset_label']] if o.get('asset') else [])
    if core_out or any(g in ctx['core_picks'] for g in give_picks):
        F.append(('warn', 'Core piece — clears your king\'s ransom' + (f' (+{ctx["ransom"]:,})' if ctx.get('ransom') else '')))
    keep_out = [n for n in give_names if n in ctx['keep']]
    if keep_out and get_only_picks:
        F.append(('crit', f'Trades {", ".join(keep_out)} for picks — your plan says keep them'))
    elif keep_out:
        F.append(('warn', f'Gives up {", ".join(keep_out)} (plan: keep as starters)'))
    for g in give_picks:
        _, y, rnd = str(g).split(':')[:3]
        if int(rnd) in ctx['hold'].get(y, set()) and g not in ctx['core_picks']:
            F.append(('crit', f'Gives a {y} round-{rnd} pick — your plan holds those'))
            break
    got_sell = [n for n in get_names if n in ctx['sell']]
    if got_sell:
        F.append(('crit', f'Takes back {", ".join(got_sell)}, who your plan says to sell'))
    selling = ctx['status'] == 'Trigger hit' or ctx['mode'] == 'rebuild'
    w, d = o.get('my_wins', 0) or 0, o.get('dyn', 0) or 0
    if selling and w > 0 and d < 0:
        F.append(('crit', 'Buys for this season while your plan says sell'))
    elif ctx['mode'] == 'contend' and not selling and w < -0.05:
        F.append(('warn', f'Costs {abs(w):.1f} wins this season (you\'re contending)'))
    if not any(c == 'crit' for c, _ in F):
        if ctx['mode'] == 'contend' and not selling and w > 0.05:
            F.append(('good', f'Fits the plan: +{w:.1f} wins this season'))
        elif selling and d > 0:
            F.append(('good', 'Fits the plan: adds long-term value while selling'))
    return F


def offers_section(ctx):
    tf = J('trade_finder.json')
    if not tf:
        return '', None
    P = J('players.json')
    nm = lambda x: (P.get(x) or {}).get('full_name') or x
    seen, offers = set(), []
    for o in (tf.get('best_by_partner') or []) + (tf.get('best_by_partner_dynasty') or []) + (tf.get('top') or [])[:10]:
        key = (o['partner'], tuple(o['give']), o['get'])
        if key not in seen:
            seen.add(key)
            offers.append(o)
    rows = []
    for o in offers:
        F = offer_flags(o, ctx, nm)
        bad = sum(c == 'crit' for c, _ in F)
        rows.append((bad, -(o.get('score') or 0), o, F))
    rows.sort(key=lambda r: (r[0], r[1]))
    best = next((o for bad, _, o, _ in rows if not bad), None)
    def row(o, F):
        return (f'<div class="offer"><div class="oline"><b>{esc(o["partner"])}</b>: give {esc(" + ".join(o["give_labels"]))} → get '
                f'<b>{esc(o["get_label"])}</b></div><div class="onums"><span>{(o.get("my_wins") or 0):+.1f} wins this season</span>'
                f'<span>{(o.get("dyn") or 0):+,} long-term value</span></div>'
                + ('<div class="chips">' + ''.join(f'<span class="chip {c}">{esc(t)}</span>' for c, t in F) + '</div>' if F else '') + '</div>')
    ok = [row(o, F) for bad, _, o, F in rows if not bad][:6]
    no = [row(o, F) for bad, _, o, F in rows if bad]
    basis = tf.get('ransom_basis') or 'market'   # update.sh runs trade_finder --ransom-basis auto (plan / season)
    rs_src = tf.get('ransom')
    # likeliest first (owner 10-08): the smallest market overpay that still clears the ransom
    rs = sorted(rs_src or [], key=lambda x: (x.get('their_overpay') or 0, -((x.get('plan_gain') or 0))))
    rs_html = ''
    if rs:
        seen_a, picks = set(), []
        for x in rs:
            if x['asset_label'] not in seen_a:
                seen_a.add(x['asset_label']); picks.append(x)
        how = {'plan': 'judged on your long-term plan (dynasty league) · likeliest first', 'season': 'judged on wins this season (redraft league)',
               'market': 'judged on market value'}[basis]
        rs_html = (f'<div class="kicker" style="margin-top:14px">Core pieces: best package that clears your king\'s ransom · {how}</div>' + ''.join(
            f'<div class="offer"><div class="oline"><b>{esc(x["asset_label"])}</b> to {esc(x["partner"])} for {esc(" + ".join(x["get_labels"]))}</div>'
            '<div class="onums">' + (f'<span>{x.get("plan_gain", 0):+,} to your plan</span>' if basis == 'plan' else '')
            + f'<span>{(x.get("my_wins") or 0):+.1f} wins this season</span><span>{x.get("their_overpay", 0):+,} market value</span></div>'
            + (f'<div class="chips"><span class="chip warn">Costs {abs(x["my_wins"]):.1f} wins this season (you\'re contending)</span></div>'
               if ctx and ctx['mode'] == 'contend' and (x.get('my_wins') or 0) < -0.05 else '') + '</div>'
            for x in picks[:5]))
    mode = ('Your plan is in <b>sell mode</b>' if ctx and ctx['status'] == 'Trigger hit' else
            f'Checked against <b>{esc(ctx["name"])}</b>' if ctx else 'No game plan yet, so offers aren\'t checked')
    html_ = (f'<section class="src-league offers" id="sec-offers-vs-plan"><div class="kicker">Trade Finder · plan check</div>'
             f'<h2 class="disp">Best Offers vs Your Plan</h2><p class="lede">{mode}. Offers that break a plan rule drop to the bottom; '
             'gold tags are allowed but need a reason.</p>' + ''.join(ok)
             + (fold(f'Offers that break your plan ({len(no)})', 'Kept for reference — each one breaks a rule in your plan', ''.join(no)) if no else '')
             + rs_html + '</section>')
    return html_, best


# ------------------------------------------------------------------ game plan: the owner's written plan, scored live
def plan_tracker(my_rid, week):
    """-> (section_html, header_strip_html, action_card or None). Reads my_plan.json at the folder root (the owner's
    own words); with none, the section explains how to add one. Everything it scores comes from the data."""
    path = os.path.join(ROOT, 'my_plan.json')
    if not os.path.exists(path):
        return (fold('Game Plan', 'No plan written yet — add one and this page will track it',
                     '<div class="src-league"><p>Write your plan in <code>my_plan.json</code> at the top of your Dynasty Scout '
                     'folder. Easiest way: ask Claude "help me write my game plan" — it looks at your team, asks you a few questions, '
                     'and writes the file for you (PLAN_INTERVIEW.md). Once it exists, this section scores it every refresh: '
                     'checkpoints such as "3 wins by week 7 or start selling", playoff odds against your floor, and whether '
                     'your core players are still on your roster.</p>' + ransom_explainer({}) + '</div>'), '', None, None)
    plan = json.load(open(path))
    season = str(LF.PROFILE.get('season') or '')
    P = J('players.json')
    R = J(os.path.join(season, 'rosters.json'), [])
    U = {u['user_id']: u['display_name'] for u in J(os.path.join(season, 'users.json'), [])}
    owner_of_rid = {r['roster_id']: U.get(r.get('owner_id')) for r in R}
    rid = int(my_rid)
    nm = lambda x: (P.get(x) or {}).get('full_name') or x
    where = {}                                    # player name -> current owner
    for r in R:
        for x in r.get('players') or []:
            where[nm(x)] = owner_of_rid.get(r['roster_id'])
    me = owner_of_rid.get(rid)

    # this season's results so far + win chance for each week still to play (same model as Your Remaining Schedule)
    from project import lineup_points
    from decided import decided, result
    projr = (J('projection.json').get('rosters') or {})
    sched = projr.get(str(rid), {}).get('schedule', [])
    proj = J('our_projection.json').get('players') or {}
    PW = {x: {int(w): v for w, v in (d.get('weekly') or {}).items()} for x, d in proj.items()}
    pos_of = lambda x: (P.get(x) or {}).get('position')
    act = {r['roster_id']: [x for x in (r['players'] or []) if x not in (r.get('reserve') or []) and x not in (r.get('taxi') or [])] for r in R}
    phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
    lock = decided(week)
    played, future = [], []
    MU = J(os.path.join(season, 'matchups.json'))   # real results (projection.json's past-week points are projections)
    for g in sched:
        if g['wk'] < week:
            wk = MU.get(str(g['wk'])) or []
            a = next((m for m in wk if m['roster_id'] == rid), None)
            b = next((m for m in wk if a and m['matchup_id'] == a['matchup_id'] and m['roster_id'] != rid), None)
            if a and b:
                played.append((g['wk'], (a.get('points') or 0) > (b.get('points') or 0)))
        else:
            fixed = result(lock, rid, g['opp'], g['wk'], week)
            pw = fixed if fixed is not None else phi((lineup_points(act[rid], g['wk'], PW, pos_of)
                                                      - lineup_points(act[g['opp']], g['wk'], PW, pos_of)) / 31)
            future.append((g['wk'], owner_of_rid.get(g['opp']), pw))
    wins = sum(1 for _, w in played if w)
    losses = len(played) - wins

    def p_at_least(probs, k):                     # chance of k+ wins from independent games
        dist = [1.0]
        for q in probs:
            dist = [(dist[i] if i < len(dist) else 0) * (1 - q) + (dist[i - 1] * q if i else 0) for i in range(len(dist) + 1)]
        return sum(dist[max(k, 0):]) if k > 0 else 1.0

    _t = (J('our_projection.json').get('teams') or {}).get(str(rid), {})
    ours, slp = _t.get('playoff'), _t.get('sleeper_playoff')
    H = J('plan_history.json', [])

    # checkpoints: a win count by a week (min_wins) or playoff odds at a week (min_odds)
    cps = []
    for c in plan.get('checkpoints') or []:
        cw, need = c['week'], c.get('min_wins', 0)
        if 'min_odds' in c:
            if week <= cw:
                st = 'open'
                odds_at = ours
            else:                                 # judge by the odds saved on the last day of that week
                past = [h for h in H if h.get('week', 99) <= cw and h.get('playoff') is not None]
                odds_at = past[-1]['playoff'] if past else None
                st = 'unknown' if odds_at is None else 'met' if odds_at >= c['min_odds'] else 'missed'
            cps.append(dict(c, status=st, chance=None, odds=odds_at, games=[]))
            continue
        if week > cw:                             # already happened: judge the record as of that week
            w_at = sum(1 for wk, w in played if w and wk <= cw)
            st, chance = ('met' if w_at >= need else 'missed'), (1.0 if w_at >= need else 0.0)
            games = []
        else:
            games = [f for f in future if f[0] <= cw]
            chance = p_at_least([f[2] for f in games], need - wins)
            st = 'met' if wins >= need else 'lost' if wins + len(games) < need else 'open'
        cps.append(dict(c, status=st, chance=chance, games=games))
    nxt = next((c for c in cps if c['status'] == 'open' and c['chance'] is not None), None)
    odds_cp = next((c for c in cps if c['status'] == 'open' and 'min_odds' in c), None)
    floor = plan.get('playoff_odds_floor')
    hist = [(s['date'], (s['teams'].get(str(rid)) or {}).get('playoff')) for s in J('lottery_history.json').get('snapshots', [])]
    hist = [(d, v) for d, v in hist if v is not None]

    # status: worst signal wins
    missed = next((c for c in cps if c['status'] in ('missed', 'lost')), None)
    if missed:
        status, css, why = 'Trigger hit', 'crit', f'{missed["label"]} {"missed" if missed["status"] == "missed" else "can no longer be met"} — your plan says: {missed["if_missed"]}'
    elif nxt and nxt['status'] == 'open' and nxt['chance'] < 0.5:
        status, css, why = 'At risk', 'warn', f'{nxt["chance"]:.0%} chance to pass the {nxt["label"].lower()}'
    elif odds_cp and ours is not None and ours < odds_cp['min_odds']:
        status, css, why = 'At risk', 'warn', f'Playoff odds {ours:.0%}, under the {odds_cp["min_odds"]:.0%} line for the {odds_cp["label"].lower()}'
    elif floor is not None and ours is not None and ours < floor:
        status, css, why = 'At risk', 'warn', f'Playoff odds {ours:.0%}, below your {floor:.0%} floor'
    else:
        status, css, why = 'On track', 'good', (f'{nxt["chance"]:.0%} chance to pass the {nxt["label"].lower()}' if nxt and nxt['status'] == 'open' else 'Checkpoints met so far')

    # history of this tracker (one row per day) so changes over the season show
    hp = os.path.join(DATA, 'plan_history.json')
    row = {'date': date.today().isoformat(), 'week': week, 'record': f'{wins}-{losses}', 'playoff': ours,
           'checkpoint': nxt['label'] if nxt else None, 'chance': round(nxt['chance'], 3) if nxt else None, 'status': status}
    H = [h for h in H if h.get('date') != row['date']] + [row]
    json.dump(H, open(hp, 'w'), indent=1)
    prev = H[-2] if len(H) > 1 else None

    # roster vs plan
    def check(names, want_mine=True):
        out = []
        for n in names or []:
            o = where.get(n)
            ok = (o == me) if want_mine else (o != me)
            out.append((n, ok, o))
        return out
    cdef = plan.get('core') or {}
    if isinstance(cdef, list):
        cdef = {'players': cdef}
    core, sell = check(cdef.get('players')), check(plan.get('sell'), want_mine=False)
    prem = {nm(k) for k in (LF.CFG.get('premium') or {}) if not str(k).startswith('pick:')}
    planned = set(cdef.get('players') or [])
    drift = sorted(prem - planned), sorted(planned - prem)
    ks = plan.get('keep_starters') or {}
    if isinstance(ks, str):
        ks = {'rule': ks}
    gone = [n for n, ok, _ in core if not ok]

    adopted = plan.get('adopted')
    age = (date.today() - date.fromisoformat(adopted)).days if adopted else None
    cur_year = season
    li = lambda x: f'<li>{x}</li>'
    def spark(vals):
        if len(vals) < 2:
            return ''
        W, Hh = 160, 36
        pts = ' '.join(f'{4 + i * (W - 8) / (len(vals) - 1):.1f},{Hh - 4 - v * (Hh - 8):.1f}' for i, v in enumerate(vals))
        fl = (f'<line x1="4" x2="{W - 4}" y1="{Hh - 4 - floor * (Hh - 8):.1f}" y2="{Hh - 4 - floor * (Hh - 8):.1f}" stroke="var(--warn)" stroke-dasharray="3 3"/>'
              if floor is not None else '')
        return (f'<svg viewBox="0 0 {W} {Hh}" width="{W}" height="{Hh}" role="img" aria-label="Playoff odds by day">{fl}'
                f'<polyline points="{pts}" fill="none" stroke="var(--accent)" stroke-width="2"/></svg>')

    cw_left = lambda w: (f'{w - week + 1} games' if w - week + 1 != 1 else '1 game')
    cp_html = ''
    for c in cps:
        if 'min_odds' in c:
            o = c.get('odds')
            if c['status'] == 'open':
                body = (f'<div class="big">{o:.0%}</div><div class="fb">playoff odds now · the line is {c["min_odds"]:.0%}</div>'
                        f'<p>{"Above" if o >= c["min_odds"] else "Below"} the line with {cw_left(c["week"])} until week {c["week"]}. '
                        'Judged on your odds when that week ends.</p>') if o is not None else '<div class="big">—</div><p>No playoff odds yet.</p>'
            else:
                word = {'met': 'Passed', 'missed': 'Missed', 'unknown': 'No odds saved'}[c['status']]
                body = f'<div class="big">{word}</div>' + (f'<p>Odds were {o:.0%} at week {c["week"]}; the line was {c["min_odds"]:.0%}.</p>' if o is not None else '')
        elif c['status'] == 'open':
            body = (f'<div class="big">{c["chance"]:.0%}</div><div class="fb">chance to pass</div>'
                    f'<p>Need <b>{c["min_wins"]} wins</b> by week {c["week"]}. You have <b>{wins}</b> ({wins}-{losses}), '
                    f'so you need {max(0, c["min_wins"] - wins)} of the next {len(c["games"])}:</p><ul class="gl">'
                    + ''.join(f'<li><span>W{w} vs {esc(str(o))}</span><span class="num">{q:.0%}</span></li>' for w, o, q in c['games']) + '</ul>')
        else:
            word = {'met': 'Passed', 'missed': 'Missed', 'lost': 'Can no longer be met'}[c['status']]
            body = f'<div class="big">{word}</div><p>Needed {c["min_wins"]} wins by week {c["week"]}; record now {wins}-{losses}.</p>'
        cp_html += (f'<div class="pcard"><div class="kicker">{esc(c["label"])} · week {c["week"]}</div>{body}'
                    f'<div class="ifs"><div><b>If you miss it:</b> {esc(c["if_missed"])}</div><div><b>If you pass:</b> {esc(c.get("if_met", "Stay the course."))}</div></div></div>')

    odds_html = ''
    if ours is not None:
        first = hist[0] if hist else None
        odds_html = (f'<div class="pcard"><div class="kicker">Playoff odds</div><div class="big">{ours:.0%}</div>'
                     f'<div class="fb">our model' + (f' · your floor {floor:.0%}' if floor is not None else '')
                     + (f' · Sleeper\'s projections say {slp:.0%} (the header number)' if slp is not None else '') + '</div>'
                     + spark([v for _, v in hist])
                     + (f'<p>Was {first[1]:.0%} on {first[0][5:].replace("-", "/")} (first saved day).</p>' if first else '') + '</div>')

    roster_html = ('<div class="pcard"><div class="kicker">Core · king\'s ransom only</div>'
                   + (f'<p class="fb" style="margin:0 0 4px">{esc(cdef["rule"])}</p>' if cdef.get('rule') else '') + '<ul class="chk">'
                   + ''.join(li(f'<span class="{"ok" if ok else "no"}">{"✓" if ok else "✗"}</span> {esc(n)}'
                                + ('' if ok else f' <small>now on {esc(str(o))}</small>' if o else ' <small>not on any roster</small>'))
                             for n, ok, o in core)
                   + ''.join(li(f'<span class="ok">◆</span> {esc(x)}') for x in cdef.get('picks') or []) + '</ul>'
                   + ((f'<p class="warnline">Plan and Trade Finder disagree: '
                       + '; '.join(x for x in (f'Trade Finder also protects {", ".join(drift[0])}' if drift[0] else '',
                                               f'plan lists {", ".join(drift[1])} but Trade Finder doesn\'t protect them' if drift[1] else '') if x)
                       + '.</p>') if drift[0] or drift[1] else '')
                   + (f'<p class="warnline">{len(gone)} core player{"s" if len(gone) != 1 else ""} no longer on your roster — '
                      'the plan needs updating.</p>' if gone else '')
                   + (('<div class="kicker" style="margin-top:8px">To sell</div><ul class="chk">' + ''.join(
                       li(f'<span class="{"ok" if ok else "no"}">{"✓" if ok else "•"}</span> {esc(n)} <small>{"sold" if ok else "still yours"}</small>')
                       for n, ok, o in sell) + '</ul>') if sell else '')
                   + (f'<p class="fb">{esc(ks.get("rule") or ", ".join(ks.get("players") or []))}</p>' if ks else '')
                   + ransom_explainer(cdef) + '</div>')

    goals_html = ('<div class="pcard"><div class="kicker">Season by season</div><ul class="goals">'
                  + ''.join(f'<li class="{"now" if y == cur_year else ""}"><b>{esc(y)}</b> {esc(t)}</li>' for y, t in (plan.get('goals') or {}).items())
                  + '</ul>' + (('<div class="kicker" style="margin-top:8px">Draft picks</div><ul class="goals">' + ''.join(
                      f'<li><b>{esc(y)}</b> {esc(t.get("text", "") if isinstance(t, dict) else t)}</li>' for y, t in plan['picks'].items()) + '</ul>') if plan.get('picks') else '') + '</div>')

    change = ''
    if prev and prev.get('chance') is not None and row['chance'] is not None and prev['chance'] != row['chance']:
        change = f' · was {prev["chance"]:.0%} on {prev["date"][5:].replace("-", "/")}'
    section = (f'<section class="plan src-league" id="sec-game-plan"><div class="kicker">Game plan · adopted {esc(adopted or "?")}'
               + (f' ({age} days ago)' if age is not None else '') + f'</div><h2 class="disp">{esc(plan.get("name", "Game Plan"))}</h2>'
               f'<div class="pstat"><span class="chip {css}">{status}</span><span>{esc(why)}{esc(change)}</span></div>'
               f'<p class="lede">{esc(plan.get("summary", ""))}</p><div class="pgrid">{cp_html}{odds_html}{roster_html}{goals_html}</div>'
               '<p class="fb">Your words come from my_plan.json; every number is recalculated on each refresh. '
               f'{len(H)} day{"s" if len(H) != 1 else ""} of tracking saved.</p></section>')
    strip = (f'<button class="planstrip {css}" data-go="sec-game-plan"><b>Plan:</b> {esc(plan.get("name", ""))} · '
             f'<span>{status}</span> · {esc(why)}</button>')
    card = None
    if status != 'On track':
        card = ('Game plan', 'crit' if status == 'Trigger hit' else 'warn', f'{plan.get("name", "Plan")}: {status.lower()}', why, 'sec-game-plan')
    elif gone:
        card = ('Game plan', 'warn', 'Your written plan is out of date', f'{", ".join(gone)} no longer on your roster.', 'sec-game-plan')
    ctx = {'status': status, 'mode': (plan.get('mode') or '').lower(), 'core': planned,
           'core_picks': {k for k in (LF.CFG.get('premium') or {}) if str(k).startswith('pick:')},
           'keep': set(ks.get('players') or []), 'sell': set(plan.get('sell') or []),
           'hold': {y: set(t.get('hold_rounds') or []) if isinstance(t, dict) else ({1, 2, 3, 4, 5} if str(t).lower().startswith('hold') else set())
                    for y, t in (plan.get('picks') or {}).items()},
           'ransom': cdef.get('ransom'), 'name': plan.get('name', 'your plan')}
    return section, strip, card, ctx


CSS = """
.draft{background:var(--gold);color:#1a1a1a;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  text-align:center;padding:5px;border-radius:6px}
.v2head{display:flex;flex-direction:column;gap:12px}
.v2top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.findbtn{font:inherit;font-size:14px;font-weight:600;color:var(--accent-ink);background:var(--card);border:1px solid var(--line);
  border-radius:999px;padding:8px 16px;cursor:pointer;white-space:nowrap}
.findbtn[aria-pressed="true"]{background:var(--accent);color:var(--paper);border-color:var(--accent)}
.dates{display:flex;gap:6px;flex-wrap:wrap}
.dates span{font-size:12.5px;color:var(--ink2);background:var(--card);border:1px solid var(--line);border-radius:999px;padding:3px 10px}
.v2head .tiles{grid-template-columns:repeat(auto-fit,minmax(120px,1fr));margin-top:12px!important}
@media(max-width:480px){.v2head .tiles{grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:8px}.v2head .tile{padding:10px}.v2head .tile .v{font-size:21px}.v2head .tile .n{display:none}
  .findbtn{width:100%}}
.tile .was{font-size:11.5px;font-weight:600;margin-top:4px}
.tile .was.up{color:var(--good)}.tile .was.dn{color:var(--crit)}
.donow{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(300px,100%),1fr));gap:10px}
.act{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:8px;padding:12px 14px;
  display:flex;flex-direction:column;gap:4px;cursor:pointer;text-align:left;font:inherit;color:inherit}
.act:hover{border-color:var(--accent)}
.act.crit{border-left-color:var(--crit)}.act.warn{border-left-color:var(--warn)}.act.good{border-left-color:var(--good)}
.act .tag{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.act .t{font-weight:600;line-height:1.3}
.act .d{font-size:13px;color:var(--ink2);white-space:pre-line}
.opp{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.opp-row{display:flex;justify-content:space-between;align-items:baseline;font-size:17px;margin:2px 0}
.fold{background:var(--card);border:1px solid var(--line);border-radius:10px}
.fold>summary{list-style:none;cursor:pointer;padding:13px 16px;display:flex;flex-direction:column;gap:2px;position:relative;padding-right:40px}
.fold>summary::-webkit-details-marker{display:none}
.fold>summary::after{content:'+';position:absolute;right:16px;top:12px;font-size:20px;color:var(--muted);font-weight:400}
.fold[open]>summary::after{content:'–'}
.fold>summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.ft{font-weight:700;font-size:16px}
.fb{font-size:13px;color:var(--muted)}
.fold-body{padding:0 12px 14px;min-width:0}
.fold-body section>h2:first-of-type,.fold-body section>.kicker:first-child{display:none}
.grouphead{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:700;margin:6px 0 -14px}
.lead{display:flex;flex-direction:column;gap:12px}
.notes ul{margin:6px 0 0;padding-left:18px}.notes li{margin:3px 0;font-size:14px}
.stale{color:var(--warn);font-weight:600}
.planstrip{font:inherit;font-size:13.5px;text-align:left;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);
  border-radius:8px;padding:8px 12px;cursor:pointer;color:var(--ink2)}
.planstrip.good{border-left-color:var(--good)}.planstrip.warn{border-left-color:var(--warn)}.planstrip.crit{border-left-color:var(--crit)}
.planstrip span{font-weight:700;color:var(--ink)}
.plan .pstat{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:6px 0 4px;font-size:14px}
.plan .chip.good{border-color:var(--good);color:var(--good)}.plan .chip.warn{border-color:var(--warn);color:var(--warn)}.plan .chip.crit{border-color:var(--crit);color:var(--crit)}
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(280px,100%),1fr));gap:12px;margin:12px 0}
.pcard{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;display:flex;flex-direction:column;gap:4px;min-width:0}
.pcard p{margin:6px 0 0;font-size:13.5px;color:var(--ink2)}
.pcard .big{font-size:30px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.gl,.chk,.goals{list-style:none;margin:6px 0 0;padding:0;font-size:13.5px}
.gl li{display:flex;justify-content:space-between;border-bottom:1px dashed var(--line);padding:3px 0}
.chk li{padding:2px 0}.chk small{color:var(--muted)}
.chk .ok{color:var(--good);font-weight:700}.chk .no{color:var(--crit);font-weight:700}
.goals li{padding:3px 0;color:var(--ink2)}.goals li.now{color:var(--ink);font-weight:600}
.ifs{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--ink2);border-top:1px solid var(--line);margin-top:8px;padding-top:8px}
.warnline{color:var(--warn)!important;font-weight:600}
.offer{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:8px 0;display:flex;flex-direction:column;gap:4px}
.oline{font-size:14.5px}.onums{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.offers .chip.good,.plan .chip.good{border-color:var(--good);color:var(--good)}
.offers .chip.warn{border-color:var(--warn);color:var(--warn)}.offers .chip.crit{border-color:var(--crit);color:var(--crit)}
.offers .chip{text-transform:none;letter-spacing:0;font-size:12px}
.explain{margin-top:10px;border-top:1px solid var(--line);padding-top:8px;font-size:13.5px}
.explain summary{cursor:pointer;font-weight:600;color:var(--accent-ink)}
.explain p{margin:8px 0 0;color:var(--ink2)}
"""

JS = """<script>(function(){
const tabs=[...document.querySelectorAll('.hubnav button')];const fb=document.getElementById('findbtn');
function show(k,push){tabs.forEach(b=>{const on=b.id==='hubtab-'+k;b.setAttribute('aria-selected',on)});
  document.querySelectorAll('.hubpanel').forEach(p=>p.hidden=p.id!=='hub-'+k);
  if(fb)fb.setAttribute('aria-pressed',k==='find');
  try{localStorage.setItem('hubtab',k)}catch(e){} if(push){try{history.replaceState(null,'','#'+k)}catch(e){}} window.scrollTo({top:0})}
tabs.forEach(b=>b.addEventListener('click',()=>show(b.id.slice(7),true)));
if(fb)fb.addEventListener('click',()=>show(fb.getAttribute('aria-pressed')==='true'?'week':'find',true));
// action cards jump to the folded section behind them and open it
document.querySelectorAll('[data-go]').forEach(a=>a.addEventListener('click',()=>{const s=document.getElementById(a.dataset.go);if(!s)return;
  const p=s.closest('.hubpanel');show(p.id.slice(4),true);s.open=true;setTimeout(()=>s.scrollIntoView({behavior:'smooth',block:'start'}),50)}));
// Game day (Sun/Mon US Eastern): the live matchup goes above the action cards
const day=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',weekday:'short'}).format(new Date());
const gd=document.getElementById('gdblock'),lead=document.getElementById('weeklead');
if(gd&&lead&&(day==='Sun'||day==='Mon'))lead.parentNode.insertBefore(gd,lead);
// "since your last visit": each tile shows its old value when it changed (kept in this browser only)
try{const K='v2tiles',old=JSON.parse(localStorage.getItem(K)||'{}'),now={};
  document.querySelectorAll('.v2head .tile').forEach(t=>{const l=t.querySelector('.l')?.textContent.trim(),v=t.querySelector('.v')?.textContent.trim();if(!l)return;now[l]=v;
    if(old[l]!==undefined&&old[l]!==v){const a=parseFloat(String(old[l]).replace(/[^0-9.-]/g,'')),b=parseFloat(String(v).replace(/[^0-9.-]/g,''));
      const better=/rank/i.test(l)?b<a:b>a;const d=document.createElement('div');d.className='was '+(isNaN(a)||isNaN(b)?'':better?'up':'dn');
      d.textContent='was '+old[l]+' last visit';t.appendChild(d)}});
  localStorage.setItem(K,JSON.stringify(now))}catch(e){}
const h=(location.hash||'').slice(1);const valid=tabs.map(b=>b.id.slice(7)).concat('find');
show(valid.includes(h)?h:'week',false);
})();</script>"""


def main():
    styles = []
    panels = {k: [] for k, *_ in TABS}
    panels['find'] = []
    unmapped = []
    lg_st, lg_head, lg_secs, lg_js = H.parts('league.html')
    an_st, _, an_secs, an_js = H.parts('analysis.html')
    ay_st, _, ay_secs, ay_js = H.parts('analyst.html')
    gd_st, gd_head, gd_secs, gd_js = H.parts('gameday.html')
    as_st, _, as_secs, as_js = H.parts('assets.html')
    for st, sc in ((lg_st, 'src-league'), (an_st, 'src-analysis'), (gd_st, 'src-gameday'), (as_st, 'src-assets'), (ay_st, 'src-analyst')):
        styles.append(H.scope_css(''.join(st), sc, keep_global=(sc == 'src-league')))
    an_set, ay_set = set(an_secs), set(ay_secs)
    for sec in lg_secs + an_secs + ay_secs:
        h = H.heading(sec)
        hit = next((r for r in ROUTE if h.startswith(r[0])), None)
        frag = f'<div class="{"src-analyst" if sec in ay_set else "src-analysis" if sec in an_set else "src-league"}">{H.drop_links(sec)}</div>'
        if not hit:
            unmapped.append(h)
            panels['league'].append((90, fold(h, '', frag)))
            continue
        _, tab, order, opened, blurb = hit
        if opened and tab != 'find':
            panels[tab].append((order, f'<div id="{slug(h)}">{frag}</div>'))
        elif tab == 'find':
            panels[tab].append((order, frag))
        else:
            panels[tab].append((order, fold(h, blurb, frag)))

    # header: team name + verdict + tiles from the league page, minus the typed list and the old link bar
    head = H.drop_links(lg_head)
    todo = (re.search(r'<div class="todo">.*?</ul></div>', head, re.S) or [''])[0]
    head = head.replace(todo, '')
    head = re.sub(r'<p class="sub" style="font-size:12px[^>]*>.*?</p>', '', head, flags=re.S)
    head = re.sub(r'</?header>', '', head)

    cards, my_rid, week = action_cards()
    plan_html, plan_strip, plan_card, ctx = plan_tracker(my_rid, week)
    if plan_card:
        cards.insert(0, plan_card)
    panels['season'].append((1, plan_html))
    off_html, best = offers_section(ctx)
    if off_html:
        panels['trades'].append((5, off_html))
    if best and ctx:                              # with a plan, the Do This Now trade card shows the best offer that fits it
        for i, c in enumerate(cards):
            if c[0] == 'Trade' and c[2].startswith('Best offer found'):
                cards[i] = ('Trade', '', f'Best offer that fits your plan: {" + ".join(best["give_labels"])} to {best["partner"]} for {best["get_label"]}',
                            c[3], 'sec-offers-vs-plan')
    donow = ('<div id="weeklead" class="lead src-league"><div><div class="kicker">Week ' + esc(str(week or '')) + '</div><h2 class="disp">Do This Now</h2></div>'
             '<div class="donow">' + ''.join(
                 f'<button class="act {c}" data-go="{go}"><span class="tag">{esc(tag)}</span><span class="t">{esc(t)}</span>'
                 + (f'<span class="d">{esc(d)}</span>' if d else '') + '</button>' for tag, c, t, d, go in cards)
             + '</div>' + opponent_card(my_rid, week) + '</div>')
    panels['week'].append((5, donow))
    stamp = (re.search(r'<p class="status" id="stamp">.*?</p>', gd_head, re.S) or [''])[0]
    panels['week'].append((10, f'<div class="gd-block src-gameday" id="gdblock"><div><div class="kicker">Game Day</div>{stamp}</div><div id="app"></div></div>'))
    if todo:   # the owner's own typed notes, if any: folded, dated, flagged when old
        fr = J('freshness.json')
        stale = next((c for c in fr.get('checks', []) if 'hand' in c.get('source', '').lower() and c.get('status') != 'ok'), None)
        note = re.sub(r'<div class="kicker"[^>]*>On the clock</div>', '', todo)
        panels['week'].append((60, fold('Your Notes', ('Typed by you, ' + stale['detail'] + ' — may be out of date') if stale
                                        else 'Notes you typed yourself', f'<div class="src-league notes">{note}</div>')))

    as_raw = open(os.path.join(D, 'assets.html')).read() if os.path.exists(os.path.join(D, 'assets.html')) else ''
    as_sub = (re.search(r'<div class="sub">.*?</div>', as_raw, re.S) or [''])[0]
    as_season = '<span id="season" hidden></span>' if 'id="season"' not in as_sub else ''
    legend = (re.search(r'<p class="legend">.*?</p>', as_raw, re.S) or [''])[0]
    panels['picks'].append((30, fold('Rosters, Picks & Prospects', 'Every roster, who holds each 2027–29 pick, and the college prospects',
                                     '<div class="src-assets"><section>' + as_sub + as_season + '</section>' + ''.join(as_secs) + legend + '</div>')))

    def scoped(x):
        if re.match(r'<script[^>]*type="application/json"', x):
            return x
        return re.sub(r'(<script[^>]*>)(.*)(</script>)', lambda m: m.group(1) + '{\n' + m.group(2) + '\n}' + m.group(3), x, flags=re.S)
    scripts = [scoped(x) for x in an_js + gd_js + as_js + lg_js + ay_js]

    nav = ('<nav class="hubnav" role="tablist" aria-label="Dashboard sections">' + ''.join(
        f'<button role="tab" id="hubtab-{k}" aria-controls="hub-{k}" aria-selected="{"true" if k == "week" else "false"}">'
        f'<span class="tl">{esc(n)}</span><span class="ts">{esc(s)}</span></button>' for k, n, s in TABS) + '</nav>')
    body = []
    for k in [t[0] for t in TABS] + ['find']:
        items = sorted(panels[k], key=lambda x: x[0])
        if k == 'season' and any(o >= DEEP for o, _ in items):
            i = next(n for n, (o, _) in enumerate(items) if o >= DEEP)
            items.insert(i, (DEEP, '<div class="grouphead">Your players in depth</div>'))
        title = '<div><div class="kicker">Search</div><h2 class="disp">Players &amp; Questions</h2></div>' if k == 'find' else ''
        body.append(f'<div class="hubpanel" role="tabpanel" id="hub-{k}"{"" if k == "week" else " hidden"}>' + title + ''.join(x for _, x in items) + '</div>')
    top = (f'<div class="v2head"><div class="src-league">{head}</div>'
           f'{plan_strip}<div class="v2top">{key_dates(week)}<button class="findbtn" id="findbtn" aria-pressed="false">Look up a player · Ask</button></div></div>')
    page = (f'<meta charset="utf-8"><title>Dynasty Command Center</title><style>{"".join(styles)}{H.HUB_CSS}{CSS}</style>'
            f'<div class="wrap">{top}{nav}{"".join(body)}<div class="src-league"><footer>Updated {LF.stamp()} · {esc(LF.LEAGUE_NAME)} · every view in one place</footer></div></div>'
            f'{"".join(scripts)}{JS}')
    open(os.path.join(D, 'hub.html'), 'w').write(page)
    print(f'hub -> dashboards/hub.html ({len(page) // 1024} KB): {len(cards)} action cards; '
          + ', '.join(f'{n} {len(panels[k])}' for k, n, _ in TABS) + f', Search {len(panels["find"])}'
          + (f'; UNMAPPED -> League: {unmapped}' if unmapped else '; all sections mapped'))


if __name__ == '__main__':
    main()
