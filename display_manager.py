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
            
            # Display state - 4 modes
            self.modes = ["weather", "stocks", "baseball", "standings"]
            self.current_mode_index = 0
            self.current_mode = self.modes[0]
            self.last_switch = time.time()
            
            # Manual mode flag
            self.manual_mode = False
            self.manual_screen = None
            
            # Load initial mode
            self.load_mode()
            
            # Set up signal handler for mode changes
            signal.signal(signal.SIGUSR1, self.handle_mode_signal)
            
            # Stock state
            self.stock_index = 0
            self.stock_cache = {}
            self.last_stock_update = 0
            self.last_stock_change = time.time()
            
            # Weather state
            self.weather_cache = None
            self.weather_cache_time = 0
            
            # Baseball state
            self.baseball_index = 0
            self.baseball_cache = []
            self.last_baseball_update = 0
            self.last_baseball_change = time.time()
            
            # Baseball renderer
            self.baseball_renderer = BaseballRenderer()

            # Standings state - refreshed every 5 minutes since standings only
            # change a handful of times a day, unlike the baseball/stock screens.
            self.standings_cache = None
            self.last_standings_update = 0
            self.standings_renderer = StandingsRenderer()
            
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
                    if self.manual_mode:
                        print(f"🎯 Manual mode: showing {self.manual_screen}")
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
        domain_map = {
            "AAPL": "apple.com", "GOOGL": "google.com", "MSFT": "microsoft.com",
            "AMZN": "amazon.com", "TSLA": "tesla.com", "NVDA": "nvidia.com",
            "META": "meta.com", "NFLX": "netflix.com", "DIS": "disney.com",
            "UPS": "ups.com"
        }
        domain = domain_map.get(symbol, f"{symbol.lower()}.com")
        logo_path = os.path.join(LOGO_DIR, f"{symbol}.png")
        
        if os.path.exists(logo_path):
            return logo_path
            
        sources = [
            f"https://logo.clearbit.com/{domain}",
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
            for dx in range(min(LOGO_SIZE[0], 16)):
                for dy in range(min(LOGO_SIZE[1], 16)):
                    canvas_x = x + dx
                    canvas_y = y + dy
                    if 0 <= canvas_x < 128 and 0 <= canvas_y < 64:
                        r, g, b, a = logo.getpixel((dx, dy))
                        if a > 128:
                            self.canvas.SetPixel(canvas_x, canvas_y, r, g, b)
        except Exception as e:
            print(f"⚠️ Logo draw error: {e}")
    
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
    def get_stock_data(self, symbol):
        """Get stock data from Yahoo Finance"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            response = requests.get(url, timeout=10, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if 'chart' in data and data['chart']['result']:
                    result = data['chart']['result'][0]
                    meta = result.get('meta', {})
                    price = meta.get('regularMarketPrice', 0)
                    prev_close = meta.get('previousClose', price)
                    change = price - prev_close
                    change_pct = (change / prev_close * 100) if prev_close > 0 else 0
                    
                    # Get chart data
                    indicators = result.get('indicators', {})
                    quote = indicators.get('quote', [{}])[0]
                    closes = quote.get('close', [])
                    prices = [p for p in closes if p is not None][-20:]
                    
                    return {
                        'symbol': symbol,
                        'price': round(price, 2),
                        'change': round(change, 2),
                        'change_pct': round(change_pct, 2),
                        'prices': prices
                    }
        except Exception as e:
            print(f"⚠️ Stock fetch error for {symbol}: {e}")
        
        # Fallback
        base = 100 + (hash(symbol) % 200)
        prices = [base * (1 + 0.01 * (i % 5 - 2)) for i in range(20)]
        return {
            'symbol': symbol,
            'price': base,
            'change': base * 0.01,
            'change_pct': 1.0,
            'prices': prices
        }
    
    def draw_stock(self, stock):
        """Draw a single stock screen"""
        try:
            self.canvas.Fill(0, 0, 0)
            
            # Logo
            self.draw_logo(2, 2, stock['symbol'])
            
            # Symbol
            rgbmatrix.graphics.DrawText(self.canvas, self.font_large, 20, 15, self.YELLOW, stock['symbol'])
            
            # Price
            price = f"${stock['price']:.2f}"
            price_len = len(price) * 10
            rgbmatrix.graphics.DrawText(self.canvas, self.font_clock, 127 - price_len, 15, self.WHITE, price)
            
            # Change
            change = stock['change']
            change_color = self.GREEN if change >= 0 else self.RED
            change_text = f"{'+' if change >= 0 else ''}{change:.2f} ({stock['change_pct']:.2f}%)"
            rgbmatrix.graphics.DrawText(self.canvas, self.font_small, 20, 30, change_color, change_text)
            
            # Chart
            if 'prices' in stock and len(stock['prices']) > 1:
                self.draw_chart(stock['prices'], 10, 40, 108, 20)
            
            # Progress bar
            progress = (time.time() - self.last_stock_change) / self.config['options']['stock_display_time']
            bar_width = int(100 * min(1.0, progress))
            for i in range(bar_width):
                self.canvas.SetPixel(10 + i, 58, 0, 255, 0)
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
    
    def draw_chart(self, prices, x, y, width, height):
        """Draw a line chart"""
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
            
            for i in range(len(valid) - 1):
                x1 = x + int(i * (width / (len(valid) - 1)))
                x2 = x + int((i + 1) * (width / (len(valid) - 1)))
                y1 = y + height - int(((valid[i] - min_p) / (max_p - min_p)) * height)
                y2 = y + height - int(((valid[i + 1] - min_p) / (max_p - min_p)) * height)
                rgbmatrix.graphics.DrawLine(self.canvas, x1, y1, x2, y2, self.GREEN)
        except Exception as e:
            print(f"⚠️ Chart draw error: {e}")
    
    # === BASEBALL FUNCTIONS ===
    def draw_baseball(self):
        """Draw baseball screen with internal rotation"""
        try:
            # Update games list periodically - always replace the cache (even with an
            # empty list) so a game ending clears it instead of leaving stale data on screen.
            if time.time() - self.last_baseball_update > 60:
                games = mlb_fetcher.get_games_for_display()
                self.baseball_cache = games
                print(f"📊 Loaded {len(games)} live game(s) for display")
                self.last_baseball_update = time.time()

            if not self.baseball_cache:
                # No live games right now
                self.canvas.Fill(0, 0, 0)
                rgbmatrix.graphics.DrawText(self.canvas, self.font_large, 20, 32, self.RED, "No Live Games")
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

    def run(self):
        """Main display loop"""
        print("🚀 Display manager running")
        print(f"📈 Stock display time: {self.config['options']['stock_display_time']}s")
        print(f"⚾ Baseball display time: {self.config['options']['baseball_display_time']}s")
        
        try:
            while True:
                # Check for reload flag
                self.check_reload_flag()
                
                # Draw current screen
                if self.manual_mode and self.manual_screen:
                    if self.manual_screen == "weather":
                        self.draw_weather()
                    elif self.manual_screen == "stocks":
                        self.draw_stocks()
                    elif self.manual_screen == "baseball":
                        self.draw_baseball()
                    elif self.manual_screen == "standings":
                        self.draw_standings()
                else:
                    rotation_rate = self.config.get('options', {}).get('rotation_rate', 20)

                    if self.current_mode == "weather":
                        self.draw_weather()
                    elif self.current_mode == "stocks":
                        self.draw_stocks()
                    elif self.current_mode == "standings":
                        self.draw_standings()
                    else:
                        self.draw_baseball()

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
