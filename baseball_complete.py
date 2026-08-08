#!/home/pi/mlb_scoreboard_venv/bin/python
"""
Complete Baseball Screen - With Team-Colored Backgrounds (Original Positioning)
"""

import time
import json
import sys
from datetime import datetime
sys.path.insert(0, '/home/pi/mlb_scoreboard/submodules/matrix/bindings/python')

from rgbmatrix import RGBMatrix, RGBMatrixOptions
import rgbmatrix.graphics

# Load configurations
with open('/home/pi/mlb_scoreboard_pro/colors_elements.json', 'r') as f:
    ELEMENT_COLORS = json.load(f)

with open('/home/pi/mlb_scoreboard_pro/colors_teams.json', 'r') as f:
    TEAM_COLORS = json.load(f)

# Layout coordinates - R/H/E moved left (was 85/100/115) to free up the right
# side for the bases diamond, which moved up near the top (was y=33/42) since
# that freed space is now clear all the way from the header row down through
# the team rows, instead of competing with the pitcher/batter area below.
LAYOUT = {
    "headers": {
        "rhe": {"x": 40, "y": 8, "text": "R H E"},
        "h": {"x": 53, "y": 8},
        "e": {"x": 66, "y": 8}
    },
    # Sits in the header row's dead space between "E" (ends ~x=72) and the bases
    # diamond (starts at x=94) - the one spot on this layout not already claimed
    # by another element.
    "nohitter": {"x": 76, "y": 8},
    "teams": {
        "away": {
            "name": {"x": 6, "y": 20},
            "runs": {"x": 40, "y": 20},
            "hits": {"x": 53, "y": 20},
            "errors": {"x": 66, "y": 20},
            "background": {"y_start": 11, "y_end": 22}
        },
        "home": {
            "name": {"x": 6, "y": 32},
            "runs": {"x": 40, "y": 32},
            "hits": {"x": 53, "y": 32},
            "errors": {"x": 66, "y": 32},
            "background": {"y_start": 22, "y_end": 34}
        }
    },
    # B:/S:/O: now stack vertically in a narrow column on the left (x=2), one per
    # row, sharing the same 3 row heights as pitcher/batter/play_result (which
    # shifted right to make room). Inning is drawn right after "B: <n>" on that
    # same row - its x isn't fixed here because it depends on the actual pixel
    # width of the balls text (which varies with the digit drawn), computed in
    # render_balls_and_inning(). Pitcher/batter/play_result names now have the
    # whole rest of the row (up to the right edge) to scroll in, instead of
    # stopping at x=70 for the old inning/count position.
    #
    # play_result sits below both pitcher and batter (rather than between them)
    # since it's the last thing that happened and reads more naturally after
    # who's involved in the next at-bat.
    "count": {
        "balls": {"x": 2, "y": 44},
        "strikes": {"x": 2, "y": 52},
        "outs": {"x": 2, "y": 60}
    },
    "pitcher": {
        "label": {"x": 40, "y": 44},
        "name": {"x": 50, "y": 44}
    },
    "batter": {
        "label": {"x": 40, "y": 52},
        "name": {"x": 50, "y": 52}
    },
    "play_result": {
        "x": 40, "y": 60
    },
    "bases": {
        "1B": {"x": 112, "y": 18, "size": 10},
        "2B": {"x": 103, "y": 9, "size": 10},
        "3B": {"x": 94, "y": 18, "size": 10}
    }
}

# Team-colored background bars stop a couple pixels short of the bases diamond
# (leftmost point is 3B's x) instead of running the full panel width, so the
# bar doesn't get drawn underneath/behind the bases.
TEAM_BACKGROUND_X_END = min(base["x"] for base in LAYOUT["bases"].values()) - 2

