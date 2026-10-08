# The king's ransom — what it is and how to set yours

Every owner who runs Dynasty Scout sets their own. Claude makes the change for you; this file is the reference
for what the setting means and where it lives.

## What it is

No player is untouchable, but some are worth more to *your plan* than the market says. The king's ransom is the
price tag on those players and picks (your **core**): a core piece only moves when a trade pays you back by at least
a set amount. In dynasty that amount is long-term plan value; in redraft it's wins this season (next section).

Dynasty values use the 0–10,000-per-player scale that KeepTradeCut and FantasyCalc use (Dynasty Scout averages
several sources). "+3,000" means what you get back is worth at least 3,000 more to your plan than what you give.

The Trade Finder enforces it. It only suggests trading a core piece when the package clears your number, and it lists
the likeliest qualifying package from each team (the smallest overpay that still clears it), likeliest first, under "Core pieces: best package that clears your king's ransom".

## How "pays you back" is measured — it depends on your league

| League | The package must… | Why |
|---|---|---|
| **Dynasty / keeper** | beat what you give by your number in **long-term plan value** | Your core exists to serve your plan, not this week's market |
| **Redraft** | add at least your number of **expected wins this season** (default +0.5) | Nothing carries over, so only this season counts |

**Long-term plan value** = what the piece is worth in each season your plan covers (the years in your plan's
"Season by season" goals), averaged. Players age along measured curves for their position. A draft pick is worth
nothing before the year it can play and its full value from then on. So:

- a **contend-now** plan (say 2026–28) counts a 2028 pick at a third of its value and a 30-year-old at well under his
  market price, which steers ransoms toward young starters who help in all three years;
- a **rebuild** plan whose seasons run later counts picks and young players at nearly full value.

The plan's own bonuses (e.g. "fills a starting hole", "adds a pick in the class you're targeting") count too.
The league type is read from your league automatically; you don't pick the measure.

## Choosing your number

The dashboard's Core card ("What's a king's ransom, and how do I set mine?") shows **your league's own history**:
the typical trade winner's edge, the top 10%, and the most lopsided trade ever. Use those, not someone else's league.

Dynasty numbers are on the same 0–10,000 scale as market value, so your league's trade history (on the dashboard)
is still the right yardstick. Redraft numbers are in wins.

| If you want… | Set it… |
|---|---|
| Your core to almost never move | Just above your league's biggest-ever trade win |
| To hear real offers, but only great ones | Around your league's top-10% trade edge |
| Your veterans easy to sell (rebuilding) | Low, or leave veterans out of the core entirely |

Picks can be core too (e.g. a 1st in a draft class you're targeting).

## Where it lives (Claude edits both; the dashboard warns if they disagree)

1. **`my_plan.json`** — your plan, in words: `core.ransom` (the number), `core.players` (exact Sleeper names),
   `core.picks` (plain-English pick descriptions), `core.rule` (one sentence).
2. **`config.json` → `premium`** — what the Trade Finder reads. One entry per core piece:
   ```json
   "premium": {
     "4984":          {"surplus": 3000},
     "pick:2028:1:5": {"surplus": 3000}
   }
   ```
   - Players are keyed by Sleeper player id (Claude looks it up from the name).
   - Picks are keyed `pick:<year>:<round>:<original roster number>` — the team the pick originally belonged to,
     not whoever holds it now.
   - `{"surplus": N}` = dynasty: the package must beat the piece by N in long-term plan value.
     `{"wins": X}` = redraft: the trade must add X expected wins this season (or set `"ransom_wins"` once for all).
   - The measure follows the league type automatically. A plain number instead of either (e.g. `1.2`) is a lighter
     rule: the other side must pay that multiple of the piece's value.
   - Different pieces can carry different numbers.

## Changing it — say it to Claude in plain words

- "Change my king's ransom to +4,000."
- "Add Jalen Coker to my core." / "Take Antonio Williams out of my core."
- "Make my 2029 1st core at +2,000."

Claude updates `my_plan.json` and `config.json` together, re-runs the Trade Finder, and the dashboard shows the
new number. Setting it for the first time is part of the game plan interview (PLAN_INTERVIEW.md, question 3).
