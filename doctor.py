#!/usr/bin/env python3
"""Setup checker — tells you (and Claude) exactly which onboarding steps are done.

    python doctor.py       (Windows)
    python3 doctor.py      (Mac / Linux)

Read-only: it changes nothing. Each line is OK, TODO (with the next action) or INFO.
Runs with only the Python standard library, so it works before anything else is set up.
"""
import json, os, platform, shutil, subprocess, sys, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


def ensure_config(root):
    """config.json is personal and git-ignored; the repo ships config.template.json. Create it once."""
    import shutil
    cfg, tpl = os.path.join(root, 'config.json'), os.path.join(root, 'config.template.json')
    if not os.path.exists(cfg) and os.path.exists(tpl):
        shutil.copy(tpl, cfg)


ensure_config(ROOT)
OK, TODO, INFO = 'OK  ', 'TODO', 'INFO'
rows = []


def add(status, step, detail):
    rows.append((status, step, detail))


def reach(url, headers=None):
    """HTTP status for url, fetched the way the pipeline fetches: with curl. (Python's own
    downloader can fail on some sites, e.g. Mac's built-in Python vs KeepTradeCut's TLS,
    while curl works; testing with curl reports what the pipeline will actually see.)"""
    hdr = ''.join(f'{k}: {v}\n' for k, v in (headers or {}).items())
    if shutil.which('curl'):
        try:
            r = subprocess.run(['curl', '-s', '-o', os.devnull, '-w', '%{http_code}', '-m', '25',
                                '-A', 'Mozilla/5.0', '-H', '@-', url],
                               input=hdr, capture_output=True, text=True, timeout=40)
            code = int(r.stdout.strip() or 0)
            return code or None
        except Exception:
            return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', **(headers or {})})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def main():
    win = platform.system() == 'Windows'
    py = 'python' if win else 'python3'
    add(INFO, 'Computer', f'{platform.system()} {platform.release()} · Python {platform.python_version()}')

    # Phase 1 — terminal access (if this script is running, Claude has it)
    add(OK, '1. Terminal access', 'This check is running, so Claude can run commands in this folder')

    # Phase 2 — tools
    add(OK if sys.version_info >= (3, 8) else TODO, '2. Python 3.8+',
        f'Python {platform.python_version()}' if sys.version_info >= (3, 8) else 'Update Python (python.org/downloads)')
    add(OK if shutil.which('curl') else TODO, '2. curl',
        'found' if shutil.which('curl') else 'Windows 10/11 and macOS include curl; update Windows or install curl')
    if win:
        add(OK if shutil.which('git') else TODO, '2. Git for Windows',
            'found' if shutil.which('git') else 'Claude can install it: winget install --id Git.Git -e (asks you first)')

    # Phase 3 — public data sources (read-only, no login)
    for name, url in [('Sleeper API', 'https://api.sleeper.app/v1/state/nfl'),
                      ('KeepTradeCut', 'https://keeptradecut.com/dynasty-rankings?format=1'),
                      ('FantasyCalc', 'https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=1&numTeams=12&ppr=1')]:
        code = reach(url)
        add(OK if code == 200 else TODO, f'3. Reach {name}',
            'reachable' if code == 200 else f'not reachable (HTTP {code}) — check the internet connection or a firewall')

    # Phase 3 — your league (any platform)
    cfg = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
    prof_path = os.path.join(ROOT, 'data', 'league_profile.json')
    if not cfg.get('league_id'):
        add(TODO, '3. League connected', f'Paste your league link to Claude (it runs: {py} ops/league_profile.py "<link>")')
    elif not os.path.exists(prof_path):
        add(TODO, '3. League settings read', f'Run: {py} ops/league_profile.py   (ESPN private / Yahoo: {py} set_platform_login.py espn|yahoo first)')
    else:
        prof = json.load(open(prof_path, encoding='utf-8'))
        add(OK, '3. League settings read', f"{prof.get('name')} on {prof.get('platform')} — {prof.get('format_label')} (see LEAGUE.md)")
    add(OK if cfg.get('draft_order') else TODO, '3. Draft-order rule',
        cfg['draft_order'].get('rule') if cfg.get('draft_order') else 'Tell Claude how your rookie draft order is set (saved as draft_order in config.json)')
    me = cfg.get('my_username', '').strip()
    users_ok = None
    try:
        seasons = sorted(json.load(open(os.path.join(ROOT, 'data', 'seasons.json'))))
        names = {u.get('display_name', '').lower(): u.get('display_name') for u in
                 json.load(open(os.path.join(ROOT, 'data', seasons[-1], 'users.json'), encoding='utf-8'))}
        users_ok = names.get(me.lower()) if me else None
    except (OSError, ValueError, IndexError):
        pass
    if not me:
        add(TODO, '3. Your team', 'Tell Claude which team is yours; your display name goes in config.json')
    elif users_ok == me:
        add(OK, '3. Your team', f'{me} is in the league')
    elif users_ok:
        add(TODO, '3. Your team', f'Spelled differently in the league: use "{users_ok}"')
    else:
        add(INFO, '3. Your team', f'"{me}" will be checked after the first data pull')

    # Phase 4 — analytics built
    have_data = os.path.exists(os.path.join(ROOT, 'data', 'values', 'consensus.json'))
    add(OK if have_data else TODO, '4. First data pull',
        'done' if have_data else f'Run: {py} update.py')
    dash = [f for f in ('league.html', 'assets.html') if os.path.exists(os.path.join(ROOT, 'dashboards', f))]
    add(OK if len(dash) == 2 else TODO, '4. Dashboards built',
        'dashboards/league.html, dashboards/assets.html' if len(dash) == 2 else f'Run: {py} update.py')
    pf = os.path.join(ROOT, 'profiles', f'{me}.md') if me else ''
    has_strat = bool(pf) and os.path.exists(pf) and 'CURRENT STRATEGY' in open(pf, encoding='utf-8').read()
    add(OK if has_strat else TODO, '4. Your strategy written down',
        'CURRENT STRATEGY is in your profile' if has_strat else 'Ask Claude: "review my team and help me pick a strategy"')

    # Phase 5 — free college-stats key (you create the account)
    kp = os.path.join(os.path.expanduser('~'), '.config', 'dynasty-scout', 'cfbd_key')
    if os.environ.get('CFBD_API_KEY') or os.path.exists(kp):
        key = os.environ.get('CFBD_API_KEY') or open(kp, encoding='utf-8').read().strip()
        code = reach('https://api.collegefootballdata.com/player/search?searchTerm=Smith',
                     {'Authorization': f'Bearer {key}'})
        add(OK if code == 200 else TODO, '5. College-stats key',
            'saved and working' if code == 200 else f'saved but the test returned HTTP {code} — run {py} set_cfbd_key.py again')
    else:
        add(TODO, '5. College-stats key (optional)', f'Get a free key at collegefootballdata.com/key, then run {py} set_cfbd_key.py yourself')

    # Phases 6-7 can't be detected from here
    add(INFO, '6. Scheduled routines (optional)', 'Not checkable from here — see ONBOARDING.md phase 6')
    add(INFO, '7. Browser access to your league site (optional)', 'Not checkable from here — see ONBOARDING.md phase 7')

    w = max(len(r[1]) for r in rows)
    print('\nDynasty Scout setup check\n')
    for s, step, d in rows:
        print(f'  [{s}] {step.ljust(w)}  {d}')
    todo = [r for r in rows if r[0] == TODO]
    print(f'\n{len(todo)} step(s) left.' if todo else '\nAll required steps are done.')


if __name__ == '__main__':
    main()
