#!/usr/bin/env python3
"""One-time login for ESPN private leagues or Yahoo leagues — run it yourself in a terminal.

    python set_platform_login.py espn      (Windows; Mac: python3 ...)
    python set_platform_login.py yahoo

Secrets are typed at hidden prompts and saved only to <home>/.config/dynasty-scout/
(readable by you alone) — never in this folder, never in a chat. Sleeper needs none of this.
"""
import base64, getpass, json, os, sys, time, urllib.error, urllib.parse, urllib.request

DIR = os.path.join(os.path.expanduser('~'), '.config', 'dynasty-scout')


def save(name, obj):
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, f'{name}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def espn():
    print('''
ESPN private league — copy two cookies from your browser (about 2 minutes):
 1. In Chrome, log into fantasy.espn.com and open your league.
 2. Press F12 (Mac: Cmd+Option+I) to open Developer Tools -> "Application" tab
    -> Storage -> Cookies -> https://fantasy.espn.com
 3. Find "espn_s2" (a long value) and "SWID" (looks like {XXXXXXXX-XXXX-...}).
 Copy each value and paste it below. Nothing shows while you paste — that is normal.
''')
    s2 = getpass.getpass('espn_s2: ').strip()
    swid = getpass.getpass('SWID: ').strip()
    if not s2 or not swid:
        sys.exit('Both values are needed — nothing saved.')
    print('Saved to', save('espn', {'espn_s2': s2, 'swid': swid}))
    print('Now run the update again; Claude will read your league.')


def yahoo():
    print('''
Yahoo league — a one-time setup (about 5 minutes):
 1. Go to https://developer.yahoo.com/apps/create/ (log in with the Yahoo account that's in the league).
 2. Create an app: any name; Application Type "Confidential Client" or "Installed Application";
    Redirect URI "oob"; API Permissions: tick "Fantasy Sports" -> "Read". Create.
 3. Copy the Client ID and Client Secret it shows, and paste them below (hidden).
''')
    cid = getpass.getpass('Client ID: ').strip()
    secret = getpass.getpass('Client Secret: ').strip()
    if not cid or not secret:
        sys.exit('Both values are needed — nothing saved.')
    url = 'https://api.login.yahoo.com/oauth2/request_auth?' + urllib.parse.urlencode(
        {'client_id': cid, 'redirect_uri': 'oob', 'response_type': 'code'})
    print(f'\n 4. Open this link, click "Agree", and copy the code Yahoo shows:\n\n    {url}\n')
    code = getpass.getpass('Code from Yahoo: ').strip()
    body = urllib.parse.urlencode({'grant_type': 'authorization_code', 'code': code, 'redirect_uri': 'oob'}).encode()
    auth = base64.b64encode(f'{cid}:{secret}'.encode()).decode()
    req = urllib.request.Request('https://api.login.yahoo.com/oauth2/get_token', data=body,
                                 headers={'Authorization': f'Basic {auth}',
                                          'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f'Yahoo refused the code (HTTP {e.code}). Codes expire fast — run this again and paste a fresh one.')
    save('yahoo', {'client_id': cid, 'client_secret': secret, 'access_token': tok['access_token'],
                   'refresh_token': tok['refresh_token'], 'expires_at': time.time() + int(tok.get('expires_in', 3600))})
    print('Yahoo login saved. Now run the update again; Claude will read your league.')


if __name__ == '__main__':
    which = (sys.argv[1] if len(sys.argv) > 1 else '').lower()
    {'espn': espn, 'yahoo': yahoo}.get(which, lambda: sys.exit('Usage: python set_platform_login.py espn|yahoo'))()
