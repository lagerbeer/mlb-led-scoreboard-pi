#!/usr/bin/env python3
"""
MLB Baseball Integration - Prioritizes Giants games
"""

import statsapi
import requests
import json
from datetime import datetime
import logging

# Setup logging
logger = logging.getLogger("mlb")

CONFIG_FILE = '/home/pi/mlb_scoreboard_pro/config.json'

def format_local_time(iso_utc_str):
    """Converts a UTC ISO8601 timestamp (as returned by the schedule API's
    game_datetime, e.g. "2026-08-08T19:05:00Z") to a friendly local time
    string like "3:05 PM", using the system's local timezone."""
    if not iso_utc_str:
        return ''
    try:
        dt = datetime.fromisoformat(iso_utc_str.replace('Z', '+00:00'))
        local = dt.astimezone()
        return local.strftime('%I:%M %p').lstrip('0')
    except Exception:
        return ''

DIVISION_SHORT_NAMES = {
    "American League East": "AL East",
    "American League Central": "AL Central",
    "American League West": "AL West",
    "National League East": "NL East",
    "National League Central": "NL Central",
    "National League West": "NL West",
}

# Team colors (RGB values) - keys match the official MLB API abbreviations
# (see TEAM_NAME_TO_CODE below), which is what everything else keys off of.
TEAM_COLORS = {
    # NL West - Giants first!
    "SF": (253, 90, 30),      # Giants - Orange
    "LAD": (0, 90, 156),       # Dodgers - Blue
    "SD": (47, 36, 29),        # Padres - Brown
    "AZ": (167, 25, 48),       # Diamondbacks - Red
    "COL": (51, 51, 102),      # Rockies - Purple

    # AL East
    "BAL": (223, 70, 41),      # Orioles
    "BOS": (189, 48, 57),      # Red Sox
    "NYY": (12, 35, 64),       # Yankees
    "TB": (9, 44, 92),         # Rays
    "TOR": (19, 74, 142),      # Blue Jays

    # AL Central
    "CWS": (39, 37, 31),       # White Sox
    "CLE": (12, 35, 64),       # Guardians
    "DET": (12, 35, 64),       # Tigers
    "KC": (0, 70, 135),        # Royals
    "MIN": (211, 17, 69),      # Twins

    # AL West
    "HOU": (235, 110, 31),     # Astros
    "LAA": (186, 0, 43),       # Angels
    "ATH": (0, 79, 51),        # Athletics
    "SEA": (12, 44, 86),       # Mariners
    "TEX": (0, 50, 120),       # Rangers

    # NL East
    "ATL": (19, 39, 79),       # Braves
    "MIA": (0, 119, 158),      # Marlins
    "NYM": (0, 45, 114),       # Mets
    "PHI": (232, 24, 40),      # Phillies
    "WSH": (171, 21, 54),      # Nationals

    # NL Central
    "CHC": (14, 51, 134),      # Cubs
    "CIN": (198, 1, 31),       # Reds
    "MIL": (18, 64, 118),      # Brewers
    "PIT": (0, 0, 0),          # Pirates
    "STL": (196, 30, 58),      # Cardinals
}

