#!/usr/bin/env python3
"""Dynasty Command Center — one self-contained HTML page tracking everything:
power rankings (win-now + dynasty), my team + plan actions, trade grades +
recent activity, and the owner board.

Data computes fresh from data/ via the shared ops/picks.py tier model and
ops/trade_grades.py grader. Qualitative reads (my action list, one-line owner
reads) live in the small dicts below — update as reads evolve. Emits a single
inline-CSS file (no external assets — publishes cleanly as a claude.ai artifact)
to dashboards/league.html. Part of ./update.sh. Stdlib only.
"""
import json, os, html
from datetime import date, datetime

import picks as PK
import league_format as LF
from picks import pick_value, owned_future_picks, rid2owner, PPROJ, TRAJ_2028
import trade_grades as TG

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CFG = json.load(open(os.path.join(ROOT, 'config.json')))
players = PK.players
cons = PK.cons
rosters = PK.rosters
latest = PK.latest
users = json.load(open(os.path.join(DATA, latest, 'users.json')))
txns = json.load(open(os.path.join(DATA, latest, 'transactions.json')))
league = json.load(open(os.path.join(DATA, latest, 'league.json')))
# "(season not started)" was hardcoded and went stale the moment week 1 kicked
# off (2026-09-10). Derive it.
_leg = (league.get('settings') or {}).get('leg') or 0
SEASON_STATE = ('season not started' if league.get('status') != 'in_season'
                else f'week {_leg}' if _leg else 'in season')
mskill = json.load(open(os.path.join(DATA, 'manager_skill.json'))) if \
    os.path.exists(os.path.join(DATA, 'manager_skill.json')) else {}
profiles = json.load(open(os.path.join(ROOT, 'profiles', 'profiles.json')))
_cp = os.path.join(DATA, 'context.json')
context = json.load(open(_cp)) if os.path.exists(_cp) else {}
_up = os.path.join(DATA, 'usage.json')
usage = json.load(open(_up)) if os.path.exists(_up) else {}
_agp = os.path.join(DATA, 'age_curve.json')
age_curve = json.load(open(_agp)) if os.path.exists(_agp) else {}

# availability severity -> chip class. Q is amber (a start/sit call), anything
# that means "cannot play" is red.
AVAIL_CLASS = {'Q': 'mid', 'IR': 'hole', 'PUP': 'hole', 'SUSPENDED': 'hole',
               'NA': 'hole', 'DNR': 'hole'}


def risk_chips(pid):
    """Availability / walk-year chips for one player, as HTML."""
    c = context.get(pid)
    if not c:
        return ''
    out = ''
    a = c.get('avail')
    if a and a != 'OK':
        body = (c.get('injury') or {}).get('body_part')
        out += (f'<span class="chip {AVAIL_CLASS.get(a, "mid")}">'
                f'{esc(a)}{esc(" · " + body if body else "")}</span>')
    ct = cons.get(str(pid), {}).get('contract') or {}
    if ct.get('class') in ('rookie_deal', 'veteran'):
        cut = round((1 - ct.get('mult', 1)) * 100)
        out += f'<span class="chip mid">Contract yr{f" −{cut}%" if cut else ""}</span>'
    if c.get('age_flag'):
        out += f'<span class="chip reb">Age {c["age_flag"]["age"]}</span>'
    if c.get('new_hc'):
        out += '<span class="chip">New HC</span>'
    return out

MY = CFG['my_username']
POS = ('QB', 'RB', 'WR', 'TE')
uid_user = {u['user_id']: u['display_name'] for u in users}
my_rid = next(r['roster_id'] for r in rosters if uid_user.get(r.get('owner_id')) == MY)
roster_of = {r['roster_id']: r for r in rosters}


def V(pid): return cons.get(str(pid), {}).get('mean', 0)
def posn(pid): return players.get(str(pid), {}).get('position')
def pname(pid): return players.get(str(pid), {}).get('full_name', str(pid))
def page(pid): return players.get(str(pid), {}).get('age')
def esc(s): return html.escape(str(s))
def team_name(rid): return rid2owner.get(rid, '?')


def optimal(pl):
    return LF.best_lineup_ids((V(pid), pid, posn(pid)) for pid in pl if posn(pid) in POS)


# ---- power-ranking metrics per team -----------------------------------------
OWNED = owned_future_picks()
pkval = {rid: sum(pick_value(s, rnd, orig)[0] for s, rnd, orig in OWNED.get(rid, [])) for rid in OWNED}
metrics = {}
for r in rosters:
    rid = r['roster_id']
    pl = [p for p in (r.get('players') or []) if posn(p) in POS]
    starters, _ = optimal(pl)
    rv = sum(V(p) for p in pl)
    metrics[rid] = {'starters': starters, 'roster': rv, 'picks': pkval.get(rid, 0),
                    'total': rv + pkval.get(rid, 0)}
dyn_rank = {rid: i + 1 for i, rid in enumerate(sorted(metrics, key=lambda k: -metrics[k]['total']))}
win_rank = {rid: i + 1 for i, rid in enumerate(sorted(metrics, key=lambda k: -metrics[k]['starters']))}

# ---- trade grades ------------------------------------------------------------
net, trades = TG.grade()
trades.sort(key=lambda x: -x[0])
trade_rank = {rid: i + 1 for i, rid in enumerate(sorted(net, key=lambda k: -net[k]))}

# ---- trade counts ------------------------------------------------------------
tcount = {rid: 0 for rid in rid2owner}
seen = set()
for s in sorted(json.load(open(os.path.join(DATA, 'seasons.json')))):
    p = os.path.join(DATA, s, 'transactions.json')
    if not os.path.exists(p):
        continue
    for t in json.load(open(p)):
        if t['type'] == 'trade' and t.get('status') == 'complete' and t['transaction_id'] not in seen:
            seen.add(t['transaction_id'])
            for rid in t['roster_ids']:
                if rid in tcount:
                    tcount[rid] += 1

# ---- my team facts -----------------------------------------------------------
me = roster_of[my_rid]
my_players = [p for p in (me.get('players') or []) if posn(p) in POS]
my_players.sort(key=lambda p: -V(p))
faab_used = (me.get('settings') or {}).get('waiver_budget_used', 0)
faab_budget = (json.load(open(os.path.join(ROOT, 'data', latest, 'league.json'))).get('settings') or {}).get('waiver_budget') or 100
my_place = PPROJ.get(my_rid, 8)
wins = (me.get('settings') or {}).get('wins', 0)
losses = (me.get('settings') or {}).get('losses', 0)

# projected record straight from ops/project.py rather than a hand-typed string,
# so the verdict line can never drift from the numbers below it
_pj = os.path.join(DATA, 'projection.json')
_pr = (json.load(open(_pj))['rosters'].get(str(my_rid)) if os.path.exists(_pj) else None)
proj_rec = f"{_pr['wins']}-{_pr['losses']}" if _pr else '?'
PLAYOFF_SPOTS = LF.PLAYOFF_TEAMS
verdict = ('Contender' if my_place <= 4 else
           'Bubble team' if my_place <= PLAYOFF_SPOTS + 1 else 'Seller')


def starter_rank_pos(pos):
    def sv(rid):
        vals = sorted((V(x) for x in (roster_of[rid].get('players') or []) if posn(x) == pos), reverse=True)
        n = LF.CORE[pos]
        return sum(vals[:n])
    order = sorted(metrics, key=lambda rid: -sv(rid))
    return order.index(my_rid) + 1


my_pos_rank = {p: starter_rank_pos(p) for p in POS}
holes = [p for p in POS if my_pos_rank[p] >= LF.HOLE_RANK and LF.CORE[p]]


# ============================ hand-maintained reads ==========================
# Starter cards. YOUR cards go in my_cards.py at the folder root (git-ignored), which overrides
# these; never edit them here, because an edited framework file blocks updates. See CLAUDE.md.
OPEN_DECISIONS_DATE = '2000-01-01'   # set to today whenever OPEN_DECISIONS is rewritten; ops/freshness.py flags it at 3+ days
OPEN_DECISIONS = ("Say \"update everything\", then ask Claude for a full league review · set your CURRENT STRATEGY in "
                  "profiles/<your username>.md · set this week's lineup")

MY_ACTIONS = [
    ('hold', 'STRATEGY — not set yet',
     'Ask Claude to review your roster, picks, playoff odds and the draft classes, propose two or three strategies '
     '(contend now, retool, rebuild), and write the one you adopt under "CURRENT STRATEGY" in your own profile\'s '
     'manual notes. Every trade gets judged against it.',
     'Start here'),
    ('hold', 'Price every trade in your league\'s format',
     'KeepTradeCut and the consensus values here are pulled for your league\'s format (1QB or superflex, '
     'PPR or not; see LEAGUE.md). Claude can load any trade into the KTC calculator and read the verdict, '
     'and ops/trade_sim.py shows what a trade does to every team\'s playoff odds.',
     'Method'),
    ('hold', 'Know your draft-order rule',
     'Pick values depend on how your rookie draft order is set (reverse record, a lottery, Max PF). No platform '
     'exposes it, so it is saved in config.json during setup. If it changes, tell Claude.',
     'League rule'),
]

# Your scouting read on each owner, keyed by Sleeper USERNAME (team names change).
OWNER_READS = {}

# Pin a team's window chip when the computed label is wrong, e.g. {'yourname': ('Contend', 'win')}
WINDOW_OVERRIDE = {}

