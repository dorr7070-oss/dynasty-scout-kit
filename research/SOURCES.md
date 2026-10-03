# College & draft-class sources — what we use, and how we reach it

_Access tested from this Mac on 2026-10-02 with plain `curl` (what scheduled routines can use) and the logged-in
Chrome session. "Automated" = pulled by a script every week. Re-test a source before declaring it dead; a 403
today can be a bot wall that Chrome gets past._

| Source | What it gives | Access (10-02) | How we use it |
|---|---|---|---|
| **KeepTradeCut devy rankings** | ~100 college players with 1QB values, draft class, trend, returning-to-school flag | ✅ curl (JSON in the page) | **Automated:** `ops/prospects.py` → `data/prospects.json`, `research/PROSPECTS.md`, Asset Board "Prospects" tab. Weekly snapshots in `data/prospects/` |
| KeepTradeCut dynasty rankings + trade calculator | Pick values (2027-29 Early/Mid/Late) on the same scale | ✅ curl / Chrome | Pricing trades; comparing a pick to a prospect |
| DraftSharks rookie & devy rankings | 2027 and 2028 rookie rankings, devy top lists with commentary | ✅ curl | Read by the class-refresh routines |
| Dynasty Nerds rookie big board + 1QB mocks | Rookie big board, 1QB rookie mock drafts | ✅ curl (free articles) | Read by the class-refresh routines. Their full devy tools are paid (see below) |
| FantasyPros devy top 300 | Devy consensus ranking | ✅ curl | Read by the class-refresh routines |
| 247Sports composite recruiting rankings | Recruiting stars/rank for each high-school class (2029-2030 pipeline) | ✅ curl | Pedigree check for 2028-2029 names |
| ESPN (Jordan Reid / Mel Kiper boards, team stats) | NFL-side big boards, college stats pages | ⚠️ articles return 202/empty to curl; work in Chrome | Read in Chrome during refreshes |
| PFF draft big board | NFL big board (full grades are paid) | ✅ curl (free board only) | NFL-side cross-check |
| NFL Mock Draft Database | Consensus big board + 1QB rookie consensus | ❌ 403 to curl (bot wall) | Try in Chrome during refreshes |
| On3 / Rivals industry rankings | Recruiting composite | ❌ 403 to curl | Chrome only |
| Sports-Reference CFB | College stat tables | ❌ 403 to curl | Chrome only |
| cfbstats.com | College game logs | ❌ timed out | Chrome only |
| **CollegeFootballData.com API (CFBD)** | Every college player's stats, usage, recruiting ranks, transfer portal — structured, free | ✅ once the free key is saved | **Automated:** `ops/cfbd.py` (after prospects.py) adds this season's stat line + usage share to every board player and lists transfer-portal moves. Key lives in `~/.config/dynasty-scout/cfbd_key`, saved with `ops/set_cfbd_key.sh`. Get your own free key (see CLAUDE.md) |
| Paid: Dynasty Nerds Dynasty Pass, DLF Premium, Campus2Canton, The Devy Royale, PFF+, The Athletic (Brugler) | Full devy boards, tiers, prospect write-ups, college grades | ❌ paywalled | Optional, paid |
