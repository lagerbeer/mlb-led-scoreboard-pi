#!/usr/bin/env python3
"""
NCAA Football Integration - live/upcoming FBS college football games via
ESPN's public scoreboard API. Same endpoint family as nfl_integration.py, so
this reuses its format_local_time()/_hex_to_rgb() helpers rather than
duplicating them.

FBS is ~130 teams and a single week can have ~100 games - far more than the
NFL's 16 - so without a preferred team set, get_games_for_display() narrows
the rotation to games involving an AP Top 25 team (falling back to the full
pool only if no ranked team is currently playing/upcoming), rather than
cycling through the entire slate.
"""

import requests
import json

from nfl_integration import format_local_time, _hex_to_rgb

CONFIG_FILE = '/home/pi/mlb_scoreboard_pro/config.json'
SCOREBOARD_URL = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80'
STANDINGS_URL = 'https://site.api.espn.com/apis/v2/sports/football/college-football/standings'

# ESPN's sentinel for "unranked" on the scoreboard endpoint's curatedRank
# field - anything from 1-25 is an actual AP Top 25 rank.
UNRANKED = 99


class NCAAFDataFetcher:
    def __init__(self, preferred_code=""):
        self.preferred_code = preferred_code  # fallback if config.json is missing/unreadable

    def _get_preferred_code(self):
        """Reads the preferred team fresh from config.json on every call - same
        reload-free pattern as nfl_integration's preferred-team lookup."""
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            return cfg.get('options', {}).get('preferred_ncaaf_team', self.preferred_code)
        except Exception:
            return self.preferred_code

    def get_current_games(self):
        """Fetch this week's FBS games (groups=80 scopes the endpoint to FBS,
        same as ESPN's own college football scoreboard page)."""
        try:
            response = requests.get(SCOREBOARD_URL, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code != 200:
                print(f"⚠️ NCAAF scoreboard fetch returned {response.status_code}")
                return []
            data = response.json()
        except Exception as e:
            print(f"❌ Error fetching NCAAF games: {e}")
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
                    rank = c.get('curatedRank', {}).get('current')
                    return {
                        'name': team.get('displayName', ''),
                        'code': team.get('abbreviation', '???'),
                        'score': int(c.get('score', 0) or 0),
                        'color': _hex_to_rgb(team.get('color')),
                        'id': team.get('id'),
                        'logo': team.get('logo', ''),
                        'rank': rank if rank and rank < UNRANKED else None
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

                home_info['timeouts'] = situation.get('homeTimeouts')
                away_info['timeouts'] = situation.get('awayTimeouts')

                start_time = event.get('date', '')

                if game_status == 'pregame':
                    status_text = format_local_time(start_time) or 'TBD'
                else:
                    status_text = status_type.get('shortDetail', '') or status_type.get('description', '')

                game_data = {
                    'game_id': event.get('id'),
                    'status': game_status,
                    'home': home_info,
                    'away': away_info,
                    'status_text': status_text,
                    # Two separate short fields rather than the combined
                    # downDistanceText ("3rd & 7 at NE 35") - down_distance
                    # goes on the LED screen's top row, field_position on
                    # whichever team's row has the ball; both need to be
                    # short enough to display without scrolling.
                    'down_distance': situation.get('shortDownDistanceText', ''),
                    'field_position': situation.get('possessionText', ''),
                    'last_play': (situation.get('lastPlay') or {}).get('text', ''),
                    'possession': possession,
                    'red_zone': situation.get('isRedZone', False),
                    'ranked': bool(home_info['rank'] or away_info['rank']),
                    'start_time': start_time,
                    'start_time_local': format_local_time(start_time)
                }
                games.append(game_data)
            except Exception as e:
                print(f"⚠️ Error parsing NCAAF game: {e}")
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
        """Priority: preferred team's live game, then other live games, then
        upcoming games sorted by kickoff - same order as nfl_integration's
        get_games_for_display(). Because a single FBS week can run ~100 games,
        once past 'preferred team's live game' the pool is narrowed to games
        involving an AP Top 25 team, unless that would empty the list entirely
        (no ranked team currently playing/upcoming), in which case it falls
        back to the full pool. The preferred team's own game is always kept
        even if neither side is ranked."""
        preferred_game, other_games = self.get_preferred_game()

        if preferred_game and preferred_game['status'] == 'live':
            return [preferred_game]

        all_games = ([preferred_game] if preferred_game else []) + other_games

        def ranked_or_preferred(g):
            return g.get('ranked') or (preferred_game and g['game_id'] == preferred_game['game_id'])

        live_games = [g for g in all_games if g['status'] == 'live']
        if live_games:
            filtered = [g for g in live_games if ranked_or_preferred(g)]
            return filtered if filtered else live_games

        upcoming = sorted(
            (g for g in all_games if g['status'] == 'pregame'),
            key=lambda g: g.get('start_time', '')
        )
        if upcoming:
            filtered = [g for g in upcoming if ranked_or_preferred(g)]
            return filtered if filtered else upcoming

        return []

    def get_game_by_id(self, game_id):
        """Look up one specific game from this week's full slate by its ESPN
        event id. Mirrors nfl_integration's get_game_by_id()."""
        for game in self.get_current_games():
            if str(game.get('game_id')) == str(game_id):
                return game
        return None

    def get_standings(self):
        """Full FBS standings, grouped by conference. Unlike NFL/MLB, ESPN's
        college football standings endpoint already groups entries by
        conference directly (no separate division level to reconstruct with a
        static mapping) - conferences with no entries yet (seen for at least
        one conference during the off-season) are skipped rather than shown
        as an empty section. Hits the API fresh on every call - like
        get_current_games(), caching is the caller's job."""
        try:
            response = requests.get(STANDINGS_URL, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code != 200:
                print(f"⚠️ NCAAF standings fetch returned {response.status_code}")
                return {}
            data = response.json()
        except Exception as e:
            print(f"❌ Error fetching NCAAF standings: {e}")
            return {}

        conferences = {}
        for conf in data.get('children', []):
            entries = conf.get('standings', {}).get('entries', [])
            if not entries:
                continue

            name = conf.get('name') or conf.get('abbreviation') or 'Unknown'
            teams = []
            for entry in entries:
                team = entry.get('team', {})
                stats = {s['name']: s.get('displayValue', '') for s in entry.get('stats', [])}
                teams.append({
                    'code': team.get('abbreviation', ''),
                    'wins': stats.get('wins', '0'),
                    'losses': stats.get('losses', '0'),
                    'pct': stats.get('winPercent', '.000'),
                    'streak': stats.get('streak', '')
                })
            teams.sort(key=lambda t: float(t['pct'] or 0), reverse=True)
            conferences[name] = teams

        return conferences


# Global instance
ncaaf_fetcher = NCAAFDataFetcher("")  # No default preferred team - set via config.json/web UI
