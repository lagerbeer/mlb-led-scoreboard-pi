# MLB LED Scoreboard (Pro)

A Python app that drives a 128x64 RGB LED matrix panel on a Raspberry Pi, rotating between a live/upcoming MLB game, division standings, weather, and a stock ticker - with a Flask web control panel for configuration and manual screen control.

Not affiliated with MLB. Team names, logos, and data are property of MLB Advanced Media / their respective teams; this project just displays publicly available game data for personal use.

## Features

- **Baseball screen** - live score, ball/strike/out count, base runners, scrolling pitcher/batter names, last play, and a no-hitter/perfect-game badge (driven by the MLB Stats API's own `noHitter`/`perfectGame` flags). When nothing's live, it scrolls through today's upcoming games instead of sitting on a blank screen.
- **Standings screen** - shows the division standings for whichever team you've set as preferred, with that team's row highlighted in its own team color.
- **Weather screen** - current temp/humidity/clock via OpenWeatherMap (optional; falls back to manually-set values if no API key is configured).
- **Stock ticker** - rotates through a configurable list of symbols with live price/change and a mini chart (Yahoo Finance, no API key needed).
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
| `options.rotation_rate` | Seconds each top-level screen (weather/stocks/baseball/standings) stays up before rotating to the next |
| `options.stock_display_time` | Seconds per stock symbol within the stocks screen |
| `options.baseball_display_time` | Seconds per game within the baseball screen's own rotation |
| `options.preferred_team` | MLB team abbreviation (e.g. `SF`) - this team's live game takes priority, and drives which division shows on the standings screen |
| `tickers.stocks` | List of stock ticker symbols to rotate through |

`config.json` is gitignored since it holds your API key - everything else in the repo is safe to commit.

`options.stock_api_key`, `options.currency`, `options.date_format`, `options.show_logos`, and `options.chart_period` exist in the config file for historical reasons but aren't currently read by any code - safe to ignore.

### 4. Install as systemd services

Two services are provided under `systemd/`: `mlb-weather.service` runs the actual display loop (needs `root` for GPIO access), and `mlb-web.service` runs the Flask control panel.

```bash
sudo cp /home/pi/mlb_scoreboard_pro/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mlb-weather.service mlb-web.service
```

The web control panel is then available at `http://<pi-ip>:5000`.

## Usage

- **Auto rotation** (default): cycles through weather → stocks → baseball → standings on a timer (`options.rotation_rate`).
- **Manual screen override**: from the control panel, pin the display to one screen type (Weather/Stocks/Baseball/Standings) until you switch back to auto rotation.
- **Pick a specific game**: from the Games page (`/games`), hit "Show on Matrix" on any game to pin the display to that exact game, live or upcoming. It stays pinned until you resume auto rotation or pick another screen/game.

Config changes made through the web UI take effect immediately - the display process picks them up via a signal/reload flag, no restart needed.

## Project structure

| File | Purpose |
|---|---|
| `display_manager.py` | Main loop - owns the RGBMatrix canvas, rotates between screens, renders weather/stocks itself, delegates baseball/standings to their dedicated renderers |
| `baseball_complete.py` | `BaseballRenderer` - live/pregame/final game rendering |
| `standings_screen.py` | `StandingsRenderer` - division standings rendering |
| `mlb_integration.py` | MLB Stats API wrapper - today's games, live game detail, standings, team-name/code/color lookups |
| `web_interface.py` | Flask control panel + Games page |
| `colors_elements.json` | Per-element color overrides (counts, no-hitter badge, standings header, etc.) |
| `colors_teams.json` | Per-team background/text/accent colors |
| `config.example.json` | Template for `config.json` (which is gitignored) |

## Credits

- [MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI) for the Python wrapper around MLB's Stats API
- [rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) by hzeller for the matrix driver and Python bindings
- [MLB-LED-Scoreboard](https://github.com/MLB-LED-Scoreboard/mlb-led-scoreboard) - the standings and no-hitter/perfect-game indicator features were inspired by this project's design
