#!/usr/bin/env python3
"""Two more dashboards (owner's ask, 2026-10-04):

  dashboards/gameday.html   Game Day — your matchup player by player (final / playing / yet to play),
                            projected final and win probability, plus every league matchup. Built with a
                            snapshot of Sleeper's live scores; while open, the page also tries to re-read
                            Sleeper every 60 s and recompute (falls back to the snapshot if the viewer
                            blocks it, and says which).
  dashboards/analysis.html  Analysis — Playoff Path (your remaining schedule, win odds per week, with and
                            without the trade plan in data/trade_plan.json), Player Trends (weekly points,
                            snap share and our projection per player), Owner Scouting (window, positional
                            strength, trade habits, latest intel, best offer and ransom per owner).

Projections are OUR model (ops/our_projections.py), never Sleeper's. Run after league_dashboard.py.
"""
import html, json, math, os, sys, time, urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402
from project import lineup_points  # noqa: E402

esc = lambda s: html.escape(str(s))
CSS = open(os.path.join(ROOT, 'ops', 'dashboard.css')).read() + """
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark}}
:root[data-theme="dark"]{color-scheme:dark}
.wrap{max-width:1040px;margin:0 auto;padding-block:28px 60px;padding-inline:max(16px,3vw);display:flex;flex-direction:column;gap:28px}
.disp{font-family:'Avenir Next Condensed','Arial Narrow','Avenir Next',system-ui,sans-serif;text-transform:uppercase;letter-spacing:.04em;font-weight:700}
.num{font-variant-numeric:tabular-nums}
nav.jump{display:flex;gap:8px;flex-wrap:wrap;position:sticky;top:env(safe-area-inset-top,0px);background:var(--paper);padding-block:8px;z-index:2}
nav.jump a{font-size:13px;font-weight:600;color:var(--accent-ink);text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:4px 12px;background:var(--card)}
nav.jump a:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.mu{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:6px 14px;align-items:center}
.mu .side{min-width:0}.mu .side.r{text-align:right}
.mu .sc{font-size:30px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1}
.mu .pf{font-size:12px;color:var(--muted)}
.wp{grid-column:1/-1;display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--track);gap:2px}
.wp span{display:block;height:100%}
.pl{display:grid;grid-template-columns:3.2em minmax(0,1fr) 5.2em 3.4em 3.4em;gap:4px 10px;align-items:center;font-size:13.5px;padding:5px 0;border-bottom:1px solid var(--line)}
.pl:last-child{border-bottom:none}
.pl .st{font-size:10.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;border-radius:999px;padding:1px 7px;text-align:center}
.st.final{background:var(--track);color:var(--ink2)}.st.live{background:var(--gold-bg);color:var(--warn)}.st.yet{border:1px solid var(--line);color:var(--muted)}
.pl .v{text-align:right;font-variant-numeric:tabular-nums}.pl .pj{color:var(--muted)}
.mini{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(300px,100%),1fr));gap:12px}
.mini .card{gap:6px}
.status{font-size:12px;color:var(--muted)}
.status b{color:var(--ink2)}
.grid2{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(320px,100%),1fr));gap:12px}
svg text{fill:var(--muted);font-size:10px;font-family:inherit}
svg .ax{stroke:var(--line);stroke-width:1}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2)}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-2px}
.chips{display:flex;gap:5px;flex-wrap:wrap}
.chip{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;border-radius:999px;padding:2px 9px;border:1px solid var(--line);color:var(--ink2)}
.chip.good{border-color:var(--good);color:var(--good)}.chip.warn{border-color:var(--warn);color:var(--warn)}.chip.crit{border-color:var(--crit);color:var(--crit)}
.kv{display:grid;grid-template-columns:7.5em minmax(0,1fr);gap:3px 10px;font-size:13px}
.kv dt{color:var(--muted)}.kv dd{margin:0;min-width:0;overflow-wrap:anywhere}
ol.ideas{display:grid;gap:10px;padding-left:20px;margin:0}
ol.ideas li{max-width:72ch}
"""


def jload(name, default=None):
    p = os.path.join(DATA, name)
    return json.load(open(p)) if os.path.exists(p) else default


def links(current):
    ls = (json.load(open(os.path.join(ROOT, 'config.json'))).get('dashboard_links') or {})
    return ('<nav class="jump" aria-label="Dashboards" style="position:static">' + ''.join(
        f'<a href="{esc(u)}">{esc(n)}</a>' for n, u in ls.items() if n != current) + '</nav>') if ls else ''


def page(title, body, scripts=''):
    return (f'<title>{esc(title)}</title><style>{CSS}</style><div class="wrap">{body}</div>{scripts}')


