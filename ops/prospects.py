#!/usr/bin/env python3
"""College prospect feed -> data/prospects.json + research/PROSPECTS.md

Pulls KeepTradeCut's devy board (1QB values for ~100 college players, tagged by draft
class) so future rookie classes sit on the SAME value scale as your picks and the
trade calculator. Each run keeps a dated snapshot in data/prospects/ and reports who
moved since the last one. Added 2026-10-02 when the owner asked to focus on college
players and draft classes; the class write-ups (sourced prose) stay in
research/draft-*.md, this is the structured, refreshable layer.

KTC's page embeds the board as JSON in <script id="ktc-players">; plain curl works
(checked 2026-10-02). If the markup changes, this fails loudly rather than writing
an empty board.
"""
import json, os, re, subprocess, sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SNAP = os.path.join(DATA, 'prospects')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league_format as LF  # noqa: E402
URL = f'https://keeptradecut.com/devy-rankings?format={LF.KTC_FORMAT}'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36'
POS = ('QB', 'RB', 'WR', 'TE')


def fetch():
    html = subprocess.run(['curl', '-s', '-m', '40', '-A', UA, URL], capture_output=True,
                          text=True, check=True).stdout
    m = re.search(r'id="ktc-players"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        sys.exit('prospects.py: KTC devy page no longer carries id="ktc-players" — markup changed, board NOT updated')
    raw = json.loads(m.group(1))
    out = []
    for p in raw:
        v = p.get('superflexValues' if LF.SUPERFLEX else 'oneQBValues') or {}
        if p.get('position') not in POS:
            continue
        out.append({'name': p['playerName'], 'pos': p['position'], 'school': p.get('team') or '',
                    'cls': p.get('seasonsExperience'), 'value': v.get('value', 0),
                    'rank': v.get('rank'), 'pos_rank': v.get('positionalRank'),
                    'trend': v.get('overallTrend', 0), 'returning': bool(p.get('isDevyReturningToSchool')),
                    'ht': f"{p.get('heightFeet') or ''}-{p.get('heightInches') or ''}", 'wt': p.get('weight') or ''})
    if len(out) < 50:
        sys.exit(f'prospects.py: only {len(out)} prospects parsed (expected ~100) — refusing to overwrite the board')
    return sorted(out, key=lambda p: -p['value'])


def pick_values():
    """KTC 1QB values of rookie picks ('2028 Mid 1st' -> 5215), same scale as the board."""
    html = subprocess.run(['curl', '-s', '-m', '40', '-A', UA,
                           f'https://keeptradecut.com/dynasty-rankings?format={LF.KTC_FORMAT}'],
                          capture_output=True, text=True).stdout
    m = re.search(r'id="ktc-players"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        print('  prospects.py: KTC pick values unavailable this run')
        return {}
    return {p['playerName']: LF.ktc_value(p) or 0
            for p in json.loads(m.group(1)) if p.get('position') == 'RDP'}


def main():
    os.makedirs(SNAP, exist_ok=True)
    board = fetch()
    picks = pick_values()
    today = date.today().isoformat()
    prev_files = sorted(f for f in os.listdir(SNAP) if f.endswith('.json') and not f.startswith(today))
    prev = {p['name']: p for p in json.load(open(os.path.join(SNAP, prev_files[-1])))} if prev_files else {}
    for p in board:
        o = prev.get(p['name'])
        p['delta'] = (p['value'] - o['value']) if o else None
    json.dump(board, open(os.path.join(SNAP, f'{today}.json'), 'w'))
    dropped = sorted(set(prev) - {p['name'] for p in board})
    json.dump({'date': today, 'source': URL, 'since': prev_files[-1][:-5] if prev_files else None,
               'dropped': dropped, 'picks': picks, 'board': board}, open(os.path.join(DATA, 'prospects.json'), 'w'))

    L = [f'# Prospect board — KTC devy, {"superflex" if LF.SUPERFLEX else "1QB"} values', '',
         f'_Generated {today} by `ops/prospects.py` from {URL}. Same value scale as KTC pick and player values, '
         f'so a prospect can be compared directly to a pick you own. Movement is vs the previous snapshot '
         f'({prev_files[-1][:-5] if prev_files else "none yet"}). Prose scouting lives in `research/draft-*.md`; '
         f'sources and access are in `research/SOURCES.md`._', '']
    for cls in sorted({p['cls'] for p in board if p['cls']}):
        group = [p for p in board if p['cls'] == cls]
        L += [f'## {cls} class — {len(group)} players', '',
              '| # | Player | Pos | School | KTC 1QB | Move | Note |', '|---|---|---|---|---|---|---|']
        for i, p in enumerate(group[:30], 1):
            mv = '' if p['delta'] is None else f"{p['delta']:+,}"
            note = 'returning to school' if p['returning'] else ''
            L.append(f"| {i} | {p['name']} | {p['pos']} | {p['school']} | {p['value']:,} | {mv} | {note} |")
        L.append('')
    if dropped:
        L += ['## Dropped off the board since last snapshot', '', ', '.join(dropped), '']
    open(os.path.join(ROOT, 'research', 'PROSPECTS.md'), 'w').write('\n'.join(L))
    movers = sorted((p for p in board if p['delta']), key=lambda p: -abs(p['delta']))[:5]
    print(f'prospects -> data/prospects.json + research/PROSPECTS.md ({len(board)} players; '
          f'classes {sorted({p["cls"] for p in board})}; biggest moves: '
          + (', '.join(f"{p['name']} {p['delta']:+}" for p in movers) or 'first snapshot') + ')')


if __name__ == '__main__':
    main()
