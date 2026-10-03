#!/usr/bin/env python3
"""Where each NFL game is played: coordinates + time zone, and the weather there.

Shared by ops/weekly_study.py (history) and ops/weekly.py (this week's forecast).
Both read weather from the SAME free source, Open-Meteo, so the effects measured on
history line up with the forecasts they are applied to (wind at 10 m, mph; °F; mm).
  geocoding  https://geocoding-api.open-meteo.com  (city -> lat/lon/timezone, no key)
  archive    https://archive-api.open-meteo.com    (hourly history, no key)
  forecast   https://api.open-meteo.com            (16-day hourly forecast, no key)
Coordinates are looked up once and cached in data/cache/team_sites.json.

nflverse game rows give the home team, a stadium_id and location Home/Neutral. A
neutral game at a US stadium takes the site of the team that normally plays there
(found from that stadium_id's home games); international venues are looked up by city.
"""
import json, os, subprocess, time, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'data', 'cache')
SITES = os.path.join(CACHE, 'team_sites.json')

# team -> (city, state/region) of its home stadium. Old codes kept for 2015-2019 history.
TEAM_CITY = {
    'ARI': ('Glendale', 'Arizona'), 'ATL': ('Atlanta', 'Georgia'), 'BAL': ('Baltimore', 'Maryland'),
    'BUF': ('Orchard Park', 'New York'), 'CAR': ('Charlotte', 'North Carolina'), 'CHI': ('Chicago', 'Illinois'),
    'CIN': ('Cincinnati', 'Ohio'), 'CLE': ('Cleveland', 'Ohio'), 'DAL': ('Arlington', 'Texas'),
    'DEN': ('Denver', 'Colorado'), 'DET': ('Detroit', 'Michigan'), 'GB': ('Green Bay', 'Wisconsin'),
    'HOU': ('Houston', 'Texas'), 'IND': ('Indianapolis', 'Indiana'), 'JAX': ('Jacksonville', 'Florida'),
    'KC': ('Kansas City', 'Missouri'), 'LA': ('Inglewood', 'California'), 'LAC': ('Inglewood', 'California'),
    'LV': ('Paradise', 'Nevada'), 'MIA': ('Miami Gardens', 'Florida'), 'MIN': ('Minneapolis', 'Minnesota'),
    'NE': ('Foxborough', 'Massachusetts'), 'NO': ('New Orleans', 'Louisiana'), 'NYG': ('East Rutherford', 'New Jersey'),
    'NYJ': ('East Rutherford', 'New Jersey'), 'OAK': ('Oakland', 'California'), 'PHI': ('Philadelphia', 'Pennsylvania'),
    'PIT': ('Pittsburgh', 'Pennsylvania'), 'SD': ('San Diego', 'California'), 'SEA': ('Seattle', 'Washington'),
    'SF': ('Santa Clara', 'California'), 'STL': ('St. Louis', 'Missouri'), 'TB': ('Tampa', 'Florida'),
    'TEN': ('Nashville', 'Tennessee'), 'WAS': ('Landover', 'Maryland'),
}
# international / one-off venues: stadium-name keyword -> (city, country code)
VENUE_CITY = [
    ('wembley', ('London', 'GB')), ('tottenham', ('London', 'GB')), ('twickenham', ('London', 'GB')),
    ('azteca', ('Mexico City', 'MX')), ('banorte', ('Mexico City', 'MX')),
    ('allianz', ('Munich', 'DE')), ('bayern', ('Munich', 'DE')), ('deutsche bank', ('frankfurt', 'DE')),
    ('olympiastadion', ('Berlin', 'DE')), ('corinthians', ('São Paulo', 'BR')), ('maracana', ('Rio de Janeiro', 'BR')),
    ('melbourne', ('Melbourne', 'AU')), ('stade de france', ('Saint-Denis', 'FR')), ('bernabeu', ('Madrid', 'ES')),
    ('croke', ('Dublin', 'IE')), ('rogers centre', ('Toronto', 'CA')),
]


