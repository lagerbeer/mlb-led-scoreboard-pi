#!/home/pi/mlb_scoreboard_venv/bin/python
"""
Football Screen - live/pregame/final NFL game rendering

Team colors come straight from ESPN's own API response (team.color, a hex
string) rather than a hand-maintained per-team JSON file like the baseball
screen's colors_teams.json - ESPN already supplies real team colors per game,
so there's no 32-team list to keep in sync here. Team logos are fetched the
same way display_manager.py fetches stock logos: downloaded once from the URL
ESPN's own API already gives us, cached to disk, resized to fit the panel.
"""

import os
import requests
import rgbmatrix.graphics
from PIL import Image

LOGO_DIR = '/home/pi/mlb_scoreboard/assets/nfl_logos'
LOGO_SIZE = (16, 16)

# Two big team rows (24px each) sandwiched between a top row (clock/status,
# full width) and a bottom row (last play, full width). Within each team
# row, the code and score sit close together right after the logo instead of
# score being pushed out to the far edge - that used to leave a wide dead
# gap in the middle of every row. Ball placement (down-and-distance + field
# position) now lives in that reclaimed space, on whichever team's row
# currently has the ball - it's team-relative info by nature (e.g. "at NE
# 35"), so showing it on that team's own row instead of a shared top strip
# reinforces which side of the field it's talking about, same idea as the
# possession marker already sitting on that row.
LAYOUT = {
    "top_y": 9,
    "away": {"bg_y_start": 12, "bg_y_end": 32, "text_y": 27},
    "home": {"bg_y_start": 32, "bg_y_end": 52, "text_y": 47},
    "bottom_y": 61,
    "logo_x": 2,
    "code_x": 21,
    "score_gap": 6,
    "score_right_margin": 4
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

        # Per-field scroll position for status text too wide to fit
        # (e.g. "End of 3rd Quarter") - same mechanism as the other renderers.
        self._scroll = {}

    def get_contrasting_text_color(self, bg_color):
        luminance = (0.299 * bg_color.red + 0.587 * bg_color.green + 0.114 * bg_color.blue) / 255
        return self.BLACK if luminance > 0.5 else self.WHITE

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

    def fill_background(self, y_start, y_end, color):
        for y in range(y_start, y_end):
            for x in range(128):
                self.canvas.SetPixel(x, y, color.red, color.green, color.blue)

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
        """Three small 2x2 pip markers just under the score, lit up to
        however many timeouts that team has left (NFL: max 3 per half) -
        dimmed gray for used ones. Skipped entirely if ESPN didn't give us a
        timeout count for this team (see nfl_integration's note on
        homeTimeouts/awayTimeouts not yet being confirmed against a live
        game)."""
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
        ball - same filled-triangle technique as display_manager's stock
        trend arrow."""
        for row in range(5):
            half = min(row, 4 - row)
            for dx in range(half + 1):
                self.canvas.SetPixel(x + dx, y + row, color.red, color.green, color.blue)

    def _draw_team_row(self, team, bg_y_start, bg_y_end, text_y, has_possession, down_distance=None, red_zone=False):
        bg_color = rgbmatrix.graphics.Color(*team['color'])
        text_color = self.get_contrasting_text_color(bg_color)
        self.fill_background(bg_y_start, bg_y_end, bg_color)

        self.draw_logo(LAYOUT["logo_x"], bg_y_start + 2, team['code'], team.get('logo', ''))

        # team.get('rank') is only ever set by ncaaf_integration (AP Top 25
        # rank) - NFL games have no 'rank' key, so this is a no-op for them.
        code_x = LAYOUT["code_x"]
        display_text = f"#{team['rank']} {team['code']}" if team.get('rank') else team['code']
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large, code_x, text_y, text_color, display_text)
        cursor_x = code_x + self.text_width(self.font_large, display_text) + 3

        if has_possession:
            self._draw_possession_marker(cursor_x, text_y - 9, text_color)
            cursor_x += 8

        score_text = str(team.get('score', 0))
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large, cursor_x, text_y, text_color, score_text)
        cursor_x += self.text_width(self.font_large, score_text) + LAYOUT["score_gap"]

        timeouts_x = 128 - LAYOUT["score_right_margin"]
        self._draw_timeouts(timeouts_x, bg_y_end - 3, team.get('timeouts'), text_color)

        if down_distance:
            # Leave room for the timeout pips at the right edge - if there's
            # not enough space left to be legible, just skip it rather than
            # cramming a couple of scrambled characters in.
            max_width = (timeouts_x - 16) - cursor_x
            if max_width > 20:
                detail_color = self.RED if red_zone else text_color
                self.draw_scrolling_text(f"yardline-{team['code']}", self.font_small, cursor_x, text_y,
                                          max_width, detail_color, down_distance)

    def render_game(self, game):
        """Render complete game: a top row (clock/status, full width), away/
        home team rows (colored to that team's real color, code+score
        clustered together next to the logo, ball placement filling the rest
        of whichever team's row currently has possession), and the last play
        along the bottom. Pregame just centers the kickoff time on the top
        row - there's no clock or ball placement yet."""
        self.canvas.Fill(0, 0, 0)

        status_color = self.YELLOW
        status_text = game.get('status_text', '')
        down_distance = game.get('down_distance', '')
        last_play = game.get('last_play', '')
        red_zone = game.get('red_zone', False)
        possession = game.get('possession')

        if game['status'] == 'pregame':
            self._draw_centered(self.font_small, LAYOUT["top_y"], status_color, status_text)
        else:
            self.draw_scrolling_text("clock", self.font_small, 4, LAYOUT["top_y"], 120, status_color, status_text)

        self._draw_team_row(game['away'], LAYOUT["away"]["bg_y_start"], LAYOUT["away"]["bg_y_end"],
                             LAYOUT["away"]["text_y"], possession == 'away',
                             down_distance if possession == 'away' else None, red_zone)
        self._draw_team_row(game['home'], LAYOUT["home"]["bg_y_start"], LAYOUT["home"]["bg_y_end"],
                             LAYOUT["home"]["text_y"], possession == 'home',
                             down_distance if possession == 'home' else None, red_zone)

        if game['status'] == 'live' and last_play:
            self.draw_scrolling_text("lastplay", self.font_small, 4, LAYOUT["bottom_y"], 120, self.GRAY, last_play)
