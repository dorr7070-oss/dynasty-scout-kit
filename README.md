# Dynasty Scout

A dynasty fantasy football analyst for **any Sleeper, ESPN or Yahoo league**, run by Claude on your own
computer. It reads your league's own settings (lineup, superflex or not, scoring, playoffs, rookie
draft) and fits every number to them. You talk to it in plain English; it runs the data work itself.

## What you need

- **A Claude plan that includes Claude Code:** Pro or higher. Check at claude.ai → your name → Settings → Billing.
- **The Claude desktop app:** [claude.com/download](https://claude.com/download). Install it and sign in.
- **A Windows 10/11 PC or a Mac.** A phone can view the dashboard later, but setup needs a computer.

You don't need to know how to code. Claude installs anything else it needs (Python and Git on
Windows) after you click **Allow**.

## Get it (pick one)

**Option A: let Claude download it (recommended, updates arrive automatically)**
1. Open the Claude app and click **Code**.
2. Open your **Documents** folder.
3. Type: `Set up Dynasty Scout for my team from https://github.com/dorr7070-oss/dynasty-scout-kit`

**Option B: download the zip**
1. Click this link to download it: [dynasty-scout-kit (zip)](https://github.com/dorr7070-oss/dynasty-scout-kit/archive/refs/heads/main.zip)
   (or, on this page, the green **Code** button → **Download ZIP**). Inside, `START HERE.txt` has these steps too.
2. Unzip it into **Documents** (Windows: right-click → Extract All; Mac: double-click, then drag the
   folder into Documents). Don't leave it in Downloads.
3. In the Claude app click **Code** → **Open folder** → pick the folder, and type: `Set this up for my team.`

A zip copy links itself to this page the first time it runs, and updates itself from then on.

## What happens next (about 10 minutes the first time)

Claude walks you through `ONBOARDING.md`. It asks you for three things:
1. **Your league's web address.** Copy it from your browser.
2. **Which team is yours.**
3. **How your rookie draft order is set** (worst record first, a lottery, something else). No platform
   publishes this, and it drives every draft pick's value.

ESPN private leagues and all Yahoo leagues need a one-time login. Claude has you type it yourself in
a terminal, hidden. **Never paste a password, cookie or key into the chat.**

Before each command Claude shows it and asks **Allow?** Allow the ones that run inside this folder.
Read anything that installs software or touches other folders first. Saying no is always safe.

**It worked when** the dashboard opens with your team name at the top.

## Using it

Just ask: "update everything", "run a review", "should I take this trade?", "set my lineup",
"build my strategy", "who are the top 2028 prospects?"

**The dashboard** (`dashboards/hub.html`) has tabs: This Week (game day, lineup call, actions),
Trades (offer finder, trade analyzer, grades), Season (playoff race, projections), Players (lookup,
injuries, market movers), League (power rankings, owner profiles), Picks (every roster and pick
2027-2029, college prospects) and Ask.

## Updates

- **GitHub copy:** every time you say "update everything", it pulls the newest version first. Your
  settings, data, notes and dashboard are never touched. To update on demand, say "get the latest version".
- **Older copy that won't update** (for example one from an emailed zip): open it in Claude's Code tab and type
  `Update Dynasty Scout from https://github.com/dorr7070-oss/dynasty-scout-kit`. Claude links it and keeps your settings.

## Your privacy

Everything runs on your computer. Your league settings, notes on other owners and dashboard stay in
your folder and are never uploaded by an update. Claude never sends a trade or message without your OK.

## If something goes wrong

Paste the error into Claude in the same window. It usually fixes it on the spot. `doctor.py` shows
which setup steps are done; ask Claude to "run the setup check".

Optional extras (free college stats, automatic weekly and Sunday-lineup routines, letting Claude read
your pending Sleeper offers) are in `ONBOARDING.md`, phases 5-8.
