# Build your strategy

A guided session that turns this league's data into a written plan for your team. Run it once after setup,
again at the trade deadline and every offseason, or any time the season turns (a big trade, a bad start).

## The prompt — paste this to Claude in this folder

> Build my dynasty strategy. Run the full update first, then read my dashboards, my roster, my picks, the
> lottery tracker, the trade finder, the trade grades and the draft-class research. Show me where my team
> really stands, ask me the questions in STRATEGY.md one or two at a time, and then write my CURRENT STRATEGY
> into my profile and my_plan.json, set my king's-ransom rule in config.json, write research/DRAFT_PLAN.md, and
> update the dashboard cards. Keep it in plain English and show your numbers.

(Also triggered by "help me write my game plan". The field-by-field reference is `PLAN_INTERVIEW.md`; the
king's-ransom reference is `KINGS_RANSOM_GUIDE.md`.)

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
3. **King's ransom.** How much must a trade pay you back before you'd move a core piece? It is measured by
   league type (`KINGS_RANSOM_GUIDE.md`): **dynasty/keeper** — in long-term plan value (each piece valued across
   the plan's seasons, players aged, picks counted only from their draft year); **redraft** — in wins this season.
   Show this league's history first (the dashboard's "What's a king's ransom?" box, or `TRADE_GRADES.md`): the
   biggest trade win ever and the typical one. A common dynasty choice is "just above the biggest win this
   league has ever made." Save it in `config.json`: `"premium": {"<player_id>": {"surplus": 3000},
   "pick:2028:1:<roster_id>": {"surplus": 3000}}` (redraft: `{"wins": 0.5}`), and the same core in `my_plan.json`.
4. **How to fill the holes.** For each weak position: trade for it, draft it (which class?), or wait?
   Match holes to strong draft classes.
5. **Picks.** Which future picks to spend (as trade currency) and which to keep (target classes)?
6. **Risk and style.** Comfortable with injured or older players at a discount? Prefer many small trades or
   a few big ones? How much FAAB to spend now vs save?
7. **Checkpoints.** When do we re-decide? Suggest concrete, scoreable rules: a record by a week ("3 wins by
   week 7 or sell veterans") and/or playoff odds at a week ("under 20% at the trade deadline, sell"). Ask what
   they'd do if they miss it and if they pass. Also a playoff-odds floor for "at risk" (e.g. 20%).
8. **Keep and sell lists.** Starters they won't trade for picks; players they are actively trying to move.

Then follow up where the answers are vague or clash ("you said contend, but you'd sell your 1st at 1-3?"), raise
data they may not know (an expiring contract, an aging core), and turn every "if things go badly" into a week
and a number. **Always end by asking: "Anything else I should know?"** — pending offers, owners they won't
trade with, players they rate differently from the market. Read the plan back in plain sentences and write
it only after a yes.

### 3. Write it down (this is what makes it the plan of record)
- **`profiles/<your username>.md`** → a dated `CURRENT STRATEGY` section below the manual-notes marker:
  window, core + king's-ransom rule, positions to fix and how, picks to spend vs keep, checkpoints.
  Never delete an older strategy; mark it superseded with the date.
- **`my_plan.json`** (folder root, git-ignored) → the scoreable plan: goals by season, core + ransom, keep/sell
  lists, pick policy with held rounds, checkpoints, playoff-odds floor. Format in `PLAN_INTERVIEW.md`. The
  dashboard's **My Plan** tab tracks it every refresh, and the Trade Finder tags every offer against it.
- **`config.json`** → `premium` (king's-ransom rules for the core — the same pieces as `my_plan.json`; the
  dashboard warns if the two disagree).
- **`research/DRAFT_PLAN.md`** → which class fills which hole, which picks to keep for it.
- **`my_cards.py`** (create it as CLAUDE.md describes) → `OPEN_DECISIONS` (the 3-5 things on the clock) and `MY_ACTIONS`
  (one card per live move, plus a "Plan" card that states the strategy in two sentences).
- Re-run `python update.py` so the Trade Finder and dashboards follow the new rules, then show the owner the
  dashboard and summarize the plan in five lines.

### 4. Use it every time after
Judge every trade, waiver claim and lineup question against `my_plan.json` / `CURRENT STRATEGY`. If a move
breaks it, say so plainly and offer to revisit the plan rather than quietly bending it. When the dashboard
shows the plan "At risk", "Trigger hit", or a core player no longer on the roster, raise it and offer a short
re-plan (steps 1, 3 and the read-back).
