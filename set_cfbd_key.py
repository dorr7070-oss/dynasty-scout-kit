#!/usr/bin/env python3
"""Save your free CollegeFootballData.com API key and test it — Windows, Mac or Linux.

    python set_cfbd_key.py      (Windows)
    python3 set_cfbd_key.py     (Mac / Linux)

The key is typed at a hidden prompt, so it never shows on screen, in a chat, or in this
folder. It is saved to <your home>/.config/dynasty-scout/cfbd_key, where ops/cfbd.py reads it.
"""
import getpass, os, sys, urllib.error, urllib.request

path = os.path.join(os.path.expanduser('~'), '.config', 'dynasty-scout', 'cfbd_key')
key = getpass.getpass('Paste your CollegeFootballData API key, then press Enter: ').strip()
if not key:
    sys.exit('No key entered — nothing saved.')
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w', encoding='utf-8') as f:
    f.write(key + '\n')
try:
    os.chmod(path, 0o600)
except OSError:
    pass
req = urllib.request.Request('https://api.collegefootballdata.com/player/search?searchTerm=Jeremiah%20Smith',
                             headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f'Key saved and working (HTTP {r.status}). College stats load on the next update.')
except urllib.error.HTTPError as e:
    print(f'Key saved, but the test call returned HTTP {e.code}. A 401 means it was mistyped or is not active yet — run this again.')
except Exception as e:
    print(f'Key saved, but the test call could not connect ({e.__class__.__name__}). Check the internet connection and run again.')
