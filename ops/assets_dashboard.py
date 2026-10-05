#!/usr/bin/env python3
"""League asset board -> dashboards/assets.html

Every team's future picks (2027-2029) and full roster on one page, with yours
first. Picks are valued with ops/picks.py (league-calibrated tiers x the
Max PF lottery odds); players at corrected consensus. Reads the data/ cache, so run it after ops/fetch.py (update.sh does).
Pending trades are NOT shown: they live only in Sleeper's logged-in GraphQL.
"""
import json, os, html, datetime, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import picks as PK  # noqa: E402
import league_format as LF  # noqa: E402

MY = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))['my_username']
SEASONS = [str(int(PK.latest) + i) for i in (1, 2, 3)]   # the next three rookie drafts
POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']
esc = html.escape

players = PK.players
cons = PK.cons
rosters = PK.rosters
users = PK.users
latest = PK.latest
_tname = {u['user_id']: (u.get('metadata') or {}).get('team_name') or u['display_name'] for u in users}
uname = PK.rid2user
team = {r['roster_id']: _tname.get(r['owner_id'], '?') for r in rosters}
my_rid = next(r for r, u in uname.items() if u == MY)


def V(pid):
    return round(cons.get(str(pid), {}).get('mean', 0))


# ---- pick ownership for 2027-2029 (default = original owner; traded_picks overrides)
override = {(t['season'], t['round'], t['roster_id']): t['owner_id'] for t in PK.traded if t['season'] in SEASONS}
own = {r['roster_id']: [] for r in rosters}
for s in SEASONS:
    for rnd in PK.ROUNDS:
        for orig in own:
            holder = override.get((s, rnd, orig), orig)
            if holder in own:
                val, tier = PK.pick_value(s, rnd, orig)
                dist = PK.slot_dist(s, orig)
                own[holder].append({'s': s, 'r': rnd, 'orig': uname.get(orig), 'mine': holder == orig,
                                    'tier': tier, 'v': round(val),
                                    'early': round(100 * sum(dist[:4])), 'top': round(100 * dist[0], 1)})
for h in own:
    own[h].sort(key=lambda p: (p['s'], p['r'], -p['v']))

# ---- rosters
def roster_rows(r):
    st, ir, tx = set(r.get('starters') or []), set(r.get('reserve') or []), set(r.get('taxi') or [])
    out = []
    for pid in r.get('players') or []:
        p = players.get(str(pid), {})
        pos = p.get('position') or ('DEF' if not str(pid).isdigit() else '?')
        name = p.get('full_name') or (f"{p.get('first_name','')} {p.get('last_name','')}".strip()) or str(pid)
        slot = 'IR' if pid in ir else 'Taxi' if pid in tx else 'Start' if pid in st else 'Bench'
        out.append({'n': name, 'pos': pos, 'nfl': p.get('team') or '', 'age': p.get('age') or '',
                    'v': V(pid), 'inj': p.get('injury_status') or '', 'slot': slot})
    out.sort(key=lambda x: (POS_ORDER.index(x['pos']) if x['pos'] in POS_ORDER else 9, -x['v']))
    return out

teams = []
for r in rosters:
    rid, s = r['roster_id'], r['settings']
    rows = roster_rows(r)
    teams.append({'rid': rid, 'user': uname.get(rid), 'team': team[rid], 'me': rid == my_rid,
                  'w': s.get('wins', 0), 'l': s.get('losses', 0),
                  'pf': s.get('fpts', 0), 'maxpf': s.get('ppts', 0),
                  'rv': sum(x['v'] for x in rows), 'pv': sum(p['v'] for p in own[rid]),
                  'n1': sum(1 for p in own[rid] if p['r'] == 1),
                  'roster': rows, 'picks': own[rid]})
teams.sort(key=lambda t: (not t['me'], -(t['rv'] + t['pv'])))
for i, t in enumerate(sorted(teams, key=lambda t: -(t['rv'] + t['pv'])), 1):
    t['rank'] = i

# who holds each original pick (for the grid)
grid = {}
for t in teams:
    for p in t['picks']:
        grid[(p['orig'], p['s'], p['r'])] = {'holder': t['user'], 'tier': p['tier'], 'v': p['v'], 'early': p['early']}