KIND_LABEL = {'buy': 'Buy', 'sell': 'Sell', 'hold': 'Plan', 'done': 'Done'}

# An owner's own cards can live in my_cards.py at the folder root (git-ignored, so an update never
# touches or blocks on it). Anything it defines (OPEN_DECISIONS_DATE, OPEN_DECISIONS, MY_ACTIONS,
# OWNER_READS, WINDOW_OVERRIDE) replaces the defaults above.
_MY_CARDS = os.path.join(ROOT, 'my_cards.py')
if os.path.exists(_MY_CARDS):
    exec(compile(open(_MY_CARDS, encoding='utf-8').read(), _MY_CARDS, 'exec'))

WINDOW_CHIP = {  # label -> (text, css class)
    'accumulating': ('Rebuild', 'reb'), 'all-in': ('All-in', 'win'),
    'balanced': ('Balanced', 'mid'), 'win-now': ('Win-now', 'win'),
}


def window_of(username):
    if username in WINDOW_OVERRIDE:
        return WINDOW_OVERRIDE[username]
    labels = (profiles.get(username, {}) or {}).get('labels', [])
    for lab in labels:
        for key, cw in WINDOW_CHIP.items():
            if key in lab.lower():
                return cw
    return ('—', 'mid')


def traj_of(username):
    d = TRAJ_2028.get(username, 0)
    if d > 0:
        return ('Declining', 'reb')
    if d < 0:
        return ('Rising', 'rise')
    return ('Steady', 'mid')


def txn_summary(t):
    def nm(i): return pname(i)
    parts = []
    if t['type'] == 'trade':
        for rid in t['roster_ids']:
            got = [nm(k) for k, v in (t.get('adds') or {}).items() if v == rid]
            got += [f"{dp['season']} R{dp['round']} pick" for dp in (t.get('draft_picks') or []) if dp.get('owner_id') == rid]
            if got:
                parts.append(f"<b>{esc(team_name(rid))}</b> ← " + esc(', '.join(got[:4])))
        return ' · '.join(parts)
    add = ', '.join(nm(k) for k in (t.get('adds') or {}))
    drop = ', '.join(nm(k) for k in (t.get('drops') or {}))
    who = team_name(t['roster_ids'][0]) if t['roster_ids'] else '?'
    s = f"<b>{esc(who)}</b> "
    if add:
        s += '+' + esc(add) + ' '
    if drop:
        s += '−' + esc(drop)
    return s


# ============================ CSS (repo pine-green system) ===================
CSS = """
:root{--paper:#F2F4EF;--ink:#182420;--ink2:#4A5A52;--muted:#7A8880;--card:#FBFCFA;
--line:#DCE2DA;--track:#E6EBE3;--accent:#2F8F5B;--accent-ink:#1F6B43;--gold:#C89B3C;
--gold-bg:#F7EFDC;--good:#2F8F5B;--warn:#B07A18;--crit:#B34A33;--you-bg:#FBF3DF;--you-line:#C89B3C;}
@media(prefers-color-scheme:dark){:root{--paper:#141A16;--ink:#E7ECE7;--ink2:#A9B5AC;--muted:#7E8A81;
--card:#1B231E;--line:#2B352E;--track:#242E27;--accent:#43A473;--accent-ink:#5FBA8B;--gold:#B58936;
--gold-bg:#2A2415;--good:#43A473;--warn:#C99A3F;--crit:#C96A52;--you-bg:#262214;--you-line:#B58936;}}
:root[data-theme="light"]{--paper:#F2F4EF;--ink:#182420;--ink2:#4A5A52;--muted:#7A8880;--card:#FBFCFA;
--line:#DCE2DA;--track:#E6EBE3;--accent:#2F8F5B;--accent-ink:#1F6B43;--gold:#C89B3C;--gold-bg:#F7EFDC;
--good:#2F8F5B;--warn:#B07A18;--crit:#B34A33;--you-bg:#FBF3DF;--you-line:#C89B3C;}
:root[data-theme="dark"]{--paper:#141A16;--ink:#E7ECE7;--ink2:#A9B5AC;--muted:#7E8A81;--card:#1B231E;
--line:#2B352E;--track:#242E27;--accent:#43A473;--accent-ink:#5FBA8B;--gold:#B58936;--gold-bg:#2A2415;
--good:#43A473;--warn:#C99A3F;--crit:#C96A52;--you-bg:#262214;--you-line:#B58936;}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);margin:0;
font-family:'Avenir Next','Helvetica Neue',system-ui,sans-serif;font-size:15px;line-height:1.5;}
.wrap{max-width:1040px;margin:0 auto;padding:32px 20px 60px;display:flex;flex-direction:column;gap:32px}
.disp{font-family:'Avenir Next Condensed','Arial Narrow','Avenir Next',system-ui,sans-serif;
text-transform:uppercase;letter-spacing:.04em;font-weight:700}
.num{font-variant-numeric:tabular-nums;font-family:ui-monospace,'SF Mono',Menlo,monospace}
header{border-bottom:3px solid var(--ink);padding-bottom:18px}
.eyebrow{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent-ink);font-weight:600;margin-bottom:6px}
h1{margin:0 0 10px;font-size:clamp(28px,5vw,44px);line-height:1.02;text-wrap:balance}
.verdict{display:inline-flex;align-items:center;gap:8px;background:var(--you-bg);border:1px solid var(--you-line);
border-radius:999px;padding:5px 14px;font-weight:600;font-size:14px}
.verdict .dot{width:9px;height:9px;border-radius:50%;background:var(--gold)}
.sub{color:var(--ink2);margin-top:10px;max-width:70ch}
section{display:flex;flex-direction:column;gap:12px}
h2.disp{margin:0;font-size:20px;letter-spacing:.05em}
.kicker{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:600}
.lede{color:var(--ink2);margin:0;max-width:74ch;font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile.you{background:var(--you-bg);border-color:var(--you-line)}
.tile .v{font-size:26px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.tile .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-top:3px}
.tile .n{font-size:12.5px;color:var(--ink2);margin-top:5px}
.scroller{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;min-width:640px}
th{font-size:11.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);text-align:left;
padding:10px 12px;border-bottom:1px solid var(--line);font-weight:600}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr.you td{background:var(--you-bg)}
td.rk{font-weight:700;font-variant-numeric:tabular-nums;width:28px;color:var(--ink2)}
td.n{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.team{font-weight:600;white-space:nowrap}.team small{display:block;font-weight:400;color:var(--muted);font-size:12px}
.bar{display:flex;align-items:center;gap:8px;min-width:150px}
.bar .track{flex:1;height:9px;background:var(--track);border-radius:0 4px 4px 0;overflow:hidden}
.bar .fill{height:100%;background:var(--accent);border-radius:0 4px 4px 0}
tr.you .bar .fill{background:var(--gold)}
.pos{font-weight:700;font-size:12px;color:var(--muted);width:26px}
.chip{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
border-radius:999px;padding:2px 9px;border:1px solid var(--line);color:var(--ink2);white-space:nowrap}
.chip.win{border-color:var(--good);color:var(--good)}
.chip.rise{border-color:var(--accent-ink);color:var(--accent-ink)}
.chip.mid{border-color:var(--warn);color:var(--warn)}
.chip.reb{border-color:var(--crit);color:var(--crit)}
.chip.hole{border-color:var(--crit);color:var(--crit)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:20px}
/* grid and flex children default to min-width:auto, so a wide table inside a
   card refuses to shrink and pushes the whole PAGE sideways instead of
   scrolling inside its own .scroller. Every level has to opt out. */
.cols>*{min-width:0}
@media(max-width:820px){.cols{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;display:flex;flex-direction:column;gap:10px;min-width:0}
.card>*{min-width:0;max-width:100%}
.card h3{margin:0;font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:600}
.prow{display:grid;grid-template-columns:26px minmax(0,1fr) 34px 46px;gap:8px;align-items:center;font-size:13.5px;min-width:0}
.prow>span{min-width:0;overflow-wrap:anywhere}
.prow .age{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums;text-align:right}
.prow .vv{font-variant-numeric:tabular-nums;font-size:12.5px;color:var(--ink2);text-align:right}
.prow.hl{background:var(--you-bg);border-radius:6px;margin:0 -6px;padding:2px 6px}
.prow .chip{font-size:9.5px;padding:0 5px;margin-left:5px;vertical-align:1px;letter-spacing:.02em}
/* .bar carries min-width:150px for the wide standings table; inside a .prow
   grid cell that floor overflows the card and runs the fill over the label. */
.prow .bar{min-width:0}
.moves{display:flex;flex-direction:column;gap:10px}
.move{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:0 10px 10px 0;padding:12px 15px}
.move.sell{border-left-color:var(--warn)}.move.hold{border-left-color:var(--gold)}.move.buy{border-left-color:var(--good)}
.move h4{margin:0 0 4px;font-size:15px}
.move p{margin:0;color:var(--ink2);font-size:13.5px}
.move .tag{margin-top:7px;font-size:12px;color:var(--accent-ink);font-weight:600}
.feed{display:flex;flex-direction:column}
.feed .row{display:flex;gap:12px;padding:8px 0;border-bottom:1px dashed var(--line);font-size:13.5px;align-items:baseline}
.feed .row:last-child{border-bottom:none}
.feed .d{color:var(--muted);font-variant-numeric:tabular-nums;font-size:12px;white-space:nowrap;min-width:42px}
.feed .k{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);min-width:64px}
.trade{display:flex;flex-direction:column;gap:3px;padding:9px 0;border-bottom:1px dashed var(--line);font-size:13px}
.trade:last-child{border-bottom:none}
.trade .h{font-weight:600}.trade .h .amt{color:var(--good);font-variant-numeric:tabular-nums}
.trade .side{color:var(--ink2);font-size:12.5px}
.oboard{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(300px,100%),1fr));gap:12px}
.ocard{min-width:0}.ocard>*{min-width:0}
.ocard{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:13px 15px;display:flex;flex-direction:column;gap:7px}
.ocard.you{background:var(--you-bg);border-color:var(--you-line)}
.ocard .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.ocard .nm{font-weight:700;font-size:15px}.ocard .nm small{display:block;color:var(--muted);font-weight:400;font-size:11.5px}
.ocard .chips{display:flex;gap:5px;flex-wrap:wrap}
.ocard .read{font-size:12.5px;color:var(--ink2)}
.ocard .stat{font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums}
footer{color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:14px}
a{color:var(--accent-ink)}

.tiles .tile .v{font-size:24px}
.todo ul{margin:6px 0 0;padding-left:18px;display:grid;gap:4px;font-size:14px}
.race .rrow,.srow{display:grid;grid-template-columns:minmax(0,10em) minmax(0,1fr) 3.2em;gap:10px;align-items:center;padding:4px 0;font-size:13.5px}
.race .rrow.you{font-weight:700;background:var(--you-bg);border-radius:6px;padding:4px 6px}
.race .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.race .track,.srow .track{position:relative;height:14px;border-radius:7px;background:var(--track);overflow:hidden;display:block}
.race .fill,.srow .fill{display:block;height:100%;border-radius:7px}
.race .v,.srow .v{text-align:right;font-variant-numeric:tabular-nums}
.race .cut{border-top:2px dashed var(--ink2);margin:6px 0;font-size:11px;color:var(--muted);text-align:right;letter-spacing:.08em;text-transform:uppercase;padding-top:2px}
.srow{grid-template-columns:3em minmax(0,1fr) 3.2em}
.srow .pos{font-weight:700}
.srow .tick{position:absolute;top:-2px;bottom:-2px;width:3px;background:var(--ink);opacity:.7}
.srow .badge{color:var(--paper);font-weight:700;border-radius:999px;text-align:center;font-size:12.5px;padding:1px 0}
details.move{cursor:pointer}
details.move summary{list-style:none;font-weight:700;font-size:15px;display:flex;gap:8px;align-items:baseline}
details.move summary::-webkit-details-marker{display:none}
details.move summary::after{content:"+";margin-left:auto;color:var(--muted);font-weight:400}
details.move[open] summary::after{content:"–"}
details.move p{margin-top:8px}
.move .kind{font-size:11px;letter-spacing:.08em;text-transform:uppercase;padding:2px 7px;border-radius:999px;border:1px solid var(--line);color:var(--ink2);flex:none}
.move.buy .kind{color:var(--good);border-color:var(--good)} .move.sell .kind{color:var(--warn);border-color:var(--warn)}
details.read summary{cursor:pointer;color:var(--accent-ink);font-size:13px;font-weight:600}
details.read{font-size:13.5px;color:var(--ink2)}
.crow{display:grid;grid-template-columns:minmax(0,15em) minmax(0,1fr) 3.4em;gap:4px 10px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.crow:last-child{border-bottom:none}
.crow.you{background:var(--you-bg);border-radius:6px;padding:6px}
.crow .nm small{color:var(--muted)}
.crow .track{display:flex;height:12px;border-radius:6px;background:var(--track);overflow:hidden}
.crow .fill{display:block;height:100%}
.crow .ghost{display:block;height:100%;background:var(--line)}
.crow .v{text-align:right;font-variant-numeric:tabular-nums}
.crow .sig{grid-column:1/-1;font-size:12.5px;color:var(--ink2)}
@media(max-width:480px){.crow{grid-template-columns:1fr 3.4em}.crow .track{grid-column:1/-1;grid-row:2}}

@media(max-width:480px){.race .rrow{grid-template-columns:minmax(0,7.5em) minmax(0,1fr) 2.8em}}
"""


