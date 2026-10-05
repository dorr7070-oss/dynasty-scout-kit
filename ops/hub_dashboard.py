#!/usr/bin/env python3
"""ONE dashboard (owner's design, 2026-10-04): every view in a single tabbed page -> dashboards/hub.html

Same design for every owner who runs the kit: everything comes from the owner's own config and data, so a
copy is private to whoever runs it — no separate public/private versions to maintain.

Tabs: This Week · Trades · Season · Players · League · Picks (bottom bar on phones, sticky top bar on desktop).
Opens to This Week; on Sundays and Mondays (US Eastern) Game Day leads that tab, other days the week's actions do.
A bare #token in the link opens a tab directly (#week #trades #season #players #league #picks).

Built from the pages the other generators write (league.html, analysis.html, gameday.html, assets.html): each
page's <section> blocks are routed to a tab by their heading, styles and scripts carried over unchanged, and the
old cross-page link bars dropped. A section whose heading isn't mapped lands in League and is listed in the log,
so nothing disappears silently. Run last (after analysis_dashboard.py).
"""
import html, json, os, re, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'dashboards')
sys.path.insert(0, os.path.join(ROOT, 'ops'))
import league_format as LF  # noqa: E402

TABS = [('week', 'This Week'), ('trades', 'Trades'), ('season', 'Season'), ('players', 'Players'), ('league', 'League'), ('picks', 'Picks'), ('ask', 'Ask')]
SHORT = {'week': 'Week'}          # phone tab bar labels where the full one is too long
ROUTE = [  # (heading starts with, tab, order within tab)
    ('Start / Sit', 'week', 20), ('News & Data Check', 'week', 25), ('Waivers, Injuries', 'week', 30),
    ('Trade Finder', 'trades', 10), ('What Would It Take', 'trades', 20), ('Plan Check', 'trades', 5), ('My Team', 'trades', 30),
    ('Contract Calendar', 'trades', 40),
    ('Playoff Race', 'season', 10), ('Our Projections vs Sleeper', 'season', 20), ('Your Remaining Schedule', 'season', 15),
    ('Projection Accuracy', 'season', 40),
    ('Your Players, Week by Week', 'players', 10), ('Value History', 'players', 20), ('Strength of Schedule', 'players', 30),
    ('Availability, Contracts', 'players', 40), ('Starters vs the League', 'players', 5), ('The WR Cliff', 'players', 60),
    ('Scheme Change', 'players', 50),
    ('Tracking Data', 'players', 15),
    ('Power Rankings', 'league', 10), ('Every Owner at a Glance', 'league', 20), ('Lineup Efficiency', 'league', 30),
    ('Trade Grades', 'league', 40), ('Owner Board', 'league', 50),
    ('Lottery Tracker', 'picks', 10), ('Draft Capital', 'picks', 20),
    ('Player Lookup', 'players', 1), ('Trade Analyzer', 'trades', 1), ('Ask the Analyst', 'ask', 10),
]
HUB_CSS = """
.hubnav{display:flex;gap:4px;position:sticky;top:env(safe-area-inset-top,0px);z-index:20;background:var(--paper);
  padding-block:8px;border-bottom:1px solid var(--line);overflow-x:auto;scrollbar-width:none}
.hubnav button{font:inherit;font-size:14px;font-weight:600;color:var(--ink2);background:none;border:none;border-radius:8px;padding:8px 14px;
  cursor:pointer;white-space:nowrap}
.hubnav button[aria-selected="true"]{background:var(--card);color:var(--accent-ink);box-shadow:inset 0 -2px 0 var(--accent)}
.hubnav button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.hubnav .ts{display:none}
.hubpanel{display:flex;flex-direction:column;gap:32px;padding-top:20px}
.hubpanel[hidden]{display:none!important}
.gd-block{display:flex;flex-direction:column;gap:20px}
@media (max-width:640px){
  .hubnav{position:fixed;left:0;right:0;bottom:0;top:auto;justify-content:space-around;border-top:1px solid var(--line);border-bottom:none;
    padding:6px 4px calc(6px + env(safe-area-inset-bottom,0px))}
  .hubnav button{font-size:11.5px;padding:8px 4px}
  .hubnav .tl{display:none}.hubnav .ts{display:inline}
  body{padding-bottom:64px}
}
"""


