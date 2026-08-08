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

# Layout coordinates. The header/team rows show a full inning-by-inning
# linescore (see render_scoreboard) instead of a bases diamond - there isn't
# room on a 128px-wide panel for both a readable 9-inning grid and a bases
# diamond at a legible size, and the linescore is the more broadcast-standard
# piece of information to prioritize.
LAYOUT = {
    "linescore": {
        "team_code_x": 4,
        "innings_x_start": 22,
        "innings_x_end": 96,
        "rhe_x": {"r": 100, "h": 109, "e": 118},
        "header_y": 8,
        "away_y": 20,
        "home_y": 32,
        "background": {
            "away": {"y_start": 11, "y_end": 22},
            "home": {"y_start": 22, "y_end": 34}
        }
    },
    # FINAL used to get its own header-row badge, but that slot is now the
    # linescore header - it's folded into the first decisions row instead
    # (see render_final).
    "final": {
        "decisions": {"x": 4, "y_start": 44, "row_height": 9}
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
    }
}

# Team-colored background bars now run the full panel width - there's no
# bases diamond to leave a gap for anymore.
TEAM_BACKGROUND_X_END = 128

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

    # ============= SCOREBOARD (header + team rows + linescore) =============
    # Replaces the old separate render_headers()/render_teams() - the header
    # row and team rows now form one inning-by-inning linescore grid, so they
    # need to agree on the same column positions and are easiest to keep in
    # sync as a single method.
    def _inning_columns(self, num_innings):
        """x position for each inning column (0-indexed), sized to fit the
        fixed budget between the team code and the R/H/E block. Compresses
        below the standard ~8px/inning width if the game has gone past 9
        innings, rather than running off the panel."""
        x_start = LAYOUT["linescore"]["innings_x_start"]
        x_end = LAYOUT["linescore"]["innings_x_end"]
        num_cols = max(9, num_innings)
        col_width = (x_end - x_start) / num_cols
        return [x_start + i * col_width for i in range(num_cols)]

    def render_scoreboard(self, game):
        """Full linescore: inning number header row, R/H/E header labels, and
        both teams' per-inning runs + R/H/E totals with team-colored row
        backgrounds. Shown identically across live/pregame/final - pregame
        just shows all-blank innings, same as a real park scoreboard before
        first pitch."""
        innings = game.get('linescore_innings') or []
        current_inning = (game.get('inning') or {}).get('number') or 0
        num_innings_needed = max(len(innings), current_inning)
        inning_x = self._inning_columns(num_innings_needed)
        rhe_x = LAYOUT["linescore"]["rhe_x"]
        header_y = LAYOUT["linescore"]["header_y"]
        away_y = LAYOUT["linescore"]["away_y"]
        home_y = LAYOUT["linescore"]["home_y"]

        header_color = self.get_color("inning.number", (255, 235, 59))
        for i, x in enumerate(inning_x):
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small, int(x), header_y, header_color, str(i + 1))
        for label, x in rhe_x.items():
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small, x, header_y, header_color, label.upper())

        away_bg_color = self.get_team_color(game['away']['code'], "home")
        home_bg_color = self.get_team_color(game['home']['code'], "home")
        away_text_color = self.get_contrasting_text_color(away_bg_color)
        home_text_color = self.get_contrasting_text_color(home_bg_color)

        self.fill_background(LAYOUT["linescore"]["background"]["away"]["y_start"],
                            LAYOUT["linescore"]["background"]["away"]["y_end"],
                            away_bg_color, TEAM_BACKGROUND_X_END)
        self.fill_background(LAYOUT["linescore"]["background"]["home"]["y_start"],
                            LAYOUT["linescore"]["background"]["home"]["y_end"],
                            home_bg_color, TEAM_BACKGROUND_X_END)

        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["linescore"]["team_code_x"], away_y,
                                   away_text_color, game['away']['code'])
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["linescore"]["team_code_x"], home_y,
                                   home_text_color, game['home']['code'])

        innings_by_num = {inn.get('num'): inn for inn in innings}
        for i, x in enumerate(inning_x):
            inning_data = innings_by_num.get(i + 1)
            away_runs = inning_data.get('away', {}).get('runs') if inning_data else None
            home_runs = inning_data.get('home', {}).get('runs') if inning_data else None
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small, int(x), away_y,
                                       away_text_color, str(away_runs) if away_runs is not None else "-")
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small, int(x), home_y,
                                       home_text_color, str(home_runs) if home_runs is not None else "-")

        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, rhe_x["r"], away_y, away_text_color, str(game['away'].get('runs', 0)))
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, rhe_x["h"], away_y, away_text_color, str(game['away'].get('hits', 0)))
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, rhe_x["e"], away_y, away_text_color, str(game['away'].get('errors', 0)))
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, rhe_x["r"], home_y, home_text_color, str(game['home'].get('runs', 0)))
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, rhe_x["h"], home_y, home_text_color, str(game['home'].get('hits', 0)))
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, rhe_x["e"], home_y, home_text_color, str(game['home'].get('errors', 0)))

    # ============= PITCHER =============
    def render_pitcher(self, pitcher_name, pitch_count=0):
        """Render pitcher name (with this game's pitch count, broadcast-style)
        close to P: label - scrolls if too wide to fit before the right edge
        of the panel."""
        pitcher_color = self.get_color("atbat.pitcher", (255, 235, 59))

        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["pitcher"]["label"]["x"],
                                   LAYOUT["pitcher"]["label"]["y"],
                                   pitcher_color, "P:")

        text = pitcher_name or ""
        if text and pitch_count:
            text = f"{text} ({pitch_count}p)"

        name_x = LAYOUT["pitcher"]["name"]["x"]
        max_width = 128 - name_x - 2
        self.draw_scrolling_text("pitcher", self.font_small, name_x,
                                  LAYOUT["pitcher"]["name"]["y"], max_width,
                                  pitcher_color, text)

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
    # Mirrors mlb-led-scoreboard's nohitter renderer: driven by the MLB API's
    # own gameData.flags.noHitter/perfectGame booleans, gated to inning 5+ so
    # a no-hit bid isn't flagged this early (common and unremarkable in the
    # 1st-4th). Used by render_play_result below - there's no separate header
    # badge slot anymore now that the header row is the linescore, so this
    # takes over the play-result row instead while a bid is active.
    NOHITTER_MIN_INNING = 5

    def _bases_description(self, bases):
        """Text description of occupied bases, e.g. "Man on 2nd" or "Bases
        loaded" - there's no room left on this layout for a bases diamond
        (see render_scoreboard's linescore), so this is the replacement,
        prefixed onto the play-result row rather than needing its own space."""
        if not bases:
            return ""
        on = []
        if bases.get('first'):
            on.append("1st")
        if bases.get('second'):
            on.append("2nd")
        if bases.get('third'):
            on.append("3rd")
        if len(on) == 3:
            return "Bases loaded"
        if len(on) == 2:
            return f"Men on {on[0]} and {on[1]}"
        if len(on) == 1:
            return f"Man on {on[0]}"
        return ""

    def render_play_result(self, result_text, play_event=None, last_pitch=None,
                            no_hitter=False, perfect_game=False, inning_number=0,
                            bases=None):
        """Render the last completed play if there is one; otherwise fall back
        to the last pitch thrown (speed + type), since that updates every
        pitch even mid-at-bat while result_text stays empty until the at-bat
        concludes. Strikeouts get the dedicated strikeout color. A no-hitter
        or perfect-game bid (inning 5+) takes over this row entirely, since
        it's more exciting/important than the play-by-play. Occupied bases
        get prefixed onto whichever of the above is showing, e.g. "Bases
        loaded - Strikeout swinging"."""
        if perfect_game and inning_number >= self.NOHITTER_MIN_INNING:
            text = "PERFECT GAME IN PROGRESS"
            color = self.get_color("perfect_game_text", (255, 110, 110))
        elif no_hitter and inning_number >= self.NOHITTER_MIN_INNING:
            text = "NO-HITTER IN PROGRESS"
            color = self.get_color("nohit_text", (255, 110, 110))
        elif result_text:
            text = result_text
            if play_event == "Strikeout":
                color = self.get_color("atbat.strikeout", (255, 0, 0))
            else:
                color = self.get_color("atbat.play_result", (255, 255, 255))
        elif last_pitch:
            text = f"Last pitch: {last_pitch['speed']:.0f}mph {last_pitch['type']}"
            color = self.get_color("atbat.pitch", (255, 255, 255))
        else:
            text = ""
            color = self.get_color("atbat.play_result", (255, 255, 255))

        runners = self._bases_description(bases)
        if runners:
            text = f"{runners} - {text}" if text else runners

        x = LAYOUT["play_result"]["x"]
        max_width = 128 - x - 2
        self.draw_scrolling_text("play_result", self.font_small, x,
                                  LAYOUT["play_result"]["y"], max_width,
                                  color, text)

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

    # ============= FINAL GAME =============
    def render_final(self, game):
        """Render final game screen: full linescore (via render_scoreboard),
        plus winning/losing/save pitcher below. "FINAL" no longer gets its
        own header-row badge (that slot is the linescore header now) - it's
        folded into the first decisions row instead."""
        self.render_scoreboard(game)

        decision_color = self.get_color("final.scrolling_text", (255, 235, 59))

        def last_name(full_name):
            return full_name.split()[-1] if full_name else ""

        first_row = "FINAL"
        if game.get("winning_pitcher"):
            first_row += f"  W: {last_name(game['winning_pitcher'])}"
        rows = [first_row]
        if game.get("losing_pitcher"):
            rows.append(f"L: {last_name(game['losing_pitcher'])}")
        if game.get("save_pitcher"):
            rows.append(f"SV: {last_name(game['save_pitcher'])}")

        y = LAYOUT["final"]["decisions"]["y_start"]
        for row_text in rows:
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                       LAYOUT["final"]["decisions"]["x"], y,
                                       decision_color, row_text)
            y += LAYOUT["final"]["decisions"]["row_height"]

    # ============= PREGAME =============
    def render_pregame(self, game):
        """Render pregame screen: full linescore (blank innings, since the
        game hasn't started - via render_scoreboard), plus a centered
        first-pitch time below it (start_time_local is already converted to
        the system's local timezone by mlb_integration.py - the API only
        gives UTC)."""
        self.render_scoreboard(game)

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
            self.render_scoreboard(game)
            self.render_balls_and_inning(game['count']['balls'], game['inning']['state'], game['inning']['number'])
            self.render_pitcher(game.get('pitcher', ''), game.get('pitch_count', 0))
            self.render_batter(game.get('batter', ''))
            self.render_play_result(game.get('play_result', ''), game.get('play_event', ''), game.get('last_pitch'),
                                     game.get('no_hitter', False), game.get('perfect_game', False), game['inning']['number'],
                                     game.get('bases'))
            self.render_count(game['count']['strikes'], game['count']['outs'])

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
