#!/usr/bin/env python3
"""Run the full Dynasty Scout pipeline — works on Windows, Mac and Linux.

    python update.py        (Windows)
    python3 update.py       (Mac / Linux; ./update.sh does the same thing)

Forces UTF-8 for every step (PYTHONUTF8=1): Windows otherwise reads and writes text in
its legacy code page and crashes on player names and symbols like "→". Steps marked
optional report a failure and carry on, so one flaky source never blocks the dashboards.
"""
import os, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('DS_REPO', 'https://github.com/dorr7070-oss/dynasty-scout-kit.git')   # DS_REPO: tests only
def ensure_config(root):
    """config.json is personal and git-ignored; the repo ships config.template.json. Create it once."""
    import shutil
    cfg, tpl = os.path.join(root, 'config.json'), os.path.join(root, 'config.template.json')
    if not os.path.exists(cfg) and os.path.exists(tpl):
        shutil.copy(tpl, cfg)


STEPS = [  # (script, optional)
    ('freshness.py --fix', True), ('league_profile.py', False), ('fetch.py', False), ('news.py', True), ('trending.py', True), ('values.py', False), ('usage.py', False), ('usage_adv.py', True), ('context.py', False), ('contract_study.py', True), ('cap.py', True), ('contracts.py', True), ('value_trends.py', True),
    ('project.py', False), ('injury_study.py', True), ('injuries.py', True), ('weekly_study.py', True), ('absence_study.py', True), ('weekly.py', True), ('waivers.py', True), ('lottery.py', False), ('lottery_tracker.py', True), ('trade_finder.py', True), ('our_projections.py', True), ('ngs.py', True), ('prospects.py', True), ('cfbd.py', True),
    ('profiles.py', False), ('report.py', False), ('advise.py', False), ('draft.py', False),
    ('trade_grades.py', False), ('manager_skill.py', False),
    ('freshness.py', True), ('league_dashboard.py', False), ('assets_dashboard.py', False), ('insights.py', True), ('analysis_dashboard.py', True), ('analyst.py', True), ('hub_dashboard.py', True),
]


def save_personal_layer():
    """Older versions kept the owner's own dashboard cards inside ops/league_dashboard.py and their owner
    trajectory reads inside ops/picks.py. Those files are framework, so an edited copy blocked every update.
    Copy that personal text into my_cards.py (git-ignored) once, and keep the two files as they were under
    backup/, so an update can replace them without losing anything the owner wrote."""
    import re, shutil
    mine = os.path.join(ROOT, 'my_cards.py')
    if os.path.exists(mine):
        return
    ld, pk = os.path.join(ROOT, 'ops', 'league_dashboard.py'), os.path.join(ROOT, 'ops', 'picks.py')
    parts = []
    if os.path.exists(ld):
        s = open(ld, encoding='utf-8').read()
        m = re.search(r'# =+ hand-maintained reads =+\n(.*?)\nKIND_LABEL = \{', s, re.S)
        if m:
            parts.append(m.group(1).rstrip() + '\n')
    if os.path.exists(pk):
        m = re.search(r'\nTRAJ_2028 = \{.*?\}\n', open(pk, encoding='utf-8').read(), re.S)
        if m:
            parts.append(m.group(0).strip() + '\n')
    if not parts:
        return
    stamp = time.strftime('%Y-%m-%d-%H%M')
    os.makedirs(os.path.join(ROOT, 'backup', stamp), exist_ok=True)
    for f in (ld, pk):
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(ROOT, 'backup', stamp, os.path.basename(f)))
    with open(mine, 'w', encoding='utf-8') as out:
        out.write('# Your own dashboard cards and owner reads. Updates never touch this file.\n'
                  '# Claude keeps it current; it replaces the starter cards in ops/league_dashboard.py.\n\n'
                  + '\n'.join(parts))
    print(f'Saved your dashboard cards to my_cards.py (originals kept in backup/{stamp}/).', flush=True)


def self_update():
    """If this folder is a git clone, pull the latest framework first (fast-forward only).
    Personal files (config.json, data/, dashboards/, profiles/, reports) are git-ignored, so an
    update never touches them. Any failure (offline, local edits) is reported and skipped."""
    try:
        git = lambda *a, t=20: subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True, timeout=t)
        if not os.path.isdir(os.path.join(ROOT, '.git')):
            # A zip copy has no update link. Turn it into a clone of the shared repo once, so every later
            # run updates itself. Only framework files are replaced; config.json, data/, dashboards/,
            # profiles/ and reports are git-ignored, so they stay exactly as they are.
            if git('--version').returncode != 0:
                return
            for args in (('init', '-q'), ('remote', 'add', 'origin', REPO), ('fetch', '-q', 'origin', 'main')):
                r = git(*args, t=120)
                if r.returncode != 0:
                    print(f'(could not link this folder to {REPO} for updates: {(r.stderr or r.stdout).strip()[:200]})')
                    return
            save_personal_layer()
            git('reset', '-q', '--hard', 'origin/main')
            git('branch', '-q', '--set-upstream-to=origin/main')
            print('This folder is now linked to the shared version and will update itself from here on.', flush=True)
            os.execv(sys.executable, [sys.executable] + sys.argv + ['--no-pull'])
        before = git('rev-parse', '--short', 'HEAD').stdout.strip()
        r = git('pull', '--ff-only', '--quiet', t=90)
        if r.returncode != 0:
            edited = git('diff', '--name-only').stdout.split()
            if edited and set(edited) <= {'ops/league_dashboard.py', 'ops/picks.py'}:
                save_personal_layer()                  # their cards move to my_cards.py first
                if os.path.exists(os.path.join(ROOT, 'my_cards.py')):
                    git('checkout', '--', *edited)
                    r = git('pull', '--ff-only', '--quiet', t=90)
        after = git('rev-parse', '--short', 'HEAD').stdout.strip()
        if r.returncode != 0:
            print(f'(framework update skipped: {(r.stderr or r.stdout).strip()[:200]})')
        elif before != after:
            print(f'Framework updated {before} -> {after}; restarting with the new version.', flush=True)
            os.execv(sys.executable, [sys.executable] + sys.argv + ['--no-pull'])
        else:
            print('Framework is up to date.')
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f'(framework update skipped: {e})')


def main():
    ensure_config(ROOT)
    if '--no-pull' not in sys.argv:
        self_update()
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    t0 = time.time()
    for script, optional in STEPS:
        name, *args = script.split()
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'ops', name), *args], cwd=ROOT, env=env)
        if r.returncode != 0:
            if optional:
                print(f'!! {script} failed (optional step) — continuing')
                continue
            sys.exit(f'!! {script} failed with exit code {r.returncode} — fix this before relying on the outputs')
    print(f'Done in {time.time() - t0:.0f}s. Dashboard: dashboards/hub.html')


if __name__ == '__main__':
    main()