def scope_css(css, scope, keep_global=False):
    """Fence one page's stylesheet to its own content (.src-<page>): the four pages reuse class names (.card, .prow,
    table, h1...) with different rules, so merged unfenced the last page wins everywhere. Page-level selectors
    (:root, html, body) become the fence itself so each page keeps its own tokens; keep_global leaves them global
    for the base page whose tokens the hub's own chrome uses."""
    out, i = [], 0
    while i < len(css):
        j = css.find('{', i)
        if j < 0:
            break
        head = css[i:j].strip()
        if head.startswith('@media') or head.startswith('@supports'):
            depth, k = 1, j + 1
            while depth and k < len(css):
                depth += {'{': 1, '}': -1}.get(css[k], 0)
                k += 1
            out.append(head + '{' + scope_css(css[j + 1:k - 1], scope, keep_global) + '}')
            i = k
            continue
        k = css.find('}', j)
        body = css[j + 1:k]
        if head.startswith('@'):                      # @font-face, @keyframes, @import: untouched
            if head.startswith('@keyframes'):
                depth, k = 1, j + 1
                while depth and k < len(css):
                    depth += {'{': 1, '}': -1}.get(css[k], 0)
                    k += 1
                out.append(css[i:k]); i = k; continue
            out.append(head + '{' + body + '}'); i = k + 1; continue
        sels = []
        for x in head.split(','):
            x = x.strip()
            first, _, rest = x.partition(' ')
            pagewide = re.match(r'^(:root|html|body)\b', first)
            if keep_global and (pagewide or x in ('*', '.wrap') or x.startswith('*')):
                sels.append(x)
            elif pagewide:
                tail = first[len(pagewide.group(1)):]      # e.g. :not([data-theme="light"]) or [data-theme="dark"]
                root = (':root' + tail + ' ') if pagewide.group(1) != 'body' and tail else ''
                sels.append((root + '.' + scope + (' ' + rest if rest else '')).strip())
            else:
                sels.append('.' + scope + ' ' + x)
        out.append(', '.join(sels) + '{' + body + '}')
        i = k + 1
    return ''.join(out)


def parts(page):
    """(styles, header_html, [sections], scripts) of a generated page."""
    h = open(os.path.join(D, page)).read() if os.path.exists(os.path.join(D, page)) else ''
    styles = re.findall(r'<style>(.*?)</style>', h, re.S)
    scripts = re.findall(r'(<script[^>]*>.*?</script>)', h, re.S)
    body = re.sub(r'<script[^>]*>.*?</script>', '', h, flags=re.S)
    body = re.sub(r'<style>.*?</style>', '', body, flags=re.S)
    body = re.sub(r'<title>.*?</title>|<meta charset[^>]*>', '', body, flags=re.S)
    header = (re.search(r'<header>.*?</header>', body, re.S) or [''])[0]
    body = body.replace(header, '')
    secs = re.findall(r'<section\b.*?</section>', body, re.S)
    # assets.html nests its views inside top-level sections; keep any non-section remainder too
    return styles, header, secs, scripts


def heading(sec):
    m = re.search(r'<h2[^>]*>(.*?)</h2>', sec, re.S)
    return html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else ''


def drop_links(fragment):
    """Remove the old 'other dashboards' link bars — one page now."""
    return re.sub(r'<nav[^>]*>(?:(?!</nav>).)*claude\.ai/artifact(?:(?!</nav>).)*</nav>', '', fragment, flags=re.S)


