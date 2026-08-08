#!/home/pi/mlb_scoreboard_venv/bin/python
"""
Standings Screen - shows the preferred team's division standings
"""

import json
import rgbmatrix.graphics

with open('/home/pi/mlb_scoreboard_pro/colors_elements.json', 'r') as f:
    ELEMENT_COLORS = json.load(f)

with open('/home/pi/mlb_scoreboard_pro/colors_teams.json', 'r') as f:
    TEAM_COLORS = json.load(f)

# 5 teams per division + a header row, one per 9px row starting at y=18 (10px
# under the title) - the same 5x8 small font used throughout the baseball
# screen, sized to fit all 6 rows within the panel's 64px height.
LAYOUT = {
    "title": {"x": 4, "y": 8},
    "rows": {
        "x_code": 4,
        "x_record": 30,
        "x_gb": 76,
        "y_start": 18,
        "row_height": 9
    }
}

class StandingsRenderer:
    def __init__(self):
        # No matrix/canvas of its own - display_manager.py hands this renderer
        # its canvas right before every render() call, same pattern as
        # BaseballRenderer.
        self.canvas = None

        self.font_small = rgbmatrix.graphics.Font()
        self.font_small.LoadFont("/home/pi/mlb_scoreboard/fonts/5x8.bdf")

        self.WHITE = rgbmatrix.graphics.Color(255, 255, 255)
        self.BLACK = rgbmatrix.graphics.Color(0, 0, 0)

    def get_color(self, element_path, default_rgb=(255, 235, 59)):
        parts = element_path.split('.')
        data = ELEMENT_COLORS
        try:
            for part in parts:
                data = data[part]
            if 'r' in data:
                return rgbmatrix.graphics.Color(data['r'], data['g'], data['b'])
        except Exception:
            pass
        r, g, b = default_rgb
        return rgbmatrix.graphics.Color(r, g, b)

    def get_team_color(self, team_code):
        team_upper = team_code.upper()
        if team_upper in TEAM_COLORS:
            color_data = TEAM_COLORS[team_upper].get("home", TEAM_COLORS["default"]["home"])
        else:
            color_data = TEAM_COLORS["default"]["home"]
        return rgbmatrix.graphics.Color(color_data["r"], color_data["g"], color_data["b"])

    def get_contrasting_text_color(self, bg_color):
        luminance = (0.299 * bg_color.red + 0.587 * bg_color.green + 0.114 * bg_color.blue) / 255
        return self.BLACK if luminance > 0.5 else self.WHITE

    def render(self, standings):
        """standings: {'division': str, 'teams': [{'code','wins','losses','gb','is_preferred'}, ...]}"""
        self.canvas.Fill(0, 0, 0)

        title_color = self.get_color("standings.title", (255, 235, 59))
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["title"]["x"], LAYOUT["title"]["y"],
                                   title_color, standings["division"])

        header_color = self.get_color("standings.header", (150, 150, 150))
        y = LAYOUT["rows"]["y_start"]
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, LAYOUT["rows"]["x_code"], y, header_color, "TM")
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, LAYOUT["rows"]["x_record"], y, header_color, "W-L")
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small, LAYOUT["rows"]["x_gb"], y, header_color, "GB")

        for i, team in enumerate(standings["teams"]):
            row_y = y + (i + 1) * LAYOUT["rows"]["row_height"]

            if team["is_preferred"]:
                bg = self.get_team_color(team["code"])
                text_color = self.get_contrasting_text_color(bg)
                for yy in range(row_y - 7, row_y + 2):
                    for xx in range(128):
                        self.canvas.SetPixel(xx, yy, bg.red, bg.green, bg.blue)
            else:
                text_color = self.WHITE

            rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                       LAYOUT["rows"]["x_code"], row_y, text_color, team["code"])
            record = f"{team['wins']}-{team['losses']}"
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                       LAYOUT["rows"]["x_record"], row_y, text_color, record)
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                       LAYOUT["rows"]["x_gb"], row_y, text_color, str(team["gb"]))
