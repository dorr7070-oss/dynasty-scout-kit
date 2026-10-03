# Build your strategy

A guided session that turns this league's data into a written plan for your team. Run it once after setup,
again at the trade deadline and every offseason, or any time the season turns (a big trade, a bad start).

## The prompt — paste this to Claude in this folder

> Build my dynasty strategy. Run the full update first, then read my dashboards, my roster, my picks, the
> lottery tracker, the trade finder, the trade grades and the draft-class research. Show me where my team
> really stands, ask me the questions in STRATEGY.md one or two at a time, and then write my CURRENT STRATEGY
> into my profile, set my king's-ransom rule in config.json, write research/DRAFT_PLAN.md, and update the
> dashboard cards. Keep it in plain English and show your numbers.

(Shorter works too: **"Build my strategy."** Claude follows this file either way.)

---

## For Claude: how to run the session

### 1. Do the homework before asking anything
Run `python update.py` (Windows) / `./update.sh` (Mac). Then gather, from the files this framework writes:
- **Where the team stands now:** power rank, win-now rank, playoff odds and expected finish (dashboard,
  `data/pick_odds.json`), starters vs the league by position (`ADVICE.md`), points per week projected.
- **Where it is headed:** roster ages against the age curve (`data/age_curve.json`), contract-year players
  (`data/contract_calendar.json`), injured players and how long they are likely out (`INJURIES.md`).
- **Assets:** every future pick you own and what it is worth (`LOTTERY.md`, Asset Board), market movers
  (`VALUE_TRENDS.md`), the best realistic offers available right now (`TRADE_FINDER.md`).
- **The league around you:** who is contending vs rebuilding, who trades a lot and how well
  (`TRADE_GRADES.md` — neutral market values for every owner), each owner's habits (`profiles/`).
- **Draft classes:** `research/draft-*.md` and the Prospects tab — which future class is strong at which position.

Open with a short, honest read in plain English: "You are the Nth-best team today, X% to make the playoffs,
your best assets are A and B, your window looks like ___ because ___." Numbers, not adjectives.

### 2. Ask these, one or two at a time (offer a recommendation with each)
1. **Window.** Win now (this season), contend over the next 2-3 seasons, or rebuild for later?
   Recommend one from the data (playoff odds, roster age, pick capital) and say why.
2. **Core.** Which 2-4 players or picks is the plan built around? No one is untouchable unless losing him
   truly breaks the plan, but the core only moves for a **king's ransom**.
3. **King's ransom.** How lopsided must a trade be before you'd move a core piece? Show this league's
   history first: the biggest trade win ever and the typical one (`TRADE_GRADES.md`). A common choice is
   "just above the biggest win this league has ever made." Save it in `config.json`:
   `"premium": {"<player_id>": {"surplus": 3000}, "pick:2028:1:<roster_id>": 1.2}` — `surplus` = the
   evaluation must favor you by that much on market value; a plain number = a multiplier.
4. **How to fill the holes.** For each weak position: trade for it, draft it (which class?), or wait?
   Match holes to strong draft classes.
5. **Picks.** Which future picks to spend (as trade currency) and which to keep (target classes)?
6. **Risk and style.** Comfortable with injured or older players at a discount? Prefer many small trades or
   a few big ones? How much FAAB to spend now vs save?
7. **Checkpoints.** When do we re-decide? Suggest a concrete rule, e.g. "week 7: 2-5 or worse means sell
   veterans; 5-2 or better means buy."

### 3. Write it down (this is what makes it the plan of record)
- **`profiles/<your username>.md`** → a dated `CURRENT STRATEGY` section below the manual-notes marker:
  window, core + king's-ransom rule, positions to fix and how, picks to spend vs keep, checkpoints.
  Never delete an older strategy; mark it superseded with the date.
- **`config.json`** → `premium` (king's-ransom rules for the core).
- **`research/DRAFT_PLAN.md`** → which class fills which hole, which picks to keep for it.
- **`ops/league_dashboard.py`** → `OPEN_DECISIONS` (the 3-5 things on the clock) and `MY_ACTIONS`
  (one card per live move, plus a "Plan" card that states the strategy in two sentences).
- Re-run `python update.py` so the Trade Finder and dashboards follow the new rules, then show the owner the
  dashboard and summarize the plan in five lines.

### 4. Use it every time after
Judge every trade, waiver claim and lineup question against `CURRENT STRATEGY`. If a move breaks it, say so
plainly and offer to revisit the plan rather than quietly bending it.