def main():
    styles, scripts = [], []
    panels = {k: [] for k, _ in TABS}
    unmapped = []

    lg_st, lg_head, lg_secs, lg_js = parts('league.html')
    an_st, _, an_secs, an_js = parts('analysis.html')
    ay_st, _, ay_secs, ay_js = parts('analyst.html')
    gd_st, gd_head, gd_secs, gd_js = parts('gameday.html')
    as_st, _, as_secs, as_js = parts('assets.html')
    for st, sc in ((lg_st, 'src-league'), (an_st, 'src-analysis'), (gd_st, 'src-gameday'), (as_st, 'src-assets'), (ay_st, 'src-analyst')):
        styles.append(scope_css(''.join(st), sc, keep_global=(sc == 'src-league')))
    an_set = set(an_secs)

    ay_set = set(ay_secs)
    for sec in lg_secs + an_secs + ay_secs:
        h = heading(sec)
        hit = next(((t, o) for pre, t, o in ROUTE if h.startswith(pre)), None)
        frag = f'<div class="{"src-analyst" if sec in ay_set else "src-analysis" if sec in an_set else "src-league"}">{drop_links(sec)}</div>'
        if hit:
            panels[hit[0]].append((hit[1], frag))
        else:
            panels['league'].append((90, frag))
            unmapped.append(h)
    # Game Day: its live app (status line + #app container) and scripts; leads This Week on Sun/Mon
    stamp = (re.search(r'<p class="status" id="stamp">.*?</p>', gd_head, re.S) or [''])[0]
    gd_block = (f'<div class="gd-block src-gameday" id="gdblock"><div><div class="kicker">Game Day</div>{stamp}</div><div id="app"></div></div>')
    panels['week'].append((10, gd_block))
    # Asset Board: its own tab bar + views + script, whole, in Picks
    # its script fills #season/#gen in its own header, so carry that line; the tier legend sits outside its sections
    as_raw = open(os.path.join(D, 'assets.html')).read() if os.path.exists(os.path.join(D, 'assets.html')) else ''
    as_sub = (re.search(r'<div class="sub">.*?</div>', as_raw, re.S) or [''])[0]
    as_season = '<span id="season" hidden></span>' if 'id="season"' not in as_sub else ''
    legend = (re.search(r'<p class="legend">.*?</p>', as_raw, re.S) or [''])[0]
    panels['picks'].append((30, '<div class="src-assets"><section><div class="kicker">Asset board</div><h2 class="disp">Rosters, Picks &amp; Prospects</h2>'
                           + as_sub + as_season + '</section>' + ''.join(as_secs) + legend + '</div>'))
    # each page's script declared its own top-level names (D, e, h, show...) — in one page those collide and the
    # later script dies on a redeclaration error, so every carried script runs in its own scope
    def scoped(x):
        if re.match(r'<script[^>]*type="application/json"', x):   # data blocks stay as they are
            return x
        return re.sub(r'(<script[^>]*>)(.*)(</script>)', lambda m: m.group(1) + '{\n' + m.group(2) + '\n}' + m.group(3), x, flags=re.S)
    scripts = [scoped(x) for x in an_js + gd_js + as_js + lg_js + ay_js]

    # header: the Command Center's (team name, verdict, tiles, on-the-clock), minus the old link bar
    head = drop_links(lg_head)
    me = json.load(open(os.path.join(ROOT, 'config.json'))).get('my_username')
    nav = ('<nav class="hubnav" role="tablist" aria-label="Dashboard sections">' + ''.join(
        f'<button role="tab" id="hubtab-{k}" aria-controls="hub-{k}" aria-selected="{"true" if k == "week" else "false"}">'
        f'<span class="tl">{html.escape(n)}</span><span class="ts">{html.escape(SHORT.get(k, n))}</span></button>'
        for k, n in TABS) + '</nav>')
    body = []
    for k, n in TABS:
        items = sorted(panels[k], key=lambda x: x[0])
        body.append(f'<div class="hubpanel" role="tabpanel" id="hub-{k}" aria-labelledby="hubtab-{k}"{"" if k == "week" else " hidden"}>'
                    + ''.join(x for _, x in items) + '</div>')
    hub_js = """<script>(function(){
const tabs=[...document.querySelectorAll('.hubnav button')];
function show(k,push){tabs.forEach(b=>{const on=b.id==='hubtab-'+k;b.setAttribute('aria-selected',on);document.getElementById('hub-'+b.id.slice(7)).hidden=!on});
  try{localStorage.setItem('hubtab',k)}catch(e){} if(push){try{history.replaceState(null,'','#'+k)}catch(e){}} window.scrollTo({top:0})}
tabs.forEach(b=>b.addEventListener('click',()=>show(b.id.slice(7),true)));
// Smart first screen: Game Day leads This Week on Sundays and Mondays (US Eastern), the week's actions otherwise
const day=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',weekday:'short'}).format(new Date());
const gd=document.getElementById('gdblock'),wk=document.getElementById('hub-week');
if(gd&&wk&&!(day==='Sun'||day==='Mon')){wk.appendChild(gd)}
const h=(location.hash||'').slice(1);const valid=tabs.map(b=>b.id.slice(7));
show(valid.includes(h)?h:'week',false);
})();</script>"""
    now = LF.stamp()
    page = (f'<meta charset="utf-8"><title>Dynasty Command Center</title><style>{"".join(styles)}{HUB_CSS}</style><div class="wrap"><div class="src-league">{head}</div>{nav}{"".join(body)}'
            f'<div class="src-league"><footer>Updated {now} · {html.escape(LF.LEAGUE_NAME)} · every view in one place</footer></div></div>{"".join(scripts)}{hub_js}')
    open(os.path.join(D, 'hub.html'), 'w').write(page)
    counts = {k: len(panels[k]) for k, _ in TABS}
    print(f'hub -> dashboards/hub.html ({len(page) // 1024} KB): ' + ', '.join(f'{n} {counts[k]}' for k, n in TABS)
          + (f'; UNMAPPED headings -> League: {unmapped}' if unmapped else '; all sections mapped'))


if __name__ == '__main__':
    main()
