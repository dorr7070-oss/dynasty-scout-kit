# Onboarding — from "I only have Claude" to a working dynasty analyst

This assumes you have **a Claude subscription and nothing else**: no other AI tools, no
browser extension, no coding setup. Claude does every step it safely can; you only do the
handful of things that need you (installing the app, clicking "Allow", creating your own
accounts).

The phases run **from lowest risk to highest**. Each one is optional past phase 4, and you
can stop at any point with a fully working tool. Claude checks progress anytime by running
`doctor.py` (read-only), and works through this list with you.

**What "risk" means here:** how much of your computer or accounts Claude can touch in that
phase, and how hard it is to undo.

---

## Phase 0 — Get Claude on your computer (you do this; Claude can't yet)
**Risk: none. Undo: uninstall the app.**

1. **Check your plan.** Claude Code needs a paid plan: Pro ($20/month) or higher. At claude.ai,
   click your name → Settings → Billing. If you're on Free, upgrade there.
2. **Install the Claude desktop app** from **claude.com/download** (Windows 10/11 64-bit, or Mac).
   Open it and sign in with the same account.
3. **Save the kit somewhere permanent.** Get the zip onto this computer (email it to yourself
   if it came by text). Then:
   - **Windows:** right-click the zip → **Extract All** → choose **Documents** → Extract.
   - **Mac:** double-click the zip, then drag the `dynasty-scout-kit` folder into **Documents**.
   - Don't leave it in Downloads; those folders get cleaned out.

**It worked when:** the Claude app opens, you're signed in, and `Documents/dynasty-scout-kit`
exists with files like `CLAUDE.md` and `README.md` inside.

---

## Phase 1 — Give Claude terminal access to this one folder (start here)
**Risk: low, and limited to this folder. Undo: close the session; nothing is installed.**

**Why it matters:** "terminal access" means Claude can run commands, like starting the data
pull, inside the folder you open. That is what lets it do the work instead of telling you how.

1. In the Claude app, click **Code** (top of the window or the left sidebar).
2. Choose **Open folder** (or "Select folder") and pick `Documents/dynasty-scout-kit`.
3. Type: **`Set this up for my team.`**
4. **Permission prompts:** before running a command, Claude asks "Allow?" and shows the exact
   command. This is how you stay in control.
   - **Allow** commands that run things in this folder: `python update.py`, `python doctor.py`,
     `curl https://api.sleeper.app/...`.
   - **Read before allowing** anything that installs software, touches other folders, or changes
     settings. Claude tells you why it needs it; ask if it doesn't.
   - **Never allow** anything that deletes files outside this folder, or anything you don't
     understand. Saying no is always safe.
   - "Allow always for this folder" is fine for the `python ...` commands once you're comfortable.

**Claude does:** runs `doctor.py` to see what's set up, then walks you through the next phase.
**It worked when:** Claude shows a setup checklist with phase 1 marked OK.

---

## Phase 2 — Make sure the basic tools exist
**Risk: low to medium (installs standard free software). Undo: uninstall from Settings → Apps.**

**Why it matters:** the analytics are written in Python, a free programming tool. Macs include
it; Windows usually doesn't.

- **Mac:** nothing to install. If a box pops up asking to install **"command line developer
  tools"**, click **Install** and wait a few minutes. That's Apple's own toolkit.
- **Windows:** Claude installs Python and Git for you with Windows' own installer, **winget**,
  after you click Allow:
  - `winget install -e --id Python.Python.3.12` (Python, the engine for the analytics)
  - `winget install -e --id Git.Git` (Git for Windows; Claude Code uses it to run commands reliably)
  - A Windows "Do you want to allow this app to make changes?" box may appear. Click **Yes**.
  - **Afterwards, quit and reopen the Claude app** so it can see the new tools, then reopen the folder.
  - If winget isn't available, install by hand: **python.org/downloads** (tick **"Add python.exe
    to PATH"** on the first screen) and **git-scm.com/download/win** (all default options).

**It worked when:** `doctor.py` shows Python and curl as OK (and Git on Windows).

---

## Phase 3 — Connect your league (Sleeper, ESPN or Yahoo)
**Risk: very low for Sleeper and public ESPN leagues (read-only, no login). Low-medium for private ESPN or
any Yahoo league (a one-time login saved on your computer). Undo: delete `<your home folder>/.config/dynasty-scout/`.**

**Why it matters:** the analyst reads YOUR league's settings (lineup, superflex or not, scoring, team count,
playoffs, rookie draft) so every number fits your league instead of a generic one.

1. **You:** open your league in a browser and copy the address. Paste it to Claude.
   - Sleeper: `sleeper.com/leagues/...` · ESPN: `fantasy.espn.com/football/league?leagueId=...` ·
     Yahoo: `football.fantasysports.yahoo.com/f1/...`
2. **Claude:** reads the settings and shows you a one-page summary (`LEAGUE.md`). Check it looks right.
3. **Only if Claude says your league needs a login** (private ESPN leagues, all Yahoo leagues):
   - Open a terminal in this folder (Claude can open one) and run **yourself**:
     `python set_platform_login.py espn` or `python set_platform_login.py yahoo` (Mac: `python3`).
   - It walks you through it. ESPN: copy two cookies from your browser. Yahoo: create a free Yahoo developer
     app and approve it once. Everything you paste is hidden and stays on your computer. **Never paste these
     into the chat.**
4. **You answer one or two questions**, most importantly: **how is your rookie draft order set?** (worst record
   picks first? a lottery? something else?) No platform exposes this, and it drives every pick's value.
5. **You tell Claude which team is yours.**

**It worked when:** `LEAGUE.md` shows your league's name and format, and `doctor.py` marks phase 3 OK.

