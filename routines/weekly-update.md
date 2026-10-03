# Routine: weekly update (suggested: Tuesdays, 8 AM local)

Paste this as a scheduled task / routine prompt in Claude Code, with this folder as its
working directory.

---

Weekly refresh of my Dynasty Scout league tracker. Read `CLAUDE.md` first.

1. Run `./update.sh` and confirm it finished without errors (report any failed step).
2. Compare to last week: my record, playoff odds (`data/pick_odds.json`), power-ranking moves,
   new trades and waiver claims across the league, and the biggest prospect-board movers
   (`research/PROSPECTS.md`).
3. Append any new intel about other owners (trades they made, needs they revealed) to their
   profiles below the MANUAL SCOUTING NOTES marker, dated. Append only.
4. Refresh stale cards in `ops/league_dashboard.py` (OPEN_DECISIONS, MY_ACTIONS, OWNER_READS),
   re-run `python3 ops/league_dashboard.py`, and republish both dashboards if a publish tool exists.
5. Brief me in under 200 words: what changed, the best 1-3 moves this week against my
   CURRENT STRATEGY, and anything with a deadline.

Do not send trades or messages. Recommend only.
