# Reading a Yahoo league from its web pages

**Why this exists (2026-10-11):** since mid-2026 Yahoo's Fantasy API answers every call from a new
developer app with HTTP 403 "This application is not authorized to perform this action", even after a
good login, until Yahoo approves the app by hand (reported 2–4 weeks; see
github.com/uberfastman/yfpy/issues/84). `league_profile.py` and `fetch.py` try the API first and fall
back to the pages saved here. When Yahoo approves the app, the API path takes over by itself.

## Refreshing the snapshot (Claude does this on "update everything")

1. In the owner's Chrome (Claude in Chrome), open `https://football.fantasysports.yahoo.com/f1/<league_id>/<my team id>`.
   The owner must already be signed in to Yahoo there. Never type their password.
2. Run `ops/yahoo_web_capture.js` in that tab with the javascript tool. Set `LID` and `WEEKS` at the top
   (`WEEKS` = the current week + 1, so next week's projections come along).
3. The script swaps the page body for a `<pre>` holding the JSON. Read it with `get_page_text`
   (the javascript tool truncates long results; page text does not), and save it as
   `data/yahoo_web/snapshot.json`. Reload the tab afterwards.
4. Settings change rarely. Re-read `/f1/<league_id>/settings` only when the commissioner changes them,
   and update `data/yahoo_web/settings.json` by hand (fields match `league_profile.read_yahoo`).
5. Run `python3 update.py`.

## Known limits
- Manager names come from the team pages; check them once after the first capture.
- Trades: Yahoo lists one row per receiving team. The converter joins rows with the same timestamp
  into one trade; three-team trades lose their source side.
- Pending offers, waiver claims and league chat aren't captured. Have the owner paste them, or read
  them from the page on request.
