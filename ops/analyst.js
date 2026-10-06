/* analyst.html page logic (ops/analyst.py embeds this). Data: the #ad JSON bundle. No libraries. */
(function () {
  const D = JSON.parse(document.getElementById('ad').textContent);
  const P = D.players, T = D.teams, WEEKS = D.weeks;
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const norm = s => String(s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[.'’,\-]/g, '').replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
  const fmt = (v, d = 0) => (v == null || isNaN(v)) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
  const pct = v => (v == null || isNaN(v)) ? '—' : Math.round(v * 100) + '%';
  const sgn = (v, d = 1) => (v == null || isNaN(v)) ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '±') + fmt(Math.abs(v), d);
  const isPick = x => String(x).startsWith('pick:');
  const RIDS = Object.keys(T);
  // "my team": fixed in the owner's edition; in the league edition it's whichever team this viewer picked (their browser only)
  const myRid = () => String((window.DS_PICK && window.DS_PICK()) || D.my_rid || '');
  const meOwner = () => (T[myRid()] || {}).owner || D.me;

  // ---------- search ----------
  function search(q, n = 8) {
    q = norm(q);
    if (!q) return [];
    const out = [];
    for (const [id, p] of Object.entries(P)) {
      const nm = norm(p.n);
      if (!nm) continue;
      const s = nm.startsWith(q) ? 3 : nm.split(' ').some(w => w.startsWith(q)) ? 2 : nm.includes(q) ? 1 : 0;
      if (s) out.push([s + (p.o ? 0.5 : 0) + p.mkt / 1e5, id]);
    }
    return out.sort((a, b) => b[0] - a[0]).slice(0, n).map(x => x[1]);
  }
  function teamOf(q) {
    q = norm(q);
    for (const r of RIDS) if (norm(T[r].owner) === q || norm(T[r].name) === q) return r;
    for (const r of RIDS) if (norm(T[r].owner).includes(q) || norm(T[r].name).includes(q)) return r;
    return null;
  }

  // ---------- player card ----------
  function tags(p) {
    const t = [];
    if (p.inj) t.push(['bad', p.inj + (p.injp ? ' · ' + p.injp : '')]);
    if (p.prac) t.push(['warn', 'Practice: ' + p.prac]);
    if (p.ngs && p.ngs.watch) t.push([p.ngs.watch === 'buy-low' ? 'good' : 'bad', 'Tracking: ' + p.ngs.watch]);
    if (p.cut && (p.cut.tier === 'easy cut' || p.cut.tier === 'cuttable')) t.push(['warn', p.cut.tier + ' next year']);
    if (p.fa && Number(p.fa) === Number(D.season) + 1) t.push(['warn', 'Free agent after this season']);
    if (p.trn && p.trn.add >= 20000) t.push(['good', fmt(p.trn.add) + ' Sleeper adds (24h)']);
    if (p.trn && p.trn.drop >= 20000) t.push(['bad', fmt(p.trn.drop) + ' Sleeper drops (24h)']);
    return t;
  }
  function kv(k, v, s) { return `<div class="an-kv"><div class="k">${esc(k)}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ''}</div>`; }
  function card(id) {
    const p = P[id];
    if (!p) return '';
    const own = p.o ? (p.o === meOwner() ? 'your team' : '@' + esc(p.o)) : 'free agent';
    const u = p.use || {};
    const ws = WEEKS.slice(0, 6);
    const row = (lab, src) => `<tr><td>${lab}</td>${ws.map(w => `<td>${src && src[w] != null ? fmt(src[w], 1) : '—'}</td>`).join('')}</tr>`;
    const nx = p.ngs || {};
    return `<div class="an-card"><div class="an-head"><h3 class="disp">${esc(p.n)}</h3><span class="an-mut">${esc(p.p)} · ${esc(p.t || 'no team')} · age ${esc(p.a ?? '—')} · ${own}</span></div>
      <div class="an-tags">${tags(p).map(([c, x]) => `<span class="an-tag ${c}">${esc(x)}</span>`).join('') || '<span class="an-tag">No injury, contract or news flags</span>'}</div>
      <div class="an-grid">
        ${kv('Market value', fmt(p.mkt), `contract-adjusted ${fmt(p.adj)} · plan window ${fmt(p.win)}`)}
        ${kv('Value trend', sgn(p.tr7 == null ? null : p.tr7 * 100, 0) + '%', `7 days · 30 days ${sgn(p.tr30 == null ? null : p.tr30 * 100, 0)}%`)}
        ${kv('Rest of season', fmt(p.ros, 1), 'pts/game, blended projection')}
        ${kv('This season', fmt(p.ppg, 1), `pts/game in ${fmt(p.gp)} games`)}
        ${kv('Usage', pct(u.snap_pct) + ' snaps', `targets ${pct(u.target_share)} · routes ${pct(u.route_pct_est)} · red zone ${pct((u.rz_tgt_share || 0) + (u.rz_carry_share || 0))}`)}
        ${kv('Tracking lift', nx.lift == null ? '—' : sgn(Math.abs(nx.lift) >= Math.abs(nx.next || 0) ? nx.lift : nx.next), 'pts/game vs box score (tested metrics only)')}
        ${kv('Contract', p.fa ? 'through ' + (Number(p.fa) - 1) : '—', p.cut ? `${p.cut.tier === 'not signed' ? 'no contract for ' + (Number(D.season) + 1) : esc(p.cut.tier) + ' in ' + (Number(D.season) + 1)}${p.cut.save != null ? ` · cut saves $${fmt(p.cut.save / 1e6, 1)}M vs $${fmt((p.cut.dead || 0) / 1e6, 1)}M dead` : ''}` : (p.ctr ? esc(p.ctr.signal || '') : ''))}
      </div>
      <div class="an-tbl"><table><thead><tr><th>Projection</th>${ws.map(w => `<th>Wk ${w}</th>`).join('')}</tr></thead><tbody>
        ${row('<b>Blend</b>', p.proj)}${row('Ours', p.projO)}${row('Sleeper', p.projS)}</tbody></table></div>
      ${p.flags && p.flags.length ? `<div class="an-list">${p.flags.map(f => `<div>• ${esc(f)}</div>`).join('')}</div>` : ''}
      ${p.news && p.news.length ? `<div class="an-list"><b>News</b>${p.news.map(n => `<div><span class="an-mut">${esc((n.k || 'news').toUpperCase())} · ${fmt(n.ago)}h ago</span> — ${n.u ? `<a href="${esc(n.u)}" target="_blank" rel="noopener">${esc(n.h)}</a>` : esc(n.h)}</div>`).join('')}</div>` : ''}
    </div>`;
  }
  function wireLookup() {
    const q = $('an-q'), sug = $('an-sug'), out = $('an-card');
    if (!q) return;
    const show = id => { out.innerHTML = card(id); sug.innerHTML = ''; q.value = P[id].n; };
    q.addEventListener('input', () => {
      const ids = search(q.value);
      sug.innerHTML = ids.map(id => `<button type="button" role="option" data-id="${id}">${esc(P[id].n)} <small>${esc(P[id].p)} · ${esc(P[id].t || '')} · ${P[id].o ? '@' + esc(P[id].o) : 'free agent'}</small></button>`).join('');
    });
    q.addEventListener('keydown', e => { if (e.key === 'Enter') { const ids = search(q.value, 1); if (ids[0]) show(ids[0]); } });
    sug.addEventListener('click', e => { const b = e.target.closest('button[data-id]'); if (b) show(b.dataset.id); });
  }

  // ---------- season simulation (same engine as lottery.py) ----------
  function lineup(ids, w) {
    const pools = {};
    for (const pos of Object.keys(D.core)) pools[pos] = [];
    for (const id of ids) { const p = P[id]; if (p && pools[p.p]) pools[p.p].push(+(p.proj[w] || 0)); }
    for (const k in pools) pools[k].sort((a, b) => b - a);
    let tot = 0;
    for (const [pos, n] of Object.entries(D.core)) { tot += pools[pos].slice(0, n).reduce((a, b) => a + b, 0); pools[pos] = pools[pos].slice(n); }
    for (const elig of D.flex) {
      let best = null;
      for (const pos of elig) if (pools[pos] && pools[pos].length && (best === null || pools[pos][0] > pools[best][0])) best = pos;
      if (best) tot += pools[best].shift();
    }
    return tot;
  }
  function rng(seed) {
    return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  }
  function simulate(rosters, N = 3000) {
    const pts = {};
    for (const r of RIDS) { pts[r] = {}; for (const w of WEEKS) pts[r][w] = lineup(rosters[r], w); }
    const R = rng(20261004);           // fixed seed: before/after runs share every random draw
    const gauss = () => { let u = 0; while (!u) u = R(); const v = R(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
    const made = {}, wins = {};
    RIDS.forEach(r => { made[r] = 0; wins[r] = 0; });
    for (let i = 0; i < N; i++) {
      const W = {}, F = {};
      RIDS.forEach(r => { W[r] = T[r].w; F[r] = T[r].pf; });
      for (const w of WEEKS) {
        const s = {};
        RIDS.forEach(r => { s[r] = (w === WEEKS[0] && D.locked[r] != null) ? D.locked[r] : pts[r][w] + D.sd * gauss(); });
        const seen = new Set();
        for (const r of RIDS) for (const g of T[r].sched) {
          if (g.wk !== w) continue;
          const o = String(g.opp), key = r < o ? r + '-' + o : o + '-' + r;
          if (seen.has(key) || !(o in s)) continue;
          seen.add(key);
          W[s[r] > s[o] ? r : o]++;
        }
        if (D.median) RIDS.slice().sort((a, b) => s[b] - s[a]).slice(0, RIDS.length / 2).forEach(r => W[r]++);
        RIDS.forEach(r => { F[r] += s[r]; });
      }
      RIDS.slice().sort((a, b) => W[b] - W[a] || F[b] - F[a]).slice(0, D.playoff_teams).forEach(r => made[r]++);
      RIDS.forEach(r => { wins[r] += W[r]; });
    }
    const res = {};
    RIDS.forEach(r => { res[r] = { po: made[r] / N, xw: wins[r] / N }; });
    return res;
  }
  let BASE = null;
  const baseRosters = () => Object.fromEntries(RIDS.map(r => [r, T[r].players.slice()]));
  const pickInfo = k => { for (const r of RIDS) for (const pk of T[r].picks) if (pk.k === k) return pk; return null; };
  const label = x => isPick(x) ? ((pickInfo(x) || {}).l || x) : ((P[x] || {}).n || x);
  const mval = x => isPick(x) ? ((pickInfo(x) || {}).v || 0) : ((P[x] || {}).mkt || 0);
  const wval = x => isPick(x) ? ((pickInfo(x) || {}).v || 0) : ((P[x] || {}).win || 0);

  function evaluateTrade(a, aGive, b, bGive) {
    if (!BASE) BASE = simulate(baseRosters());
    const after = baseRosters();
    after[a] = after[a].filter(x => !aGive.includes(x)).concat(bGive.filter(x => !isPick(x)));
    after[b] = after[b].filter(x => !bGive.includes(x)).concat(aGive.filter(x => !isPick(x)));
    const S = simulate(after);
    const sum = (xs, f) => xs.reduce((t, x) => t + f(x), 0);
    const side = (r, give, get) => ({
      team: T[r].name, owner: T[r].owner, gives: give.map(label), gets: get.map(label),
      playoff_before: BASE[r].po, playoff_after: S[r].po, wins_before: BASE[r].xw, wins_after: S[r].xw,
      market_in: sum(get, mval), market_out: sum(give, mval), window_in: sum(get, wval), window_out: sum(give, wval),
    });
    const flags = [];
    for (const x of aGive.concat(bGive)) {
      if (isPick(x)) continue;
      const p = P[x]; if (!p) continue;
      const f = tags(p).map(t => t[1]);
      const fresh = (p.news || []).filter(n => n.ago <= 72).slice(0, 1).map(n => 'news: ' + n.h);
      if (f.length || fresh.length) flags.push({ player: p.n, flags: f.concat(fresh) });
    }
    return { a: side(a, aGive, bGive), b: side(b, bGive, aGive), flags, sims: 3000 };
  }
  function tradeHTML(res) {
    const row = s => `<tr><td><b>${esc(s.team)}</b><br><span class="an-mut">gets ${esc(s.gets.join(', ') || 'nothing')}</span></td>
      <td>${pct(s.playoff_before)} → <b>${pct(s.playoff_after)}</b><br><span class="an-mut">${sgn((s.playoff_after - s.playoff_before) * 100, 0)} pts</span></td>
      <td>${fmt(s.wins_before, 1)} → <b>${fmt(s.wins_after, 1)}</b><br><span class="an-mut">${sgn(s.wins_after - s.wins_before, 2)}</span></td>
      <td>${sgn(s.market_in - s.market_out, 0)}<br><span class="an-mut">in ${fmt(s.market_in)} · out ${fmt(s.market_out)}</span></td>
      <td>${sgn(s.window_in - s.window_out, 0)}</td></tr>`;
    const tot = Math.max(1, res.a.market_in + res.a.market_out);
    const gap = Math.abs(res.a.market_in - res.a.market_out) / tot;
    const verdict = gap <= 0.1 ? 'Even on market value (within 10%).' :
      `${res.a.market_in > res.a.market_out ? res.a.team : res.b.team} wins on market value by ${fmt(Math.abs(res.a.market_in - res.a.market_out))}.`;
    return `<div class="an-card"><div><b>${esc(verdict)}</b> <span class="an-mut">Season odds from ${fmt(res.sims)} simulated seasons each way, same random draws.</span></div>
      <div class="an-tbl"><table><thead><tr><th>Team</th><th>Playoff odds</th><th>Expected wins</th><th>Market value</th><th>Plan-window value</th></tr></thead>
      <tbody>${row(res.a)}${row(res.b)}</tbody></table></div>
      ${res.flags.length ? `<div class="an-list"><b>Check before you send it</b>${res.flags.map(f => `<div>• <b>${esc(f.player)}</b>: ${esc(f.flags.join(' · '))}</div>`).join('')}</div>` : ''}</div>`;
  }
  function wireAnalyzer() {
    const A = $('an-a'), B = $('an-b'), go = $('an-go'), out = $('an-out');
    if (!A) return;
    const opts = RIDS.map(r => `<option value="${r}">${esc(T[r].name)} (@${esc(T[r].owner)})</option>`).join('');
    const build = (el, rid) => {
      el.innerHTML = `<select aria-label="Team">${opts}</select><input type="search" placeholder="Filter…" aria-label="Filter players"><div class="opts"></div>`;
      const sel = el.querySelector('select'), flt = el.querySelector('input'), box = el.querySelector('.opts');
      sel.value = rid;
      const list = () => {
        const r = sel.value, f = norm(flt.value);
        const items = (T[r].all || T[r].players).filter(x => P[x]).sort((x, y) => P[y].mkt - P[x].mkt)
          .map(x => [x, P[x].n, `${P[x].p} · ${fmt(P[x].mkt)}${T[r].players.includes(x) ? '' : ' · IR/taxi'}`])
          .concat(T[r].picks.map(pk => [pk.k, pk.l, fmt(pk.v)]));
        box.innerHTML = items.filter(it => !f || norm(it[1]).includes(f))
          .map(([k, n, s]) => `<label><input type="checkbox" value="${esc(k)}"> ${esc(n)} <small>${esc(s)}</small></label>`).join('');
      };
      sel.addEventListener('change', list); flt.addEventListener('input', list); list();
    };
    build(A, myRid() || RIDS[0]);
    build(B, RIDS.find(r => r !== myRid()));
    window.DS_SET_TEAM = rid => { const s = A.querySelector('select'); if (s && T[rid]) { s.value = rid; s.dispatchEvent(new Event('change')); } };
    const picked = el => [...el.querySelectorAll('.opts input:checked')].map(i => i.value);
    go.addEventListener('click', () => {
      const a = A.querySelector('select').value, b = B.querySelector('select').value;
      if (a === b) { out.innerHTML = '<p class="an-mut">Pick two different teams.</p>'; return; }
      const ag = picked(A), bg = picked(B);
      if (!ag.length && !bg.length) { out.innerHTML = '<p class="an-mut">Tick at least one player or pick on either side.</p>'; return; }
      go.disabled = true; out.innerHTML = '<p class="an-mut">Simulating the season both ways…</p>';
      setTimeout(() => { try { out.innerHTML = tradeHTML(evaluateTrade(a, ag, b, bg)); } finally { go.disabled = false; } }, 30);
    });
  }

  // ---------- ask the analyst ----------
  const brief = id => {
    const p = P[id];
    return { id, name: p.n, pos: p.p, team: p.t, age: p.a, owner: p.o || 'free agent', injury: p.inj, injury_part: p.injp, practice: p.prac,
      market_value: p.mkt, contract_adjusted_value: p.adj, plan_window_value: p.win, value_change_7d: p.tr7, value_change_30d: p.tr30,
      rest_of_season_ppg_blend: p.ros, season_ppg: p.ppg, games: p.gp, usage: p.use, tracking: p.ngs, contract_signal: p.ctr && p.ctr.signal,
      free_agent_year: p.fa, cut_risk_next_year: p.cut, sleeper_trending_24h: p.trn, this_week_projection: p.wk, flags: p.flags,
      projections_next_weeks: Object.fromEntries(WEEKS.slice(0, 4).map(w => [w, { blend: p.proj[w], ours: p.projO[w], sleeper: p.projS[w] }])),
      news_21d: p.news };
  };
  const findIn = (r, name) => {
    const q = norm(name);
    const ids = (T[r].all || T[r].players).filter(x => P[x]);
    return ids.find(x => norm(P[x].n) === q) || ids.find(x => norm(P[x].n).includes(q))
      || (T[r].picks.find(pk => norm(pk.l).includes(q)) || {}).k || null;
  };
  const TOOLS = [
    { name: 'find_player', description: 'Look up one NFL player in this league (rostered or a free agent people are adding). Returns everything the dashboard knows: values, projections (blend/ours/Sleeper), injury, usage, tracking, contract, cut risk, news, owner.',
      inputSchema: { type: 'object', properties: { name: { type: 'string' } }, required: ['name'] },
      execute: ({ name }) => { const ids = search(String(name || ''), 3); if (!ids.length) throw new Error('No player matching ' + name); return { best: brief(ids[0]), other_matches: ids.slice(1).map(i => P[i].n) }; } },
    { name: 'team', description: 'One team by owner username or team name: record, points, playoff odds, expected wins, every player with position, rest-of-season points/game, market value and injury, and its draft picks.',
      inputSchema: { type: 'object', properties: { owner_or_team: { type: 'string' } }, required: ['owner_or_team'] },
      execute: ({ owner_or_team }) => { const r = teamOf(String(owner_or_team || '')); if (!r) throw new Error('No team matching ' + owner_or_team); const t = T[r];
        return { team: t.name, owner: t.owner, record: `${t.w}-${t.l}`, points_for: t.pf, playoff_odds: t.po, expected_wins: t.xw,
          players: t.players.filter(x => P[x]).map(x => ({ name: P[x].n, pos: P[x].p, ros_ppg: P[x].ros, value: P[x].mkt, injury: P[x].inj })).sort((a, b) => b.value - a.value),
          picks: t.picks.map(pk => ({ pick: pk.l, value: pk.v })) }; } },
    { name: 'evaluate_trade', description: 'Run the trade analyzer: each team gives a list of player names or pick labels (e.g. "2027 Mid 1st"). Re-simulates the season both ways; returns playoff odds and expected wins before/after for both teams, market and plan-window value in/out, and flags on the moving players.',
      inputSchema: { type: 'object', properties: { team_a: { type: 'string' }, a_gives: { type: 'array', items: { type: 'string' } }, team_b: { type: 'string' }, b_gives: { type: 'array', items: { type: 'string' } } }, required: ['team_a', 'a_gives', 'team_b', 'b_gives'] },
      execute: ({ team_a, a_gives, team_b, b_gives }) => {
        const a = teamOf(String(team_a || '')), b = teamOf(String(team_b || ''));
        if (!a || !b) throw new Error('Unknown team: ' + (!a ? team_a : team_b));
        const res = [], miss = [];
        for (const [r, list] of [[a, a_gives], [b, b_gives]]) res.push((Array.isArray(list) ? list : []).map(n => { const k = findIn(r, String(n)); if (!k) miss.push(`${n} (not on ${T[r].owner})`); return k; }).filter(Boolean));
        if (miss.length) throw new Error('Not found: ' + miss.join(', '));
        return evaluateTrade(a, res[0], b, res[1]); } },
    { name: 'league', description: "League overview: every team's record, points and playoff odds, data freshness and how the projections were tested (plus the owner's own notes where this page has them).",
      execute: () => ({ league: D.league, season: D.season, data_generated: D.generated, you: meOwner(),
        standings: RIDS.map(r => ({ team: T[r].name, owner: T[r].owner, record: `${T[r].w}-${T[r].l}`, points_for: T[r].pf, playoff_odds: T[r].po, expected_wins: T[r].xw })).sort((x, y) => (y.playoff_odds || 0) - (x.playoff_odds || 0)),
        ...(D.plan ? { trade_plan: D.plan } : {}), ...(D.alerts ? { news_alerts: D.alerts } : {}), stale_sources: D.fresh.stale, freshness_checked: D.fresh.checked,
        projection_test: `2025 held-out weeks: blend ${D.model.test_blend} vs ours ${D.model.test} vs Sleeper ${D.model.test_sleeper} average points of error per player-game; blend weights on ours ${JSON.stringify(D.model.blend)}` }) },
  ];
  const rules = () => { const myTeam = T[myRid()] || {}; return `You are the analyst for the dynasty fantasy football league "${D.league}" on Sleeper. ${myTeam.name ? `The person asking manages "${myTeam.name}" (@${myTeam.owner}); "my team" means that one.` : 'The person asking has not picked a team yet; ask which team is theirs if it matters.'}
Answer from this dashboard's data using the tools: find_player, team, evaluate_trade, league. The data was generated ${D.generated}; mention timing when it matters (injuries, news).
Rules: lead with the answer, then the 2-4 numbers that support it. Plain English, no jargon; under 200 words unless asked for more. Never invent stats, injuries, news or values: if the tools don't have it, say it isn't in the data. "Blend" projections = our model mixed with Sleeper's (it beat both on held-out 2025 games). Trade values are neutral market values; playoff odds come from simulated seasons. No betting advice.`; };
  const COPY = { not_granted: 'Claude access was declined for this page. Allow it from the page menu to ask questions.', rate_limited: 'Too many questions at once — wait a moment, then ask again.',
    session_expired: 'Your Claude session expired — sign in again, then ask.', sampling_disabled: 'Claude isn\'t available for this account here.', refused: 'Claude declined that question.',
    prompt_too_large: 'That question pulled in too much data — ask about fewer players at once.', tools_unavailable: 'This view can\'t run the analyst\'s tools.', cancelled: '' };
  // answers come back with light markdown (**bold**, "- " bullets): escape everything, then render just those two
  const md = t => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/^\s*[-*] /gm, '• ');
  async function wireAsk() {
    const box = $('an-in'), btn = $('an-ask'), stop = $('an-stop'), note = $('an-note'), out = $('an-ans');
    if (!btn) return;
    let sample = null;
    try { if (window.claude && typeof window.claude.use === 'function') sample = await window.claude.use('sample'); } catch (e) { sample = null; }
    if (!sample) {
      btn.disabled = true; box.disabled = true;
      note.textContent = 'Ask works once this dashboard is published (each question uses the viewer\'s Claude usage). The lookup and trade analyzer work everywhere.';
      return;
    }
    const turns = [];
    let ctl = null;
    stop.addEventListener('click', () => ctl && ctl.abort());
    const ask = async () => {
      const q = box.value.trim();
      if (!q) return;
      ctl = new AbortController();
      btn.disabled = true; stop.hidden = false; note.textContent = 'Thinking…'; out.textContent = '';
      turns.push({ role: 'user', content: q });
      try {
        const tools = TOOLS.map(t => ({ ...t, execute: (inp, ctx) => { note.textContent = 'Checking the data (' + t.name.replace('_', ' ') + ')…'; return t.execute(inp || {}, ctx); } }));
        const { text } = await sample([{ role: 'user', content: rules() }, { role: 'assistant', content: 'Understood. Ask away.' }, ...turns.slice(-6)],
          { signal: ctl.signal, tools, onText: ({ text }) => { out.innerHTML = md(text); note.textContent = ''; } });
        out.innerHTML = md(text); note.textContent = '';
        turns.push({ role: 'assistant', content: text });
        box.value = '';
      } catch (e) {
        turns.pop();
        out.innerHTML = e && e.text ? md(e.text) : '';
        note.textContent = (e && e.code in COPY) ? COPY[e.code] : 'Something went wrong (' + ((e && e.code) || 'error') + '). Try again.';
      } finally { btn.disabled = false; stop.hidden = true; }
    };
    btn.addEventListener('click', ask);
    box.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) ask(); });
  }

  wireLookup(); wireAnalyzer(); wireAsk();
  window.DS_ANALYST = { search, card, evaluateTrade, simulate, lineup };   // console / testing hook
})();
