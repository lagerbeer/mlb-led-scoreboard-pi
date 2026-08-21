#!/home/pi/mlb_scoreboard_venv/bin/python
"""
Football Screen - live/pregame/final NFL game rendering

Layout follows an ESPN-style scorecard (per the user's reference screenshot):
team logos side by side with the score centered between them, team code +
timeouts + possession indicator under each logo, down-and-distance/field
position combined on one centered line below that, and the last play along
the bottom. No team-colored background bars - logos carry the color instead,
matching the reference's flat dark background.

Team colors/logos come straight from ESPN's own API response (team.color,
a hex string, and team.logo, a URL) rather than a hand-maintained per-team
JSON file like the baseball screen's colors_teams.json - ESPN already
supplies both per game. Logos are fetched the same way display_manager.py
fetches stock logos: downloaded once, cached to disk, resized to fit.
"""

import os
import requests
import rgbmatrix.graphics
from PIL import Image

LOGO_DIR = '/home/pi/mlb_scoreboard/assets/nfl_logos'
LOGO_SIZE = (16, 16)

LAYOUT = {
    "top_y": 8,
    "logo_y": 12,
    "score_y": 28,
    "name_y": 40,
    "detail_y": 51,
    "lastplay_y": 61,
    "away_logo_x": 4,
    "home_logo_x": 108,
}