class BaseballRenderer:
    def __init__(self):
        # No matrix/canvas of its own - there's only one physical panel, owned by
        # display_manager.py. It hands this renderer its canvas (self.canvas) right
        # before every render_game() call. Previously this constructor created its
        # own second RGBMatrix for the same hardware, which is at best wasted GPIO
        # setup and at worst a contributing cause of display corruption.
        self.canvas = None

        # Load fonts
        self.font_large = rgbmatrix.graphics.Font()
        self.font_large.LoadFont("/home/pi/mlb_scoreboard/7x13.bdf")

        # 5x7.bdf (the font this used to load) has zero lowercase glyphs - every
        # mixed-case name (pitcher/batter) and play description silently rendered
        # as just its uppercase/digit characters. 5x8.bdf is only 1px taller than
        # the original but has full upper/lowercase coverage, and still fits the
        # 8px row spacing used throughout this layout without overlapping the row
        # below it.
        self.font_small = rgbmatrix.graphics.Font()
        try:
            self.font_small.LoadFont("/home/pi/mlb_scoreboard/fonts/5x8.bdf")
        except:
            self.font_small = self.font_large

        # Per-field scroll position for names too wide to fit their area - keyed by
        # a caller-chosen name (e.g. "pitcher", "batter"). Each entry also remembers
        # the text it was scrolling, so a new name (new batter up, screen switched to
        # a different game) resets to the start instead of continuing mid-scroll.
        self._scroll = {}

        # Colors
        bg = ELEMENT_COLORS["default"]["background"]
        self.BACKGROUND = rgbmatrix.graphics.Color(bg["r"], bg["g"], bg["b"])
        self.WHITE = rgbmatrix.graphics.Color(255, 255, 255)
        self.BLACK = rgbmatrix.graphics.Color(0, 0, 0)
        self.YELLOW = rgbmatrix.graphics.Color(255, 235, 59)
        self.GRAY50 = rgbmatrix.graphics.Color(50, 50, 50)

    def get_color(self, element_path, default_rgb=(255, 235, 59)):
        """Get color from element colors"""
        parts = element_path.split('.')
        data = ELEMENT_COLORS
        try:
            for part in parts:
                data = data[part]
            if 'r' in data:
                return rgbmatrix.graphics.Color(data['r'], data['g'], data['b'])
        except:
            pass
        r, g, b = default_rgb
        return rgbmatrix.graphics.Color(r, g, b)

    def get_team_color(self, team_code, color_type="home"):
        """Get team color"""
        team_upper = team_code.upper()
        if team_upper in TEAM_COLORS:
            color_data = TEAM_COLORS[team_upper].get(color_type, 
                         TEAM_COLORS[team_upper].get("home", {"r": 255, "g": 255, "b": 255}))
        else:
            color_data = TEAM_COLORS["default"]["home"]
        return rgbmatrix.graphics.Color(color_data["r"], color_data["g"], color_data["b"])

    def get_contrasting_text_color(self, bg_color):
        """Determine if white or black text provides better contrast on background"""
        luminance = (0.299 * bg_color.red + 0.587 * bg_color.green + 0.114 * bg_color.blue) / 255
        return self.BLACK if luminance > 0.5 else self.WHITE

    def fill_background(self, y_start, y_end, color, x_end=128):
        """Fill a horizontal strip with color, from x=0 up to (not including) x_end"""
        for y in range(y_start, y_end):
            for x in range(x_end):
                self.canvas.SetPixel(x, y, color.red, color.green, color.blue)

    # ============= SCROLLING TEXT =============
    def text_width(self, font, text):
        """Pixel width of text in the given font, without drawing it."""
        return sum(font.CharacterWidth(ord(ch)) for ch in text)

    def draw_scrolling_text(self, key, font, x, y, max_width, color, text):
        """Draws text at (x, y). If it fits within max_width, it's drawn once and
        stays put. If it's wider, it scrolls right-to-left, wrapping around with a
        gap, and resets to the start whenever the text itself changes (new batter,
        new pitcher, screen switched to a different game)."""
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

        # Two back-to-back copies so the wraparound looks seamless, both clipped to
        # [x, clip_right) so the scroll never bleeds into whatever's drawn to its right.
        self._draw_clipped_text(font, x - state["offset"], y, x, clip_right, color, padded_text)
        self._draw_clipped_text(font, x - state["offset"] + padded_width, y, x, clip_right, color, padded_text)

        state["offset"] += 1
        if state["offset"] >= padded_width:
            state["offset"] = 0

    def _draw_clipped_text(self, font, start_x, y, clip_left, clip_right, color, text):
        """Draws text one character at a time, skipping any character that starts
        outside [clip_left, clip_right) - DrawText itself has no clip-region concept."""
        cx = start_x
        for ch in text:
            w = font.CharacterWidth(ord(ch))
            if clip_left <= cx < clip_right:
                rgbmatrix.graphics.DrawText(self.canvas, font, cx, y, color, ch)
            cx += w
            if cx >= clip_right:
                break

    # ============= HEADERS =============
    def render_headers(self):
        """Render R H E header with proper spacing"""
        rhe_color = self.get_color("inning.number", (255, 235, 59))
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["headers"]["rhe"]["x"],
                                   LAYOUT["headers"]["rhe"]["y"],
                                   rhe_color, "R")
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["headers"]["h"]["x"],
                                   LAYOUT["headers"]["h"]["y"],
                                   rhe_color, "H")
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["headers"]["e"]["x"],
                                   LAYOUT["headers"]["e"]["y"],
                                   rhe_color, "E")

    # ============= NO-HITTER / PERFECT GAME =============
    # Mirrors mlb-led-scoreboard's nohitter renderer: a compact badge driven by
    # the MLB API's own gameData.flags.noHitter/perfectGame booleans, gated to
    # inning 5+ so a no-hit bid isn't flagged this early (common and unremarkable
    # in the 1st-4th).
    NOHITTER_MIN_INNING = 5

    def render_nohit_indicator(self, no_hitter, perfect_game, inning_number):
        if inning_number < self.NOHITTER_MIN_INNING:
            return
        if perfect_game:
            text, color = "P.G", self.get_color("perfect_game_text", (255, 110, 110))
        elif no_hitter:
            text, color = "N.H", self.get_color("nohit_text", (255, 110, 110))
        else:
            return

        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["nohitter"]["x"],
                                   LAYOUT["nohitter"]["y"],
                                   color, text)

    # ============= TEAMS =============
    def render_teams(self, game):
        """Render team names, runs, hits, errors with team-colored backgrounds"""
        # Get team colors
        away_bg_color = self.get_team_color(game['away']['code'], "home")
        home_bg_color = self.get_team_color(game['home']['code'], "home")
        
        # Get contrasting text colors
        away_text_color = self.get_contrasting_text_color(away_bg_color)
        home_text_color = self.get_contrasting_text_color(home_bg_color)
        
        # Fill backgrounds
        self.fill_background(LAYOUT["teams"]["away"]["background"]["y_start"],
                            LAYOUT["teams"]["away"]["background"]["y_end"],
                            away_bg_color, TEAM_BACKGROUND_X_END)
        self.fill_background(LAYOUT["teams"]["home"]["background"]["y_start"],
                            LAYOUT["teams"]["home"]["background"]["y_end"],
                            home_bg_color, TEAM_BACKGROUND_X_END)
        
        # Away team name
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   LAYOUT["teams"]["away"]["name"]["x"],
                                   LAYOUT["teams"]["away"]["name"]["y"],
                                   away_text_color, game['away']['code'])
        
        # Home team name
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   LAYOUT["teams"]["home"]["name"]["x"],
                                   LAYOUT["teams"]["home"]["name"]["y"],
                                   home_text_color, game['home']['code'])
        
        # Runs, Hits, Errors
        away_runs = str(game['away'].get('runs', 0))
        away_hits = str(game['away'].get('hits', 0))
        away_errors = str(game['away'].get('errors', 0))
        
        home_runs = str(game['home'].get('runs', 0))
        home_hits = str(game['home'].get('hits', 0))
        home_errors = str(game['home'].get('errors', 0))
        
        # Away stats
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   LAYOUT["teams"]["away"]["runs"]["x"],
                                   LAYOUT["teams"]["away"]["runs"]["y"],
                                   away_text_color, away_runs)
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   LAYOUT["teams"]["away"]["hits"]["x"],
                                   LAYOUT["teams"]["away"]["hits"]["y"],
                                   away_text_color, away_hits)
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   LAYOUT["teams"]["away"]["errors"]["x"],
                                   LAYOUT["teams"]["away"]["errors"]["y"],
                                   away_text_color, away_errors)
        
        # Home stats
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   LAYOUT["teams"]["home"]["runs"]["x"],
                                   LAYOUT["teams"]["home"]["runs"]["y"],
                                   home_text_color, home_runs)
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   LAYOUT["teams"]["home"]["hits"]["x"],
                                   LAYOUT["teams"]["home"]["hits"]["y"],
                                   home_text_color, home_hits)
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   LAYOUT["teams"]["home"]["errors"]["x"],
                                   LAYOUT["teams"]["home"]["errors"]["y"],
                                   home_text_color, home_errors)

    # ============= PITCHER =============
    def render_pitcher(self, pitcher_name):
        """Render pitcher name close to P: label - scrolls if too wide to fit
        before the right edge of the panel."""
        pitcher_color = self.get_color("atbat.pitcher", (255, 235, 59))

        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["pitcher"]["label"]["x"],
                                   LAYOUT["pitcher"]["label"]["y"],
                                   pitcher_color, "P:")

        name_x = LAYOUT["pitcher"]["name"]["x"]
        max_width = 128 - name_x - 2
        self.draw_scrolling_text("pitcher", self.font_small, name_x,
                                  LAYOUT["pitcher"]["name"]["y"], max_width,
                                  pitcher_color, pitcher_name or "")

    # ============= BALLS + INNING =============
    def render_balls_and_inning(self, balls, inning_state, inning_number):
        """Draws 'B: <n>' then the inning indicator right after it. The gap is
        computed from the actual measured width of the balls text rather than a
        fixed offset, since that width changes with the digit drawn - a fixed
        offset either overlapped a wide "B: <n>" or left an uneven gap for a
        narrow one. (T/B prefix on the inning number conveys the arrow's old job -
        there's no room left for a separate up/down arrow glyph here.)"""
        count_color = self.get_color("count.balls", (76, 217, 100))
        inning_color = self.get_color("inning.number", (255, 235, 59))

        x = LAYOUT["count"]["balls"]["x"]
        y = LAYOUT["count"]["balls"]["y"]
        balls_text = f"B: {balls}"
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, x, y, count_color, balls_text)

        inning_display = f"T{inning_number}" if inning_state == "Top" else f"B{inning_number}"
        inning_x = x + self.text_width(self.font_small, balls_text) + 3
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, inning_x, y, inning_color, inning_display)

    # ============= PLAY RESULT =============
    def render_play_result(self, result_text):
        """Render the last play - scrolls if too wide to fit before the right
        edge of the panel, same as the pitcher/batter names."""
        result_color = self.get_color("atbat.play_result", (255, 255, 255))
        x = LAYOUT["play_result"]["x"]
        max_width = 128 - x - 2
        self.draw_scrolling_text("play_result", self.font_small, x,
                                  LAYOUT["play_result"]["y"], max_width,
                                  result_color, result_text or "")

    # ============= BATTER =============
    def render_batter(self, batter_name):
        """Render batter name close to B: label - scrolls if too wide to fit
        before the right edge of the panel."""
        batter_color = self.get_color("atbat.batter", (255, 235, 59))

        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["batter"]["label"]["x"],
                                   LAYOUT["batter"]["label"]["y"],
                                   batter_color, "B:")

        name_x = LAYOUT["batter"]["name"]["x"]
        max_width = 128 - name_x - 2
        self.draw_scrolling_text("batter", self.font_small, name_x,
                                  LAYOUT["batter"]["name"]["y"], max_width,
                                  batter_color, batter_name or "")

    # ============= COUNT =============
    def render_count(self, strikes, outs):
        """Render strikes and outs (balls is drawn together with inning by
        render_balls_and_inning, since inning's position depends on it)"""
        strikes_color = self.get_color("count.strikes", (255, 235, 59))
        outs_color = self.get_color("count.outs", (255, 60, 60))

        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["count"]["strikes"]["x"],
                                   LAYOUT["count"]["strikes"]["y"],
                                   strikes_color, f"S: {strikes}")
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["count"]["outs"]["x"],
                                   LAYOUT["count"]["outs"]["y"],
                                   outs_color, f"O: {outs}")

    # ============= BASES =============
    def render_base_outline(self, base, color):
        x, y = base["x"], base["y"]
        size = base["size"]
        half = size // 2
        
        rgbmatrix.graphics.DrawLine(self.canvas, x + half, y, x, y + half, color)
        rgbmatrix.graphics.DrawLine(self.canvas, x + half, y, x + size, y + half, color)
        rgbmatrix.graphics.DrawLine(self.canvas, x + half, y + size, x, y + half, color)
        rgbmatrix.graphics.DrawLine(self.canvas, x + half, y + size, x + size, y + half, color)

    def render_baserunner(self, base, color):
        x, y = base["x"], base["y"]
        size = base["size"]
        half = size // 2
        
        for offset in range(1, half + 1):
            rgbmatrix.graphics.DrawLine(self.canvas, 
                                       x + half - offset, y + size - offset,
                                       x + half + offset, y + size - offset, color)
            rgbmatrix.graphics.DrawLine(self.canvas,
                                       x + half - offset, y + offset,
                                       x + half + offset, y + offset, color)

    def render_bases(self, bases):
        base_color = self.get_color("bases.1B", (255, 235, 59))
        
        base_order = ["1B", "2B", "3B"]
        base_keys = ["first", "second", "third"]
        
        for i, (base_name, base_key) in enumerate(zip(base_order, base_keys)):
            base = LAYOUT["bases"][base_name]
            occupied = bases.get(base_key, False)
            
            self.render_base_outline(base, base_color)
            if occupied:
                self.render_baserunner(base, base_color)

    # ============= FINAL GAME =============
    def render_final(self, game):
        """Render final game screen"""
        self.render_headers()
        self.render_teams(game)
        
        final_color = self.get_color("final.inning", (255, 235, 59))
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   60, 52, final_color, "FINAL")

    # ============= PREGAME =============
    def render_pregame(self, game):
        """Render pregame screen: team matchup, plus a centered first-pitch
        time below it (start_time_local is already converted to the system's
        local timezone by mlb_integration.py - the API only gives UTC)."""
        self.render_headers()
        self.render_teams(game)

        time_str = game.get('start_time_local') or 'TBD'

        label = "First Pitch"
        label_color = self.get_color("pregame.scrolling_text", (255, 235, 59))
        label_width = self.text_width(self.font_small, label)
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   (128 - label_width) // 2, 46,
                                   label_color, label)

        time_color = self.get_color("pregame.start_time", (255, 235, 59))
        time_width = self.text_width(self.font_large, time_str)
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   (128 - time_width) // 2, 60,
                                   time_color, time_str)

    # ============= MAIN RENDER METHOD =============
    def render_game(self, game):
        """Render complete game based on status"""
        # Start with black background
        self.canvas.Fill(0, 0, 0)
        
        if game['status'] == 'live':
            self.render_headers()
            self.render_nohit_indicator(game.get('no_hitter', False),
                                         game.get('perfect_game', False),
                                         game['inning']['number'])
            self.render_teams(game)
            self.render_balls_and_inning(game['count']['balls'], game['inning']['state'], game['inning']['number'])
            self.render_pitcher(game.get('pitcher', ''))
            self.render_batter(game.get('batter', ''))
            self.render_play_result(game.get('play_result', ''))
            self.render_count(game['count']['strikes'], game['count']['outs'])
            self.render_bases(game.get('bases', {}))
        
        elif game['status'] == 'final':
            self.render_final(game)
        else:
            self.render_pregame(game)

    def test(self):
        """Run test with sample data - this is the one case that needs its own
        matrix/canvas, since it's meant to run standalone (python baseball_complete.py),
        not through display_manager.py."""
        options = RGBMatrixOptions()
        options.rows = 64
        options.cols = 128
        options.gpio_slowdown = 4
        options.brightness = 90
        options.hardware_mapping = "regular"
        options.panel_type = "FM6126A"
        options.disable_hardware_pulsing = True
        options.drop_privileges = False
        options.multiplexing = 0

        self.matrix = RGBMatrix(options=options)
        self.canvas = self.matrix.CreateFrameCanvas()

        test_games = [
            # Live game with full stats
            {
                'status': 'live',
                'away': {'code': 'LAD', 'runs': 6, 'hits': 8, 'errors': 0},
                'home': {'code': 'SD', 'runs': 0, 'hits': 1, 'errors': 0},
                'inning': {'state': 'Bottom', 'number': 7},
                'count': {'balls': 0, 'strikes': 2, 'outs': 2},
                'bases': {'first': False, 'second': False, 'third': False},
                'pitcher': 'SMITTS',
                'batter': 'MAYS',
                'play_result': 'Strikeout swinging'
            },
            # Final game
            {
                'status': 'final',
                'away': {'code': 'LAD', 'runs': 6, 'hits': 8, 'errors': 0},
                'home': {'code': 'SD', 'runs': 0, 'hits': 1, 'errors': 0},
                'inning': {'number': 9, 'state': 'Final'}
            },
            # Pregame
            {
                'status': 'pregame',
                'away': {'code': 'LAD', 'runs': 0, 'hits': 0, 'errors': 0},
                'home': {'code': 'SD', 'runs': 0, 'hits': 0, 'errors': 0},
                'start_time': '2025-03-20T19:05:00Z'
            }
        ]
        
        print("🧪 Testing Baseball Screen - Original Background Positioning")
        print("============================================================")
        
        try:
            for i, game in enumerate(test_games, 1):
                print(f"\n📊 Test {i}: {game['away']['code']} @ {game['home']['code']} ({game['status']})")
                if 'count' in game:
                    print(f"   Count: B: {game['count']['balls']} S: {game['count']['strikes']} O: {game['count']['outs']}")
                self.render_game(game)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(8)
        except KeyboardInterrupt:
            print("\n🛑 Test stopped")
        finally:
            self.canvas.Fill(0, 0, 0)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

if __name__ == "__main__":
    renderer = BaseballRenderer()
    renderer.test()
