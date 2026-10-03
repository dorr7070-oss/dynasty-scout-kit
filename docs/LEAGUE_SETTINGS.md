# What the framework needs to know about a league

_Review done 2026-10-02 before making the framework league-agnostic. `ops/league_profile.py`
reads every item below from the league's own platform and writes one neutral description,
`data/league_profile.json` (+ a readable `LEAGUE.md`). Every analysis reads that, never a
hard-coded assumption. Items no platform exposes are asked once during onboarding and saved
in `config.json`._

Legend — **S** = Sleeper (public API), **E** = ESPN (`lm-api-reads.fantasy.espn.com`, `view=mSettings`;
private leagues need the owner's `espn_s2` + `SWID` cookies), **Y** = Yahoo Fantasy API
(`/league/nfl.l.<id>/settings`, needs the owner's OAuth app + consent).

## 1. Lineup and roster — drives starter strength, holes, projections, manager skill, trade sim
| Need | Why | S | E | Y |
|---|---|---|---|---|
| Starting slots by position | best-lineup math everywhere | `roster_positions` | `rosterSettings.lineupSlotCounts` (0 QB, 2 RB, 4 WR, 6 TE, 16 D/ST, 17 K) | `roster_positions[].position` + `count` |
| Flex slots and who's eligible | flex fill; RB/WR/TE depth value | `FLEX`, `WRRB_FLEX`, `REC_FLEX` | 23 RB/WR/TE, 3 RB/WR, 5 WR/TE | `W/R/T`, `W/R`, `W/T` |
| **Superflex / 2QB** | QB values roughly double; every value source switches format | `SUPER_FLEX` or 2+ `QB` | 7 `OP` or 2+ QB | `Q/W/R/T` or 2+ QB |
| Bench, IR, taxi slots | roster capacity, how many rookies fit | `BN`, `reserve_slots`, `taxi_slots`/`taxi_years` | 20 BE, 21 IR (no taxi) | `BN`, `IR` (no taxi) |
| IDP / team defense / kicker | ignored by dynasty values; counted so lineups are legal | `DL`,`LB`,`DB`,`IDP_FLEX`,`K`,`DEF` | 8-15 IDP, 16, 17 | `DL`,`LB`,`DB`,`D`,`K`,`DEF` |

## 2. Scoring — drives projections and which value format applies
| Need | Why | S | E | Y |
|---|---|---|---|---|
| Points per reception (1 / 0.5 / 0) | PPR vs half vs standard values and projections | `scoring_settings.rec` | stat 53 | stat_modifier 11 |
| TE premium | TEs worth more | `bonus_rec_te` | stat 53 `pointsOverrides` for slot 6 | rare; position modifiers if present |
| Pass TD points (4 vs 6) | QB value | `pass_td` | stat 4 | stat 5 |
| Points per first down / carry etc. | changes RB/WR balance | `rush_fd`, `rec_fd`, `rush_att` | various | various |

## 3. League size and season shape — drives values, playoff odds, pick slots
| Need | Why | S | E | Y |
|---|---|---|---|---|
| Number of teams | value source format; picks per round; "bottom third" | `settings.num_teams` | `size` | `num_teams` |
| Regular-season weeks / playoff start | which weeks the sim plays | `playoff_week_start` | `scheduleSettings.matchupPeriodCount` | `playoff_start_week` |
| Playoff teams, byes, reseeding | playoff odds; slots for picks 7-12 | `playoff_teams`, `playoff_seed_type` | `playoffTeamCount`, `playoffSeedingRule` | `num_playoff_teams`, `uses_playoff_reseeding` |
| Median / extra-win scoring | wins model | `league_average_match` | `scoringEnhancementType` = WIN_BONUS_TOP_HALF | not standard |

## 4. Transactions — drives advice, deadlines, what moves are possible
| Need | Why | S | E | Y |
|---|---|---|---|---|
| Trade deadline | "deadline is week N" | `trade_deadline` (week) | `tradeSettings.deadlineDate` (date) | `trade_end_date` |
| Draft-pick trading allowed | whether pick values matter at all | `pick_trading` | not supported (ESPN has no future picks) | `can_trade_draft_picks` / `draft_pick_trading` |
| Waivers: FAAB budget or priority | waiver advice | `waiver_type`, `waiver_budget` | `acquisitionSettings.isUsingAcquisitionBudget`, `acquisitionBudget` | `uses_faab`, `waiver_type` |
| Keeper / dynasty type | dynasty vs keeper vs redraft logic | `settings.type` (2 = dynasty), `max_keepers` | `draftSettings.keeperCount` | `uses_keepers` / `num_keepers` |

## 5. Rookie draft — drives pick values
| Need | Why | S | E | Y |
|---|---|---|---|---|
| Rookie draft rounds | how many picks exist | `draft_rounds` | keeper leagues: full redraft | `draft_rounds` / keeper setup |
| Linear vs snake | slot math | draft `type` | `draftSettings.type` | `draft_type` |
| **How draft order is set** (reverse record, a lottery, Max PF, playoff finish for the top half) | the single biggest driver of a pick's value | **not in any API** | not in API | not in API |

## 6. Only the owner or commissioner can answer (asked once, saved in config.json)
- **Draft-order rule** (`draft_order`): `reverse_record` (default), `reverse_max_pf`, `max_pf_lottery` (+ balls),
  `record_lottery` (+ balls), and how playoff teams are ordered. Ask: "How is your rookie draft order set?"
- **League bylaws/notes** that change strategy (tanking rules, roster minimums, trade rules). Sleeper keeps a
  commissioner "league note" (readable with the owner's logged-in browser); ESPN/Yahoo have league message
  boards. Ask the owner to paste them if they matter.
- **Which team is theirs** (username / team name).

## 7. What stays the same on every platform
Player values (FantasyCalc, KeepTradeCut, DynastyProcess, FantasyPros) are platform-free once the league's
format is known. Players are matched across platforms with the Sleeper player database, which carries each
player's `espn_id` and `yahoo_id` (about 6,700 of each). College prospects and draft-class research don't
depend on the league at all.