def _model_line(m):
    """Plain-English description of the live start/sit model (data/weekly_model.json picks it)."""
    base = "Sleeper's weekly projection" if m.startswith('sleeper') else "this season's form, anchored to Sleeper's projection"
    adds = {'': '', '+extremes': ', adjusted for the measured hit from extreme weather (wind 15+ mph, rain, snow, bitter cold) and backup-QB starts',
            '+conditions': ', adjusted by the measured effects of weather, rest, travel and backup QBs',
            '+all': ', adjusted by the measured effects of Vegas lines, matchup, weather, rest, travel and backup QBs'}
    tail = next((v for k, v in adds.items() if k and m.endswith(k)), '')
    how = ' (variant chosen by backtest on last season)' if tail or m == 'form' else ''
    return f'Projection = {base}{tail}{how}, then injury and practice reports.'


def bar(v, mx):
    pct = max(3, round(100 * v / mx)) if mx else 0
    return f'<div class="bar"><div class="track"><div class="fill" style="width:{pct}%"></div></div><span class="vv num">{round(v):,}</span></div>'


def _pos_strength():
    """Per position: each team's starter value (QB1, RB2, WR3, TE1)."""
    need = {p: n for p, n in LF.CORE.items() if n}
    out = {}
    for pos, n in need.items():
        vals = {}
        for rid in metrics:
            v = sorted((V(x) for x in (roster_of[rid].get('players') or []) if posn(x) == pos), reverse=True)
            vals[rid] = sum(v[:n])
        out[pos] = vals
    return out


def _odds():
    pth = os.path.join(ROOT, 'data', 'pick_odds.json')
    d = json.load(open(pth)) if os.path.exists(pth) else {}
    return ({int(k): v for k, v in (d.get('playoff') or {}).items()},
            {int(k): v for k, v in (d.get('pts_wk') or {}).items()})