def _get(url, timeout=120):
    # Free tier: 600 calls/min, 5,000/hour, 10,000/day; a long date range counts as several calls.
    # A minutely refusal is waited out; an hourly/daily one is raised (callers keep what they saved).
    for attempt in range(6):
        r = subprocess.run(['curl', '-sL', '--max-time', str(timeout), url], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.startswith('{'):
            d = json.loads(r.stdout)
            if not d.get('error'):
                return d
            reason = d.get('reason', '')
            if 'Minutely' in reason:
                time.sleep(62)
                continue
            if 'Hourly' in reason or 'Daily' in reason:
                raise RuntimeError(f'open-meteo limit: {reason}')
        time.sleep(2 + attempt * 3)
    raise RuntimeError(f'open-meteo failed: {url[:120]}')


def _geocode(name, region=None, country=None):
    q = {'name': name, 'count': 10, 'language': 'en'}
    if country:
        q['countryCode'] = country
    res = _get('https://geocoding-api.open-meteo.com/v1/search?' + urllib.parse.urlencode(q)).get('results') or []
    if region:
        res = [r for r in res if r.get('admin1') == region] or res
    if not res:
        return None
    r = res[0]
    return {'lat': round(r['latitude'], 4), 'lon': round(r['longitude'], 4), 'tz': r['timezone']}


def sites():
    """{team_code or 'venue:<name>': {lat, lon, tz}} — cached."""
    s = json.load(open(SITES)) if os.path.exists(SITES) else {}
    changed = False
    for t, (city, region) in TEAM_CITY.items():
        if t not in s:
            s[t] = _geocode(city, region, 'US')
            changed = True
    for _, (city, cc) in VENUE_CITY:
        k = f'venue:{city}'
        if k not in s:
            s[k] = _geocode(city, None, cc)
            changed = True
    if changed:
        os.makedirs(CACHE, exist_ok=True)
        json.dump(s, open(SITES, 'w'), indent=1)
    return s


def game_site(g, site_map, stadium_home):
    """Site dict for a games.csv row, or None when unknown."""
    if g.get('location') != 'Neutral':
        return site_map.get(g['home_team'])
    owner = stadium_home.get(g.get('stadium_id'))
    if owner:
        return site_map.get(owner)
    name = (g.get('stadium') or '').lower()
    for kw, (city, _) in VENUE_CITY:
        if kw in name:
            return site_map.get(f'venue:{city}')
    return None


def stadium_owners(games):
    """stadium_id -> the team that most often hosts there (for neutral games at US stadiums)."""
    from collections import Counter
    c = {}
    for g in games:
        if g.get('location') == 'Home' and g.get('stadium_id'):
            c.setdefault(g['stadium_id'], Counter())[g['home_team']] += 1
    return {k: v.most_common(1)[0][0] for k, v in c.items()}


HOURLY = 'temperature_2m,precipitation,snowfall,wind_speed_10m'


def _hourly_table(d):
    h = d['hourly']
    return {t: (h['temperature_2m'][i], h['precipitation'][i], h['snowfall'][i], h['wind_speed_10m'][i])
            for i, t in enumerate(h['time'])}


def history(site, start, end):
    """Hourly archive keyed 'YYYY-MM-DDTHH:00' in US Eastern time (games.csv kickoff clock)."""
    q = {'latitude': site['lat'], 'longitude': site['lon'], 'start_date': start, 'end_date': end,
         'hourly': HOURLY, 'wind_speed_unit': 'mph', 'temperature_unit': 'fahrenheit',
         'precipitation_unit': 'mm', 'timezone': 'America/New_York'}
    return _hourly_table(_get('https://archive-api.open-meteo.com/v1/archive?' + urllib.parse.urlencode(q), 300))


def forecast(site):
    q = {'latitude': site['lat'], 'longitude': site['lon'], 'hourly': HOURLY, 'forecast_days': 16,
         'wind_speed_unit': 'mph', 'temperature_unit': 'fahrenheit', 'precipitation_unit': 'mm',
         'timezone': 'America/New_York'}
    return _hourly_table(_get('https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(q)))


def game_weather(table, gameday, gametime):
    """Kickoff-to-+3h window: mean temp, max wind, total rain mm, total snow cm. None if missing."""
    try:
        hh = int((gametime or '13:00').split(':')[0])
    except ValueError:
        hh = 13
    rows = [table.get(f'{gameday}T{h:02d}:00') for h in range(hh, hh + 4)]
    rows = [r for r in rows if r and r[0] is not None]
    if not rows:
        return None
    return {'temp': round(sum(r[0] for r in rows) / len(rows), 1), 'wind': round(max(r[3] for r in rows), 1),
            'rain': round(sum(r[1] or 0 for r in rows), 1), 'snow': round(sum(r[2] or 0 for r in rows), 1)}


def tz_offset(tz, date):
    """UTC offset in hours for an IANA zone on a date (stdlib zoneinfo)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    d = datetime.fromisoformat(date + 'T13:00').replace(tzinfo=ZoneInfo(tz))
    return d.utcoffset().total_seconds() / 3600