class FootballRenderer:
    def __init__(self, logo_dir=LOGO_DIR):
        # No matrix/canvas of its own - display_manager.py hands this renderer
        # its canvas right before every render_game() call, same pattern as
        # BaseballRenderer/StandingsRenderer/FlightScreenRenderer.
        self.canvas = None

        # This renderer is shared between the NFL and NCAAF screens (same
        # game-dict shape, same drawing logic) - each gets its own logo cache
        # directory so a team-code collision between the two (e.g. both an
        # NFL and a college team using "MIA") can never serve the wrong
        # sport's cached logo for the other.
        self.logo_dir = logo_dir

        self.font_large = rgbmatrix.graphics.Font()
        self.font_large.LoadFont("/home/pi/mlb_scoreboard/7x13.bdf")

        self.font_small = rgbmatrix.graphics.Font()
        try:
            self.font_small.LoadFont("/home/pi/mlb_scoreboard/fonts/5x8.bdf")
        except:
            self.font_small = self.font_large

        self.WHITE = rgbmatrix.graphics.Color(255, 255, 255)
        self.BLACK = rgbmatrix.graphics.Color(0, 0, 0)
        self.YELLOW = rgbmatrix.graphics.Color(255, 235, 59)
        self.RED = rgbmatrix.graphics.Color(255, 60, 60)
        self.GRAY = rgbmatrix.graphics.Color(150, 150, 150)
        self.GREEN = rgbmatrix.graphics.Color(80, 220, 100)
        self.TEAL = rgbmatrix.graphics.Color(80, 170, 220)

        # Per-field scroll position for text too wide to fit its area - same
        # mechanism as the other renderers.
        self._scroll = {}

    def text_width(self, font, text):
        return sum(font.CharacterWidth(ord(ch)) for ch in text)

    def _draw_centered(self, font, y, color, text):
        width = self.text_width(font, text)
        rgbmatrix.graphics.DrawText(self.canvas, font, (128 - width) // 2, y, color, text)

    def draw_scrolling_text(self, key, font, x, y, max_width, color, text):
        state = self._scroll.get(key)
        if state is None or state["text"] != text:
            state = {"text": text, "offset": 0}
            self._scroll[key] = state

        width = self.text_width(font, text)
        if width <= max_width:
            rgbmatrix.graphics.DrawText(self.canvas, font, x, y, color, text)
            state["offset"] = 0
            return

        gap = "   "
        padded_text = text + gap
        padded_width = self.text_width(font, padded_text)
        clip_right = x + max_width

        self._draw_clipped_text(font, x - state["offset"], y, x, clip_right, color, padded_text)
        self._draw_clipped_text(font, x - state["offset"] + padded_width, y, x, clip_right, color, padded_text)

        state["offset"] += 1
        if state["offset"] >= padded_width:
            state["offset"] = 0

    def _draw_clipped_text(self, font, start_x, y, clip_left, clip_right, color, text):
        cx = start_x
        for ch in text:
            w = font.CharacterWidth(ord(ch))
            if clip_left <= cx < clip_right:
                rgbmatrix.graphics.DrawText(self.canvas, font, cx, y, color, ch)
            cx += w
            if cx >= clip_right:
                break

    def fetch_logo(self, code, url):
        """Downloads and caches one team's logo, keyed by team code - mirrors
        display_manager.py's fetch_logo() for stock company logos (same
        cached-file-size-sanity-check, same resize-once approach), just with
        a single known-good source URL instead of guessing between multiple."""
        if not url:
            return None

        os.makedirs(self.logo_dir, exist_ok=True)
        logo_path = os.path.join(self.logo_dir, f"{code}.png")

        if os.path.exists(logo_path):
            try:
                with Image.open(logo_path) as cached:
                    if cached.size == LOGO_SIZE:
                        return logo_path
            except Exception:
                pass

        try:
            response = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code == 200:
                with open(logo_path, 'wb') as f:
                    f.write(response.content)
                img = Image.open(logo_path).convert('RGBA')
                img = img.resize(LOGO_SIZE, Image.Resampling.LANCZOS)
                img.save(logo_path, 'PNG')
                return logo_path
        except Exception as e:
            print(f"⚠️ NFL logo fetch error for {code}: {e}")
        return None

    def draw_logo(self, x, y, code, url):
        logo_path = self.fetch_logo(code, url)
        if not logo_path:
            return

        try:
            logo = Image.open(logo_path).convert('RGBA')
            img_w, img_h = logo.size
            draw_w = min(LOGO_SIZE[0], img_w, 16)
            draw_h = min(LOGO_SIZE[1], img_h, 16)
            for dx in range(draw_w):
                for dy in range(draw_h):
                    canvas_x = x + dx
                    canvas_y = y + dy
                    if 0 <= canvas_x < 128 and 0 <= canvas_y < 64:
                        r, g, b, a = logo.getpixel((dx, dy))
                        if a > 128:
                            self.canvas.SetPixel(canvas_x, canvas_y, r, g, b)
        except Exception as e:
            print(f"⚠️ NFL logo draw error for {code}: {e}")

    def _draw_timeouts(self, right_x, y, timeouts, color):
        """Three small 2x2 pip markers, lit up to however many timeouts that
        team has left (NFL: max 3 per half) - dimmed gray for used ones.
        Skipped entirely if ESPN didn't give us a timeout count for this
        team. Dots run left-to-right, ending at right_x."""
        if timeouts is None:
            return

        dot_size = 2
        gap = 2
        total_width = 3 * dot_size + 2 * gap
        start_x = right_x - total_width

        for i in range(3):
            dot_x = start_x + i * (dot_size + gap)
            lit = i < timeouts
            dot_color = color if lit else self.GRAY
            for px in range(dot_size):
                for py in range(dot_size):
                    self.canvas.SetPixel(dot_x + px, y + py, dot_color.red, dot_color.green, dot_color.blue)

    def _draw_possession_marker(self, x, y, color):
        """Small right-pointing triangle (5px tall) marking which team has the
        ball - stands in for the reference design's football icon at this
        resolution. Same filled-triangle technique as display_manager's
        stock trend arrow."""
        for row in range(5):
            half = min(row, 4 - row)
            for dx in range(half + 1):
                self.canvas.SetPixel(x + dx, y + row, color.red, color.green, color.blue)

    def _team_display_text(self, team):
        # team.get('rank') is only ever set by ncaaf_integration (AP Top 25
        # rank) - NFL games have no 'rank' key, so this is a no-op for them.
        return f"#{team['rank']} {team['code']}" if team.get('rank') else team['code']

    def _draw_team_identity(self, team, has_possession, anchor_x, align_right):
        """Draws [code] [timeout pips] [possession marker] as one cluster,
        anchored either left (away, hangs off the logo's left edge) or right
        (home, ends flush with the logo's right edge) - same building blocks
        for both sides, just mirrored, so they land symmetrically without
        needing two separate code paths."""
        TIMEOUT_DOTS_WIDTH = 10  # matches _draw_timeouts's own math (3*2 + 2*2)
        MARKER_WIDTH = 6
        GAP = 4

        display_text = self._team_display_text(team)
        code_width = self.text_width(self.font_small, display_text)
        has_timeouts = team.get('timeouts') is not None

        total = code_width
        if has_timeouts:
            total += GAP + TIMEOUT_DOTS_WIDTH
        if has_possession:
            total += GAP + MARKER_WIDTH

        cx = (anchor_x - total) if align_right else anchor_x

        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, cx, LAYOUT["name_y"], self.WHITE, display_text)
        cx += code_width

        if has_timeouts:
            cx += GAP
            self._draw_timeouts(cx + TIMEOUT_DOTS_WIDTH, LAYOUT["name_y"] - 5, team.get('timeouts'), self.YELLOW)
            cx += TIMEOUT_DOTS_WIDTH

        if has_possession:
            cx += GAP
            self._draw_possession_marker(cx, LAYOUT["name_y"] - 6, self.YELLOW)

    def render_game(self, game):
        """Render complete game: top strip (league label left, clock/status
        right), team logos side by side with the score centered between
        them, team identity (code + timeouts + possession) under each logo,
        down-and-distance + field position combined on one centered line
        (e.g. "1st & 10 at SF 12"), and the last play along the bottom."""
        self.canvas.Fill(0, 0, 0)

        away = game['away']
        home = game['home']
        possession = game.get('possession')
        red_zone = game.get('red_zone', False)
        down_distance = game.get('down_distance', '')
        field_position = game.get('field_position', '')
        last_play = game.get('last_play', '')
        status_text = game.get('status_text', '')

        # Top strip
        league_label = "NCAAF" if 'rank' in away else "NFL"
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, 2, LAYOUT["top_y"], self.TEAL, league_label)

        if game['status'] == 'pregame':
            clock_text = game.get('start_time_local') or 'TBD'
            clock_color = self.GRAY
        else:
            clock_text = status_text
            clock_color = self.GREEN if game['status'] == 'live' else self.GRAY

        clock_width = self.text_width(self.font_small, clock_text)
        if clock_width <= 56:
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small, 126 - clock_width, LAYOUT["top_y"], clock_color, clock_text)
        else:
            self.draw_scrolling_text("clock", self.font_small, 70, LAYOUT["top_y"], 56, clock_color, clock_text)

        # Logos + centered score
        self.draw_logo(LAYOUT["away_logo_x"], LAYOUT["logo_y"], away['code'], away.get('logo', ''))
        self.draw_logo(LAYOUT["home_logo_x"], LAYOUT["logo_y"], home['code'], home.get('logo', ''))
        score_text = f"{away.get('score', 0)} - {home.get('score', 0)}"
        self._draw_centered(self.font_large, LAYOUT["score_y"], self.WHITE, score_text)

        # Team identity rows
        self._draw_team_identity(away, possession == 'away', LAYOUT["away_logo_x"], align_right=False)
        self._draw_team_identity(home, possession == 'home', LAYOUT["home_logo_x"] + 16, align_right=True)

        # Down-and-distance + field position, combined onto one centered line
        if down_distance or field_position:
            if down_distance and field_position:
                detail_text = f"{down_distance} at {field_position}"
            else:
                detail_text = down_distance or field_position
            detail_color = self.RED if red_zone else self.GRAY
            if self.text_width(self.font_small, detail_text) <= 120:
                self._draw_centered(self.font_small, LAYOUT["detail_y"], detail_color, detail_text)
            else:
                self.draw_scrolling_text("detail", self.font_small, 4, LAYOUT["detail_y"], 120, detail_color, detail_text)

        if game['status'] == 'live' and last_play:
            self.draw_scrolling_text("lastplay", self.font_small, 4, LAYOUT["lastplay_y"], 120, self.GRAY, last_play)