def build():
    O = []
    O.append('<meta charset="utf-8">')
    O.append(f'<title>Dynasty Command Center — {esc(profiles.get(MY,{}).get("team",MY) or MY)}</title>')
    O.append(f'<style>{CSS}</style>')
    O.append('<div class="wrap">')

    # ---- header ----
    my = metrics[my_rid]
    O.append('<header>')
    O.append(f'<div class="eyebrow">{esc(LF.LEAGUE_NAME)} · Command Center</div>')
    _my_team = next(((u.get('metadata') or {}).get('team_name') or u.get('display_name')
                     for u in json.load(open(os.path.join(ROOT, 'data', latest, 'users.json'))) if u.get('display_name') == MY), MY)
    O.append(f'<h1 class="disp">{esc(_my_team.strip())}</h1>')   # the owner's own Sleeper team name — no hand-typed names
    cut = ('last playoff spot' if my_place == PLAYOFF_SPOTS else
           'in the playoffs' if my_place < PLAYOFF_SPOTS else 'misses the playoffs')
    podds, ppw = _odds()
    my_odds = podds.get(my_rid)
    O.append(f'<span class="verdict"><span class="dot"></span>{verdict}</span>')
    tiles = [(f'{wins}-{losses}', 'Record', SEASON_STATE),
             (f'{my_odds * 100:.0f}%' if my_odds is not None else '—', 'Playoff odds',
              f'{sorted(podds, key=lambda k: -podds[k]).index(my_rid) + 1}th best' if my_odds is not None else ''),
             (f'#{win_rank[my_rid]}', 'Win-now rank', 'starting lineup value'),
             (f'#{dyn_rank[my_rid]}', 'Dynasty rank', 'roster + picks'),
             (f'{ppw.get(my_rid, 0):.0f}', 'Pts / week', 'rest of season, projected'),
             (f'${faab_budget - faab_used}', 'FAAB left', '')]
    O.append('<div class="tiles" style="margin-top:14px">' + ''.join(
        f'<div class="tile"><div class="v">{esc(v)}</div><div class="l">{esc(l)}</div><div class="n">{esc(n)}</div></div>'
        for v, l, n in tiles) + '</div>')
    items = [x.strip() for x in OPEN_DECISIONS.split(' · ') if x.strip()]
    O.append('<div class="todo"><div class="kicker" style="margin-top:14px">On the clock</div><ul>' +
             ''.join(f'<li>{esc(x)}</li>' for x in items) + '</ul></div>')
    O.append(f'<p class="sub" style="font-size:12px;color:var(--muted)">Updated {LF.stamp()} from live league data · refreshed on every update</p>')
    _links = CFG.get('dashboard_links') or {}
    if _links:
        O.append('<nav style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">' + ''.join(
            f'<a href="{esc(u)}" style="font-size:13px;font-weight:600;color:var(--accent-ink);text-decoration:none;border:1px solid var(--line);'
            f'border-radius:999px;padding:4px 12px;background:var(--card)">{esc(n)}</a>' for n, u in _links.items() if n != 'Command Center') + '</nav>')
    O.append('</header>')

    # ---- this week: start/sit (ops/weekly.py) ----
    _wp = os.path.join(ROOT, 'data', 'weekly.json')
    if os.path.exists(_wp):
        wkj = json.load(open(_wp))
        t = (wkj.get('teams') or {}).get(str(my_rid))
        PL = wkj.get('players') or {}
        if t:
            gain = t['gain']
            head = (f'Start {", ".join(esc(PL[p]["name"]) for p in t["swap_in"])} over '
                    f'{", ".join(esc(PL[p]["name"]) for p in t["swap_out"])} (+{gain:.1f} pts)' if gain >= 2
                    else 'Lineup is set — no swap worth 2+ points' if gain < 0.5 else
                    f'Coin flip only (+{gain:.1f} pts) — leave it unless news breaks')
            O.append(f'<section><div class="kicker">Week {esc(wkj["week"])}</div><h2 class="disp">Start / Sit</h2>'
                     f'<p class="lede"><b>{head}.</b> {_model_line(wkj["model"])} Updated {esc(wkj["generated"])}.</p><div class="card">')
            for pl_ in t.get('gametime_plans') or []:
                x_ = PL[pl_['pid']]
                fb = PL[pl_['fallback']]['name'] if pl_.get('fallback') else None
                O.append(f'<p class="lede" style="margin-top:-4px">⏱ <b>{esc(x_["name"])}</b> plays {pl_["p_play"]:.0%} of the time with this '
                         f'status and practice level. ' + (f'Keep him in; if he is inactive (about 90 min before his {esc(pl_["lock"])} kickoff), '
                         f'swap in <b>{esc(fb)}</b>.' if fb else f'No later-kickoff fallback on the bench, so his projection is discounted to '
                         f'{x_["proj"] * pl_["p_play"]:.1f}.') + '</p>')
            mx = max([PL[p]['proj'] for p in t['best'] + t['set']] + [1])
            bench = sorted((p for p in PL if PL[p]['roster_id'] == my_rid and p not in t['best']),
                           key=lambda p: -PL[p]['proj'])[:5]
            for grp, ids in (('Best lineup', t['best']), ('Bench', bench)):
                O.append(f'<div class="kicker" style="margin:8px 0 2px">{grp}</div>')
                for p in sorted(ids, key=lambda p: (['QB', 'RB', 'WR', 'TE'].index(PL[p]['pos']), -PL[p]['proj'])):
                    x = PL[p]
                    adj = [f'{k} {v["bucket"]} ×{v["mult"]:.2f}' for k, v in (x.get('adjustments') or {}).items()]
                    sig = ' · '.join(x.get('flags', []) + adj)
                    col = 'crit' if x['proj'] == 0 else 'warn' if x.get('flags') else 'good'
                    mark = ' you' if p in t['swap_in'] else ''
                    O.append(f'<div class="crow{mark}"><span class="nm"><b>{esc(x["name"])}</b> <small>{esc(x["pos"])} · '
                             f'{esc(x.get("team") or "")} vs {esc(x.get("opp") or "—")} · {esc(x.get("kickoff") or "")}'
                             f'{" · imp " + str(x["implied_pts"]) if x.get("implied_pts") else ""}</small></span>'
                             f'<span class="track"><span class="fill" style="width:{100 * x["proj"] / mx:.0f}%;background:var(--{col})"></span></span>'
                             f'<span class="v num">{x["proj"]:.1f}</span>'
                             + (f'<span class="sig">{esc(sig)}</span>' if sig else '') + '</div>')
            O.append('</div></section>')

    # ---- playoff race (chart) ----
    if podds:
        order = sorted(podds, key=lambda k: -podds[k])
        O.append('<section><div class="kicker">This season</div><h2 class="disp">Playoff Race</h2>'
                 '<p class="lede">Chance to finish top 6, from 6,000 simulated seasons. The line is the playoff cut.</p><div class="card race">')
        for i, rid in enumerate(order):
            pct = podds[rid] * 100
            cls = ' you' if rid == my_rid else ''
            col = 'good' if pct >= 60 else 'warn' if pct >= 20 else 'crit'
            O.append(f'<div class="rrow{cls}"><span class="nm">{esc(team_name(rid))}</span>'
                     f'<span class="track"><span class="fill" style="width:{max(1.5, pct):.1f}%;background:var(--{col})"></span></span>'
                     f'<span class="v num">{pct:.0f}%</span></div>')
            if i == PLAYOFF_SPOTS - 1:
                O.append('<div class="cut">playoff line</div>')
        O.append('</div></section>')

    # ---- our projections (ops/our_projections.py) — independent of Sleeper ----
    _op = os.path.join(ROOT, 'data', 'our_projection.json')
    if os.path.exists(_op):
        opj = json.load(open(_op))
        mdl, tms = opj.get('model') or {}, opj.get('teams') or {}
        order_ = sorted(tms, key=lambda k: tms[k]['exp_place'])
        _bt = mdl.get('blend_test') or {}
        O.append('<section><div class="kicker">Our model</div><h2 class="disp">Our Projections vs Sleeper</h2>'
                 f'<p class="lede">Our model (recent form, targets/carries/attempts priced at measured rates, last season, Vegas lines, '
                 f'extreme weather, backup QBs and injuries) blended with Sleeper\'s projections where the mix tested better. On 2025 '
                 f'weeks it never saw: blend {_bt.get("blend", "—")} points of error per player-week, ours {_bt.get("ours", "—")}, '
                 f'Sleeper {_bt.get("sleeper", "—")} (weights per position: {", ".join(f"{k} {round(v * 100)}% ours" for k, v in (mdl.get("blend") or {}).items())}). '
                 f'Bar = blended playoff odds; the tick marks Sleeper-only odds.</p><div class="card race">')
        for k in order_:
            t = tms[k]
            pct, sp = t['playoff'] * 100, (t.get('sleeper_playoff') or 0) * 100
            col = 'good' if pct >= 60 else 'warn' if pct >= 20 else 'crit'
            you = ' you' if t['owner'] == MY else ''
            O.append(f'<div class="rrow{you}"><span class="nm">{esc(t["owner"])} <small style="color:var(--muted)">{esc(t["record"])} · '
                     f'{t["pts_wk"]:.0f}/wk · {t["exp_wins"]:.1f} W</small></span>'
                     f'<span class="track" style="position:relative"><span class="fill" style="width:{max(1.5, pct):.1f}%;background:var(--{col})"></span>'
                     f'<span style="position:absolute;top:-2px;bottom:-2px;left:{sp:.1f}%;width:2px;background:var(--ink)"></span></span>'
                     f'<span class="v num">{pct:.0f}%</span></div>')
        O.append('</div>')
        _pj = os.path.join(ROOT, 'data', 'projection.json')
        slw = json.load(open(_pj))['player_weekly'] if os.path.exists(_pj) else {}
        wks_ = opj.get('weeks') or []
        rng = range(wks_[0], wks_[1] + 1) if wks_ else range(0)
        my_ids = next((r['players'] for r in rosters if r['roster_id'] == my_rid), []) or []
        rows_ = []
        for pid in my_ids:
            x = (opj.get('players') or {}).get(pid)
            if not x:
                continue
            ours_ = [v for w, v in x['weekly'].items() if v > 0]
            slv = [v for w, v in (slw.get(pid) or {}).items() if int(w) in rng and v > 0]
            if ours_ or slv:
                rows_.append((x['name'], x['pos'], sum(ours_) / len(ours_) if ours_ else 0, sum(slv) / len(slv) if slv else 0))
        rows_.sort(key=lambda r: -r[2])
        if rows_:
            O.append('<div class="card"><h3>Your players — our points per game vs Sleeper\'s</h3>'
                     '<div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">Rest of the regular season, games played only. '
                     'Big gaps are where our data sees something Sleeper doesn\'t (or the reverse).</div>')
            for nm_, pos_, o_, s_ in rows_[:14]:
                d_ = o_ - s_
                c_ = 'var(--good)' if d_ >= 1 else 'var(--crit)' if d_ <= -1 else 'var(--ink2)'
                O.append(f'<div class="prow"><span class="pos">{esc(pos_)}</span><span>{esc(nm_)}</span>'
                         f'<span class="age">{s_:.1f}</span><span class="vv num" style="color:{c_}">{o_:.1f}</span></div>')
            O.append('<div style="font-size:11px;color:var(--muted)">grey = Sleeper · right = ours</div></div>')
        O.append('</section>')

    # ---- lottery tracker (ops/lottery_tracker.py) ----
    _lh = os.path.join(ROOT, 'data', 'lottery_history.json')
    if os.path.exists(_lh):
        lh = json.load(open(_lh))
        snaps = lh.get('snapshots') or []
        if snaps:
            cur, prv = snaps[-1]['teams'], (snaps[-2]['teams'] if len(snaps) > 1 else {})
            order_ = sorted(cur, key=lambda k: cur[k]['exp_slot'])
            O.append(f'<section><div class="kicker">{esc(lh["season"])} rookie draft</div><h2 class="disp">Lottery Tracker</h2>'
                     f'<p class="lede">Each team\'s next 1st, by original owner. Bar = chance it lands top 3; the line under it says who owns it now '
                     f'and what it is worth. Arrows compare with the previous snapshot ({len(snaps)} so far, one per day the update runs).</p><div class="card">')
            for k in order_:
                t = cur[k]
                p = prv.get(k)
                d = (t['p_top3'] - p['p_top3']) if p else 0
                arrow = '' if not p or abs(d) < 0.02 else (f' ▲{d * 100:.0f}' if d > 0 else f' ▼{-d * 100:.0f}')
                you = ' you' if t['r1']['owner'] == MY or t['team'] == MY else ''
                col = 'crit' if t['p_top3'] >= 0.5 else 'warn' if t['p_top3'] >= 0.15 else 'good'
                O.append(f'<div class="crow{you}"><span class="nm"><b>{esc(t["team"])}</b> <small>{esc(t["record"])} · Max PF {t["max_pf"]:.0f} · '
                         f'playoffs {t["playoff"]:.0%}</small></span>'
                         f'<span class="track"><span class="fill" style="width:{max(1.5, t["p_top3"] * 100):.0f}%;background:var(--{col})"></span></span>'
                         f'<span class="v num">{t["p_top3"]:.0%}{esc(arrow)}</span>'
                         f'<span class="sig">#1 pick {t["p_1"]:.0%} · expected slot {t["exp_slot"]:.1f} · 1st owned by <b>{esc(t["r1"]["owner"])}</b> '
                         f'(worth {t["r1"]["value"]:,}) · 2nd owned by {esc(t.get("r2", {}).get("owner", "—"))}</span></div>')
            O.append('</div></section>')

    # ---- edge finder: trade finder, waivers, injuries, market movers (2026-10-02) ----
    def _j(name):
        p_ = os.path.join(ROOT, 'data', name)
        return json.load(open(p_)) if os.path.exists(p_) else None
    tf, wv, io, vt = _j('trade_finder.json'), _j('waivers.json'), _j('injury_outlook.json'), _j('value_trends.json')
    if tf and tf.get('best_by_partner'):
        O.append('<section><div class="kicker">Edge finder</div><h2 class="disp">Trade Finder</h2>'
                 f'<p class="lede">The best offer to each owner, tested on both schedules: expected wins it adds for you over the rest '
                 f'of the season (now {tf["base_wins"]:.1f}), and the reason the other owner says yes; a second list ranks offers for your long-term plan. Core players are left out here; '
                 'they only move for a king\'s ransom (below).</p><div class="card">')
        for o in tf['best_by_partner'][:8]:
            O.append(f'<div class="crow"><span class="nm"><b>{esc(o["get_label"])}</b> <small>{esc(o["get_pos"])} from @{esc(o["partner"])} '
                     f'({o["playoff"]:.0%} playoffs)</small></span>'
                     f'<span class="track"><span class="fill" style="width:{min(100, o["my_wins"] * 100):.0f}%;background:var(--good)"></span></span>'
                     f'<span class="v num">+{o["my_wins"]:.2f}</span>'
                     f'<span class="sig">Give {esc(" + ".join(o["give_labels"]))} · your value {o["my_value"]:+,} · theirs {o["their_value"]:+,}'
                     f'{" · they must drop one" if o["they_must_drop"] else ""}</span></div>')
        bd = tf.get('best_by_partner_dynasty') or []
        if bd:
            O.append('<div class="card"><h3>Best for the long-term plan (' + esc((lambda: (json.load(open(os.path.join(ROOT, 'my_plan.json'))).get('name') if os.path.exists(os.path.join(ROOT, 'my_plan.json')) else None) or 'your long-term plan')()) + ')</h3><div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                     'Dynasty value = market value across 2026-28 aged with our age curves, plus plan bonuses (spend 2027 picks, keep 2028 picks, '
                     'fill RB2/TE now, add a WR 25 or younger). Season can\'t drop more than 0.2 wins.</div>')
            for o in bd[:8]:
                O.append(f'<div class="prow"><span class="pos">{esc(o["get_pos"])}</span><span><b>{esc(o["get_label"])}</b> ← @{esc(o["partner"])}: give '
                         f'{esc(" + ".join(o["give_labels"]))} <small style="color:var(--muted)">season {o["my_wins"]:+.2f} W</small></span>'
                         f'<span class="age"></span><span class="vv num" style="color:var(--good)">{o["dyn"]:+,}</span></div>')
            O.append('</div>')
        rs = tf.get('ransom') or []
        if rs:
            O.append('<div class="card"><h3>King\'s ransom: what the core would cost</h3><div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                     'Rule: the evaluation must favor you by +3,000 or more on market value. The cheapest qualifying package per team, '
                     'the two likeliest shown.</div>')
            for a in dict.fromkeys(x['asset'] for x in rs):
                rr = [x for x in rs if x['asset'] == a][:2]
                for x in rr:
                    O.append(f'<div class="prow"><span class="pos"></span><span><b>{esc(x["asset_label"])}</b> ← @{esc(x["partner"])}: '
                             f'{esc(" + ".join(x["get_labels"]))} <small style="color:var(--muted)">value back {x["value_back"]:,} · '
                             f'your wins {x["my_wins"]:+.2f}</small></span><span class="age"></span><span class="vv num">{x["their_overpay"]:+,}</span></div>')
            O.append('</div>')
        O.append('</div></section>')
    # news radar + data check (added 2026-10-04: always work off the most current information)
    _nw = json.load(open(os.path.join(ROOT, 'data', 'news.json'))) if os.path.exists(os.path.join(ROOT, 'data', 'news.json')) else None
    _fr = json.load(open(os.path.join(ROOT, 'data', 'freshness.json'))) if os.path.exists(os.path.join(ROOT, 'data', 'freshness.json')) else None
    if _nw or _fr:
        O.append('<section><div class="kicker">Current as of now</div><h2 class="disp">News &amp; Data Check</h2><div class="cols">')
        if _nw:
            _seen, _rows = set(), []
            for a in _nw['alerts']:                       # newest story per player and kind
                if (a['pid'], a['kind']) not in _seen:
                    _seen.add((a['pid'], a['kind'])); _rows.append(a)
            O.append('<div class="card"><h3>News radar · last 72 hours</h3><div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                     'ESPN stories and official transactions on your players and your trade-plan targets: injury, suspension, contract, role and roster moves. '
                     f'{_nw["stories_in_log"]} stories in the 21-day log, refreshed {esc(_nw["generated"])}.</div>')
            for a in _rows[:10]:
                O.append(f'<div class="prow"><span class="pos">{esc({"injury": "INJ", "suspension": "SUS", "contract": "CTR", "role": "ROL", "transaction": "TXN"}.get(a["kind"], ""))}</span><span><b>{esc(a["player"])}</b>'
                         f'{"" if a["mine"] else " <small style=" + chr(34) + "color:var(--muted)" + chr(34) + ">(@" + esc(a["owner"]) + ")</small>"} '
                         f'<a href="{esc(a["url"])}" target="_blank" rel="noopener" style="color:inherit">{esc(a["headline"])}</a></span>'
                         f'<span class="age"></span><span class="vv num">{a["hours_ago"]:.0f}h</span></div>')
            if not _rows:
                O.append('<div style="font-size:12px;color:var(--muted)">No injury, suspension, contract or role news on your players or targets in 72 hours.</div>')
            O.append('</div>')
        if _fr:
            _bad = [c for c in _fr['checks'] if c['status'] != 'ok']
            O.append(f'<div class="card"><h3>Data check · {len(_fr["checks"]) - len(_bad)} of {len(_fr["checks"])} current</h3>'
                     '<div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">Each source checked for what it contains, not just when it was '
                     f'downloaded. Checked {esc(_fr["generated"])}.</div>')
            for c in sorted(_fr['checks'], key=lambda c: c['status'] == 'ok'):
                O.append(f'<div class="prow"><span class="pos">{"OK" if c["status"] == "ok" else "⚠"}</span><span>{esc(c["source"])} '
                         f'<small style="color:var(--muted)">{esc(c["detail"])}{(" · fix: " + esc(c["fix"])) if c["status"] != "ok" and c.get("fix") else ""}'
                         '</small></span><span class="age"></span><span class="vv num"></span></div>')
            O.append('</div>')
        O.append('</div></section>')
    if wv or io or vt:
        O.append('<section><div class="kicker">Edge finder</div><h2 class="disp">Waivers, Injuries &amp; Market Movers</h2><div class="cols">')
        if wv:
            fa = wv['faab']
            O.append(f'<div class="card"><h3>Waivers · ${wv["budget_left"]} FAAB left</h3>'
                     f'<div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">This league\'s winning bids: median ${fa["median"]}, '
                     f'top quarter ${fa["p75"]}+, top 10% ${fa["p90"]}+ (n={fa["n"]}).</div>')
            rows_ = [(x, 'starts') for x in wv['start'][:4]] + [(x, 'rising') for x in wv['rising'][:5]]
            for x, why in rows_:
                tag = f'+{x["gain"]}/wk' if why == 'starts' else f'RZ {x["rz"]:.0%} · tgt {(x["tgt_share"] or 0):.0%}'
                O.append(f'<div class="prow"><span class="pos">{esc(x["pos"])}</span><span>{esc(x["name"])} '
                         f'<small style="color:var(--muted)">{esc(x["team"])} · {tag}</small></span><span class="age">{x["ros"]}</span>'
                         f'<span class="vv num">${x["bid"]}</span></div>')
            if not wv['start']:
                O.append('<div style="font-size:12px;color:var(--muted)">No free agent would start for you right now.</div>')
            O.append('</div>')
        if io:
            mine_ = [x for x in io['players'] if x['owner'] == MY][:6]
            sig_ = [x for x in io['players'] if x.get('signal')][:3]
            O.append('<div class="card"><h3>Injury outlook</h3><div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                     'Measured on 2015-2025: game-day odds by practice status; games missed by injury type.</div>')
            for x in mine_ + [s for s in sig_ if s not in mine_]:
                O.append(f'<div class="prow"><span class="pos">{esc(x["pos"])}</span><span>{esc(x["name"])} '
                         f'<small style="color:var(--muted)">{esc(x["status"])} · {esc(x["injury"])} — {esc(x.get("read", ""))}'
                         f'{" · " + esc(x["signal"]) if x.get("signal") else ""}</small></span><span class="age"></span>'
                         f'<span class="vv num">{x["value"]:,}</span></div>')
            O.append('</div>')
        if vt and vt.get('movers'):
            mv_ = [m for m in vt['movers'] if m['owner'] == MY][:4] + [m for m in vt['movers'] if m['owner'] != MY][:6]
            pc = lambda v: '—' if v is None else f'{v:+.0%}'
            O.append(f'<div class="card"><h3>Market movers</h3><div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                     f'Market value vs {esc(vt.get("ref_7d") or "—")} (7d) and {esc(vt.get("ref_30d") or "—")} (30d).</div>')
            long_out = {x['pid']: x for x in (io or {}).get('players', [])
                        if (x.get('season_share_lost') or 0) >= 0.5 or 'season-ending' in (x.get('read') or '')}
            for m in mv_:
                if m['pid'] in long_out and m['tag'] == 'crashing':
                    m = dict(m, action='falling on a long injury (see Injury outlook), so the drop is priced in, not a bargain')
                col = 'var(--good)' if m['tag'] == 'rising' else 'var(--crit)'
                O.append(f'<div class="prow"><span class="pos">{esc(m["pos"])}</span><span>{esc(m["name"])} '
                         f'<small style="color:var(--muted)">@{esc(m["owner"])} · {esc(m["action"])}</small></span>'
                         f'<span class="age" style="color:{col}">{pc(m["w"])}</span><span class="vv num" style="color:{col}">{pc(m["m"])}</span></div>')
            O.append('</div>')
        O.append('</div></section>')

    # ---- where my starters stand (chart) ----
    ps = _pos_strength()
    O.append('<section><div class="kicker">My lineup</div><h2 class="disp">Starters vs the League</h2>'
             '<p class="lede">Value of your starters at each position. The tick marks the league average; the badge is your rank of ' + str(LF.NUM_TEAMS) + '.</p><div class="card">')
    for pos in ('QB', 'RB', 'WR', 'TE'):
        vals = ps[pos]; mx = max(vals.values()) or 1; avg = sum(vals.values()) / len(vals)
        rk = sorted(vals, key=lambda k: -vals[k]).index(my_rid) + 1
        col = 'good' if rk <= 4 else 'warn' if rk <= 8 else 'crit'
        O.append(f'<div class="srow"><span class="pos">{pos}</span>'
                 f'<span class="track"><span class="fill" style="width:{100 * vals[my_rid] / mx:.0f}%;background:var(--{col})"></span>'
                 f'<span class="tick" style="left:{100 * avg / mx:.0f}%"></span></span>'
                 f'<span class="badge" style="background:var(--{col})">#{rk}</span></div>')
    O.append('</div></section>')

    # ---- power rankings ----
    mxT = max(m['total'] for m in metrics.values())
    O.append('<section><div class="kicker">Standings</div><h2 class="disp">Power Rankings</h2>')
    O.append('<p class="lede"><b>Win-now</b> = best starting lineup value (this season). <b>Dynasty</b> = roster + future picks (tier-valued). Sorted by dynasty.</p>')
    O.append('<div class="scroller"><table><thead><tr><th>#</th><th>Team</th><th style="text-align:right">Win-now</th><th style="text-align:right">Roster</th><th style="text-align:right">Picks</th><th>Dynasty total</th></tr></thead><tbody>')
    for rid in sorted(metrics, key=lambda k: -metrics[k]['total']):
        m = metrics[rid]
        you = ' class="you"' if rid == my_rid else ''
        O.append(f'<tr{you}><td class="rk">{dyn_rank[rid]}</td>'
                 f'<td class="team">{esc(team_name(rid))}<small>win-now #{win_rank[rid]}</small></td>'
                 f'<td class="n">{round(m["starters"]):,}</td><td class="n">{round(m["roster"]):,}</td>'
                 f'<td class="n">{round(m["picks"]):,}</td><td>{bar(m["total"], mxT)}</td></tr>')
    O.append('</tbody></table></div></section>')

    # ---- my team + actions ----
    O.append('<section><div class="kicker">My franchise</div><h2 class="disp">My Team &amp; Moves</h2>')
    O.append('<div class="cols">')
    # roster card
    O.append('<div class="card"><h3>Roster by value</h3>')
    _, lineup = optimal(me.get('players') or [])
    start_set = set(lineup)
    mxv = V(my_players[0]) if my_players else 1
    for pid in my_players[:16]:
        hl = ' hl' if pid in start_set else ''
        O.append(f'<div class="prow{hl}"><span class="pos">{esc(posn(pid))}</span>'
                 f'<span>{esc(pname(pid))}{risk_chips(pid)}</span>'
                 f'<span class="age">{esc(page(pid))}</span>'
                 f'<span class="vv num">{round(V(pid)):,}</span></div>')
    # picks
    picklist = sorted(OWNED.get(my_rid, []))
    pv = [(f"{s} {pick_value(s, rnd, orig)[1]} {PK._RN[rnd]}", pick_value(s, rnd, orig)[0]) for s, rnd, orig in picklist]
    mxp = max([v for _, v in pv] or [1])
    O.append('<h3 style="margin-top:14px">Picks</h3>')
    for lab, v in pv:
        O.append(f'<div class="srow"><span class="pos" style="width:auto;min-width:8.5em">{esc(lab)}</span>'
                 f'<span class="track"><span class="fill" style="width:{100 * v / mxp:.0f}%;background:var(--gold)"></span></span>'
                 f'<span class="v num">{round(v):,}</span></div>')
    O.append('</div>')
    # actions card
    O.append('<div class="moves">')
    for kind, title, body, tag in MY_ACTIONS:
        O.append(f'<details class="move {kind}"><summary><span class="kind">{esc(KIND_LABEL.get(kind, kind))}</span>{esc(title)}</summary>'
                 f'<p>{esc(body)}</p><div class="tag">{esc(tag)}</div></details>')
    O.append('</div></div></section>')

    # ---- availability / contract / handcuff context ----
    # Facts the consensus value does not carry. Kept as its own section because
    # it answers a different question: not "what is he worth" but "can he play,
    # is he leaving, and who inherits the job".
    if context:
        owner_of = {pid: rid for rid, r in
                    ((r['roster_id'], r) for r in rosters)
                    for pid in (r.get('players') or [])}
        hurt, walk, hcs = [], [], []
        for pid in my_players:
            c = context.get(pid)
            if not c:
                continue
            if c.get('avail') not in (None, 'OK'):
                inj = c.get('injury') or {}
                detail = ' · '.join(x for x in (inj.get('body_part'),
                                                inj.get('notes')) if x)
                hurt.append((c['avail'], pname(pid), posn(pid), detail, V(pid)))
            ct = cons.get(str(pid), {}).get('contract') or {}
            if ct.get('class') in ('rookie_deal', 'veteran'):
                walk.append((V(pid), pname(pid), posn(pid), page(pid), ct,
                             cons[str(pid)].get('mean_market', V(pid))))
            h = (c.get('handcuff') or {}).get('handcuff')
            if h and posn(pid) in ('RB', 'QB', 'TE') and V(pid) >= 1200:
                hcs.append((V(pid), pname(pid), pname(h), owner_of.get(h)))
        O.append('<section><div class="kicker">Context</div>'
                 '<h2 class="disp">Availability, Contracts &amp; Handcuffs</h2>')
        O.append('<p class="lede">Who can\'t play, who is in a contract year, and who backs up your starters.</p>')
        O.append('<div class="cols">')
        O.append('<div class="card"><h3>Not fully available</h3>')
        if hurt:
            for a, n, ps, d, v in sorted(hurt, key=lambda x: -x[4]):
                det = f'<small style="color:var(--muted)"> {esc(d)}</small>' if d else ''
                O.append(f'<div class="prow"><span class="pos">{esc(ps)}</span>'
                         f'<span>{esc(n)}<span class="chip '
                         f'{AVAIL_CLASS.get(a, "mid")}">{esc(a)}</span>{det}</span>'
                         f'<span class="age"></span>'
                         f'<span class="vv num">{round(v):,}</span></div>')
        else:
            O.append('<div class="prow"><span></span><span>Everyone is clear.</span></div>')
        O.append('</div>')
        O.append('<div class="card"><h3>Last year of the deal</h3>')
        if walk:
            for v, n, ps, ag, ct, mk in sorted(walk, key=lambda x: -x[0]):
                lab = 'rookie deal' if ct['class'] == 'rookie_deal' else 'veteran'
                O.append(f'<div class="prow"><span class="pos">{esc(ps)}</span>'
                         f'<span>{esc(n)} <small style="color:var(--muted)">'
                         f'{lab} · FA {ct.get("fa_year")} · value {round(mk):,} → {round(v):,}</small></span>'
                         f'<span class="age">{esc(ag)}</span>'
                         f'<span class="vv num">−{round((1 - ct.get("mult", 1)) * 100)}%</span></div>')
            O.append('<div style="font-size:12px;color:var(--muted);margin-top:4px">'
                     'Measured on 2018-21 seasons: contract-year players kept 63% of production the next year '
                     'vs 83% for others. Only future seasons are discounted; this season counts in full.</div>')
        else:
            O.append('<div class="prow"><span></span><span>No walk years on the roster.</span></div>')
        O.append('</div></div>')
        # playoff SOS + bye stacking: both knowable today, both decide games
        sos = sorted(((c['sos']['mean_rank'], pid, c['sos'])
                      for pid, c in ((q, context.get(q) or {}) for q in my_players)
                      if c.get('sos') and V(pid) >= 1400))
        byes = {}
        for pid in my_players:
            b = (context.get(pid) or {}).get('bye')
            if b and V(pid) >= 1000:
                byes.setdefault(b, []).append(pid)
        stack = {w: v for w, v in byes.items() if len(v) >= 2}
        if sos or stack:
            O.append('<div class="cols">')
            if sos:
                wks = ', '.join(str(x['wk']) for x in sos[0][2]['weeks'])
                O.append(f'<div class="card"><h3>Fantasy-playoff draw · weeks {wks}</h3>'
                         '<div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                         'Opponent defence at his position, out of 32, on PPR allowed '
                         'per game. <b>#1 = softest</b>, #32 = toughest.</div>')
                for mr, pid, sd in sos:
                    det = ' · '.join(f"wk{x['wk']} {x['opp']} #{x['rank']}"
                                     for x in sd['weeks'])
                    cls = 'good' if mr <= 12 else 'crit' if mr >= 22 else 'ink2'
                    O.append(f'<div class="prow"><span class="pos">{esc(posn(pid))}</span>'
                             f'<span>{esc(pname(pid))} <small style="color:var(--muted)">'
                             f'{esc(det)}</small></span><span class="age"></span>'
                             f'<span class="vv num" style="color:var(--{cls})">'
                             f'#{mr}</span></div>')
                O.append('</div>')
            if stack:
                O.append('<div class="card"><h3>Bye-week stacking</h3>'
                         '<div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                         'Assets worth 1,000+ sharing a bye. A knowable hole, months out.'
                         '</div>')
                for w in sorted(stack):
                    who = ', '.join(pname(q) for q in
                                    sorted(stack[w], key=lambda x: -V(x)))
                    O.append(f'<div class="prow"><span class="pos">W{w}</span>'
                             f'<span>{esc(who)}</span><span class="age"></span>'
                             f'<span class="vv num">{len(stack[w])}</span></div>')
                O.append('</div>')
            O.append('</div>')
        if hcs:
            O.append('<div class="card"><h3>Handcuffs on my key men</h3>')
            for v, n, hn, rid in sorted(hcs, reverse=True):
                who = ('<b>mine</b>' if rid == my_rid else
                       esc(team_name(rid)) if rid else '<b>free agent</b>')
                O.append(f'<div class="prow"><span class="pos"></span>'
                         f'<span>{esc(n)} <small style="color:var(--muted)">→ '
                         f'{esc(hn)}</small></span><span class="age"></span>'
                         f'<span class="vv" style="text-align:right">{who}</span></div>')
            O.append('</div>')
        # role check — usage leads value
        role = sorted(((V(pid), pid, usage[pid]) for pid in my_players
                       if usage.get(pid) and V(pid) >= 1000), reverse=True)
        if role:
            O.append(f'<div class="card"><h3>Role check — snap &amp; target share '
                     f'({role[0][2]["season"]})</h3>'
                     '<div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                     'Usage moves before value does. High value on a falling snap share '
                     'is the sell the market has not made yet.</div>'
                     '<div class="scroller" style="border:none"><table style="min-width:0">'
                     '<thead><tr><th>Player</th><th style="text-align:right">Snap</th>'
                     '<th style="text-align:right">Tgt</th>'
                     '<th style="text-align:right">Air yds</th>'
                     '<th style="text-align:right">PPR/gm</th></tr></thead><tbody>')
            for v, pid, u in role:
                ps = posn(pid)
                pc = lambda x: f'{x * 100:.0f}%' if x is not None else '—'
                ts = pc(u['target_share']) if ps != 'QB' else '—'
                ay = pc(u['air_yards_share']) if ps in ('WR', 'TE') else '—'
                O.append(f'<tr><td class="team">{esc(pname(pid))}'
                         f'<small>{esc(ps)}</small></td>'
                         f'<td class="n">{pc(u["snap_pct"])}</td>'
                         f'<td class="n">{ts}</td><td class="n">{ay}</td>'
                         f'<td class="n">{u["ppr_ppg"]:.1f}</td></tr>')
            O.append('</tbody></table></div></div>')
        O.append('</section>')

    # ---- contract calendar (league-wide; ops/contracts.py) ----
    _cp = os.path.join(ROOT, 'data', 'contract_calendar.json')
    if os.path.exists(_cp):
        cc = json.load(open(_cp))
        rows_ = [x for x in cc['players'] if x.get('owner')][:16]
        if rows_:
            mx = max(x['market'] for x in rows_)
            O.append('<section><div class="kicker">Contracts</div><h2 class="disp">Contract Calendar</h2>'
                     f'<p class="lede">Players worth 800+ whose NFL contract ends after this season. Bar = market value; '
                     f'the solid part is what is left after the measured contract-year cut. '
                     f'Key dates: trade deadline week {esc(cc.get("trade_deadline_week") or "—")} · {esc(cc.get("free_agency", ""))}.</p>'
                     '<div class="card">')
            for x in rows_:
                you = ' you' if x['owner'] == MY else ''
                col = 'warn' if x['class'] == 'veteran' else 'accent'
                O.append(f'<div class="crow{you}"><span class="nm"><b>{esc(x["name"])}</b> <small>{esc(x["pos"])} {esc(x["age"])} · '
                         f'{"rookie deal" if x["class"] == "rookie_deal" else "veteran"} · @{esc(x["owner"])}</small></span>'
                         f'<span class="track"><span class="fill" style="width:{100 * x["adjusted"] / mx:.0f}%;background:var(--{col})"></span>'
                         f'<span class="ghost" style="width:{100 * (x["market"] - x["adjusted"]) / mx:.0f}%"></span></span>'
                         f'<span class="v num">−{round((1 - x["mult"]) * 100)}%</span>'
                         f'<span class="sig">{esc(x["signal"])}</span></div>')
            O.append('</div>')
            cuts_ = [x for x in cc.get('cut_risk', []) if x.get('owner')][:10]
            if cuts_:
                O.append(f'<div class="card" style="margin-top:16px"><h3>Cut risk next offseason</h3>'
                         f'<div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">Signed past this season, but cheap to release: '
                         f'what a cut before June 1 saves the team vs leaves as dead money ({esc(cc.get("cut_risk_note", ""))}). '
                         'Veterans here can lose their job and their value together.</div>')
                for x in cuts_:
                    O.append(f'<div class="prow"><span class="pos">{esc(x["pos"])}</span><span><b>{esc(x["name"])}</b> '
                             f'<small style="color:var(--muted)">{esc(x["age"])} · {esc(x["team"])} · @{esc(x["owner"])} · {esc(x["signal"])}</small></span>'
                             f'<span class="age"></span><span class="vv num">{x["market"]:,}</span></div>')
                O.append('</div>')
            O.append('</section>')

    # ---- under the hood: tracking data (ops/ngs.py) — only metrics that passed the held-out test move anything ----
    _ng = json.load(open(os.path.join(ROOT, 'data', 'ngs.json'))) if os.path.exists(os.path.join(ROOT, 'data', 'ngs.json')) else None
    if _ng and _ng.get('players'):
        _kept = [(k, 'rest of season', e) for k, e in _ng['evaluation'].items() if e['use']] + \
                [(k, 'next season', e) for k, e in _ng.get('evaluation_next_season', {}).items() if e['use']]
        _lab = {'air_yards_share': 'share of team air yards', 'yac_over_exp': 'yards after catch over expected',
                'separation': 'separation', 'ryoe_per_att': 'rush yards over expected', 'cpoe': 'completion % over expected',
                'time_to_throw': 'time to throw'}
        O.append('<section><div class="kicker">Under the hood</div><h2 class="disp">Tracking Data: Better or Worse Than the Box Score</h2>'
                 '<p class="lede">The NFL\'s player-tracking numbers, tested before trusted: each was checked on 2019-2025 seasons it had '
                 'never seen, and only these beat points alone — '
                 + '; '.join(f'{esc(_lab.get(k.split("|")[0], k))} for {k.split("|")[1]}s ({h}, {e["gain_pct"]:+.1f}%)' for k, h, e in _kept)
                 + '. Separation, rushing yards over expected and completion % over expected did not. Lift = points a game the tracking '
                 f'data adds to (or takes from) the box-score estimate; ±{_ng["lift_threshold"]:.0f} flags a buy-low or sell-high.</p><div class="cols">')
        _rows = list(_ng['players'].values())
        _best = lambda r: r['lift'] if abs(r['lift']) >= abs(r['lift_next']) else r['lift_next']
        _when = lambda r: 'rest of season' if abs(r['lift']) >= abs(r['lift_next']) else 'next season'
        for title, sel in (('Your players', [r for r in _rows if r['owner'] == MY and _best(r)]),
                           ('Buy-low watch (other teams)', [r for r in _rows if r['owner'] != MY and r['watch'] == 'buy-low']),
                           ('Sell-high watch (other teams)', [r for r in _rows if r['owner'] != MY and r['watch'] == 'sell-high'])):
            sel = sorted(sel, key=lambda r: -abs(_best(r)))[:8]
            if not sel:
                continue
            O.append(f'<div class="card"><h3>{esc(title)}</h3>')
            for r in sel:
                O.append(f'<div class="prow"><span class="pos">{esc(r["pos"])}</span><span><b>{esc(r["name"])}</b> '
                         f'<small style="color:var(--muted)">{"" if r["owner"] == MY else "@" + esc(r["owner"]) + " · "}{r["ppg"]:.1f} pts/game · '
                         f'{_when(r)}{" · " + r["watch"] if r["watch"] else ""}</small></span><span class="age"></span>'
                         f'<span class="vv num">{_best(r):+.1f}</span></div>')
            O.append('</div>')
        O.append('</div></section>')

    # ---- age vs price: WR production vs the price paid for it ----
    # Two curves side by side is the whole argument: production stays flat with
    # age while the price paid for it collapses. Computed here rather than
    # hard-coded so it self-corrects as seasons land.
    wr_curve = ((age_curve.get('positions') or {}).get('WR') or {}).get('curve') or []
    per_pt = {}
    if usage:
        buck = {}
        for pid, u in usage.items():
            pl_ = players.get(pid) or {}
            c = cons.get(pid)
            if (pl_.get('position') != 'WR' or not pl_.get('age') or not c
                    or u['games'] < 10 or u['ppr_ppg'] < 10):
                continue
            buck.setdefault(int(pl_['age']), []).append((c['mean'], u['ppr_ppg']))
        for a, g in buck.items():
            if len(g) >= 4:
                per_pt[a] = (sum(x[0] for x in g) / len(g)
                             / (sum(x[1] for x in g) / len(g)), len(g))
    if wr_curve or per_pt:
        O.append('<section><div class="kicker">Evidence</div>'
                 '<h2 class="disp">The WR Cliff Is a Price Cliff</h2>')
        O.append('<p class="lede"><b>WR production stays flat with age; the price collapses.</b> That is why veteran WRs are cheap wins.</p>')
        O.append('<div class="cols">')
        if wr_curve:
            mx = max(r['retention'] for r in wr_curve)
            O.append('<div class="card"><h3>Production retained, year over year</h3>')
            for r in wr_curve:
                w = r['retention'] / mx * 100
                O.append(f'<div class="prow"><span class="pos">{r["age"]}</span>'
                         f'<span><div class="bar"><div class="track">'
                         f'<div class="fill" style="width:{w:.0f}%"></div></div></div></span>'
                         f'<span class="age">n={r["n"]}</span>'
                         f'<span class="vv num">{r["retention"]:.0%}</span></div>')
            O.append('<div style="font-size:12px;color:var(--muted)">No break anywhere '
                     'through 31. The same test flags RB hard at 27 &rarr; 28.</div></div>')
        if per_pt:
            mx = max(v for v, _ in per_pt.values())
            O.append('<div class="card"><h3>Value paid per point of production</h3>')
            for a in sorted(per_pt):
                v, n = per_pt[a]
                w = v / mx * 100
                col = 'crit' if v < mx * 0.7 else 'accent'
                O.append(f'<div class="prow"><span class="pos">{a}</span>'
                         f'<span><div class="bar"><div class="track">'
                         f'<div class="fill" style="width:{w:.0f}%;'
                         f'background:var(--{col})"></div></div></div></span>'
                         f'<span class="age">n={n}</span>'
                         f'<span class="vv num">{v:.0f}</span></div>')
            O.append('<div style="font-size:12px;color:var(--muted)">Like-for-like: only '
                     'WRs with 10+ games and 10+ PPR/gm last season. Small buckets — '
                     'read the shape, not the decimals.</div></div>')
        O.append('</div></section>')

    # ---- risk detail: new coaches + the downside-adjusted column ----
    nhc = sorted(((V(pid), pid, (context.get(pid) or {})['new_hc'])
                  for pid in my_players if (context.get(pid) or {}).get('new_hc')),
                 reverse=True)
    radj = sorted(((V(pid), pid, (context.get(pid) or {})['risk'])
                   for pid in my_players
                   if (context.get(pid) or {}).get('risk') and V(pid) >= 1000),
                  reverse=True)
    if nhc or radj:
        O.append('<section><div class="kicker">Risk</div>'
                 '<h2 class="disp">Scheme Change &amp; Downside</h2><div class="cols">')
        if nhc:
            O.append('<div class="card"><h3>New head coach</h3>'
                     '<div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                     'A new staff rewrites the offense. Head coaches only — no free '
                     'source lists coordinators, so an OC swap under a retained head '
                     'coach still needs a manual note.</div>')
            for v, pid, h in nhc:
                O.append(f'<div class="prow"><span class="pos">{esc(posn(pid))}</span>'
                         f'<span>{esc(pname(pid))} <small style="color:var(--muted)">'
                         f'{esc(h["departing"])} &rarr; <b>{esc(h["incoming"])}</b>'
                         f'</small></span><span class="age"></span>'
                         f'<span class="vv num">{round(v):,}</span></div>')
            O.append('</div>')
        if radj:
            O.append('<div class="card"><h3>Downside-adjusted value</h3>'
                     '<div style="font-size:12px;color:var(--muted);margin:-4px 0 4px">'
                     'What each asset is worth <b>if the visible risks break badly</b> — '
                     'not an expected value, and it never replaces the consensus. Kept '
                     'separate on purpose: folded in, the guess would reach the power '
                     'rankings and argue against you when selling.</div>'
                     '<div class="scroller" style="border:none">'
                     '<table style="min-width:0"><thead><tr><th>Player</th>'
                     '<th style="text-align:right">Value</th>'
                     '<th style="text-align:right">Adj</th>'
                     '<th>Why</th></tr></thead><tbody>')
            for v, pid, r in radj:
                adj = v * r['mult']
                O.append(f'<tr><td class="team">{esc(pname(pid))}</td>'
                         f'<td class="n">{round(v):,}</td>'
                         f'<td class="n" style="color:var(--crit)">{round(adj):,}</td>'
                         f'<td style="font-size:12px;color:var(--muted)">'
                         f'{esc(", ".join(r["why"]))}</td></tr>')
            O.append('</tbody></table></div></div>')
        O.append('</div></section>')

    # ---- trade grades + activity ----
    O.append('<section><div class="kicker">Market</div><h2 class="disp">Trade Grades &amp; Activity</h2>')
    O.append('<div class="cols">')
    # net ranking
    O.append('<div class="card"><h3>Net trade value (hindsight)</h3><div class="scroller" style="border:none"><table style="min-width:0"><tbody>')
    for rid in sorted(net, key=lambda k: -net[k]):
        you = ' class="you"' if rid == my_rid else ''
        v = round(net[rid])
        col = 'var(--good)' if v >= 0 else 'var(--crit)'
        O.append(f'<tr{you}><td class="rk">{trade_rank[rid]}</td><td class="team">{esc(team_name(rid))}</td>'
                 f'<td class="n" style="color:{col};font-weight:700">{v:+,}</td></tr>')
    O.append('</tbody></table></div></div>')
    # top trades + recent feed
    O.append('<div class="card"><h3>Most lopsided trades</h3>')
    for mg, dt, w, l, got in trades[:5]:
        wi = ', '.join(f'{esc(n)}' for n, _ in sorted(got[w], key=lambda x: -x[1])[:3])
        O.append(f'<div class="trade"><div class="h">{esc(team_name(w))} <span class="amt">+{round(mg):,}</span></div>'
                 f'<div class="side">{esc(dt)} · got {wi}</div></div>')
    O.append('</div></div>')
    # recent activity feed
    O.append('<div class="card"><h3>Recent activity</h3><div class="feed">')
    for t in sorted(txns, key=lambda x: -x['created'])[:12]:
        d = datetime.fromtimestamp(t['created'] / 1000).strftime('%m/%d')
        O.append(f'<div class="row"><span class="d">{d}</span><span class="k">{esc(t["type"].replace("_"," "))}</span><span>{txn_summary(t)}</span></div>')
    O.append('</div></div></section>')

    # ---- owner board ----
    O.append('<section><div class="kicker">Scouting</div><h2 class="disp">Owner Board</h2>')
    O.append('<div class="oboard">')
    for rid in sorted(metrics, key=lambda k: -metrics[k]['total']):
        owner = team_name(rid)
        uname = uid_user.get(roster_of[rid].get('owner_id'), '')
        wtxt, wc = window_of(uname)
        ttxt, tc = traj_of(uname)
        you = ' you' if rid == my_rid else ''
        eff = ''
        ms = mskill.get(uname) or mskill.get(owner)
        if isinstance(ms, dict) and ms.get('efficiency') is not None:
            eff = f" · lineup {round(ms['efficiency'])}%"
        read = OWNER_READS.get(uname, '')
        O.append(f'<div class="ocard{you}"><div class="top"><div class="nm">{esc(owner)}<small>{esc(uname)}</small></div>'
                 f'<div class="chips"><span class="chip {wc}">{esc(wtxt)}</span><span class="chip {tc}">{esc(ttxt)}</span></div></div>'
                 f'<details class="read"><summary>Scouting read</summary>{esc(read)}</details>'
                 f'<div class="stat">Dynasty #{dyn_rank[rid]} · trade net {round(net[rid]):+,} · {tcount[rid]} trades{eff}</div></div>')
    O.append('</div></section>')

    O.append(f'<footer>Dynasty Scout · league {CFG.get("league_id","")} · regenerate with <span class="num">./update.sh</span>. '
             f'Values are hindsight/current; pick tiers use projected finishes. Not gospel — cross-check the profiles.</footer>')
    O.append('</div>')
    return '\n'.join(O)


if __name__ == '__main__':
    out = os.path.join(ROOT, 'dashboards', 'league.html')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'w').write(build())
    print(f'league command center -> dashboards/league.html')
