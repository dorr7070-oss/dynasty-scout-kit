# Routine: Sunday lineup check (suggested: Sundays 5:30 AM Arizona / 8:30 AM ET)

International games can kick off around 9:30 AM ET, so run early enough to cover them.
Paste as a scheduled task / routine prompt, with this folder as its working directory.

---

Game-day start/sit check on my dynasty roster (league details in `LEAGUE.md`). Read `CLAUDE.md` first.
My username is in `config.json`.

1. Read my live lineup: my league's team page in the browser if available (Sleeper, ESPN or Yahoo),
   otherwise the latest pulled rosters plus `https://api.sleeper.com/projections/nfl/<season>/<week>`. Get each player's
   kickoff time, projection and injury tag.
2. Search the news for every Questionable/Doubtful/Out starter and notable teammates.
   A Questionable player is projected as if healthy; a player ruled Out is projected 0.
3. Search this week's betting lines; implied team total = total/2 ± spread/2. Flag any starter
   whose team is implied under ~18 points.
4. Compare my set lineup to the best legal lineup. Don't recommend swaps under ~2 projected
   points. The binding deadline for a swap is the earliest kickoff involved.
5. If a starter is ruled Out and a bench player at a legal slot plays later or at the same time,
   name the swap and the deadline. If a late-game starter is Questionable with no later backup, say so.

Output under 250 words, verdict first ("No changes needed" or "ACTION by <time>: ...").
Do not change the lineup unless I've told you to in this session.
