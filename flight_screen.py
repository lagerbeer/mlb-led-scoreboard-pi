#!/home/pi/mlb_scoreboard_venv/bin/python
"""
Flight Screen - shows one nearby aircraft at a time

Layout follows the reference project's approach (ColinWaddell/FlightTracker):
three big, centered rows - route, callsign, aircraft type - as the visual
focus, rather than cramming everything in at the same size. Altitude/speed
still get shown, but as a smaller fourth row rather than competing for
attention with the main three.
"""

import json
import rgbmatrix.graphics

with open('/home/pi/mlb_scoreboard_pro/colors_elements.json', 'r') as f:
    ELEMENT_COLORS = json.load(f)

LAYOUT = {
    "route": {"y": 16},
    "callsign": {"y": 34},
    "aircraft": {"y": 50},
    "telemetry": {"y": 60},
    "counter": {"x": 108, "y": 8}
}


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

    def _draw_centered(self, font, y, color, text):
        width = self.text_width(font, text)
        rgbmatrix.graphics.DrawText(self.canvas, font, (128 - width) // 2, y, color, text)

    def render(self, flight, index=None, total=None):
        """flight: {'callsign','altitude_ft','ground_speed_kt','heading',
        'origin','destination','aircraft_code','distance_km'}"""
        self.canvas.Fill(0, 0, 0)

        if index is not None and total is not None and total > 1:
            counter_color = self.get_color("flight.detail", (150, 150, 150))
            counter_text = f"{index + 1}/{total}"
            counter_width = self.text_width(self.font_small, counter_text)
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small,
                                       128 - counter_width - 2, LAYOUT["counter"]["y"],
                                       counter_color, counter_text)

        origin = flight.get("origin")
        destination = flight.get("destination")
        if origin or destination:
            route_text = f"{origin or '???'} -> {destination or '???'}"
        else:
            route_text = "En Route"
        route_color = self.get_color("flight.route", (120, 220, 100))
        self._draw_centered(self.font_large, LAYOUT["route"]["y"], route_color, route_text)

        callsign_color = self.get_color("flight.callsign", (255, 255, 255))
        self._draw_centered(self.font_large, LAYOUT["callsign"]["y"], callsign_color, flight["callsign"])

        aircraft_code = flight.get("aircraft_code")
        if aircraft_code:
            aircraft_color = self.get_color("flight.aircraft", (200, 130, 255))
            self._draw_centered(self.font_large, LAYOUT["aircraft"]["y"], aircraft_color, aircraft_code)

        # Smaller row below the three main ones - keeps route/callsign/aircraft
        # as the visual focus while still surfacing altitude/speed.
        telemetry_text = f"{flight['altitude_ft']:,}ft @ {flight['ground_speed_kt']}kt"
        telemetry_color = self.get_color("flight.detail", (150, 150, 150))
        self._draw_centered(self.font_small, LAYOUT["telemetry"]["y"], telemetry_color, telemetry_text)
