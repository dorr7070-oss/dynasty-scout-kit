# Game plan interview — how Claude helps an owner write `my_plan.json`

Use this when an owner says anything like "help me write my game plan", "set up my strategy", or when the
dashboard's Game Plan card says no plan exists. The owner talks; Claude writes the file. The owner never edits JSON.

The dashboard scores the plan on every refresh (checkpoints, playoff odds vs a floor, core players still rostered,
plan vs Trade Finder). So the plan must be specific enough to score: weeks, win counts, odds, player names.

## 1. Look before asking (no questions yet)

Read the owner's data first so every question is about THEIR team, not a generic form:
`data/our_projection.json` (record, playoff odds), `data/weekly.json` (current week), their roster and top values
(`data/values/consensus.json`), their picks (`dashboards/assets.html` data or `ops/picks.py`), the league's trade
deadline and playoff weeks (`data/league_profile.json`), and any existing plan or notes in their profile.

Open with one sentence of where they stand, e.g. "You're 1-3, our model gives you 26% playoff odds, and your three
most valuable players are Jeanty, Allen and Smith."

## 2. Starter questions (ask these, a few at a time, in plain words)

1. **Window.** Are you trying to win now, rebuilding for later, or somewhere in between? For which seasons?
2. **Core.** Which players (and picks) do you want to build around? Suggest the top values and ages from step 1.
3. **Price for the core.** Is anyone truly untouchable, or does everyone have a price? If a price: how lopsided
   must a trade be before a core piece moves (the "king's ransom")? Dynasty: in long-term plan value (e.g. +3,000);
   redraft: in wins this season (e.g. +0.5). Show them their league's trade history first (KINGS_RANSOM_GUIDE.md).
4. **When would you change course?** A record by a week ("3 wins by week 7, or I sell") and/or playoff odds at a
   week ("under 20% at the trade deadline, I sell"). What do you do if you miss it, and if you pass?
5. **Draft picks.** For each upcoming year: spend them, hold them, or target that class?
6. **This season's goal**, and what next season and the one after should look like.

## 3. Follow-up questions (Claude decides — ask only what sharpens the plan)

- **Conflicts:** "You said contend, but you want to sell your 2027 1st and you're 1-3 — which wins?"
- **Vague answers:** turn "if things go badly" into a week and a record or odds number. Offer a number, ask to confirm.
- **Data they may not know:** "Your core WR is 31 and his contract ends after next season — still core?"
- **Missing pieces:** a contend plan with no checkpoint, a rebuild with no pick policy, a core with no ransom.
- **Players to keep or move:** starters they won't trade for picks; players they're actively trying to sell.

Stop when every field below can be filled with something scoreable. Don't ask for what the data already says.

## 4. Always end with an open invitation

"Anything else I should know — offers you're waiting on, owners you won't trade with, a player you're higher or
lower on than the market, plans for the offseason?" Put what fits into the plan fields; keep the rest in their
profile's manual notes.

## 5. Read it back, then write it

Summarize the plan in 5-8 plain sentences and ask "Is that right?" Write `my_plan.json` only after a yes.
Date it (`adopted` the first time, `updated` on every change). Tell them the dashboard will now track it on the
My Plan tab.

## The file (field names fixed; words are the owner's)

```json
{
  "name": "Contend 2026–28",
  "adopted": "YYYY-MM-DD", "updated": "YYYY-MM-DD",
  "mode": "contend | rebuild | balanced",
  "summary": "One or two sentences in the owner's words.",
  "goals": {"2026": "...", "2027": "...", "2028": "..."},
  "core": {
    "rule": "Plain-English ransom rule.",
    "ransom": 3000,
    "players": ["Exact Sleeper names"],
    "picks": ["Plain-English pick descriptions"]
  },
  "keep_starters": {"players": ["Exact Sleeper names"], "rule": "Not for picks: each starts (optional)."},
  "sell": ["Players they are trying to move (optional)"],
  "picks": {"2027": {"text": "Spend", "hold_rounds": []}, "2028": {"text": "Hold both 1sts", "hold_rounds": [1]}},
  "checkpoints": [
    {"week": 7, "label": "Week-7 check", "min_wins": 3, "if_missed": "...", "if_met": "..."},
    {"week": 11, "label": "Trade-deadline check", "min_odds": 0.20, "if_missed": "...", "if_met": "..."}
  ],
  "playoff_odds_floor": 0.20
}
```

The Trade Finder's plan check uses these fields: offers that give a held round, trade a keep-starter for picks only,
take back a sell-list player, or buy while the plan says sell drop to the bottom. See KINGS_RANSOM_GUIDE.md for the ransom.

Player names must match Sleeper's spelling exactly, or the roster check marks them missing.
If the ransom changes, also set the matching `premium` entries in `config.json` so the Trade Finder protects the
same players; the dashboard flags any mismatch between the two.

## Keeping it current

Re-run a short version (steps 1, 3, 5) when the dashboard flags the plan: a core player gone, a checkpoint hit, a
plan-vs-Trade-Finder mismatch, or a new season.