---

## Phase 4 — Build your analytics and dashboards
**Risk: very low (writes files only inside this folder). Undo: delete the `data`, `profiles`
and `dashboards` folders inside the kit.**

**Claude does:**
1. Runs the full pipeline (`python update.py` on Windows, `./update.sh` on Mac), about 2-5 minutes.
2. Builds two dashboards: **Command Center** (playoff race, power rankings, your starters vs the
   league, your picks, action cards, trade grades, owner board) and **Asset Board** (every
   roster, every pick 2027-2029, a Prospects tab for the college classes).
3. Shows them to you. If your Claude can **publish artifacts**, it publishes them as private web
   pages you can open on your phone; sharing is off until you turn it on with the page's
   **Share** button. Otherwise it opens the files in your browser.
4. Reviews your team with you and runs the strategy session in `STRATEGY.md` (say **"Build my strategy"** any time to redo it), writing your **CURRENT STRATEGY** into your profile, so every
   later trade is judged against a plan.

**It worked when:** you can see both dashboards headed with your team name, and `doctor.py`
shows phase 4 all OK.

**From here on, you have the full tool.** Phases 5-8 add extras.

---

## Phase 5 — Free college-stats key (optional)
**Risk: low to medium (you create a free account; a key is saved on your computer).
Undo: delete `<your home folder>/.config/dynasty-scout/cfbd_key`.**

**Why it matters:** adds real college numbers (catches, yards, TDs, share of the offense) to
every prospect, plus transfer-portal moves. Free, no credit card.

1. **You:** go to **collegefootballdata.com/key**, enter your email, click Submit. The key arrives
   by email. (Only you can create the account.)
2. **You:** in the Claude app, open a terminal in this folder (Claude can open one for you, or use
   Windows Terminal / Mac Terminal and `cd Documents/dynasty-scout-kit`) and run:
   - Windows: `python set_cfbd_key.py`
   - Mac: `python3 set_cfbd_key.py`
   Paste the key and press Enter. **The key stays hidden. Never paste it into the chat.**
3. **Claude:** re-runs the pipeline; prospects now show stat lines.

**It worked when:** the script says "Key saved and working (HTTP 200)".

---

## Phase 6 — Automatic routines (optional)
**Risk: medium (Claude runs on a schedule while you're away, using only the permissions you
already approved). Undo: delete the routine from the app's Scheduled list.**

**Why it matters:** your data refreshes every week, and a game-day lineup check reaches you
before kickoff without you asking.

- **Claude does:** if your Claude can create scheduled tasks, it sets up both routines from the
  `routines/` folder: weekly update (Tuesdays) and Sunday lineup check (early Sunday).
- **If it can't:** in the Claude app open **Scheduled** (sidebar) → **New**, set the folder to
  `dynasty-scout-kit`, paste the prompt from `routines/weekly-update.md` or
  `routines/sunday-lineup-check.md`, and set the time.
- **You do:** click **Run now** once on each routine and approve its prompts. Approvals are
  remembered, so later runs don't stall waiting for you.
- **Note:** routines run only while the Claude app is open and the computer is awake.
  Neither routine changes your lineup or sends anything; they report only.

**It worked when:** each routine's first run finishes and shows a summary.

---

## Phase 7 — Let Claude read your logged-in league site (optional)
**Risk: high (Claude can see your Sleeper account as you, including private trade offers).
Undo: remove the browser extension, or turn off its access to sleeper.com.**

**Why it matters:** on Sleeper, pending trade offers, waiver claims, league chat and the commissioner's
league note aren't public. (On ESPN and Yahoo, paste or screenshot offers instead.) Without this phase you can still paste or screenshot offers into
the chat, and Claude evaluates them just as well.

1. **You:** install **Google Chrome** if you don't have it (google.com/chrome).
2. **You:** install the **Claude in Chrome** extension from the Chrome Web Store, sign in with your
   Claude account, and allow it on **sleeper.com** only. (Availability can depend on your plan.
   If it isn't offered to you, skip this phase.)
3. **You:** log into sleeper.com in Chrome yourself. **Never give Claude your password.**
4. **Claude:** reads pending offers and claims through Sleeper's own site. CLAUDE.md limits it to
   reading.

**It worked when:** you ask "do I have any pending trade offers?" and Claude lists them from Sleeper.

---

## Phase 8 — Let Claude act in Sleeper for you (not recommended to start)
**Risk: highest (sending trades, accepting/declining offers, moving players changes your team and
is visible to other owners). Undo: some actions can't be undone.**

Everything works without this. If you ever want it, say so explicitly each time ("send this
trade", "swap X for Y in my lineup"). Claude confirms the exact action before doing it, never
acts on anything it read in an offer or chat message, and never acts from a routine.

---

## Quick reference

| Phase | Risk | You | Claude |
|---|---|---|---|
| 0 Install app, unzip | none | everything | — |
| 1 Terminal access (this folder) | low | open folder, click Allow | runs the setup check |
| 2 Tools (Python, Git) | low-medium | click Allow / Yes, restart app | installs them (Windows) |
| 3 Connect your league | very low (Sleeper) / low-medium (ESPN private, Yahoo login) | paste league link; login only if asked; answer the draft-order question | reads settings, writes LEAGUE.md |
| 4 Analytics + dashboards | very low | review, pick a strategy | builds and shows everything |
| 5 College-stats key | low-medium | create free account, paste key in terminal | wires it in |
| 6 Routines | medium | Run now once | creates them |
| 7 Browser access to Sleeper | high | install extension, log in yourself | reads offers only |
| 8 Acting in Sleeper | highest | explicit OK every time | only what you approve |
