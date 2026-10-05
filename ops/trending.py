#!/usr/bin/env python3
"""Sleeper trending adds / drops (added 2026-10-04): how many Sleeper leagues added or dropped each player in the last
24 hours and the last 7 days. It is the crowd's reaction to news, usually hours before trade values move — a waiver
target everyone is adding is gone by the next run, and a starter being dropped en masse is a news story to read.

Writes data/trending.json (+ a daily copy in data/trending_history/) {sleeper_id: {add_24h, drop_24h, add_7d, drop_7d}} for the top 200 of each list.
Used by waivers.py (how contested a pickup is), the player lookup, and the news-and-data card.
"""
import json, os, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
API = 'https://api.sleeper.app/v1/players/nfl/trending'


def get(kind, hours):
    url = f'{API}/{kind}?lookback_hours={hours}&limit=200&t={int(time.time())}'
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=20))


def main():
    out, failed = {}, []
    for kind in ('add', 'drop'):
        for hours, lab in ((24, '24h'), (168, '7d')):
            try:
                for x in get(kind, hours):
                    out.setdefault(x['player_id'], {})[f'{kind}_{lab}'] = x['count']
            except Exception as e:
                failed.append(f'{kind} {lab}: {e}')
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'), 'failed': failed, 'players': out},
              open(os.path.join(DATA, 'trending.json'), 'w'))
    # one snapshot a day (same-day reruns replace it): with this league's later waiver bids, it lets the "100k adds =
    # contested" rule in waivers.py be MEASURED instead of assumed, once a few weeks have piled up
    hd = os.path.join(DATA, 'trending_history')
    os.makedirs(hd, exist_ok=True)
    if out:
        json.dump(out, open(os.path.join(hd, time.strftime('%Y-%m-%d') + '.json'), 'w'))
    P = json.load(open(os.path.join(DATA, 'players.json')))
    top = sorted(out.items(), key=lambda kv: -kv[1].get('add_24h', 0))[:5]
    print(f'trending -> data/trending.json: {len(out)} players ({len(failed)} feeds failed); most added 24h: '
          + ', '.join(f"{(P.get(k) or {}).get('full_name', k)} {v.get('add_24h', 0):,}" for k, v in top))


if __name__ == '__main__':
    main()