_pp = os.path.join(DATA, 'prospects.json')
PROS = json.load(open(_pp)) if os.path.exists(_pp) else {'board': [], 'picks': {}, 'date': None}
_RNK = PK._RN
my_ktc = [{'label': f"{p['s']} {p['tier']} {_RNK[p['r']]}", 'cls': int(p['s']),
           'v': PROS['picks'].get(f"{p['s']} {p['tier']} {_RNK[p['r']]}", 0),
           'via': None if p['mine'] else p['orig']}
          for t in teams if t['me'] for p in t['picks']]

payload = {'fmt': 'superflex' if LF.SUPERFLEX else '1QB', 'rounds': list(PK.ROUNDS), 'teams': teams, 'prospects': PROS['board'], 'pros_date': PROS.get('date'), 'my_ktc': my_ktc, 'seasons': SEASONS, 'me': MY,
           'grid': [{'orig': k[0], 's': k[1], 'r': k[2], **v} for k, v in grid.items()],
           'gen': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'season': latest}

CSS = open(os.path.join(ROOT, 'ops', 'dashboard.css')).read()
PAGE = r'''<meta charset="utf-8"><title>__LEAGUE__ Asset Board</title>
<style>
''' + CSS + r'''
/* layout: summary table first, then three views (my picks / league pick grid / rosters) behind tabs */
.tabs{display:flex;flex-wrap:wrap;gap:8px}
.tab{font:inherit;font-weight:600;font-size:14px;padding:8px 16px;border-radius:999px;border:1px solid var(--line);
  background:var(--card);color:var(--ink);cursor:pointer}
.tab[aria-selected="true"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.tab:focus-visible,.chip:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
tr.me td{background:var(--you-bg)}
.pill{display:inline-block;font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  padding:2px 8px;border-radius:999px;border:1px solid var(--line);white-space:nowrap}
.t-Early{color:var(--good);border-color:var(--good)}
.t-Mid{color:var(--warn);border-color:var(--warn)}
.t-Late{color:var(--muted)}
.inj{color:var(--crit);font-weight:700;font-size:12px}
.slot-Start{font-weight:700}
.slot-IR,.slot-Taxi{color:var(--muted)}
.muted{color:var(--muted)}
.grid td,.grid th{text-align:center;padding:8px 6px}
.grid td:first-child,.grid th:first-child{text-align:left;padding-left:12px}
.cell{display:flex;flex-direction:column;align-items:center;gap:1px;font-size:12.5px;line-height:1.25}
.cell .h{font-weight:700}
.cell.kept .h{color:var(--muted);font-weight:500}
.cell.mine .h{color:var(--gold)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font:inherit;font-size:13px;padding:6px 12px;border-radius:8px;border:1px solid var(--line);background:var(--card);
  color:var(--ink);cursor:pointer}
.chip[aria-pressed="true"]{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent);font-weight:700}
.teamhead{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:baseline}
.teamhead h3{margin:0;font-size:20px}
.cols{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:16px}
@media (max-width:760px){.cols{grid-template-columns:1fr}}
.legend{font-size:13px;color:var(--ink2);max-width:75ch}
.pbar{display:grid;grid-template-columns:minmax(0,9.5em) 2.6em minmax(0,1fr) 3.6em;gap:8px;align-items:center;font-size:13px;padding:3px 0}
.pbar .nm{overflow:hidden;font-weight:600}
.pbar .nm small{white-space:normal}
.pbar .nm small{display:block;font-weight:400;color:var(--muted);font-size:11px}
.pbar .track{height:12px;border-radius:6px;background:var(--track);overflow:hidden}
.pbar .fill{height:100%;border-radius:6px}
.pbar .v{text-align:right;font-variant-numeric:tabular-nums;font-size:12px}
.p-QB{background:var(--crit)} .p-RB{background:var(--accent)} .p-WR{background:var(--gold)} .p-TE{background:var(--warn)}
.pospill{font-size:11px;font-weight:700;color:var(--paper);border-radius:4px;padding:1px 0;text-align:center}
.mypick{border-top:2px dashed var(--gold);border-bottom:2px dashed var(--gold);background:var(--you-bg);padding:6px 8px;margin:4px 0;
  font-size:13px;font-weight:700;border-radius:4px}
.ret{color:var(--muted);font-size:11px;font-weight:600}
</style>
<div class="wrap">
<header>
  <div class="eyebrow">__LEAGUE__ · <span id="season"></span> season</div>
  <h1><span class="disp">Asset Board</span></h1>
  <div class="sub">Every team's roster and its 2027–2029 rookie picks. Player values are league consensus; pick values use this league's
  calibrated pick prices and the commissioner's Max PF lottery. Generated <span id="gen" class="num"></span> from Sleeper data.
  Pending trades are not shown until they complete.</div>
</header>

<section>
  <h2 class="disp">League summary</h2>
  <p class="lede">Ranked by total assets (roster + picks). Your row is highlighted.</p>
  <div class="scroller"><table id="summary"></table></div>
</section>

<section>
  <div class="tabs" role="tablist">
    <button class="tab" role="tab" id="tab-mine" aria-selected="true">My picks</button>
    <button class="tab" role="tab" id="tab-grid" aria-selected="false">Every pick in the league</button>
    <button class="tab" role="tab" id="tab-rosters" aria-selected="false">Rosters</button>
    <button class="tab" role="tab" id="tab-prospects" aria-selected="false">Prospects</button>
  </div>
</section>

<section id="view-mine"></section>
<section id="view-grid" hidden></section>
<section id="view-rosters" hidden></section>
<section id="view-prospects" hidden></section>

<p class="legend"><b>Tier</b> is the band a pick most likely lands in: Early = the first third of a round, Mid = the middle third, Late = the last third.
<b>Early %</b> is the chance it lands in picks 1–4. For 2027 that comes from a simulation of the rest of the 2026 season and the lottery;
2028–2029 use projected finish plus owner trajectory reads, so treat them as rough. Values: picks ≈ what this league's past picks became; a 2028 Mid 1st ≈ 1,700–1,950.</p>
</div>
<script>
const D = __DATA__;
const $ = s => document.querySelector(s);
const f = n => Number(n).toLocaleString('en-US');
const e = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const RN = {1:'1st',2:'2nd',3:'3rd',4:'4th',5:'5th',6:'6th'};
$('#season').textContent = D.season; $('#gen').textContent = D.gen;

// summary
$('#summary').innerHTML = '<tr><th>#</th><th>Team</th><th>Record</th><th>Max PF</th><th>Roster value</th><th>Pick value</th><th>1sts held</th><th>Total</th></tr>' +
  [...D.teams].sort((a,b)=>a.rank-b.rank).map(t => `<tr class="${t.me?'me':''}"><td class="num">${t.rank}</td>
  <td><b>${e(t.team)}</b> <span class="muted">@${e(t.user)}</span></td><td class="num">${t.w}-${t.l}</td>
  <td class="num">${f(t.maxpf)}</td><td class="num">${f(t.rv)}</td><td class="num">${f(t.pv)}</td>
  <td class="num">${t.n1}</td><td class="num"><b>${f(t.rv+t.pv)}</b></td></tr>`).join('');

function pickTable(ps, showHolder){
  if(!ps.length) return '<p class="muted">No 2027–2029 picks.</p>';
  return `<div class="scroller"><table><tr><th>Year</th><th>Round</th><th>Original team</th><th>Tier</th><th>Early %</th><th>#1 %</th><th>Value</th></tr>` +
    ps.map(p => `<tr><td class="num">${p.s}</td><td>${RN[p.r]}</td><td>${p.mine?'<span class="muted">Own</span>':'via @'+e(p.orig)}</td>
    <td><span class="pill t-${p.tier}">${p.tier}</span></td><td class="num">${p.early}%</td><td class="num">${p.top}%</td><td class="num">${f(p.v)}</td></tr>`).join('') +
    `<tr><td colspan="6"><b>Total</b></td><td class="num"><b>${f(ps.reduce((a,p)=>a+p.v,0))}</b></td></tr></table></div>`;
}

// my picks
const me = D.teams.find(t=>t.me);
$('#view-mine').innerHTML = `<h2 class="disp">My picks — ${e(me.team)}</h2>
  <p class="lede">${me.picks.length} picks worth ${f(me.pv)}.</p>` + pickTable(me.picks);

// league grid: rows = original team, cols = season x round; cell = who holds it
const users = [...D.teams].sort((a,b)=>a.user.localeCompare(b.user, undefined, {sensitivity:'base'})).map(t=>t.user);
const G = {}; D.grid.forEach(g => G[g.orig+'|'+g.s+'|'+g.r] = g);
let gh = '<tr><th>Original team</th>' + D.seasons.map(s=>D.rounds.map(r=>`<th>${s} ${RN[r]}</th>`).join('')).join('') + '</tr>';
users.forEach(u => {
  gh += `<tr class="${u===D.me?'me':''}"><td><b>@${e(u)}</b></td>` + D.seasons.map(s=>D.rounds.map(r=>{
    const g = G[u+'|'+s+'|'+r]; if(!g) return '<td class="muted">—</td>';
    const kept = g.holder===u, mine = g.holder===D.me;
    return `<td><div class="cell ${kept?'kept':''} ${mine?'mine':''}"><span class="h">${kept?'kept':'@'+e(g.holder)}</span>
      <span class="pill t-${g.tier}">${g.tier}</span></div></td>`;}).join('')).join('') + '</tr>';
});
$('#view-grid').innerHTML = `<h2 class="disp">Every pick in the league</h2>
  <p class="lede">Each row is the team the pick originally belonged to; each cell shows who holds it now. Gold = you hold it. Grey "kept" = still with its original team.</p>
  <div class="scroller"><table class="grid" style="min-width:1100px">${gh}</table></div>
  <h2 class="disp" style="margin-top:24px">Pick holdings by team</h2>
  <div class="scroller"><table><tr><th>Team</th><th>2027</th><th>2028</th><th>2029</th><th>Value</th></tr>` +
  [...D.teams].sort((a,b)=>b.pv-a.pv).map(t=>`<tr class="${t.me?'me':''}"><td><b>@${e(t.user)}</b></td>` +
    D.seasons.map(s=>'<td>'+t.picks.filter(p=>p.s===s).map(p=>`${RN[p.r]}${p.mine?'':' <span class="muted">('+e(p.orig)+')</span>'}`).join(', ')+'</td>').join('') +
    `<td class="num">${f(t.pv)}</td></tr>`).join('') + '</table></div>';

// rosters
let cur = (()=>{ try { return localStorage.getItem('asset-team') } catch(_) { return null } })() || D.me;
if(!D.teams.some(t=>t.user===cur)) cur = D.me;
function renderRoster(){
  const t = D.teams.find(x=>x.user===cur);
  const chips = D.teams.map(x=>`<button class="chip" aria-pressed="${x.user===cur}" data-u="${e(x.user)}">${x.me?'★ ':''}${e(x.team)}</button>`).join('');
  const rows = t.roster.map(p=>`<tr><td class="num">${e(p.pos)}</td><td class="slot-${p.slot}">${e(p.n)}${p.inj?` <span class="inj">${e(p.inj.slice(0,4).toUpperCase())}</span>`:''}</td>
    <td>${e(p.nfl)}</td><td class="num">${p.age}</td><td class="slot-${p.slot}">${p.slot}</td><td class="num">${f(p.v)}</td></tr>`).join('');
  $('#view-rosters').innerHTML = `<h2 class="disp">Rosters</h2><div class="chips" role="group" aria-label="Choose a team">${chips}</div>
    <div class="teamhead" style="margin-top:16px"><h3>${e(t.team)}</h3><span class="muted">@${e(t.user)}</span>
    <span class="num">${t.w}-${t.l}</span><span>Rank <b>${t.rank}</b></span><span>Roster <b class="num">${f(t.rv)}</b></span><span>Picks <b class="num">${f(t.pv)}</b></span></div>
    <div class="cols" style="margin-top:12px"><div class="scroller" style="min-width:0"><table style="min-width:520px"><tr><th>Pos</th><th>Player</th><th>NFL</th><th>Age</th><th>Slot</th><th>Value</th></tr>${rows}</table></div>
    <div style="min-width:0">${pickTable(t.picks)}</div></div>`;
  document.querySelectorAll('#view-rosters .chip').forEach(b=>b.onclick=()=>{cur=b.dataset.u; try{localStorage.setItem('asset-team',cur)}catch(_){} renderRoster();});
}
renderRoster();

// prospects
const POSC = {QB:'p-QB',RB:'p-RB',WR:'p-WR',TE:'p-TE'};
let pcls = 2028, ppos = 'ALL';
function renderPros(){
  const all = D.prospects.filter(p=>p.cls===pcls && (ppos==='ALL'||p.pos===ppos)).slice(0,30);
  const mx = Math.max(1, ...D.prospects.filter(p=>p.cls===pcls).map(p=>p.value));
  const mine = D.my_ktc.filter(m=>m.cls===pcls && m.v).sort((a,b)=>b.v-a.v);
  let rows = '', mi = 0;
  all.forEach(p=>{
    while(mi<mine.length && mine[mi].v>p.value){ rows += `<div class="mypick">▶ Your ${e(mine[mi].label)}${mine[mi].via?' (via '+e(mine[mi].via)+')':''} ≈ ${f(mine[mi].v)} — players above cost more than this pick</div>`; mi++; }
    const mv = p.delta? `<span style="color:var(--${p.delta>0?'good':'crit'})">${p.delta>0?'▲':'▼'}${f(Math.abs(p.delta))}</span>` : '';
    rows += `<div class="pbar"><span class="nm">${e(p.name)}<small>${e(p.school)}${p.returning?' · <span class="ret">returning to school</span>':''}${p.stats?'<br>'+e(p.stats):''}</small></span>
      <span class="pospill ${POSC[p.pos]}">${p.pos}</span>
      <span class="track"><span class="fill ${POSC[p.pos]}" style="display:block;width:${Math.max(3,Math.round(100*p.value/mx))}%"></span></span>
      <span class="v">${f(p.value)} ${mv}</span></div>`;
  });
  while(mi<mine.length){ rows += `<div class="mypick">▶ Your ${e(mine[mi].label)} ≈ ${f(mine[mi].v)}</div>`; mi++; }
  const classes = [...new Set(D.prospects.map(p=>p.cls))].filter(c=>c>=2027).sort();
  const counts = c => ['QB','RB','WR','TE'].map(ps=>`${ps} ${D.prospects.filter(p=>p.cls===c&&p.pos===ps).length}`).join(' · ');
  $('#view-prospects').innerHTML = `<h2 class="disp">College prospects</h2>
    <p class="lede">KeepTradeCut devy values (${D.fmt}), the same scale as your picks. Updated ${e(D.pros_date||'—')}; arrows show movement since the last weekly snapshot.</p>
    <div class="chips" role="group" aria-label="Draft class">${classes.map(c=>`<button class="chip" data-c="${c}" aria-pressed="${c===pcls}">${c} class</button>`).join('')}</div>
    <div class="chips" role="group" aria-label="Position" style="margin-top:8px">${['ALL','QB','RB','WR','TE'].map(ps=>`<button class="chip" data-p="${ps}" aria-pressed="${ps===ppos}">${ps==='ALL'?'All':ps}</button>`).join('')}</div>
    <p class="muted" style="font-size:12.5px;margin:10px 0 6px">${pcls} board: ${counts(pcls)}</p>
    <div>${rows || '<p class="muted">No prospects listed for this class yet.</p>'}</div>`;
  document.querySelectorAll('#view-prospects [data-c]').forEach(b=>b.onclick=()=>{pcls=+b.dataset.c; renderPros();});
  document.querySelectorAll('#view-prospects [data-p]').forEach(b=>b.onclick=()=>{ppos=b.dataset.p; renderPros();});
}
renderPros();

// tabs
const tabs = ['mine','grid','rosters','prospects'];
function show(k){ tabs.forEach(x=>{ $('#tab-'+x).setAttribute('aria-selected', x===k); $('#view-'+x).hidden = x!==k; }); }
tabs.forEach(k=>$('#tab-'+k).onclick=()=>show(k));
const h = location.hash.slice(1); if(tabs.includes(h)) show(h);
</script>
'''

out = os.path.join(ROOT, 'dashboards', 'assets.html')
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, 'w').write(PAGE.replace('__LEAGUE__', html.escape(LF.LEAGUE_NAME)).replace('__DATA__', json.dumps(payload).replace('</', '<\\/')))
print(f'asset board -> dashboards/assets.html ({len(teams)} teams, '
      f'{sum(len(t["picks"]) for t in teams)} picks 2027-2029)')
