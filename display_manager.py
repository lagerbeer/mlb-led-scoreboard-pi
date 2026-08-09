#!/usr/bin/env python3
"""
Modern Display Manager - With Better Error Handling
"""

import time
import json
import os
import sys
import requests
import signal
import traceback
from datetime import datetime
from PIL import Image

# Add rgbmatrix path
sys.path.insert(0, '/home/pi/mlb_scoreboard/submodules/matrix/bindings/python')

from rgbmatrix import RGBMatrix, RGBMatrixOptions
import rgbmatrix.graphics

# Import MLB integration
from mlb_integration import mlb_fetcher
from baseball_complete import BaseballRenderer
from standings_screen import StandingsRenderer
from flight_tracker import flight_fetcher
from flight_screen import FlightScreenRenderer

# Configuration file
CONFIG_FILE = '/home/pi/mlb_scoreboard_pro/config.json'
MODE_FILE = '/tmp/mlb_display_mode.json'
RELOAD_FLAG = '/tmp/mlb_display_reload'
LOGO_DIR = '/home/pi/mlb_scoreboard/assets/logos'
LOGO_SIZE = (16, 16)

class DisplayManager:
    def __init__(self):
        try:
            # Get brightness from config first
            self.load_config()
            brightness = self.config.get('display', {}).get('brightness', 90)
            
            # Matrix setup
            options = RGBMatrixOptions()
            options.rows = 64
            options.cols = 128
            options.gpio_slowdown = 4
            options.brightness = brightness
            options.hardware_mapping = "regular"
            options.panel_type = "FM6126A"
            options.disable_hardware_pulsing = True
            options.drop_privileges = False
            options.multiplexing = 0  # Try different values if lines persist

            self.matrix = RGBMatrix(options=options)
            self.canvas = self.matrix.CreateFrameCanvas()
            self.brightness = brightness

            # Load fonts
            self.font_large = rgbmatrix.graphics.Font()
            self.font_large.LoadFont("/home/pi/mlb_scoreboard/7x13.bdf")
            
            self.font_clock = rgbmatrix.graphics.Font()
            self.font_clock.LoadFont("/home/pi/mlb_scoreboard/10x20.bdf")
            
            self.font_small = rgbmatrix.graphics.Font()
            try:
                self.font_small.LoadFont("/home/pi/mlb_scoreboard/5x7.bdf")
            except:
                self.font_small = self.font_large

            # Colors
            self.YELLOW = rgbmatrix.graphics.Color(255, 255, 0)
            self.GREEN = rgbmatrix.graphics.Color(0, 255, 0)
            self.TEAL = rgbmatrix.graphics.Color(0, 128, 128)
            self.RED = rgbmatrix.graphics.Color(255, 0, 0)
            self.WHITE = rgbmatrix.graphics.Color(255, 255, 255)
            self.GRAY = rgbmatrix.graphics.Color(100, 100, 100)
            self.ORANGE = rgbmatrix.graphics.Color(255, 165, 0)
            
            # Create logo directory
            os.makedirs(LOGO_DIR, exist_ok=True)
            
            # Display state. self.screens is the single source of truth for what
            # screens exist and their rotation order - adding a new screen means
            # adding one entry here (plus its own draw_*/state setup) rather than
            # touching dispatch logic in two places in run(). Built here rather
            # than as a class-level dict since it binds to this instance's methods.
            self.screens = {
                "weather": self.draw_weather,
                "stocks": self.draw_stocks,
                "baseball": self.draw_baseball,
                "standings": self.draw_standings,
                "flights": self.draw_flights,
            }
            self.modes = list(self.screens.keys())
            self.current_mode_index = 0
            self.current_mode = self.modes[0]
            self.last_switch = time.time()
            
            # Manual mode flag
            self.manual_mode = False
            self.manual_screen = None
            self.manual_game_id = None  # set when the web UI picks one specific game

            # Load initial mode
            self.load_mode()
            
            # Set up signal handler for mode changes
            signal.signal(signal.SIGUSR1, self.handle_mode_signal)
            
            # Stock state
            self.stock_index = 0
            self.stock_cache = {}
            self.last_stock_update = 0
            self.last_stock_change = time.time()

            # Per-field scroll position for text too wide to fit its area -
            # same mechanism as BaseballRenderer._scroll (mirrors it here
            # since this class owns weather/stocks text directly rather than
            # delegating to a dedicated renderer).
            self._scroll = {}
            
            # Weather state
            self.weather_cache = None
            self.weather_cache_time = 0
            
            # Baseball state
            self.baseball_index = 0
            self.baseball_cache = []
            self.last_baseball_update = 0
            self.last_baseball_change = time.time()

            # Manually-selected single game (from the Games web page) - separate
            # cache from the auto-rotation one above since it tracks one specific
            # gamePk instead of "whatever's live/upcoming right now".
            self.selected_game_cache = None
            self.last_selected_game_update = 0

            # Baseball renderer
            self.baseball_renderer = BaseballRenderer()

            # Standings state - refreshed every 5 minutes since standings only
            # change a handful of times a day, unlike the baseball/stock screens.
            self.standings_cache = None
            self.last_standings_update = 0
            self.standings_renderer = StandingsRenderer()

            # Flight state - refreshed every 60s (matches baseball's cadence).
            # The unofficial FR24 API returns empty results if polled too
            # frequently, so this must not be fetched on every frame.
            self.flight_index = 0
            self.flight_cache = []
            self.last_flight_update = 0
            self.last_flight_change = time.time()
            self.flight_renderer = FlightScreenRenderer()
            
            # Clear screen on startup
            self.canvas.Fill(0, 0, 0)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)
            
            print("✅ Display manager initialized successfully")
            
        except Exception as e:
            print(f"❌ Initialization error: {e}")
            traceback.print_exc()
            sys.exit(1)
    
    def load_config(self):
        """Load configuration from JSON file"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    self.config = json.load(f)
                print(f"✅ Loaded config from {CONFIG_FILE}")
            else:
                print(f"⚠️ Config file not found, creating default")
                self.config = {
                    "weather": {
                        "apikey": "b484b586a93f8d25c600360b110b43f0",
                        "location": "Davenport,fl,us",
                        "metric_units": True,
                        "temp": "72",
                        "humidity": "45"
                    },
                    "display": {
                        "brightness": 90
                    },
                    "options": {
                        "stock_api_key": "SVQ3B011RLV2539M",
                        "rotation_rate": 20,
                        "stock_display_time": 5,
                        "baseball_display_time": 8,
                        "currency": "USD",
                        "date_format": "MM/DD/YYYY",
                        "show_logos": True,
                        "chart_period": "1d"
                    },
                    "tickers": {
                        "stocks": ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "UPS"]
                    }
                }
                self.save_config()
        except Exception as e:
            print(f"⚠️ Error loading config: {e}")
            self.config = {}
    
    def save_config(self):
        """Save configuration to file"""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
        except:
            pass
    
    def load_mode(self):
        """Load display mode from mode file"""
        try:
            if os.path.exists(MODE_FILE):
                with open(MODE_FILE, 'r') as f:
                    mode_data = json.load(f)
                    self.manual_mode = (mode_data.get('mode') == 'manual')
                    self.manual_screen = mode_data.get('screen')
                    self.manual_game_id = mode_data.get('game_id')
                    if self.manual_mode:
                        detail = f" (game {self.manual_game_id})" if self.manual_game_id else ""
                        print(f"🎯 Manual mode: showing {self.manual_screen}{detail}")
                    else:
                        print("🔄 Auto rotation mode")
        except:
            pass
    
    def check_reload_flag(self):
        """Check if we need to reload config"""
        if os.path.exists(RELOAD_FLAG):
            try:
                # Remove the flag
                os.remove(RELOAD_FLAG)
                # Reload config and mode
                self.load_config()
                self.load_mode()
                print("🔄 Reloaded configuration")
                return True
            except:
                pass
        return False
    
    def handle_mode_signal(self, signum, frame):
        """Handle SIGUSR1 to reload mode"""
        print("📡 Received mode update signal")
        self.load_mode()
    
    def fetch_logo(self, symbol):
        """Fetch company logo"""
        logo_path = os.path.join(LOGO_DIR, f"{symbol}.png")

        # A cached file only counts if it's actually the size we expect - some
        # logos in this cache predate LOGO_SIZE being 16x16 (found some at
        # 32x14), which made draw_logo's getpixel() go out of bounds on every
        # single draw. Re-fetching a bad cache entry is cheap and self-heals
        # this instead of silently failing forever.
        if os.path.exists(logo_path):
            try:
                with Image.open(logo_path) as cached:
                    if cached.size == LOGO_SIZE:
                        return logo_path
            except Exception:
                pass

        # logo.clearbit.com (the original source here) shut down its free
        # Logo API after Clearbit's 2023 HubSpot acquisition - the domain
        # doesn't even resolve anymore, so every fetch was silently failing.
        # Both of these are keyed by ticker symbol directly, no domain
        # guessing needed.
        sources = [
            f"https://financialmodelingprep.com/image-stock/{symbol}.png",
            f"https://companieslogo.com/img/orig/{symbol}.png"
        ]

        for url in sources:
            try:
                response = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
                if response.status_code == 200:
                    with open(logo_path, "wb") as f:
                        f.write(response.content)
                    img = Image.open(logo_path).convert("RGBA")
                    img = img.resize(LOGO_SIZE, Image.Resampling.LANCZOS)
                    img.save(logo_path, "PNG")
                    return logo_path
            except:
                continue
        return None
    
    def draw_logo(self, x, y, symbol):
        """Draw logo on canvas"""
        logo_path = self.fetch_logo(symbol)
        if not logo_path:
            return
            
        try:
            logo = Image.open(logo_path).convert("RGBA")
            # Bounded by the image's actual size, not just LOGO_SIZE - a
            # mis-sized cache entry (see fetch_logo) shouldn't be able to
            # crash this with an out-of-range getpixel().
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
            print(f"⚠️ Logo draw error: {e}")

    # === SCROLLING TEXT ===
    # Same technique as BaseballRenderer.draw_scrolling_text: draws text once
    # if it fits, otherwise scrolls it right-to-left with a wraparound gap.
    def text_width(self, font, text):
        return sum(font.CharacterWidth(ord(ch)) for ch in text)

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

    # === WEATHER FUNCTIONS ===
    def get_weather(self):
        """Get weather data"""
        weather_config = self.config.get('weather', {})
        api_key = weather_config.get('apikey', '')
        location = weather_config.get('location', 'Chicago,us')
        metric = weather_config.get('metric_units', True)
        city = location.split(',')[0].strip().capitalize()
        
        if not api_key:
            temp = weather_config.get('temp', '72')
            humidity = weather_config.get('humidity', '45')
            unit = '°C' if metric else '°F'
            return {'city': city, 'temp': str(temp) + unit, 'humidity': str(humidity) + '%', 'icon': 'sunny'}
        
        try:
            units = 'metric' if metric else 'imperial'
            url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={api_key}&units={units}"
            response = requests.get(url, timeout=5)
            data = response.json()
            
            if response.status_code == 200:
                temp = round(data['main']['temp'])
                humidity = data['main']['humidity']
                condition = data['weather'][0]['main'].lower()
                icon = 'sunny' if 'clear' in condition else 'cloudy' if 'cloud' in condition else 'rain'
                return {
                    'city': city,
                    'temp': str(temp) + ('°C' if metric else '°F'),
                    'humidity': str(humidity) + '%',
                    'icon': icon
                }
        except Exception as e:
            print(f"⚠️ Weather fetch error: {e}")
        
        temp = weather_config.get('temp', '72')
        humidity = weather_config.get('humidity', '45')
        unit = '°C' if metric else '°F'
        return {'city': city, 'temp': str(temp) + unit, 'humidity': str(humidity) + '%', 'icon': 'sunny'}
    
    def draw_weather(self):
        """Draw weather screen"""
        try:
            self.canvas.Fill(0, 0, 0)
            
            if not self.weather_cache or time.time() - self.weather_cache_time > 300:
                self.weather_cache = self.get_weather()
                self.weather_cache_time = time.time()
            
            weather = self.weather_cache
            
            # Temperature
            rgbmatrix.graphics.DrawText(self.canvas, self.font_large, 0, 13, self.YELLOW, weather['temp'])
            
            # Simple weather icon
            for i in range(5):
                for j in range(5):
                    self.canvas.SetPixel(59 + j, 4 + i, 255, 255, 0)
            
            # Humidity
            hum_len = len(weather['humidity']) * 7
            rgbmatrix.graphics.DrawText(self.canvas, self.font_large, 127 - hum_len, 13, self.YELLOW, weather['humidity'])
            
            # Clock
            clock = datetime.now().strftime("%H:%M:%S")
            clock_x = (128 - (len(clock) * 10)) // 2
            rgbmatrix.graphics.DrawText(self.canvas, self.font_clock, clock_x, 32, self.TEAL, clock)
            
            # City
            city = weather['city'][:15]
            city_x = (128 - (len(city) * 7)) // 2
            rgbmatrix.graphics.DrawText(self.canvas, self.font_large, city_x, 63, self.GREEN, city)
        except Exception as e:
            print(f"⚠️ Weather draw error: {e}")
    
    # === STOCK FUNCTIONS ===
    # Trimmed off the end of a company's long name for a cleaner fit on a
    # small display ("Apple Inc." -> "Apple") - same suffix list used by
    # feram18/led-stock-ticker, a similar RGB-matrix stock ticker project.
    NAME_SUFFIXES = ['Company', 'Corporation', 'Holdings', 'Incorporated', 'Inc', '.com', '(The)']

    # Yahoo's chart endpoint needs an explicit interval for anything beyond
    # ~8 days of range - without one it 422s past 5d (verified against the
    # real API: 1m granularity is only allowed for 8 days). Each entry is
    # (range, interval, short display label) keyed by the same range string
    # stored in config - these are the periods Yahoo Finance's own UI offers.
    CHART_PERIODS = {
        '1d':  ('1d',  '2m',  '1D'),
        '5d':  ('5d',  '15m', '1W'),
        '1mo': ('1mo', '1d',  '1M'),
        '3mo': ('3mo', '1d',  '3M'),
        '6mo': ('6mo', '1d',  '6M'),
        'ytd': ('ytd', '1d',  'YTD'),
        '1y':  ('1y',  '1d',  '1Y'),
        '2y':  ('2y',  '1wk', '2Y'),
        '5y':  ('5y',  '1wk', '5Y'),
        '10y': ('10y', '1mo', '10Y'),
        'max': ('max', '1mo', 'All'),
    }

    def _clean_company_name(self, name):
        for suffix in self.NAME_SUFFIXES:
            name = name.replace(suffix, '')
        return name.rstrip('& .,').rstrip()

    def _downsample(self, values, max_points=30):
        """The chart line only needs ~30 points to look smooth on a 120px-wide
        panel - a 5y/1wk fetch alone can return 250+, and this gets redrawn
        every ~100ms display frame, so trimming it down matters for
        performance, not just tidiness."""
        if len(values) <= max_points:
            return values
        step = len(values) / max_points
        return [values[int(i * step)] for i in range(max_points)]

    def get_stock_data(self, symbol):
        """Get stock data from Yahoo Finance for the configured chart period.
        Change/% change reflect growth over that whole period (last price vs
        the period's first price), not just today's move - so switching the
        period in the web UI actually changes what the numbers mean, same as
        picking a range on Yahoo Finance's own chart."""
        period_key = self.config.get('options', {}).get('chart_period', '1d')
        yahoo_range, interval, period_label = self.CHART_PERIODS.get(period_key, self.CHART_PERIODS['1d'])

        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={yahoo_range}&interval={interval}"
            response = requests.get(url, timeout=10, headers=headers)

            if response.status_code == 200:
                data = response.json()
                if 'chart' in data and data['chart']['result']:
                    result = data['chart']['result'][0]
                    meta = result.get('meta', {})
                    price = meta.get('regularMarketPrice', 0)

                    indicators = result.get('indicators', {})
                    quote = indicators.get('quote', [{}])[0]
                    closes = [p for p in quote.get('close', []) if p is not None]

                    period_start = closes[0] if closes else price
                    change = price - period_start
                    change_pct = (change / period_start * 100) if period_start > 0 else 0

                    name = meta.get('longName') or meta.get('shortName') or symbol
                    name = self._clean_company_name(name)

                    # No explicit "market state" field on this endpoint - derive
                    # it from whether now falls inside today's regular session.
                    is_market_open = False
                    try:
                        regular = meta['currentTradingPeriod']['regular']
                        is_market_open = regular['start'] <= time.time() <= regular['end']
                    except (KeyError, TypeError):
                        pass

                    return {
                        'symbol': symbol,
                        'name': name,
                        'is_market_open': is_market_open,
                        'price': round(price, 2),
                        'change': round(change, 2),
                        'change_pct': round(change_pct, 2),
                        'period_label': period_label,
                        'prices': self._downsample(closes)
                    }
        except Exception as e:
            print(f"⚠️ Stock fetch error for {symbol}: {e}")

        # Fallback
        base = 100 + (hash(symbol) % 200)
        prices = [base * (1 + 0.01 * (i % 5 - 2)) for i in range(20)]
        return {
            'symbol': symbol,
            'name': symbol,
            'is_market_open': False,
            'price': base,
            'change': base * 0.01,
            'change_pct': 1.0,
            'period_label': period_label,
            'prices': prices
        }
    
    def draw_trend_arrow(self, x, y, up, color):
        """Small filled 5x5 triangle - up for a gain, down for a loss."""
        for row in range(5):
            half = row if up else 4 - row
            for dx in range(-half, half + 1):
                self.canvas.SetPixel(x + 2 + dx, y + row, color.red, color.green, color.blue)

    def draw_stock(self, stock):
        """Draw a single stock screen, Yahoo Finance style: a market-status
        bar + logo/symbol/price at top, the company name below that
        (scrolling if too wide), change with a trend arrow (colored and
        signed the same way for both the dollar amount and the percent),
        then a filled area chart in that same trend color. Layout and the
        market-status-bar idea are adapted from feram18/led-stock-ticker,
        another RGB-matrix stock ticker built for the same 128x64 panel."""
        try:
            self.canvas.Fill(0, 0, 0)

            status_color = self.GREEN if stock.get('is_market_open') else self.RED
            for sy in range(2, 18):
                self.canvas.SetPixel(0, sy, status_color.red, status_color.green, status_color.blue)
                self.canvas.SetPixel(1, sy, status_color.red, status_color.green, status_color.blue)

            self.draw_logo(4, 2, stock['symbol'])

            rgbmatrix.graphics.DrawText(self.canvas, self.font_large, 22, 15, self.YELLOW, stock['symbol'])

            price = f"${stock['price']:.2f}"
            price_len = len(price) * 10
            rgbmatrix.graphics.DrawText(self.canvas, self.font_clock, 127 - price_len, 15, self.WHITE, price)

            name = stock.get('name') or stock['symbol']
            self.draw_scrolling_text('stock_name', self.font_small, 4, 26, 122, self.GRAY, name)

            change = stock['change']
            is_up = change >= 0
            trend_color = self.GREEN if is_up else self.RED
            sign = '+' if is_up else ''

            self.draw_trend_arrow(4, 29, is_up, trend_color)
            # Prefixed with the period the change is over (1D/1M/1Y/etc) -
            # without it, a change/% pair with no time context "makes no
            # sense" on its own. Scrolls if a period label + wide dollar
            # amount ever don't fit (e.g. "10Y: +1234.56 (+312.45%)").
            period_label = stock.get('period_label', '1D')
            change_text = f"{period_label}: {sign}{change:.2f} ({sign}{stock['change_pct']:.2f}%)"
            self.draw_scrolling_text('stock_change', self.font_small, 14, 36, 112, trend_color, change_text)

            if 'prices' in stock and len(stock['prices']) > 1:
                self.draw_chart(stock['prices'], 4, 42, 120, 19, trend_color)

            # Progress bar sits below the chart now - it used to be drawn at a
            # fixed y=58 while the chart spanned y=40-60, so it overlapped
            # the bottom of the chart whenever the price dipped low there.
            progress = (time.time() - self.last_stock_change) / self.config['options']['stock_display_time']
            bar_width = int(120 * min(1.0, progress))
            for i in range(bar_width):
                self.canvas.SetPixel(4 + i, 63, 80, 80, 80)
        except Exception as e:
            print(f"⚠️ Stock draw error: {e}")
    
    def draw_stocks(self):
        """Draw stocks screen with internal rotation"""
        symbols = self.config.get('tickers', {}).get('stocks', [])
        if not symbols:
            return
        
        # Always advance to next stock based on timer
        if time.time() - self.last_stock_change >= self.config['options']['stock_display_time']:
            self.stock_index = (self.stock_index + 1) % len(symbols)
            self.last_stock_change = time.time()
        
        symbol = symbols[self.stock_index]
        
        if symbol not in self.stock_cache or time.time() - self.last_stock_update > 60:
            stock = self.get_stock_data(symbol)
            self.stock_cache[symbol] = stock
            self.last_stock_update = time.time()
        else:
            stock = self.stock_cache[symbol]
        
        self.draw_stock(stock)
    
    def draw_chart(self, prices, x, y, width, height, color):
        """Draw a line chart with a shaded area underneath, Yahoo Finance
        style - color is the trend color (green for a gain, red for a loss),
        with the fill a dimmed version of it."""
        try:
            if len(prices) < 2:
                return

            valid = [p for p in prices if p is not None]
            if len(valid) < 2:
                return

            max_p = max(valid)
            min_p = min(valid)
            if max_p == min_p:
                max_p += 0.01

            points = []
            for i, p in enumerate(valid):
                px = x + int(i * (width / (len(valid) - 1)))
                py = y + height - int(((p - min_p) / (max_p - min_p)) * height)
                points.append((px, py))

            fill_color = rgbmatrix.graphics.Color(color.red // 4, color.green // 4, color.blue // 4)
            baseline = y + height

            # Fill: shade every column from the line down to the baseline,
            # stepping along each segment so the fill has no gaps even on
            # steep segments.
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                steps = max(abs(x2 - x1), 1)
                for s in range(steps + 1):
                    t = s / steps
                    cx = int(x1 + (x2 - x1) * t)
                    cy = int(y1 + (y2 - y1) * t)
                    for fy in range(cy, baseline + 1):
                        self.canvas.SetPixel(cx, fy, fill_color.red, fill_color.green, fill_color.blue)

            # Line on top of the fill.
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                rgbmatrix.graphics.DrawLine(self.canvas, x1, y1, x2, y2, color)
        except Exception as e:
            print(f"⚠️ Chart draw error: {e}")
    
    # === BASEBALL FUNCTIONS ===
    def draw_baseball(self):
        """Draw baseball screen with internal rotation"""
        try:
            # A specific game picked on the Games web page overrides the usual
            # live/upcoming rotation entirely - refreshed every 15s (faster than
            # the 60s auto-rotation cache) since the whole point of picking one
            # game is to watch it closely.
            if self.manual_mode and self.manual_screen == 'baseball' and self.manual_game_id:
                if not self.selected_game_cache or time.time() - self.last_selected_game_update > 15:
                    self.selected_game_cache = mlb_fetcher.get_game_by_id(self.manual_game_id)
                    self.last_selected_game_update = time.time()

                if not self.selected_game_cache:
                    self.canvas.Fill(0, 0, 0)
                    rgbmatrix.graphics.DrawText(self.canvas, self.font_large, 8, 32, self.RED, "Game Not Found")
                    return

                self.baseball_renderer.canvas = self.canvas
                self.baseball_renderer.render_game(self.selected_game_cache)
                return

            # Update games list periodically - always replace the cache (even with an
            # empty list) so a game ending clears it instead of leaving stale data on screen.
            if time.time() - self.last_baseball_update > 60:
                games = mlb_fetcher.get_games_for_display()
                self.baseball_cache = games
                print(f"📊 Loaded {len(games)} game(s) for display")
                self.last_baseball_update = time.time()

            if not self.baseball_cache:
                # No live or upcoming games today
                self.canvas.Fill(0, 0, 0)
                rgbmatrix.graphics.DrawText(self.canvas, self.font_large, 14, 32, self.RED, "No Games Today")
                return

            # Keep the index in range in case the cache shrank since the last rotation.
            self.baseball_index = self.baseball_index % len(self.baseball_cache)

            # Always advance to next game based on timer
            baseball_display_time = self.config.get('options', {}).get('baseball_display_time', 8)
            if time.time() - self.last_baseball_change >= baseball_display_time:
                self.baseball_index = (self.baseball_index + 1) % len(self.baseball_cache)
                self.last_baseball_change = time.time()

            game = self.baseball_cache[self.baseball_index]
            
            # Use the dedicated baseball renderer
            self.baseball_renderer.canvas = self.canvas
            self.baseball_renderer.render_game(game)
        except Exception as e:
            print(f"⚠️ Baseball draw error: {e}")

    # === STANDINGS FUNCTIONS ===
    def draw_standings(self):
        """Draw the preferred team's division standings"""
        try:
            if not self.standings_cache or time.time() - self.last_standings_update > 300:
                self.standings_cache = mlb_fetcher.get_standings_for_display()
                self.last_standings_update = time.time()

            if not self.standings_cache:
                self.canvas.Fill(0, 0, 0)
                rgbmatrix.graphics.DrawText(self.canvas, self.font_large, 10, 32, self.RED, "No Standings")
                return

            self.standings_renderer.canvas = self.canvas
            self.standings_renderer.render(self.standings_cache)
        except Exception as e:
            print(f"⚠️ Standings draw error: {e}")

    # === FLIGHT FUNCTIONS ===
    def draw_flights(self):
        """Draw nearby aircraft, rotating through them like the baseball
        screen rotates through games."""
        try:
            if time.time() - self.last_flight_update > 60:
                flights = flight_fetcher.get_nearby_flights()
                self.flight_cache = flights
                print(f"✈️ Found {len(flights)} nearby aircraft")
                self.last_flight_update = time.time()

            if not self.flight_cache:
                self.canvas.Fill(0, 0, 0)
                rgbmatrix.graphics.DrawText(self.canvas, self.font_large, 14, 32, self.RED, "No Aircraft")
                return

            self.flight_index = self.flight_index % len(self.flight_cache)

            flight_display_time = self.config.get('options', {}).get('flight_display_time', 8)
            if time.time() - self.last_flight_change >= flight_display_time:
                self.flight_index = (self.flight_index + 1) % len(self.flight_cache)
                self.last_flight_change = time.time()

            flight = self.flight_cache[self.flight_index]

            self.flight_renderer.canvas = self.canvas
            self.flight_renderer.render(flight, index=self.flight_index, total=len(self.flight_cache))
        except Exception as e:
            print(f"⚠️ Flight draw error: {e}")

    def run(self):
        """Main display loop"""
        print("🚀 Display manager running")
        print(f"📈 Stock display time: {self.config['options']['stock_display_time']}s")
        print(f"⚾ Baseball display time: {self.config['options']['baseball_display_time']}s")
        
        try:
            while True:
                # Check for reload flag
                self.check_reload_flag()
                
                # Draw current screen - looked up from the registry built in
                # __init__ rather than an if/elif chain, so a new screen only
                # needs an entry in self.screens, not a change here.
                if self.manual_mode and self.manual_screen:
                    draw_fn = self.screens.get(self.manual_screen)
                    if draw_fn:
                        draw_fn()
                else:
                    rotation_rate = self.config.get('options', {}).get('rotation_rate', 20)
                    self.screens[self.current_mode]()

                    if time.time() - self.last_switch > rotation_rate:
                        self.current_mode_index = (self.current_mode_index + 1) % len(self.modes)
                        self.current_mode = self.modes[self.current_mode_index]
                        self.last_switch = time.time()
                
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")
            self.canvas.Fill(0, 0, 0)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)
        except Exception as e:
            print(f"❌ Fatal error: {e}")
            traceback.print_exc()
            self.canvas.Fill(0, 0, 0)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

if __name__ == "__main__":
    display = DisplayManager()
    display.run()