# Full team name (exactly as statsapi.schedule() returns it in home_name/away_name)
# to official MLB abbreviation. Previously this was keyed by short nicknames like
# "Mets" or "Giants", which never matched the full names the API actually sends
# ("New York Mets") - every lookup silently fell back to the first 3 letters of
# the full name, which is why e.g. the Mets showed as "NEW" instead of "NYM".
TEAM_NAME_TO_CODE = {
    "Arizona Diamondbacks": "AZ", "Atlanta Braves": "ATL", "Athletics": "ATH",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS", "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET", "Houston Astros": "HOU",
    "Kansas City Royals": "KC", "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN",
    "New York Mets": "NYM", "New York Yankees": "NYY", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

# ESPN's public (undocumented) standings endpoint - same source used by
# nfl_integration.get_standings(). It groups teams by league (AL/NL) but not
# by division, so - same as NFL_DIVISIONS in nfl_integration.py - division
# membership is a static mapping here.
MLB_STANDINGS_URL = 'https://site.api.espn.com/apis/v2/sports/baseball/mlb/standings'

MLB_DIVISIONS = {
    "AL East": ["BAL", "BOS", "NYY", "TB", "TOR"],
    "AL Central": ["CWS", "CLE", "DET", "KC", "MIN"],
    "AL West": ["HOU", "LAA", "ATH", "SEA", "TEX"],
    "NL East": ["ATL", "MIA", "NYM", "PHI", "WSH"],
    "NL Central": ["CHC", "CIN", "MIL", "PIT", "STL"],
    "NL West": ["AZ", "COL", "LAD", "SD", "SF"],
}

# ESPN's abbreviations differ from this codebase's convention (TEAM_NAME_TO_CODE
# above, also used by the preferred-team dropdown) for exactly these two teams -
# normalized when building get_full_standings()'s by-code lookup so MLB_DIVISIONS
# membership and the preferred-team highlight both resolve correctly.
ESPN_CODE_OVERRIDES = {"ARI": "AZ", "CHW": "CWS"}


class MLBDataFetcher:
    def __init__(self, preferred_code="SF"):
        self.cache = {}
        self.last_fetch = 0
        self.preferred_code = preferred_code  # fallback if config.json is missing/unreadable

    def _get_preferred_code(self):
        """Reads the preferred team fresh from config.json on every call, so a
        change made in the web UI takes effect without restarting the display
        process - same reload-free pattern as the rest of the config."""
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            return cfg.get('options', {}).get('preferred_team', self.preferred_code)
        except Exception:
            return self.preferred_code

    def get_team_code(self, team_name):
        """Convert full team name (as returned by the schedule API) to abbreviation"""
        return TEAM_NAME_TO_CODE.get(team_name, team_name[:3].upper())
    
    def get_team_color(self, team_code):
        """Get team colors as RGB dict"""
        if team_code in TEAM_COLORS:
            r, g, b = TEAM_COLORS[team_code]
            return {'r': r, 'g': g, 'b': b}
        return {'r': 255, 'g': 255, 'b': 255}  # Default white
    
    def get_today_games(self):
        """Fetch today's MLB games"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            games = statsapi.schedule(date=today)
            
            if not games:
                print("📅 No MLB games today")
                return []
            
            processed_games = []
            for game in games:
                # Determine game status
                status_text = game.get('status', '')
                if 'Final' in status_text:
                    game_status = 'final'
                elif 'In Progress' in status_text:
                    game_status = 'live'
                elif 'Postponed' in status_text:
                    game_status = 'postponed'
                elif any(s in status_text for s in ('Scheduled', 'Pre-Game', 'Warmup', 'Preview', 'Delayed Start')):
                    game_status = 'pregame'
                else:
                    game_status = 'unknown'
                
                # Get team codes and colors
                home_name = game.get('home_name', '')
                away_name = game.get('away_name', '')
                home_code = self.get_team_code(home_name)
                away_code = self.get_team_code(away_name)
                
                home_color = self.get_team_color(home_code)
                away_color = self.get_team_color(away_code)
                
                # Get scores
                home_score = game.get('home_score', 0)
                away_score = game.get('away_score', 0)
                home_hits = game.get('home_hits', 0)
                away_hits = game.get('away_hits', 0)
                home_errors = game.get('home_errors', 0)
                away_errors = game.get('away_errors', 0)
                
                # Get inning info
                inning = game.get('current_inning', 0)
                inning_state = game.get('inning_state', '')
                outs = game.get('outs', 0)
                
                # Default values
                balls = strikes = 0
                bases = {'first': False, 'second': False, 'third': False}
                batter_name = pitcher_name = ''
                last_pitch = None
                play_result = ''
                play_event = ''
                pitch_count = 0
                no_hitter = perfect_game = False
                winning_pitcher = losing_pitcher = save_pitcher = None
                linescore_innings = []
                
                # Get detailed info for live games
                if game_status == 'live':
                    try:
                        game_data = statsapi.get('game', {'gamePk': game['game_id']})
                        # The real API response nests everything under liveData - it's not
                        # at the top level. batter/pitcher live under offense/defense, and
                        # balls/strikes/outs are directly on linescore (no "count" sub-object).
                        live_data = game_data.get('liveData', {})
                        linescore = live_data.get('linescore', {})
                        linescore_innings = linescore.get('innings', [])

                        # schedule() (where home_score/home_hits/home_errors were set above)
                        # only ever returns runs - hits and errors simply aren't part of that
                        # response, which is why hits/errors always showed 0. All three are
                        # available here and more current than the schedule() snapshot.
                        team_line = linescore.get('teams', {})
                        home_score = team_line.get('home', {}).get('runs', home_score)
                        away_score = team_line.get('away', {}).get('runs', away_score)
                        home_hits = team_line.get('home', {}).get('hits', home_hits)
                        away_hits = team_line.get('away', {}).get('hits', away_hits)
                        home_errors = team_line.get('home', {}).get('errors', home_errors)
                        away_errors = team_line.get('away', {}).get('errors', away_errors)

                        balls = linescore.get('balls', 0)
                        strikes = linescore.get('strikes', 0)
                        outs = linescore.get('outs', outs)

                        # gameData.flags carries these as plain booleans straight from the
                        # API - no need to derive them from the boxscore ourselves.
                        game_flags = game_data.get('gameData', {}).get('flags', {})
                        no_hitter = game_flags.get('noHitter', False)
                        perfect_game = game_flags.get('perfectGame', False)

                        offense = linescore.get('offense', {})
                        defense = linescore.get('defense', {})

                        # Base runners: offense holds the runner (a player dict) when
                        # occupied, and omits the key (or sets it None) when empty.
                        bases = {
                            'first': offense.get('first') is not None,
                            'second': offense.get('second') is not None,
                            'third': offense.get('third') is not None
                        }

                        # Get at bat info
                        batter = offense.get('batter') or {}
                        pitcher = defense.get('pitcher') or {}
                        batter_name = batter.get('fullName', '')
                        pitcher_name = pitcher.get('fullName', '')

                        # Current pitcher's pitch count this game - looked up from
                        # the boxscore by matching the defensive pitcher's ID.
                        # Checking both sides rather than figuring out which team
                        # is on defense avoids needing another lookup just for that.
                        pitcher_id = pitcher.get('id')
                        if pitcher_id:
                            boxscore = live_data.get('boxscore', {})
                            player_key = f'ID{pitcher_id}'
                            for side in ('home', 'away'):
                                side_players = boxscore.get('teams', {}).get(side, {}).get('players', {})
                                if player_key in side_players:
                                    pitch_count = side_players[player_key].get('stats', {}).get('pitching', {}).get('numberOfPitches', 0)
                                    break

                        # Get last pitch info
                        plays = live_data.get('plays', {}).get('allPlays', [])
                        if plays:
                            last_play = plays[-1]
                            if 'playEvents' in last_play:
                                events = last_play['playEvents']
                                if events and 'pitchData' in events[-1]:
                                    pitch_data = events[-1]['pitchData']
                                    if pitch_data:
                                        speed = pitch_data.get('startSpeed', 0)
                                        pitch_type = pitch_data.get('pitchType', '')
                                        if pitch_type:
                                            # Map full pitch type to abbreviation
                                            pitch_map = {
                                                'Four-Seam Fastball': 'FF',
                                                'Fastball': 'FF',
                                                'Sinker': 'SI',
                                                'Slider': 'SL',
                                                'Curveball': 'CU',
                                                'Changeup': 'CH',
                                                'Cutter': 'FC',
                                                'Splitter': 'FS',
                                                'Knuckleball': 'KN'
                                            }
                                            pitch_abbr = pitch_map.get(pitch_type, pitch_type[:2])
                                            last_pitch = {'speed': speed, 'type': pitch_abbr}

                                # Get play result
                                result = last_play.get('result', {})
                                play_result = result.get('description', '')
                                play_event = result.get('event', '')
                        else:
                            # Try current play
                            current_play = offense.get('currentPlay', {})
                            if current_play:
                                result = current_play.get('result', {})
                                play_result = result.get('description', '')
                                play_event = result.get('event', '')
                    except Exception as e:
                        print(f"⚠️ Error getting live game details: {e}")

                elif game_status == 'final':
                    try:
                        # liveData.decisions (a sibling of boxscore, not nested
                        # inside it) holds the winning/losing/save pitcher once
                        # the game's over - each just an id + fullName, no
                        # win-loss record attached.
                        game_data = statsapi.get('game', {'gamePk': game['game_id']})
                        decisions = game_data.get('liveData', {}).get('decisions', {})
                        winning_pitcher = decisions.get('winner', {}).get('fullName')
                        losing_pitcher = decisions.get('loser', {}).get('fullName')
                        save_pitcher = decisions.get('save', {}).get('fullName')
                        linescore_innings = game_data.get('liveData', {}).get('linescore', {}).get('innings', [])
                    except Exception as e:
                        print(f"⚠️ Error getting final game decisions: {e}")

                # Full names are passed through as-is - the renderer scrolls
                # them on screen if they're too wide to fit, instead of us
                # cutting them down to "LastName, F" / 10 characters here.

                game_data = {
                    'game_id': game.get('game_id'),
                    'status': game_status,
                    'home': {
                        'name': home_name,
                        'code': home_code,
                        'runs': home_score,
                        'hits': home_hits,
                        'errors': home_errors,
                        'color': home_color
                    },
                    'away': {
                        'name': away_name,
                        'code': away_code,
                        'runs': away_score,
                        'hits': away_hits,
                        'errors': away_errors,
                        'color': away_color
                    },
                    'inning': {
                        'state': inning_state,
                        'number': inning,
                        'is_final': game_status == 'final'
                    },
                    'count': {
                        'balls': balls,
                        'strikes': strikes,
                        'outs': outs
                    },
                    'bases': bases,
                    'pitcher': pitcher_name,
                    'batter': batter_name,
                    'pitch_count': pitch_count,
                    'last_pitch': last_pitch,
                    'play_result': play_result,
                    'play_event': play_event,
                    'no_hitter': no_hitter,
                    'perfect_game': perfect_game,
                    'winning_pitcher': winning_pitcher,
                    'losing_pitcher': losing_pitcher,
                    'save_pitcher': save_pitcher,
                    'linescore_innings': linescore_innings,
                    'start_time': game.get('game_datetime', ''),
                    'start_time_local': format_local_time(game.get('game_datetime', ''))
                }
                processed_games.append(game_data)
            
            return processed_games
            
        except Exception as e:
            print(f"❌ Error fetching MLB games: {e}")
            return []
    
    def get_giants_game(self):
        """Get the preferred team's game if they're playing today"""
        all_games = self.get_today_games()
        preferred = self._get_preferred_code()

        preferred_game = None
        other_games = []

        for game in all_games:
            if (game['home']['code'] == preferred or
                game['away']['code'] == preferred):
                preferred_game = game
            else:
                other_games.append(game)

        if preferred_game:
            print(f"✅ Found {preferred} game: {preferred_game['away']['code']} @ {preferred_game['home']['code']} ({preferred_game['status']})")
        else:
            print(f"📅 No {preferred} game today")

        return preferred_game, other_games

    def get_games_for_display(self):
        """Get games to display. Prioritizes the preferred team's live game, then
        any other live games, then - if nothing is live - today's upcoming
        (pregame) games sorted by start time, so the screen has something to
        scroll through instead of sitting on a blank "no live games" message."""
        preferred_game, other_games = self.get_giants_game()

        if preferred_game and preferred_game['status'] == 'live':
            print(f"🎯 {self._get_preferred_code()} is live - showing only their game")
            return [preferred_game]

        all_games = ([preferred_game] if preferred_game else []) + other_games

        live_others = [g for g in all_games if g['status'] == 'live']
        if live_others:
            print(f"📊 Showing {len(live_others)} live game(s)")
            return live_others

        upcoming = sorted(
            (g for g in all_games if g['status'] == 'pregame'),
            key=lambda g: g.get('start_time', '')
        )
        if upcoming:
            print(f"🗓️ No live games - showing {len(upcoming)} upcoming game(s)")
            return upcoming

        print(f"📅 No live or upcoming games right now")
        return []

    def get_game_by_id(self, game_id):
        """Look up one specific game from today's full slate by its MLB gamePk -
        used when the web UI has the user pick an exact game to show, rather
        than the usual live/upcoming rotation."""
        for game in self.get_today_games():
            if str(game.get('game_id')) == str(game_id):
                return game
        return None

    def get_standings_for_display(self):
        """Standings for the preferred team's division. Hits the API fresh on
        every call - like get_today_games(), caching is the caller's job since
        standings only change a handful of times a day."""
        try:
            preferred = self._get_preferred_code()
            raw = statsapi.standings_data(leagueId='103,104', division='all')

            target_division = None
            for division in raw.values():
                for team in division['teams']:
                    if self.get_team_code(team['name']) == preferred:
                        target_division = division
                        break
                if target_division:
                    break

            # Preferred team not found (e.g. bad/unknown code) - fall back to
            # the first division rather than showing a blank screen.
            if target_division is None:
                target_division = next(iter(raw.values()), None)
            if target_division is None:
                return None

            short_name = DIVISION_SHORT_NAMES.get(target_division['div_name'], target_division['div_name'])
            teams = []
            for team in target_division['teams']:
                code = self.get_team_code(team['name'])
                teams.append({
                    'code': code,
                    'wins': team['w'],
                    'losses': team['l'],
                    'gb': team['gb'],
                    'rank': int(team['div_rank']),
                    'is_preferred': code == preferred
                })
            teams.sort(key=lambda t: t['rank'])

            return {'division': short_name, 'teams': teams}
        except Exception as e:
            print(f"⚠️ Error fetching standings: {e}")
            return None

    def get_full_standings(self):
        """Full MLB standings for all 30 teams, grouped into the 6 standard
        divisions (see MLB_DIVISIONS) with each division's teams sorted by win
        percentage - for the web control panel's Games page, which shows the
        whole league rather than just the preferred team's division (that's
        what get_standings_for_display() above is for, used by the LED
        standings screen). Sourced from ESPN rather than the MLB Stats API,
        matching nfl_integration.get_standings()'s approach - ESPN's endpoint
        happens to be the more convenient source for a full-league view.
        Hits the API fresh on every call - like get_today_games(), caching is
        the caller's job."""
        try:
            response = requests.get(MLB_STANDINGS_URL, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code != 200:
                print(f"⚠️ MLB standings fetch returned {response.status_code}")
                return {}
            data = response.json()
        except Exception as e:
            print(f"❌ Error fetching full MLB standings: {e}")
            return {}

        by_code = {}
        for league in data.get('children', []):
            for entry in league.get('standings', {}).get('entries', []):
                team = entry.get('team', {})
                code = team.get('abbreviation', '')
                code = ESPN_CODE_OVERRIDES.get(code, code)
                stats = {s['name']: s.get('displayValue', '') for s in entry.get('stats', [])}
                by_code[code] = {
                    'code': code,
                    'wins': stats.get('wins', '0'),
                    'losses': stats.get('losses', '0'),
                    'pct': stats.get('winPercent', '.000'),
                    'gb': stats.get('divisionGamesBehind', '-'),
                    'streak': stats.get('streak', '')
                }

        divisions = {}
        for division_name, codes in MLB_DIVISIONS.items():
            teams = [by_code[c] for c in codes if c in by_code]
            teams.sort(key=lambda t: float(t['pct'] or 0), reverse=True)
            divisions[division_name] = teams

        return divisions

# Global instance
mlb_fetcher = MLBDataFetcher("SF")  # Fallback if config.json has no preferred_team set
