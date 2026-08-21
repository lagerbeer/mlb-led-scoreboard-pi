#!/usr/bin/env python3
"""
NFL Integration - live/upcoming NFL games via ESPN's public scoreboard API.
No API key needed - this is the same undocumented endpoint espn.com/nfl
itself calls, already relied on by many open-source scoreboard projects.
"""

import requests
import json
from datetime import datetime

CONFIG_FILE = '/home/pi/mlb_scoreboard_pro/config.json'
SCOREBOARD_URL = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
STANDINGS_URL = 'https://site.api.espn.com/apis/v2/sports/football/nfl/standings'

# ESPN's standings endpoint only groups teams by conference (AFC/NFC), not
# division - there's no per-team division field in that response to group by,
# so division membership is a static mapping here, same in spirit to
# mlb_integration's TEAM_NAME_TO_CODE. Realignment is rare enough (last NFL
# division change was 2002) that hardcoding this is safe.
NFL_DIVISIONS = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"],
    "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"],
    "AFC West": ["DEN", "KC", "LAC", "LV"],
    "NFC East": ["DAL", "NYG", "PHI", "WSH"],
    "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"],
    "NFC West": ["ARI", "LAR", "SEA", "SF"],
}


def format_local_time(iso_utc_str):
    """Converts a UTC ISO8601 kickoff time to a friendly local string like
    "Sun 1:00 PM". Unlike MLB's games (all same day), a week's NFL games span
    Thu/Sun/Mon, so - unlike mlb_integration's format_local_time - the day
    needs to be shown too."""
    if not iso_utc_str:
        return ''
    try:
        dt = datetime.fromisoformat(iso_utc_str.replace('Z', '+00:00'))
        local = dt.astimezone()
        return local.strftime('%a %I:%M %p').replace(' 0', ' ')
    except Exception:
        return ''


def _hex_to_rgb(hex_color, default=(60, 60, 60)):
    if not hex_color or len(hex_color) != 6:
        return default
    try:
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