def main():
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    me, lid = cfg.get('my_username'), cfg.get('league_id')
    P = json.load(open(os.path.join(DATA, 'players.json')))
    season = max(d for d in os.listdir(DATA) if d.isdigit())
    R = json.load(open(os.path.join(DATA, season, 'rosters.json')))
    U = {u['user_id']: u['display_name'] for u in json.load(open(os.path.join(DATA, season, 'users.json')))}
    rid_owner = {r['roster_id']: U.get(r.get('owner_id')) for r in R}
    my_rid = next(rid for rid, o in rid_owner.items() if o == me)
    op = jload('our_projection.json', {})
    proj = op.get('players') or {}
    league = json.load(open(os.path.join(DATA, season, 'league.json')))
    done = (league.get('settings') or {}).get('last_scored_leg', 0)
    week = done + 1
    now = datetime.now().strftime('%a %b %-d, %-I:%M %p')
    pos_of = lambda s: (P.get(s) or {}).get('position')
    nm = lambda s: (P.get(s) or {}).get('full_name') or (P.get(s) or {}).get('last_name') or s
    teamof = lambda s: (P.get(s) or {}).get('team') or s

    # ---------- GAME DAY ----------
    try:
        M = json.load(urllib.request.urlopen(f'https://api.sleeper.app/v1/league/{lid}/matchups/{week}?_={int(time.time())}', timeout=30))
    except Exception:
        M = []
    W = None
    try:
        import weekly as WK
        S = WK.Season(int(season), live=True)
        games = {}
        for g in S.week_games(week):
            for t in (g['home_team'], g['away_team']):
                games[{'LA': 'LAR'}.get(t, t)] = {'ko': f"{g['gameday']} {g['gametime']}", 'final': bool(g['home_score'])}
    except Exception:
        games = {}
    pmeta = {}
    for m in M:
        for s in (m.get('starters') or []):
            if s and s != '0':
                x = proj.get(s) or {}
                pmeta[s] = {'n': nm(s), 'p': pos_of(s) or ('DEF' if s.isalpha() else '?'), 't': teamof(s),
                            'pj': (x.get('weekly') or {}).get(str(week)) or 0}
    gd = {'league': lid, 'week': week, 'me': my_rid, 'built': now,
          'owners': {str(k): v for k, v in rid_owner.items()},
          'matchups': [{'mid': m['matchup_id'], 'rid': m['roster_id'], 'starters': [s for s in (m.get('starters') or []) if s and s != '0'],
                        'pp': m.get('players_points') or {}, 'pts': m.get('points') or 0} for m in M],
          'players': pmeta, 'games': games}
    js = r"""
<script>
const D=JSON.parse(document.getElementById('gd').textContent);
const PHI=x=>0.5*(1+erf(x/Math.SQRT2));
function erf(x){const t=1/(1+0.3275911*Math.abs(x));const y=1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x);return x>=0?y:-y}
function etNow(){const p=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(new Date());const g=k=>p.find(x=>x.type===k).value;return `${g('year')}-${g('month')}-${g('day')} ${g('hour')}:${g('minute')}`}
function state(pid){const t=(D.players[pid]||{}).t;const g=D.games[t]||D.games[pid];if(!g)return 'final';if(g.final)return 'final';return g.ko<=etNow()?'live':'yet'}
function side(m){let cur=0,rem=0,n=0,k=0;const rows=m.starters.map(pid=>{const pts=+(m.pp[pid]||0),pj=+((D.players[pid]||{}).pj||0),st=state(pid);let r=st==='yet'?pj:st==='live'?Math.max(0,pj-pts)*0.5:0;if(r>0)k++;if(st!=='final')n++;cur+=pts;rem+=r;return{pid,pts,pj,st}});return{cur,rem,n,k,rows,proj:cur+rem}}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function render(live,stamp){
  const by={};D.matchups.forEach(m=>(by[m.mid]=by[m.mid]||[]).push(m));
  const pairs=Object.values(by).filter(p=>p.length===2);
  const mine=pairs.find(p=>p.some(m=>m.rid===D.me));
  const out=[];
  const card=(p,big)=>{let [a,b]=p;if(b.rid===D.me)[a,b]=[b,a];const A=side(a),B=side(b);const sd=Math.sqrt((A.k+B.k+0.5*(A.n+B.n))*36)||1e-6;let wa=(A.n+B.n)?PHI((A.proj-B.proj)/sd):(A.cur>=B.cur?1:0);
    const nmA=esc(D.owners[a.rid]||a.rid),nmB=esc(D.owners[b.rid]||b.rid);
    let h=`<div class="card"><div class="mu"><div class="side"><div class="kicker">${nmA}</div><div class="sc">${A.cur.toFixed(1)}</div><div class="pf">proj ${A.proj.toFixed(1)} · ${A.n} still to finish</div></div><div class="kicker">vs</div><div class="side r"><div class="kicker">${nmB}</div><div class="sc">${B.cur.toFixed(1)}</div><div class="pf">proj ${B.proj.toFixed(1)} · ${B.n} still to finish</div></div>
    <div class="wp" role="img" aria-label="${nmA} ${(wa*100).toFixed(0)}% to win"><span style="width:${(wa*100).toFixed(1)}%;background:var(--accent)"></span><span style="flex:1;background:var(--muted)"></span></div>
    <div class="pf" style="grid-column:1/-1">${nmA} ${(wa*100).toFixed(0)}% · ${nmB} ${(100-wa*100).toFixed(0)}% to win</div></div>`;
    if(big){for(const [S,lab] of [[A,nmA],[B,nmB]]){h+=`<div class="kicker" style="margin-top:10px">${lab}</div>`;S.rows.forEach(r=>{const pm=D.players[r.pid]||{};h+=`<div class="pl"><span class="pos">${esc(pm.p||'')}</span><span>${esc(pm.n||r.pid)} <small style="color:var(--muted)">${esc(pm.t||'')}</small></span><span class="st ${r.st}">${r.st==='yet'?'to play':r.st}</span><span class="v">${r.pts.toFixed(1)}</span><span class="v pj">${(pm.p==='K'||pm.p==='DEF')?'—':r.pj.toFixed(1)}</span></div>`})}}
    return h+'</div>'};
  if(mine)out.push(`<section><div class="kicker">Week ${D.week}</div><h2 class="disp">Your Matchup</h2>${card(mine,true)}<p class="status">Columns: status · points · our projection. Win odds use our model for players still to play.</p></section>`);
  out.push(`<section><div class="kicker">Around the league</div><h2 class="disp">Every Matchup</h2><div class="mini">${pairs.filter(p=>p!==mine).map(p=>card(p,false)).join('')}</div></section>`);
  document.getElementById('app').innerHTML=out.join('');
  document.getElementById('stamp').innerHTML=live?`<b>Live</b> · scores re-read from Sleeper at ${stamp}, every minute while this page is open`:`Snapshot from ${esc(D.built)} (Arizona time). Live re-reading isn't available in this view; the page refreshes 4x a day and on every update.`;
}
render(false);
async function poll(){try{const r=await fetch(`https://api.sleeper.app/v1/league/${D.league}/matchups/${D.week}`,{cache:'no-store'});if(!r.ok)throw 0;const M=await r.json();M.forEach(m=>{const x=D.matchups.find(y=>y.rid===m.roster_id);if(x){x.pp=m.players_points||{};x.starters=(m.starters||[]).filter(s=>s&&s!=='0')}});render(true,new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}));setTimeout(poll,60000)}catch(e){render(false)}}
poll();
</script>"""
    body = (f'<header><div class="eyebrow">{esc(LF.LEAGUE_NAME)} · Game Day</div><h1 class="disp">Week {week} Live</h1>'
            f'<p class="status" id="stamp">Snapshot from {esc(now)}</p>{links("Game Day")}</header><div id="app"></div>'
            '<script type="application/json" id="gd">' + json.dumps(gd).replace('</', '<' + chr(92) + '/') + '</script>')
    open(os.path.join(ROOT, 'dashboards', 'gameday.html'), 'w').write(page('Game Day Live', body, js))

    # ---------- ANALYSIS ----------
    PW = {s: {int(w): v for w, v in (x.get('weekly') or {}).items()} for s, x in proj.items()}
    sched = {int(k): v['schedule'] for k, v in (jload('projection.json', {}).get('rosters') or {}).items()}
    act = {r['roster_id']: [s for s in (r['players'] or []) if s not in (r.get('reserve') or []) and s not in (r.get('taxi') or [])] for r in R}
    phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    plan = jload('trade_plan.json', {'trades': []})
    plan_roster = list(act[my_rid])
    for t in plan['trades']:
        plan_roster = [s for s in plan_roster if s not in t['give']] + list(t['get'])
    rows = []
    cum_b = cum_p = 0.0
    for g in sched.get(my_rid, []):
        w = g['wk']
        if w < week:
            continue
        mine = lineup_points(act[my_rid], w, PW, pos_of)
        mplan = lineup_points(plan_roster, w, PW, pos_of)
        opp = lineup_points(act[g['opp']], w, PW, pos_of)
        b, p = phi((mine - opp) / 31), phi((mplan - opp) / 31)
        cum_b += b
        cum_p += p
        rows.append({'w': w, 'opp': rid_owner.get(g['opp']), 'me': mine, 'plan': mplan, 'opp_pts': opp, 'b': b, 'p': p})
    rec = next(r for r in R if r['roster_id'] == my_rid)['settings']
    # SVG: grouped bars per week (base = muted, plan = accent), y = win probability 0-100%
    Wd, Hd, padL, padB = 640, 220, 34, 26
    n = max(1, len(rows))
    bw = (Wd - padL - 10) / n
    svg = [f'<svg viewBox="0 0 {Wd} {Hd + padB}" role="img" aria-label="Win probability by week, now vs with the trade plan" style="width:100%;height:auto">']
    for yv in (0, 25, 50, 75, 100):
        y = 10 + (Hd - 10) * (1 - yv / 100)
        svg.append(f'<line class="ax" x1="{padL}" x2="{Wd - 4}" y1="{y:.1f}" y2="{y:.1f}" stroke-dasharray="{"" if yv in (0, 50) else "2 4"}"/>'
                   f'<text x="{padL - 6}" y="{y + 3:.1f}" text-anchor="end">{yv}%</text>')
    for i, r in enumerate(rows):
        x0 = padL + i * bw + bw * 0.14
        w2 = bw * 0.34
        for j, (v, col, lab) in enumerate(((r['b'], 'var(--muted)', 'now'), (r['p'], 'var(--accent)', 'with plan'))):
            h = (Hd - 10) * v
            x = x0 + j * (w2 + 2)
            svg.append(f'<rect x="{x:.1f}" y="{10 + (Hd - 10) - h:.1f}" width="{w2:.1f}" height="{h:.1f}" rx="3" fill="{col}">'
                       f'<title>Week {r["w"]} vs {esc(r["opp"])} — {lab}: {v:.0%} ({(r["plan"] if j else r["me"]):.0f} vs {r["opp_pts"]:.0f} projected)</title></rect>')
        svg.append(f'<text x="{x0 + w2:.1f}" y="{Hd + 16}" text-anchor="middle">W{r["w"]}</text>')
    svg.append('</svg>')
    must = [r for r in rows if 0.35 <= r['b'] <= 0.65]
    path_html = (f'<section id="path"><div class="kicker">Playoff path</div><h2 class="disp">Your Remaining Schedule</h2>'
                 f'<p class="lede">Win chance each week from our projections (your best lineup vs theirs, ±31 pts weekly swing). Record {rec["wins"]}-{rec["losses"]}; '
                 f'expected wins from here <b>{cum_b:.1f}</b> now, <b>{cum_p:.1f}</b> with the top-5 trade plan ({len(plan["trades"])} trades). '
                 'Coin-flip weeks (35-65%) are where a move pays off most: ' + (', '.join('W%s vs %s' % (r['w'], esc(r['opp'])) for r in must) or 'none') + '.</p>'
                 f'<div class="card"><div class="legend"><span><i style="background:var(--muted)"></i>Now</span><span><i style="background:var(--accent)"></i>With trade plan</span></div>'
                 + ''.join(svg) +
                 '<div class="scroller" style="border:none"><table style="min-width:0"><thead><tr><th>Wk</th><th>Opponent</th><th style="text-align:right">You</th>'
                 '<th style="text-align:right">Them</th><th style="text-align:right">Win now</th><th style="text-align:right">With plan</th></tr></thead><tbody>'
                 + ''.join(f'<tr><td class="rk">{r["w"]}</td><td class="team">{esc(r["opp"])}</td><td class="n">{r["me"]:.0f}</td><td class="n">{r["opp_pts"]:.0f}</td>'
                           f'<td class="n">{r["b"]:.0%}</td><td class="n">{r["p"]:.0%}</td></tr>' for r in rows)
                 + '</tbody></table></div><div class="status">Plan: ' + esc('; '.join(t['name'] for t in plan['trades'])) + '</div></div></section>')

    # Player trends: small multiples — weekly points (bars) with our projection line, snap share sparkline
    usage = jload('usage.json', {})
    tcards = []
    for s in sorted(act[my_rid], key=lambda s: -((proj.get(s) or {}).get('base') or 0)):
        u = usage.get(s) or {}
        wk = u.get('wk') or {}
        if not wk or pos_of(s) not in LF.POS:
            continue
        weeks_ = sorted(int(k) for k in wk)
        pts = [(w, wk[str(w)].get('pts') or 0, wk[str(w)].get('snap')) for w in weeks_]
        base = (proj.get(s) or {}).get('base') or 0
        mx = max([p for _, p, _ in pts] + [base, 10])
        cw, ch = 300, 90
        bw2 = cw / max(1, len(pts))
        g = [f'<svg viewBox="0 0 {cw} {ch + 34}" style="width:100%;height:auto" role="img" aria-label="{esc(nm(s))} weekly points">']
        for i, (w, p, sn) in enumerate(pts):
            h = ch * p / mx
            g.append(f'<rect x="{i * bw2 + 3:.1f}" y="{ch - h:.1f}" width="{bw2 - 6:.1f}" height="{h:.1f}" rx="3" fill="var(--accent)"><title>Week {w}: {p:.1f} pts{"" if sn is None else f", {sn:.0%} snaps"}</title></rect>'
                     f'<text x="{i * bw2 + bw2 / 2:.1f}" y="{ch + 12}" text-anchor="middle">W{w}</text>')
        yb = ch - ch * base / mx
        g.append(f'<line x1="0" x2="{cw}" y1="{yb:.1f}" y2="{yb:.1f}" stroke="var(--ink)" stroke-width="2" stroke-dasharray="5 4"><title>Our projection: {base:.1f}/gm</title></line>')
        sn_pts = [(i, sn) for i, (_, _, sn) in enumerate(pts) if sn is not None]
        if len(sn_pts) >= 2:
            line = ' '.join(f'{i * bw2 + bw2 / 2:.1f},{ch + 32 - 14 * sn:.1f}' for i, sn in sn_pts)
            g.append(f'<polyline points="{line}" fill="none" stroke="var(--gold)" stroke-width="2"/>')
        g.append('</svg>')
        last_sn = sn_pts[-1][1] if sn_pts else None
        trend = u.get('snap_trend')
        chip = ('good', 'role growing') if (trend or 0) >= 0.05 else ('crit', 'role shrinking') if (trend or 0) <= -0.05 else ('', 'role steady')
        tcards.append(f'<div class="card"><h3>{esc(nm(s))} · {esc(pos_of(s))} {esc(teamof(s))}</h3>'
                      f'<div class="chips"><span class="chip">{u.get("ppr_ppg", 0):.1f} PPR/gm</span><span class="chip">our proj {base:.1f}</span>'
                      + (f'<span class="chip">snaps {last_sn:.0%}</span>' if last_sn is not None else '')
                      + (f'<span class="chip {chip[0]}">{chip[1]}</span>' if trend is not None else '') + '</div>' + ''.join(g) + '</div>')
    trends_html = ('<section id="trends"><div class="kicker">Player trends</div><h2 class="disp">Your Players, Week by Week</h2>'
                   '<p class="lede">Bars = points each week. Dashed line = our projection per game. Gold line under the axis = snap share (top = 100%).</p>'
                   '<div class="legend"><span><i style="background:var(--accent)"></i>Weekly points</span><span><i style="background:var(--ink)"></i>Our projection</span>'
                   '<span><i style="background:var(--gold)"></i>Snap share</span></div>'
                   f'<div class="grid2">{"".join(tcards)}</div></section>')

    # Owner scouting
    cons = jload('values/consensus.json', {})
    mv = lambda s: (cons.get(s) or {}).get('mean_market', (cons.get(s) or {}).get('mean', 0))
    tf = jload('trade_finder.json', {})
    best = {o['partner']: o for o in tf.get('best_by_partner') or []}
    ransom = {}
    for x in tf.get('ransom') or []:
        ransom.setdefault(x['partner'], []).append(x)
    ledger = {x['owner']: x for x in jload('trade_ledger.json', [])}
    teams_o = {t['owner']: t for t in (op.get('teams') or {}).values()}
    # positional strength: sum of market value of each team's best starters at each position, ranked
    strength = {}
    for rid, ss in act.items():
        bypos = {}
        for p in LF.POS:
            vals = sorted((mv(s) for s in ss if pos_of(s) == p), reverse=True)[:max(1, LF.CORE.get(p, 1))]
            bypos[p] = sum(vals)
        strength[rid] = bypos
    rank = {p: {rid: i + 1 for i, rid in enumerate(sorted(strength, key=lambda r: -strength[r][p]))} for p in LF.POS}

    def last_note(owner):
        pth = os.path.join(ROOT, 'profiles', f'{owner}.md')
        if not os.path.exists(pth):
            return ''
        txt = open(pth).read()
        lines = [l.strip()[2:] for l in txt.split('\n') if l.strip().startswith('- **20')]
        return lines[-1][:260] + ('…' if lines and len(lines[-1]) > 260 else '') if lines else ''
    ocards = []
    for rid in sorted(act, key=lambda r: (teams_o.get(rid_owner[r]) or {}).get('exp_place', 99)):
        o = rid_owner[rid]
        if o == me:
            continue
        t = teams_o.get(o) or {}
        po = t.get('playoff', 0)
        win = ('good', 'contending') if po >= 0.6 else ('crit', 'rebuilding') if po <= 0.25 else ('warn', 'on the bubble')
        rk = rank
        needs = sorted(LF.POS, key=lambda p: -rk[p][rid])[:2]
        led = ledger.get(o) or {}
        b = best.get(o)
        rs = sorted(ransom.get(o, []), key=lambda x: -x['my_wins'])[:1]
        ocards.append(
            f'<div class="card"><div class="top" style="display:flex;justify-content:space-between;gap:8px"><h3>{esc(o)}</h3>'
            f'<span class="chip {win[0]}">{win[1]} · {po:.0%}</span></div><dl class="kv">'
            f'<dt>Record</dt><dd>{esc(t.get("record", "—"))} · our proj. finish {t.get("exp_place", 0):.1f}</dd>'
            f'<dt>Strength</dt><dd>' + ' · '.join(f'{p} #{rk[p][rid]}' for p in LF.POS) + '</dd>'
            f'<dt>Needs</dt><dd>{", ".join(needs)}</dd>'
            f'<dt>Trading</dt><dd>{led.get("trades", 0)} trades, ahead in {led.get("won", 0)}, net {led.get("net", 0):+,.0f}</dd>'
            + (f'<dt>Best offer</dt><dd>Give {esc(" + ".join(b["give_labels"]))} for <b>{esc(b["get_label"])}</b> (+{b["my_wins"]:.2f} wins)</dd>' if b else '')
            + (f'<dt>Ransom</dt><dd>{esc(rs[0]["asset_label"])} ← {esc(" + ".join(rs[0]["get_labels"]))}</dd>' if rs else '')
            + (f'<dt>Latest intel</dt><dd>{esc(last_note(o))}</dd>' if last_note(o) else '')
            + '</dl></div>')
    owners_html = ('<section id="owners"><div class="kicker">Owner scouting</div><h2 class="disp">Every Owner at a Glance</h2>'
                   '<p class="lede">Sorted by our projected finish. Strength = rank of each position\'s starters by market value (1 = best). '
                   'Best offer and ransom come from the Trade Finder; latest intel is the newest dated note in that owner\'s profile.</p>'
                   f'<div class="grid2">{"".join(ocards)}</div></section>')
    # ---------- six insight sections (ops/insights.py) ----------
    ins = jload('insights.json', {}) or {}
    rk_chip = lambda r: '' if r is None else f'<span class="chip {"good" if r <= 8 else "crit" if r >= 25 else ""}">{r}</span>'
    sos = (ins.get('sos') or {})
    sos_rows = ''.join(
        f'<tr><td class="team">{esc(x["name"])}<small>{esc(x["pos"])} {esc(x["team"])}</small></td>'
        f'<td class="n">{"—" if x["ros"] is None else x["ros"]}</td>'
        + ''.join(f'<td class="n">{esc(p_["opp"])} {rk_chip(p_["rank"])}</td>' for p_ in x['playoffs'])
        + '<td></td>' * (3 - len(x['playoffs'])) + '</tr>' for x in sos.get('players', []))
    sos_html = ('<section id="sos"><div class="kicker">Schedule</div><h2 class="disp">Strength of Schedule</h2>'
                f'<p class="lede">Each defense ranked by PPR points it allows per game to the position this season (1 = softest, {sos.get("n_teams", 32)} = toughest), '
                f'based on {sos.get("weeks_used", 0)} weeks so far, so early ranks are noisy. Rest-of-season = average rank of the remaining regular-season opponents; '
                'then the fantasy playoffs, weeks 15-17. Green = soft (1-8), red = tough (25+).</p>'
                '<div class="scroller"><table><thead><tr><th>Player</th><th style="text-align:right">Rest of season</th><th style="text-align:right">Wk 15</th>'
                f'<th style="text-align:right">Wk 16</th><th style="text-align:right">Wk 17</th></tr></thead><tbody>{sos_rows}</tbody></table></div></section>')

    eff = ins.get('efficiency') or []
    mxl = max([e['left_pg'] or 0 for e in eff] + [1])
    eff_html = ('<section id="efficiency"><div class="kicker">Owners</div><h2 class="disp">Lineup Efficiency</h2>'
                '<p class="lede">Share of the best possible lineup each owner actually started, and points left on the bench per game, across their games on record. '
                'Owners who leave a lot on the bench are the easiest to sell depth to.</p><div class="card race">'
                + ''.join(f'<div class="rrow{" you" if e["owner"] == me else ""}"><span class="nm">{esc(e["owner"])} <small style="color:var(--muted)">{e["eff"]:.1f}%</small></span>'
                          f'<span class="track"><span class="fill" style="width:{100 * (e["left_pg"] or 0) / mxl:.0f}%;background:var(--{"crit" if (e["left_pg"] or 0) >= 25 else "warn" if (e["left_pg"] or 0) >= 18 else "good"})"></span></span>'
                          f'<span class="v num">{e["left_pg"]:.1f}</span></div>' for e in eff)
                + '<div class="status">Bar = points left on the bench per game.</div></div></section>')

    vh = ins.get('values') or {}
    days_ = vh.get('days') or []
    vcards = []
    for x in (vh.get('players') or [])[:16]:
        ser = [(i, v) for i, v in enumerate(x['series']) if v]
        if len(ser) < 2:
            continue
        lo, hi = min(v for _, v in ser), max(v for _, v in ser)
        span = max(1, hi - lo)
        cw, ch = 300, 70
        pts_ = ' '.join(f'{cw * i / max(1, len(days_) - 1):.1f},{ch - 6 - (ch - 12) * (v - lo) / span:.1f}' for i, v in ser)
        first, last = ser[0][1], ser[-1][1]
        chg = (last - first) / first if first else 0
        ex, ey = cw * ser[-1][0] / max(1, len(days_) - 1), ch - 6 - (ch - 12) * (last - lo) / span
        vcards.append(f'<div class="card"><h3>{esc(x["name"])} · {esc(x["pos"])}</h3><div class="chips"><span class="chip">{last:,}</span>'
                      f'<span class="chip {"good" if chg >= 0.05 else "crit" if chg <= -0.05 else ""}">{chg:+.0%} since {esc(days_[ser[0][0]][5:])}</span></div>'
                      f'<svg viewBox="-4 0 {cw + 8} {ch}" style="width:100%;height:auto" role="img" aria-label="{esc(x["name"])} market value over time">'
                      f'<polyline points="{pts_}" fill="none" stroke="var(--accent)" stroke-width="2"/>'
                      f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="var(--accent)"><title>{last:,} on {esc(days_[-1])}</title></circle>'
                      f'<text x="0" y="10">{hi:,}</text><text x="0" y="{ch - 1}">{lo:,}</text></svg></div>')
    val_html = ('<section id="values"><div class="kicker">Market</div><h2 class="disp">Value History</h2>'
                f'<p class="lede">Market value of your players over time ({len(days_)} daily snapshots, {esc(days_[0] if days_ else "")} to {esc(days_[-1] if days_ else "")}). '
                'Buy the dips, sell the spikes; a fall with no injury or role change behind it is usually noise.</p>'
                f'<div class="grid2">{"".join(vcards)}</div></section>')

    calc = ins.get('calculator') or []
    calc_html = ('<section id="calc"><div class="kicker">Trades</div><h2 class="disp">What Would It Take?</h2>'
                 '<p class="lede">Pick any player worth 800+ on another roster to see the cheapest packages of yours that clear both sides\' rules '
                 '(rebuilders want market value back, contenders accept within 10%, core pieces only at the king’s ransom), ranked two ways: best for this season and best for your long-term plan.</p>'
                 '<div class="card"><label for="calcq" class="kicker">Player</label>'
                 '<input id="calcq" list="calcl" placeholder="Start typing a name…" style="font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);width:100%">'
                 '<datalist id="calcl">' + ''.join(f'<option value="{esc(c["name"])}">' for c in calc) + '</datalist>'
                 '<div id="calcout" class="status">Showing the most valuable target. Type a name to switch.</div></div>'
                 '<script type="application/json" id="calcd">' + json.dumps(calc).replace('</', '<' + chr(92) + '/') + '</script>'
                 """<script>(function(){const C=JSON.parse(document.getElementById('calcd').textContent);const q=document.getElementById('calcq'),o=document.getElementById('calcout');
const e=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function show(t){if(!t){o.textContent='No match. Pick a name from the list.';return}
let h=`<p style="margin:10px 0 4px"><b>${e(t.name)}</b> · ${e(t.pos)} ${e(t.team||'')} · @${e(t.owner)} (${e(t.window)}) · value ${t.value.toLocaleString()}</p>`;
const row=(p,i)=>`<div class="prow" style="grid-template-columns:1.6em minmax(0,1fr) 4.6em 5em"><span class="pos">${i+1}</span><span>${p.give.map(e).join(' + ')}${p.why&&p.why.length?`<br><small style="color:var(--muted)">${p.why.map(e).join(' · ')}</small>`:''}</span><span class="vv num" style="color:${p.my_wins>=0.1?'var(--good)':p.my_wins<=-0.1?'var(--crit)':'var(--ink2)'}">${p.my_wins>=0?'+':''}${p.my_wins.toFixed(2)} W</span><span class="vv num" style="color:${p.dyn>=150?'var(--good)':p.dyn<=-150?'var(--crit)':'var(--ink2)'}">${p.dyn>=0?'+':''}${p.dyn.toLocaleString()}</span></div>`;
if(!t.packages.length)h+='<p>No package of yours clears both sides’ rules for this player.</p>';
else{h+='<div class="kicker" style="margin-top:8px">Best for this season</div>'+t.packages.map(row).join('');h+='<div class="kicker" style="margin-top:10px">Best for the long-term plan (Contend 2026-28)</div>'+((t.dynasty||[]).map(row).join('')||'<p class="status">None that keeps the season intact.</p>')}
o.innerHTML=h+'<div class="status">Columns: what you give · expected wins this season · dynasty value across 2026-28 (aged with our age curves, plus the plan notes under each package).</div>'}
q.addEventListener('input',()=>{const t=C.find(c=>c.name.toLowerCase()===q.value.trim().toLowerCase());if(t)show(t)});show(C[0]);})();</script>"""
                 + '</section>')

    acc = ins.get('accuracy') or {}
    aw = acc.get('weeks') or []
    bt = acc.get('backtest_2025') or {}
    acc_html = ('<section id="accuracy"><div class="kicker">Our model</div><h2 class="disp">Projection Accuracy</h2>'
                f'<p class="lede">Average miss in PPR points per player each finished week: our projection (rebuilt from what was known before that week) vs Sleeper\'s, '
                f'for players Sleeper projected 5+. Lower is better. Full 2025 test: ours {bt.get("ours", "—")} vs Sleeper {bt.get("sleeper", "—")}.</p>'
                '<div class="scroller"><table><thead><tr><th>Week</th><th style="text-align:right">Players</th><th style="text-align:right">Ours</th><th style="text-align:right">Sleeper</th>'
                '<th style="text-align:right">QB</th><th style="text-align:right">RB</th><th style="text-align:right">WR</th><th style="text-align:right">TE</th></tr></thead><tbody>'
                + ''.join(f'<tr><td class="rk">{a["week"]}</td><td class="n">{a["n"]}</td>'
                          f'<td class="n" style="color:var(--{"good" if a["ours"] < a["sleeper"] else "ink2"})">{a["ours"]:.2f}</td><td class="n">{a["sleeper"]:.2f}</td>'
                          + ''.join((f'<td class="n">{a["by_pos"][p][0]:.1f} / {a["by_pos"][p][1]:.1f}</td>' if p in a["by_pos"] else '<td></td>') for p in ('QB', 'RB', 'WR', 'TE'))
                          + '</tr>' for a in aw)
                + '</tbody></table></div><div class="status">Position columns: ours / Sleeper. Green = we beat Sleeper that week.</div></section>')

    capd = ins.get('capital') or {}
    ct = capd.get('teams') or []
    mxc = max([t['total'] for t in ct] + [1])
    cap_html = ('<section id="capital"><div class="kicker">Picks</div><h2 class="disp">Draft Capital</h2>'
                '<p class="lede">Every team\'s 2027-2029 picks, valued by tier over the projected finish and lottery odds. Bar = total pick value; '
                'the line under it shows 1sts by year, the best pick, and where that team\'s own 2027 1st sits.</p><div class="card">'
                + ''.join(f'<div class="crow{" you" if t["owner"] == me else ""}"><span class="nm"><b>{esc(t["owner"])}</b> <small>{t["n"]} picks · {t["firsts"]} firsts</small></span>'
                          f'<span class="track"><span class="fill" style="width:{100 * t["total"] / mxc:.0f}%;background:var(--gold)"></span></span>'
                          f'<span class="v num">{t["total"]:,}</span>'
                          f'<span class="sig">1sts: ' + ', '.join(f'{y} ×{c}' for y, c in t['firsts_by_year'].items() if c) + (f' · best: {esc(t["best"][0])} ({t["best"][1]:,})' if t.get('best') else '')
                          + (f' · own 2027 1st held by {esc(t["own_1st_owner"])}' if t.get('own_1st_owner') and t['own_1st_owner'] != t['owner'] else '')
                          + (f' · own 2027 1st top-3 odds {t["own_1st_top3_trend"][-1]:.0%}' if t.get('own_1st_top3_trend') and t['own_1st_top3_trend'][-1] is not None else '')
                          + '</span></div>' for t in ct)
                + '</div></section>')
    ideas = ['<b>Rest-of-season strength of schedule</b> by position, from defenses\' points allowed — flags which of your players face soft or tough paths into the fantasy playoffs (weeks 15-17).',
             '<b>Lineup efficiency tracker</b> for every owner — points left on the bench each week; owners who leave a lot are the easiest to sell depth to.',
             '<b>Trade value history chart</b> per player (market value over the season from the daily snapshots) — buy the dips, sell the spikes.',
             '<b>"What it would take" calculator</b> — pick any player in the league and see the cheapest package of yours that clears both sides\' rules.',
             '<b>Projection accuracy board</b> — each week, our projection vs Sleeper\'s vs what actually happened, so you can see which to trust by position.',
             '<b>Draft capital tracker</b> — every 2027-2029 pick\'s owner and value over time, tied to the lottery odds, to time pick trades.']
    ideas_html = ('<section id="ideas"><div class="kicker">Next</div><h2 class="disp">More Analysis We Can Add</h2>'
                  f'<ol class="ideas">{"".join(f"<li>{i}</li>" for i in ideas)}</ol></section>')
    head = (f'<header><div class="eyebrow">{esc(LF.LEAGUE_NAME)} · Analysis</div><h1 class="disp">Season Analysis</h1>'
            f'<p class="status">Updated {esc(now)} Arizona time · our own projections · refreshes 4x a day and on every update</p>{links("Analysis")}</header>'
            '<nav class="jump" aria-label="Sections"><a href="#plan">Plan check</a><a href="#path">Playoff path</a><a href="#calc">What would it take</a><a href="#sos">Schedule</a><a href="#trends">Player trends</a>'
            '<a href="#values">Value history</a><a href="#owners">Owner scouting</a><a href="#efficiency">Lineup efficiency</a><a href="#capital">Draft capital</a><a href="#accuracy">Accuracy</a></nav>')
    pc = ins.get('plan') or {}
    wr = pc.get('window_rank') or []
    mxw = max([x['players'] + x['picks'] for x in wr] + [1])
    plan_rows = ''.join(f'<tr><td class="team">{esc(t["name"])}<small>with {esc(t["partner"])}</small></td>'
                        f'<td class="n" style="color:var(--{"good" if (t.get("dynasty") or 0) >= 150 else "crit" if (t.get("dynasty") or 0) <= -150 else "ink2"})">{(t.get("dynasty") or 0):+,}</td></tr>'
                        for t in pc.get('trades') or [])
    plan_html = ('<section id="plan"><div class="kicker">Long-term plan</div><h2 class="disp">Plan Check · Contend 2026-28</h2>'
                 f'<p class="lede">Window strength = each team\'s top 16 players valued across the next {pc.get("window_years", 3)} seasons (aged with our measured age curves) '
                 f'plus its 2027-28 picks. You rank <b>{pc.get("my_rank", "—")} of {len(wr)}</b>. The trade plan lifts your players\' window value to '
                 f'<b>{pc.get("after_players", 0):,}</b> and nets <b>{(pc.get("dynasty_total") or 0):+,}</b> in plan value after picks spent.</p>'
                 '<div class="cols"><div class="card race">' + ''.join(
                     f'<div class="rrow{" you" if x["owner"] == me else ""}"><span class="nm">{esc(x["owner"])}</span>'
                     f'<span class="track"><span class="fill" style="width:{100 * (x["players"] + x["picks"]) / mxw:.0f}%;background:var(--accent)"></span></span>'
                     f'<span class="v num">{(x["players"] + x["picks"]) / 1000:.1f}k</span></div>' for x in wr)
                 + '</div><div class="card"><h3>Trade plan, long-term value</h3><div class="scroller" style="border:none"><table style="min-width:0"><tbody>'
                 + plan_rows + '</tbody></table></div><div class="status">Season effect of each trade is on the Playoff Path above; '
                 'the What Would It Take tool ranks every target both ways.</div></div></div></section>')
    open(os.path.join(ROOT, 'dashboards', 'analysis.html'), 'w').write(page('Season Analysis', head + plan_html + path_html + calc_html + sos_html + trends_html + val_html
                                                                           + owners_html + eff_html + cap_html + acc_html))
    print(f'analysis dashboards -> dashboards/gameday.html (week {week}, {len(M) // 2} matchups) + dashboards/analysis.html '
          f'({len(rows)} weeks on the path; exp. wins {cum_b:.1f} now / {cum_p:.1f} with plan; {len(tcards)} player trend cards; {len(ocards)} owner cards)')


if __name__ == '__main__':
    main()
