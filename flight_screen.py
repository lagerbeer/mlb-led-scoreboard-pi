#!/home/pi/mlb_scoreboard_venv/bin/python
"""
Flight Screen - shows one nearby aircraft at a time
"""

import json
import rgbmatrix.graphics

with open('/home/pi/mlb_scoreboard_pro/colors_elements.json', 'r') as f:
    ELEMENT_COLORS = json.load(f)

LAYOUT = {
    "callsign": {"y": 14},
    "detail_left": {"x": 6, "y": 30},
    "detail_right": {"x": 70, "y": 30},
    "route": {"x": 6, "y": 42},
    "distance": {"x": 6, "y": 54},
    "counter": {"x": 108, "y": 8}
}

# 8-point compass, used instead of a degree symbol since the bitmap fonts
# used elsewhere on this panel don't reliably include "°".
COMPASS_POINTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def heading_to_compass(heading):
    idx = int((heading % 360) / 45 + 0.5) % 8
    return COMPASS_POINTS[idx]


class FlightScreenRenderer:
    def __init__(self):
        # No matrix/canvas of its own - display_manager.py hands this renderer
        # its canvas right before every render() call, same pattern as
        # BaseballRenderer/StandingsRenderer.
        self.canvas = None

        self.font_small = rgbmatrix.graphics.Font()
        self.font_small.LoadFont("/home/pi/mlb_scoreboard/fonts/5x8.bdf")

        self.font_large = rgbmatrix.graphics.Font()
        self.font_large.LoadFont("/home/pi/mlb_scoreboard/7x13.bdf")

        self.WHITE = rgbmatrix.graphics.Color(255, 255, 255)

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

    def text_width(self, font, text):
        return sum(font.CharacterWidth(ord(ch)) for ch in text)

    def render(self, flight, index=None, total=None):
        """flight: {'callsign','altitude_ft','ground_speed_kt','heading',
        'origin','destination','distance_km'}"""
        self.canvas.Fill(0, 0, 0)

        callsign_color = self.get_color("flight.callsign", (255, 235, 59))
        callsign = flight["callsign"]
        callsign_width = self.text_width(self.font_large, callsign)
        rgbmatrix.graphics.DrawText(self.canvas, self.font_large,
                                   (128 - callsign_width) // 2, LAYOUT["callsign"]["y"],
                                   callsign_color, callsign)

        if index is not None and total is not None and total > 1:
            counter_color = self.get_color("flight.detail", (150, 150, 150))
            counter_text = f"{index + 1}/{total}"
            counter_width = self.text_width(self.font_small, counter_text)
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                       128 - counter_width - 2, LAYOUT["counter"]["y"],
                                       counter_color, counter_text)

        detail_color = self.get_color("flight.detail", (255, 255, 255))
        alt_text = f"ALT {flight['altitude_ft']:,}ft"
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["detail_left"]["x"], LAYOUT["detail_left"]["y"],
                                   detail_color, alt_text)

        heading_text = heading_to_compass(flight["heading"])
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["detail_right"]["x"], LAYOUT["detail_right"]["y"],
                                   detail_color, heading_text)

        speed_text = f"GS {flight['ground_speed_kt']}kt"
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["detail_left"]["x"], LAYOUT["detail_left"]["y"] + 10,
                                   detail_color, speed_text)

        route_color = self.get_color("flight.route", (96, 239, 255))
        origin = flight.get("origin") or "???"
        destination = flight.get("destination") or "???"
        route_text = f"{origin} -> {destination}"
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["route"]["x"], LAYOUT["route"]["y"],
                                   route_color, route_text)

        distance_text = f"{flight['distance_km']} km away"
        rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                   LAYOUT["distance"]["x"], LAYOUT["distance"]["y"],
                                   detail_color, distance_text)
