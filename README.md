# MLB LED Scoreboard (Pro)

A Python app that drives a 128x64 RGB LED matrix panel on a Raspberry Pi, rotating between a live/upcoming MLB game, division standings, nearby aircraft, weather, and a stock ticker - with a Flask web control panel for configuration and manual screen control.

Not affiliated with MLB. Team names, logos, and data are property of MLB Advanced Media / their respective teams; this project just displays publicly available game data for personal use.

## Features

- **Baseball screen** - full inning-by-inning linescore (runs per inning + R/H/E, team-colored rows), ball/strike/out count, scrolling pitcher name with this game's pitch count, last pitch speed/type or last play (strikeouts get their own color), and a no-hitter/perfect-game announcement (driven by the MLB Stats API's own `noHitter`/`perfectGame` flags) that takes over the play-by-play row while a bid is active. The final screen adds winning/losing/save pitcher. When nothing's live, it scrolls through today's upcoming games instead of sitting on a blank screen. (There's no bases-occupied diamond - a 128px-wide panel doesn't have room for both that and a readable linescore, and the linescore is the more broadcast-standard thing to prioritize.)
- **Standings screen** - shows the division standings for whichever team you've set as preferred, with that team's row highlighted in its own team color.
- **Flight tracker screen** - three big centered rows (route, callsign, aircraft type) for whatever's currently overhead within a configurable radius of home, styled after the reference project's own display rather than cramming in every telemetry field at once. Uses the unofficial FlightRadar24 API - no account or hardware receiver needed. (Approach inspired by [ColinWaddell/FlightTracker](https://github.com/ColinWaddell/FlightTracker) - see Credits.)
- **Weather screen** - an animated icon (rotating sun, twinkling moon + stars, drifting clouds, falling rain, flashing thunderstorm, falling snow, or drifting fog) matched to OpenWeatherMap's own condition/day-night code, plus temperature, condition text, feels-like, humidity, clock, and city. Falls back to manually-set temp/humidity (shown as clear/sunny) if no API key is configured.
- **Stock ticker** - rotates through a configurable list of symbols, Yahoo-Finance-styled: company logo, name, and a market-open/closed status bar up top, price and signed change/percent with a trend arrow, and a filled area chart colored to match the period's trend (Yahoo Finance's own chart endpoint, no API key needed). Layout adapted from [feram18/led-stock-ticker](https://github.com/feram18/led-stock-ticker) - see Credits. Chart period (1 Day through All) is configurable in the web UI - the change/% shown always reflects growth or loss over whichever period is selected, same as picking a range on Yahoo Finance's own chart.
- **Web control panel** (`:5000`) - edit weather/stock/baseball/display settings, pick your preferred team, and manually pin the display to one specific screen.
- **Games page** (`:5000/games`) - browse every game scheduled today (live, upcoming, or final) and push any one of them to the matrix on demand.

## Hardware

- Raspberry Pi (any model capable of driving the matrix at a reasonable refresh rate)
- 128x64 HUB75 RGB LED matrix panel (this project's layout is hardcoded to 128x64; a panel with an FM6126A driver chip is assumed in `display_manager.py`'s `RGBMatrixOptions` - adjust `panel_type`/`hardware_mapping`/`multiplexing` in that file to match your panel if it's different)
- An [Adafruit RGB Matrix HAT](https://www.adafruit.com/product/3211) or equivalent, and adequate 5V power for the panel

## Directory layout

This repo is `mlb_scoreboard_pro/` - the application itself. It expects a **sibling directory**, `mlb_scoreboard/`, containing the LED matrix driver and font assets:

```
/home/pi/
├── mlb_scoreboard/            # driver + fonts (not part of this repo)
│   ├── submodules/matrix/     # hzeller/rpi-rgb-led-matrix, with Python bindings built
│   ├── fonts/                 # .bdf fonts shipped with rpi-rgb-led-matrix
│   ├── 5x7.bdf, 7x13.bdf, 10x20.bdf   # copies of specific fonts at the top level
│   └── assets/logos/          # auto-created cache dir for stock logos
├── mlb_scoreboard_venv/       # Python virtualenv
└── mlb_scoreboard_pro/        # THIS REPO
```

## Installation

These steps assume Raspberry Pi OS with Python 3 already installed, and everything running as user `pi` with home directory `/home/pi`.

### 1. Build the LED matrix driver

```bash
mkdir -p /home/pi/mlb_scoreboard/submodules
cd /home/pi/mlb_scoreboard/submodules
git clone https://github.com/hzeller/rpi-rgb-led-matrix.git matrix
cd matrix
make build-python PYTHON=$(which python3)
sudo make install-python PYTHON=$(which python3)
```

Copy the fonts this project needs directly into `mlb_scoreboard/` (the code loads a few by an absolute path one level up from the `fonts/` folder that ships with the library):

```bash
cp /home/pi/mlb_scoreboard/submodules/matrix/fonts/{5x7,7x13,10x20}.bdf /home/pi/mlb_scoreboard/
mkdir -p /home/pi/mlb_scoreboard/fonts
cp /home/pi/mlb_scoreboard/submodules/matrix/fonts/*.bdf /home/pi/mlb_scoreboard/fonts/
```

### 2. Clone this repo and set up the virtualenv

```bash
cd /home/pi
git clone https://github.com/lagerbeer/mlb-led-scoreboard-pi.git mlb_scoreboard_pro

python3 -m venv /home/pi/mlb_scoreboard_venv
/home/pi/mlb_scoreboard_venv/bin/pip install -r /home/pi/mlb_scoreboard_pro/requirements.txt
```

### 3. Configure

```bash
cd /home/pi/mlb_scoreboard_pro
cp config.example.json config.json
```

Edit `config.json`:

| Field | Notes |
|---|---|
| `weather.apikey` | Free [OpenWeatherMap](https://openweathermap.org/api) API key. Leave blank to use the manual `weather.temp`/`weather.humidity` fallback instead. |
| `weather.location` | `City,State,Country` (e.g. `Chicago,il,us`) |
| `weather.metric_units` | `true` for °C, `false` for °F |
| `display.brightness` | 0-100 |
| `options.rotation_rate` | Seconds each top-level screen (weather/stocks/baseball/standings/flights) stays up before rotating to the next |
| `options.stock_display_time` | Seconds per stock symbol within the stocks screen |
| `options.chart_period` | Yahoo chart range the stock screen fetches - `1d`, `5d`, `1mo`, `3mo`, `6mo`, `ytd`, `1y`, `2y`, `5y`, `10y`, or `max`. The change/% shown is growth or loss over this whole period, not just the day's move. Easiest set via the web UI's Chart Period dropdown rather than by hand. |
| `options.baseball_display_time` | Seconds per game within the baseball screen's own rotation |
| `options.flight_display_time` | Seconds per aircraft within the flight screen's own rotation |
| `options.preferred_team` | MLB team abbreviation (e.g. `SF`) - this team's live game takes priority, and drives which division shows on the standings screen |
| `tickers.stocks` | List of stock ticker symbols to rotate through |
| `flight.home_lat` / `flight.home_lon` | Decimal coordinates of the panel's location - aircraft distance/search radius is measured from here. Look these up once (e.g. via a geocoding API or Google Maps) and hardcode them; the app doesn't do this for you. |
| `flight.radius_km` | Search radius around home, in km |
| `flight.min_altitude_ft` / `flight.max_altitude_ft` | Altitude band to include - the default (500-45,000 ft) filters out ground traffic at nearby airports |

`config.json` is gitignored since it holds your API key - everything else in the repo is safe to commit.

`options.stock_api_key`, `options.currency`, `options.date_format`, and `options.show_logos` exist in the config file for historical reasons but aren't currently read by any code - safe to ignore.

The flight screen uses the unofficial FlightRadar24 API (via the `FlightRadarAPI` package), which rate-limits (returns empty results) if polled too often. `display_manager.py` caches flight data for 60 seconds for this reason - don't lower that interval without a good reason.

### 4. Install as systemd services

Two services are provided under `systemd/`: `mlb-weather.service` runs the actual display loop (needs `root` for GPIO access), and `mlb-web.service` runs the Flask control panel.

```bash
sudo cp /home/pi/mlb_scoreboard_pro/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mlb-weather.service mlb-web.service
```

The web control panel is then available at `http://<pi-ip>:5000`.

## Usage

- **Auto rotation** (default): cycles through weather → stocks → baseball → standings → flights on a timer (`options.rotation_rate`).
- **Manual screen override**: from the control panel, pin the display to one screen type (Weather/Stocks/Baseball/Standings/Flights) until you switch back to auto rotation.
- **Pick a specific game**: from the Games page (`/games`), hit "Show on Matrix" on any game to pin the display to that exact game, live or upcoming. It stays pinned until you resume auto rotation or pick another screen/game.

Config changes made through the web UI take effect immediately - the display process picks them up via a signal/reload flag, no restart needed.

## Adding a new screen

`display_manager.py` rotates screens by looking them up in a single dict built in `__init__`:

```python
self.screens = {
    "weather": self.draw_weather,
    "stocks": self.draw_stocks,
    "baseball": self.draw_baseball,
    "standings": self.draw_standings,
    "flights": self.draw_flights,
}
self.modes = list(self.screens.keys())  # rotation order = insertion order
```

Both the manual-screen-override dispatch and the auto-rotation dispatch in `run()` look a screen up from this dict rather than branching on its name - adding a screen doesn't touch dispatch logic at all. To add one:

1. Write a renderer, ideally in its own file mirroring `standings_screen.py` or `flight_screen.py`: a class that takes `self.canvas` (assigned by `display_manager.py` right before each render call) and a `render(...)` method that draws directly via `rgbmatrix.graphics` calls, sized for the 128x64 panel.
2. Write a `draw_x(self)` method on `DisplayManager` that owns that screen's own cache/rotation state (see `draw_baseball`/`draw_flights` for the pattern: cache data for N seconds, fall back to a message if empty, rotate through multiple items on its own timer if applicable).
3. Add one line to `self.screens` in `__init__`. That's it - it's now in both manual selection and auto rotation.
4. If it needs a web UI settings card or a manual-selector button, follow the pattern of any existing card/button in `web_interface.py` (they're all independent copy-paste templates, not driven by a shared registry - there's no equivalent abstraction needed there since it's one page, not a dispatch loop).

## Project structure

| File | Purpose |
|---|---|
| `display_manager.py` | Main loop - owns the RGBMatrix canvas, rotates between screens via the `self.screens` registry (see "Adding a new screen" below), renders weather/stocks itself, delegates baseball/standings/flights to their dedicated renderers |
| `baseball_complete.py` | `BaseballRenderer` - live/pregame/final game rendering |
| `standings_screen.py` | `StandingsRenderer` - division standings rendering |
| `flight_screen.py` | `FlightScreenRenderer` - nearby aircraft rendering |
| `mlb_integration.py` | MLB Stats API wrapper - today's games, live game detail, standings, team-name/code/color lookups |
| `flight_tracker.py` | FlightRadar24 wrapper - nearby aircraft within the configured radius/altitude band |
| `web_interface.py` | Flask control panel + Games page |
| `colors_elements.json` | Per-element color overrides (counts, no-hitter badge, standings header, etc.) |
| `colors_teams.json` | Per-team background/text/accent colors |
| `config.example.json` | Template for `config.json` (which is gitignored) |

## Credits

- [MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI) for the Python wrapper around MLB's Stats API
- [rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) by hzeller for the matrix driver and Python bindings
- [MLB-LED-Scoreboard](https://github.com/MLB-LED-Scoreboard/mlb-led-scoreboard) - the standings and no-hitter/perfect-game indicator features were inspired by this project's design
- [ColinWaddell/FlightTracker](https://github.com/ColinWaddell/FlightTracker) - the flight screen's approach (using the unofficial FlightRadar24 API for nearby-aircraft data) is inspired by this project, though the fetch/render code here is a from-scratch, much simpler implementation sized for this panel rather than a port of FlightTracker's own scene framework
- [feram18/led-stock-ticker](https://github.com/feram18/led-stock-ticker) - the stock screen's layout (market-status bar, company name row, edge-to-edge trend-colored chart) is adapted from this project, also built for a 128x64 panel
