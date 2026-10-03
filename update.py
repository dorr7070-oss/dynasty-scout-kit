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
def ensure_config(root):
    """config.json is personal and git-ignored; the repo ships config.template.json. Create it once."""
    import shutil
    cfg, tpl = os.path.join(root, 'config.json'), os.path.join(root, 'config.template.json')
    if not os.path.exists(cfg) and os.path.exists(tpl):
        shutil.copy(tpl, cfg)


STEPS = [  # (script, optional)
    ('league_profile.py', False), ('fetch.py', False), ('values.py', False), ('usage.py', False), ('usage_adv.py', True), ('context.py', False), ('contract_study.py', True), ('contracts.py', True),
    ('project.py', False), ('weekly_study.py', True), ('weekly.py', True), ('lottery.py', False), ('lottery_tracker.py', True), ('prospects.py', True), ('cfbd.py', True),
    ('profiles.py', False), ('report.py', False), ('advise.py', False), ('draft.py', False),
    ('trade_grades.py', False), ('manager_skill.py', False),
    ('league_dashboard.py', False), ('assets_dashboard.py', False),
]


def self_update():
    """If this folder is a git clone, pull the latest framework first (fast-forward only).
    Personal files (config.json, data/, dashboards/, profiles/, reports) are git-ignored, so an
    update never touches them. Any failure (offline, local edits) is reported and skipped."""
    if not os.path.isdir(os.path.join(ROOT, '.git')):
        return
    try:
        git = lambda *a, t=20: subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True, timeout=t)
        before = git('rev-parse', '--short', 'HEAD').stdout.strip()
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
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'ops', script)], cwd=ROOT, env=env)
        if r.returncode != 0:
            if optional:
                print(f'!! {script} failed (optional step) — continuing')
                continue
            sys.exit(f'!! {script} failed with exit code {r.returncode} — fix this before relying on the outputs')
    print(f'Done in {time.time() - t0:.0f}s. Dashboards: dashboards/league.html, dashboards/assets.html')


if __name__ == '__main__':
    main()