class NFLDataFetcher:
    def __init__(self, preferred_code=""):
        self.preferred_code = preferred_code  # fallback if config.json is missing/unreadable

    def _get_preferred_code(self):
        """Reads the preferred team fresh from config.json on every call, so a
        change made in the web UI takes effect without restarting the display
        process - same reload-free pattern as mlb_integration's preferred-team
        lookup."""
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            return cfg.get('options', {}).get('preferred_nfl_team', self.preferred_code)
        except Exception:
            return self.preferred_code

    def get_current_games(self):
        """Fetch this week's NFL games. ESPN's scoreboard endpoint scopes to
        the current week automatically (same as visiting espn.com/nfl/scoreboard
        with no date filter) - there's no single "today" for NFL the way MLB
        has one, since a week's games spread across Thu/Sun/Mon."""
        try:
            response = requests.get(SCOREBOARD_URL, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code != 200:
                print(f"⚠️ NFL scoreboard fetch returned {response.status_code}")
                return []
            data = response.json()
        except Exception as e:
            print(f"❌ Error fetching NFL games: {e}")
            return []

        games = []
        for event in data.get('events', []):
            try:
                competition = event['competitions'][0]
                status = competition.get('status', {})
                status_type = status.get('type', {})
                state = status_type.get('state', '')

                if state == 'in':
                    game_status = 'live'
                elif state == 'post':
                    game_status = 'final'
                else:
                    game_status = 'pregame'

                competitors = {c['homeAway']: c for c in competition.get('competitors', [])}
                home = competitors.get('home', {})
                away = competitors.get('away', {})

                def team_info(c):
                    team = c.get('team', {})
                    return {
                        'name': team.get('displayName', ''),
                        'code': team.get('abbreviation', '???'),
                        'score': int(c.get('score', 0) or 0),
                        'color': _hex_to_rgb(team.get('color')),
                        'id': team.get('id'),
                        'logo': team.get('logo', '')
                    }

                home_info = team_info(home)
                away_info = team_info(away)

                situation = competition.get('situation', {})
                possession_id = situation.get('possession')
                possession = None
                if possession_id and possession_id == home_info['id']:
                    possession = 'home'
                elif possession_id and possession_id == away_info['id']:
                    possession = 'away'

                # Not confirmed against a live game yet (none in progress at
                # implementation time) - homeTimeouts/awayTimeouts is ESPN's
                # documented field name elsewhere in their site API, but if
                # it's wrong or absent this just stays None and the renderer
                # skips drawing timeout markers for that team.
                home_info['timeouts'] = situation.get('homeTimeouts')
                away_info['timeouts'] = situation.get('awayTimeouts')

                start_time = event.get('date', '')

                if game_status == 'pregame':
                    status_text = format_local_time(start_time) or 'TBD'
                else:
                    # ESPN's own phrasing ("3rd Quarter, 2:52", "Halftime",
                    # "Final", "Final/OT") - more robust than deriving quarter/
                    # clock text ourselves, and the renderer scrolls it if a
                    # variant like "End of 3rd Quarter" is too wide to fit.
                    status_text = status_type.get('shortDetail', '') or status_type.get('description', '')

                game_data = {
                    'game_id': event.get('id'),
                    'status': game_status,
                    'home': home_info,
                    'away': away_info,
                    'status_text': status_text,
                    # downDistanceText (not the "short" variant) includes the
                    # ball's field position - e.g. "3rd & 7 at NE 35" - team-
                    # relative to whichever side of the field it's actually on.
                    'down_distance': situation.get('downDistanceText', ''),
                    'last_play': (situation.get('lastPlay') or {}).get('text', ''),
                    'possession': possession,
                    'red_zone': situation.get('isRedZone', False),
                    'start_time': start_time,
                    'start_time_local': format_local_time(start_time)
                }
                games.append(game_data)
            except Exception as e:
                print(f"⚠️ Error parsing NFL game: {e}")
                continue

        return games

    def get_preferred_game(self):
        """Get the preferred team's game if they're playing this week"""
        all_games = self.get_current_games()
        preferred = self._get_preferred_code()

        preferred_game = None
        other_games = []

        for game in all_games:
            if preferred and (game['home']['code'] == preferred or game['away']['code'] == preferred):
                preferred_game = game
            else:
                other_games.append(game)

        return preferred_game, other_games

    def get_games_for_display(self):
        """Get games to display. Prioritizes the preferred team's live game, then
        any other live games, then - if nothing is live - this week's upcoming
        (pregame) games sorted by kickoff time. Mirrors mlb_integration's
        get_games_for_display() exactly."""
        preferred_game, other_games = self.get_preferred_game()

        if preferred_game and preferred_game['status'] == 'live':
            return [preferred_game]

        all_games = ([preferred_game] if preferred_game else []) + other_games

        live_others = [g for g in all_games if g['status'] == 'live']
        if live_others:
            return live_others

        upcoming = sorted(
            (g for g in all_games if g['status'] == 'pregame'),
            key=lambda g: g.get('start_time', '')
        )
        if upcoming:
            return upcoming

        return []

    def get_game_by_id(self, game_id):
        """Look up one specific game from this week's full slate by its ESPN
        event id - used when the web UI has the user pick an exact game to
        show, rather than the usual live/upcoming rotation. Mirrors
        mlb_integration's get_game_by_id()."""
        for game in self.get_current_games():
            if str(game.get('game_id')) == str(game_id):
                return game
        return None

    def get_standings(self):
        """Full NFL standings, grouped into the 8 standard divisions (see
        NFL_DIVISIONS) with each division's teams sorted by win percentage.
        Hits the API fresh on every call - like get_current_games(), caching
        is the caller's job."""
        try:
            response = requests.get(STANDINGS_URL, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code != 200:
                print(f"⚠️ NFL standings fetch returned {response.status_code}")
                return {}
            data = response.json()
        except Exception as e:
            print(f"❌ Error fetching NFL standings: {e}")
            return {}

        by_code = {}
        for conference in data.get('children', []):
            for entry in conference.get('standings', {}).get('entries', []):
                team = entry.get('team', {})
                code = team.get('abbreviation', '')
                stats = {s['name']: s.get('displayValue', '') for s in entry.get('stats', [])}
                by_code[code] = {
                    'code': code,
                    'wins': stats.get('wins', '0'),
                    'losses': stats.get('losses', '0'),
                    'ties': stats.get('ties', '0'),
                    'pct': stats.get('winPercent', '.000'),
                    'streak': stats.get('streak', '')
                }

        divisions = {}
        for division_name, codes in NFL_DIVISIONS.items():
            teams = [by_code[c] for c in codes if c in by_code]
            teams.sort(key=lambda t: float(t['pct'] or 0), reverse=True)
            divisions[division_name] = teams

        return divisions


# Global instance
nfl_fetcher = NFLDataFetcher("")  # No default preferred team - set via config.json/web UI
