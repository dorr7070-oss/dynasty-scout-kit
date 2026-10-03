# Dynasty Scout — starter kit

A dynasty fantasy football analytics framework for **any Sleeper, ESPN or Yahoo league**,
built to be run by Claude Code. It reads your league's own settings (lineup, superflex, scoring,
playoffs, rookie draft) and adapts every analysis to them.

## Setup (5-15 minutes)

**Start with `ONBOARDING.md`.** It walks you through everything from "I only have Claude" to a working
analyst, ordered from lowest to highest risk, and Claude does most of it for you.

**You need:** a paid Claude plan that includes Claude Code (Pro or higher) and the Claude desktop app
(claude.com/download). Works on Windows 10/11 (64-bit) or a Mac.

**Windows only, before the first run:**
- Install **Python** from https://www.python.org/downloads/ and tick **"Add python.exe to PATH"** on the
  first installer screen.
- Install **Git for Windows** from https://git-scm.com/download/win (all default options). Claude Code
  uses it to run commands reliably.

Then:
1. Get the folder. **From GitHub (recommended — updates arrive automatically):** in the Claude app's
   Code tab, open your Documents folder and say "Clone <the repo link you were sent> here", or run
   `git clone <link>` yourself. **From a zip:** unzip it somewhere permanent (Windows: right-click →
   Extract All → put it in Documents).
2. Open it in Claude Code (desktop app: Code tab → open folder; terminal: `cd` into it and run `claude`).
3. Say: **"Set this up for my team."** Claude reads `CLAUDE.md`, asks you to paste your league link,
   runs the pipeline and builds your dashboards.

A GitHub copy updates itself every time you say "update everything" (it pulls the latest framework
first; your settings, data and notes are never touched).

Then just talk to it: "update everything", "run a review", "should I take this trade?",
"set my lineup", "who are the top 2028 prospects?"

## What you get

- **Command Center dashboard:** playoff race, power rankings, your starters vs the league,
  your picks, your action cards, trade grades, an owner board.
- **Asset Board:** every team's roster and 2027-2029 picks, plus a Prospects tab charting each
  college class against your picks on the same value scale.
- **Trade analysis** on KeepTradeCut (in your league's format) and league-calibrated values, plus playoff-odds simulation.
- **Draft-order model** for your league's rule (reverse record, lotteries, Max PF), so pick values are realistic.
- **Lottery Tracker:** every team's next 1st and 2nd: who owns it, its top-3 and #1 odds, its value, and how that moves week to week (LOTTERY.md + dashboard).
- **Weekly start/sit:** your best lineup vs the one you set, using injuries, practice reports, Vegas lines, backup-QB starts and the stadium forecast.
- **Owner profiles** that learn each manager's habits; your notes stay private to your machine.

Optional: a free CollegeFootballData.com key adds real college stats to every prospect
(run `python set_cfbd_key.py` on Windows or `python3 set_cfbd_key.py` on Mac and paste the key at the hidden prompt).

Requirements: Windows 10/11 or macOS, Python 3, and Claude Code. On a Mac, Python is built in.
