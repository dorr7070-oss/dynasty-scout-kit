// Read a Yahoo fantasy league from its web pages in the owner's signed-in browser (docs/YAHOO_WEB.md).
// Run in a tab on football.fantasysports.yahoo.com; then read the page text and save it as
// data/yahoo_web/snapshot.json.
const LID = 'YOUR_LEAGUE_ID', TEAMS = 12, WEEKS = 14;   // set LID from the league link; WEEKS = last regular-season week
const g = async u => new DOMParser().parseFromString(await fetch(u, {credentials: 'include'}).then(r => r.text()), 'text/html');
const T = s => (s || '').replace(/\s+/g, ' ').trim();
const ds = {league_id: LID, captured: new Date().toISOString(), teams: [], standings: [], weeks: {}, trades: []};
for (let t = 1; t <= TEAMS; t++) {
  const d = await g(`/f1/${LID}/${t}`);
  const body = T(d.body.innerText);
  const mg = (body.match(/([A-Za-z][A-Za-z .'-]{0,30}) \(Since '\d+\)/) || [])[1] || '';
  const players = [...d.querySelectorAll('table tbody tr')].map(tr => {
    const a = tr.querySelector('a[href*="/nfl/players/"]');
    if (!a) return null;
    const txt = T(tr.innerText);
    const tp = txt.match(/ ([A-Z][a-z]{1,2}) - ([A-Z,\/]+)/) || [];
    const inj = (txt.match(/\b(Q|O|D|IR|PUP-R|SUSP|NA)\b(?= )/) || [])[1] || '';
    return [tr.querySelector('td')?.innerText.trim(), a.getAttribute('href').split('/').pop(), a.innerText.trim(), tp[1] || '', tp[2] || '', inj];
  }).filter(Boolean);
  ds.teams.push({tid: t, name: T(d.querySelector('title')?.innerText).replace(/ \| Fantasy.*$/, '').replace(/^[^-]+ - /, ''), manager: T(mg), players});
}
const s = await g(`/f1/${LID}?lhst=stand`);
ds.standings = [...s.querySelectorAll('table tbody tr')].map(tr => {
  const a = tr.querySelector(`a[href^="/f1/${LID}/"]`);
  return a && /\/\d+$/.test(a.getAttribute('href')) ? [a.getAttribute('href').split('/').pop(), T(tr.innerText)] : null;
}).filter(Boolean).slice(0, TEAMS);
for (let w = 1; w <= WEEKS; w++) {
  const m = await g(`/f1/${LID}?matchup_week=${w}&module=matchups`);
  ds.weeks[w] = [...m.querySelectorAll('li')].filter(li => /View Matchup/.test(li.innerText)).map(li => {
    const tm = [...new Set([...li.querySelectorAll(`a[href^="/f1/${LID}/"]`)].map(a => a.getAttribute('href')).filter(h => /\/\d+$/.test(h)).map(h => h.split('/').pop()))];
    const n = T(li.innerText).match(/(-?\d+\.\d\d) (-?\d+\.\d\d) vs (-?\d+\.\d\d) (-?\d+\.\d\d)/) || [];
    return [tm, n.slice(1).map(Number)];
  });
}
const tr = await g(`/f1/${LID}/transactions?transactionsfilter=trade`);
ds.trades = [...tr.querySelectorAll('table tbody tr')].map(r => ({
  txt: T(r.innerText),
  start: parseInt(r.querySelector('td[rowspan]')?.getAttribute('rowspan') || '0'),   // first row of each trade
  ids: [...r.querySelectorAll('a[href*="/nfl/players/"]')].map(a => a.getAttribute('href').split('/').pop()),
  teams: [...r.querySelectorAll(`a[href^="/f1/${LID}/"]`)].map(a => a.getAttribute('href').split('/').pop()).filter(x => /^\d+$/.test(x)),
}));
const pre = document.createElement('pre');
pre.textContent = JSON.stringify(ds);
document.body.replaceChildren(pre);
`${ds.teams.length} teams, ${ds.teams.reduce((a, t) => a + t.players.length, 0)} players, ${Object.keys(ds.weeks).length} weeks, ${ds.trades.length} trade rows`;
