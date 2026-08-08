#!/usr/bin/env python3
"""
Web Interface for MLB Scoreboard - With Manual Screen Selection
"""

from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify
import json
import os
import secrets
import subprocess
import signal
import time

from mlb_integration import TEAM_NAME_TO_CODE, mlb_fetcher

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

CONFIG_FILE = '/home/pi/mlb_scoreboard_pro/config.json'
MODE_FILE = '/tmp/mlb_display_mode.json'
RELOAD_FLAG = '/tmp/mlb_display_reload'

# code -> full name, sorted for the team-selection dropdown
TEAMS = sorted(
    ((code, name) for name, code in TEAM_NAME_TO_CODE.items()),
    key=lambda t: t[1]
)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>MLB Scoreboard Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            padding: 20px;
            color: #fff;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        h1 {
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            background: linear-gradient(45deg, #00ff87, #60efff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 0 20px rgba(0,255,135,0.3);
        }
        
        .card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 25px;
            margin-bottom: 25px;
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }
        
        h2 {
            color: #00ff87;
            margin-bottom: 20px;
            font-size: 1.5em;
            border-bottom: 2px solid #00ff87;
            padding-bottom: 10px;
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        label {
            display: block;
            margin-bottom: 5px;
            color: #60efff;
            font-weight: 500;
        }
        
        input, select {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 10px;
            background: rgba(255,255,255,0.1);
            color: white;
            border: 1px solid rgba(255,255,255,0.2);
            font-size: 16px;
            transition: all 0.3s;
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: #00ff87;
            background: rgba(255,255,255,0.15);
        }
        
        button {
            background: linear-gradient(45deg, #00ff87, #60efff);
            color: #1a1a2e;
            border: none;
            padding: 12px 25px;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            margin-right: 10px;
            margin-bottom: 10px;
            box-shadow: 0 4px 15px rgba(0,255,135,0.3);
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0,255,135,0.4);
        }
        
        .btn-danger {
            background: linear-gradient(45deg, #ff416c, #ff4b2b);
            color: white;
            box-shadow: 0 4px 15px rgba(255,65,108,0.3);
        }
        
        .btn-warning {
            background: linear-gradient(45deg, #f7971e, #ffd200);
            color: #1a1a2e;
        }
        
        .btn-success {
            background: linear-gradient(45deg, #00b09b, #96c93d);
            color: white;
        }
        
        .screen-selector {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .screen-btn {
            background: rgba(255,255,255,0.1);
            border: 2px solid rgba(255,255,255,0.2);
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .screen-btn:hover {
            transform: translateY(-5px);
            border-color: #00ff87;
        }
        
        .screen-btn.active {
            border-color: #00ff87;
            background: rgba(0,255,135,0.1);
            box-shadow: 0 0 20px rgba(0,255,135,0.3);
        }
        
        .screen-btn .emoji {
            font-size: 48px;
            margin-bottom: 10px;
        }
        
        .screen-btn .name {
            font-size: 18px;
            font-weight: 600;
        }
        
        .status-card {
            background: rgba(0,0,0,0.3);
            border-radius: 15px;
            padding: 20px;
        }
        
        .status-item {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .status-label {
            color: #60efff;
        }
        
        .status-value {
            font-weight: 600;
        }
        
        .status-value.running {
            color: #00ff87;
        }
        
        .status-value.stopped {
            color: #ff416c;
        }
        
        .badge {
            display: inline-block;
            padding: 5px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 10px;
        }
        
        .badge-success {
            background: #00ff87;
            color: #1a1a2e;
        }
        
        .badge-warning {
            background: #f7971e;
            color: #1a1a2e;
        }
        
        .alert {
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
            animation: slideIn 0.3s ease-out;
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(-10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .alert-success {
            background: rgba(0,255,135,0.2);
            border: 1px solid #00ff87;
            color: #00ff87;
        }
        
        .alert-error {
            background: rgba(255,65,108,0.2);
            border: 1px solid #ff416c;
            color: #ff416c;
        }
        
        .stock-item {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
        }
        
        .stock-item input {
            flex: 1;
        }
        
        .stock-item button {
            background: #ff416c;
            color: white;
            padding: 12px 20px;
            margin: 0;
        }
        
        .mode-indicator {
            display: inline-block;
            padding: 8px 15px;
            border-radius: 25px;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 15px;
        }
        
        .mode-auto {
            background: rgba(0,255,135,0.2);
            color: #00ff87;
            border: 1px solid #00ff87;
        }
        
        .mode-manual {
            background: rgba(255,193,7,0.2);
            color: #ffc107;
            border: 1px solid #ffc107;
        }
        
        .action-bar {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚾ MLB Scoreboard Pro Control Panel ⚾</h1>

        <div style="text-align:center; margin-bottom: 20px;">
            <a href="/games" style="display:inline-block; background: linear-gradient(45deg, #00ff87, #60efff); color: #1a1a2e; padding: 12px 25px; border-radius: 10px; font-size: 16px; font-weight: 600; text-decoration: none; box-shadow: 0 4px 15px rgba(0,255,135,0.3);">📅 View All Games</a>
        </div>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <!-- Manual Screen Selection -->
        <div class="card">
            <h2>🎯 Manual Screen Override</h2>
            <div class="mode-indicator {{ 'mode-auto' if mode == 'auto' else 'mode-manual' }}">
                Current Mode: {{ '🔄 Auto Rotation' if mode == 'auto' else '📺 Manual - ' + current_screen.title() }}
            </div>
            
            <div class="screen-selector">
                <div class="screen-btn {{ 'active' if current_screen == 'weather' and mode == 'manual' }}" onclick="selectScreen('weather')">
                    <div class="emoji">🌤️</div>
                    <div class="name">Weather</div>
                </div>
                <div class="screen-btn {{ 'active' if current_screen == 'stocks' and mode == 'manual' }}" onclick="selectScreen('stocks')">
                    <div class="emoji">📈</div>
                    <div class="name">Stocks</div>
                </div>
                <div class="screen-btn {{ 'active' if current_screen == 'baseball' and mode == 'manual' }}" onclick="selectScreen('baseball')">
                    <div class="emoji">⚾</div>
                    <div class="name">Baseball</div>
                </div>
                <div class="screen-btn {{ 'active' if current_screen == 'standings' and mode == 'manual' }}" onclick="selectScreen('standings')">
                    <div class="emoji">📊</div>
                    <div class="name">Standings</div>
                </div>
                <div class="screen-btn {{ 'active' if current_screen == 'flights' and mode == 'manual' }}" onclick="selectScreen('flights')">
                    <div class="emoji">✈️</div>
                    <div class="name">Flights</div>
                </div>
            </div>
            
            <div class="action-bar">
                <form action="/set_manual" method="post" style="display: inline;" id="manualForm">
                    <input type="hidden" name="screen" id="selected_screen" value="">
                    <button type="submit" class="btn-warning">📺 Show Selected Screen Only</button>
                </form>
                
                <form action="/set_auto" method="post" style="display: inline;">
                    <button type="submit" class="btn-success">🔄 Resume Auto Rotation</button>
                </form>
                
                <form action="/reload" method="post" style="display: inline;">
                    <button type="submit" class="btn-danger">🔄 Reload Display</button>
                </form>
            </div>
        </div>
        
        <!-- Settings Grid -->
        <div class="grid">
            <!-- Weather Settings -->
            <div class="card">
                <h2>🌤️ Weather Settings</h2>
                <form action="/update_weather" method="post">
                    <div class="form-group">
                        <label>OpenWeatherMap API Key:</label>
                        <input type="text" name="apikey" value="{{ config.weather.apikey }}" placeholder="Enter your API key">
                    </div>
                    <div class="form-group">
                        <label>Location (City,us):</label>
                        <input type="text" name="location" value="{{ config.weather.location }}" required>
                    </div>
                    <div class="form-group">
                        <label>Temperature (manual fallback):</label>
                        <input type="text" name="temp" value="{{ config.weather.temp }}" placeholder="72">
                    </div>
                    <div class="form-group">
                        <label>Humidity (manual fallback):</label>
                        <input type="text" name="humidity" value="{{ config.weather.humidity }}" placeholder="45">
                    </div>
                    <div class="form-group">
                        <label>Units:</label>
                        <select name="metric_units">
                            <option value="true" {% if config.weather.metric_units %}selected{% endif %}>Metric (°C)</option>
                            <option value="false" {% if not config.weather.metric_units %}selected{% endif %}>Imperial (°F)</option>
                        </select>
                    </div>
                    <button type="submit">Update Weather</button>
                </form>
            </div>
            
            <!-- Stock Settings -->
            <div class="card">
                <h2>📈 Stock Settings</h2>
                <form action="/update_stocks" method="post">
                    <div id="stocks">
                        {% for symbol in config.tickers.stocks %}
                        <div class="stock-item">
                            <input type="text" name="stocks[]" value="{{ symbol }}" placeholder="Symbol">
                            <button type="button" onclick="this.parentElement.remove()">✖</button>
                        </div>
                        {% endfor %}
                    </div>
                    <button type="button" onclick="addStock()" style="background: #00b09b; margin-bottom: 10px;">+ Add Stock</button>
                    
                    <div class="form-group">
                        <label>Time per Stock (seconds):</label>
                        <input type="number" name="stock_display_time" value="{{ config.options.stock_display_time }}" min="2" max="15">
                    </div>

                    <button type="submit">Update Stocks</button>
                </form>
            </div>
            
            <!-- Baseball Settings -->
            <div class="card">
                <h2>⚾ Baseball Settings</h2>
                <form action="/update_baseball" method="post">
                    <div class="form-group">
                        <label>Preferred Team (also drives the Standings screen):</label>
                        <select name="preferred_team">
                            {% for code, name in teams %}
                            <option value="{{ code }}" {% if config.options.get('preferred_team', 'SF') == code %}selected{% endif %}>{{ name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Time per Game (seconds):</label>
                        <input type="number" name="baseball_display_time" value="{{ config.options.baseball_display_time }}" min="3" max="20">
                    </div>
                    <button type="submit">Update Baseball</button>
                </form>
            </div>
            
            <!-- Display Settings -->
            <div class="card">
                <h2>⚙️ Display Settings</h2>
                <form action="/update_display" method="post">
                    <div class="form-group">
                        <label>Auto Rotation Interval (seconds):</label>
                        <input type="number" name="rotation_rate" value="{{ config.options.rotation_rate }}" min="5" max="60">
                    </div>
                    
                    <div class="form-group">
                        <label>Brightness (0-100):</label>
                        <input type="number" name="brightness" value="{{ config.display.brightness }}" min="0" max="100">
                    </div>
                    
                    <button type="submit">Update Display</button>
                </form>
            </div>

            <!-- Flight Tracker Settings -->
            <div class="card">
                <h2>✈️ Flight Tracker Settings</h2>
                <form action="/update_flight" method="post">
                    <div class="form-group">
                        <label>Home Latitude:</label>
                        <input type="text" name="home_lat" value="{{ config.flight.home_lat }}" required>
                    </div>
                    <div class="form-group">
                        <label>Home Longitude:</label>
                        <input type="text" name="home_lon" value="{{ config.flight.home_lon }}" required>
                    </div>
                    <div class="form-group">
                        <label>Search Radius (km):</label>
                        <input type="number" name="radius_km" value="{{ config.flight.radius_km }}" min="5" max="150">
                    </div>
                    <div class="form-group">
                        <label>Min Altitude (ft):</label>
                        <input type="number" name="min_altitude_ft" value="{{ config.flight.min_altitude_ft }}" min="0" max="50000">
                    </div>
                    <div class="form-group">
                        <label>Max Altitude (ft):</label>
                        <input type="number" name="max_altitude_ft" value="{{ config.flight.max_altitude_ft }}" min="0" max="50000">
                    </div>
                    <div class="form-group">
                        <label>Time per Aircraft (seconds):</label>
                        <input type="number" name="flight_display_time" value="{{ config.options.flight_display_time }}" min="3" max="20">
                    </div>
                    <button type="submit">Update Flight Tracker</button>
                </form>
            </div>
        </div>

        <!-- System Status -->
        <div class="card">
            <h2>📊 System Status</h2>
            <div class="status-card">
                <div class="status-item">
                    <span class="status-label">Display Service:</span>
                    <span class="status-value {{ 'running' if service_status else 'stopped' }}">
                        {{ '🟢 Running' if service_status else '🔴 Stopped' }}
                    </span>
                </div>
                
                <div class="status-item">
                    <span class="status-label">Display Mode:</span>
                    <span class="status-value">
                        {{ '🔄 Auto Rotation' if mode == 'auto' else '📺 Manual - ' + current_screen.title() }}
                    </span>
                </div>
                
                <div class="status-item">
                    <span class="status-label">Weather API:</span>
                    <span class="status-value">{{ '✅ Configured' if config.weather.apikey else '❌ Not configured' }}</span>
                </div>
                
                <div class="status-item">
                    <span class="status-label">Location:</span>
                    <span class="status-value">{{ config.weather.location }}</span>
                </div>
                
                <div class="status-item">
                    <span class="status-label">Stocks Tracked:</span>
                    <span class="status-value">{{ config.tickers.stocks|length }}</span>
                </div>

                <div class="status-item">
                    <span class="status-label">Preferred Team:</span>
                    <span class="status-value">{{ config.options.get('preferred_team', 'SF') }}</span>
                </div>

                <div class="action-bar">
                    <form action="/restart" method="post" style="display: inline;">
                        <button type="submit" class="btn-danger">🔄 Restart Display</button>
                    </form>
                    
                    <form action="/stop" method="post" style="display: inline;">
                        <button type="submit" class="btn-danger">⏹️ Stop Display</button>
                    </form>
                    
                    <form action="/start" method="post" style="display: inline;">
                        <button type="submit" class="btn-success">▶️ Start Display</button>
                    </form>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let selectedScreen = 'weather';
        
        function selectScreen(screen) {
            selectedScreen = screen;
            document.querySelectorAll('.screen-btn').forEach(btn => btn.classList.remove('active'));
            event.currentTarget.classList.add('active');
        }
        
        document.querySelectorAll('.screen-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.screen-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                
                const name = this.querySelector('.name').textContent.toLowerCase();
                if (name.includes('weather')) selectedScreen = 'weather';
                else if (name.includes('stock')) selectedScreen = 'stocks';
                else if (name.includes('baseball')) selectedScreen = 'baseball';
                else if (name.includes('standings')) selectedScreen = 'standings';
                else if (name.includes('flights')) selectedScreen = 'flights';
                
                document.getElementById('selected_screen').value = selectedScreen;
            });
        });
        
        function addStock() {
            const container = document.getElementById('stocks');
            const div = document.createElement('div');
            div.className = 'stock-item';
            div.innerHTML = `
                <input type="text" name="stocks[]" placeholder="Symbol">
                <button type="button" onclick="this.parentElement.remove()">✖</button>
            `;
            container.appendChild(div);
        }
    </script>
</body>
</html>
'''

GAMES_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>MLB Games</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            padding: 20px;
            color: #fff;
        }

        .container { max-width: 900px; margin: 0 auto; }

        h1 {
            text-align: center;
            margin-bottom: 10px;
            font-size: 2.2em;
            background: linear-gradient(45deg, #00ff87, #60efff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .top-links { text-align: center; margin-bottom: 25px; }

        .top-links a, .top-links button {
            display: inline-block;
            background: linear-gradient(45deg, #00ff87, #60efff);
            color: #1a1a2e;
            padding: 10px 20px;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 600;
            text-decoration: none;
            border: none;
            cursor: pointer;
            margin: 0 5px;
        }

        .top-links .btn-success { background: linear-gradient(45deg, #00b09b, #96c93d); color: white; }

        .alert {
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .alert-success { background: rgba(0,255,135,0.2); border: 1px solid #00ff87; color: #00ff87; }
        .alert-error { background: rgba(255,65,108,0.2); border: 1px solid #ff416c; color: #ff416c; }

        .game-card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 18px 20px;
            margin-bottom: 15px;
            border: 1px solid rgba(255,255,255,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 15px;
            flex-wrap: wrap;
        }

        .game-card.selected { border-color: #00ff87; box-shadow: 0 0 15px rgba(0,255,135,0.3); }

        .game-info { flex: 1; min-width: 200px; }

        .matchup { font-size: 1.2em; font-weight: 600; margin-bottom: 4px; }

        .game-meta { color: #60efff; font-size: 0.9em; }

        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            margin-right: 8px;
            text-transform: uppercase;
        }
        .badge-live { background: #ff416c; color: white; }
        .badge-upcoming { background: #f7971e; color: #1a1a2e; }
        .badge-final { background: #60efff; color: #1a1a2e; }
        .badge-other { background: #666; color: white; }

        .game-actions button {
            background: linear-gradient(45deg, #00ff87, #60efff);
            color: #1a1a2e;
            border: none;
            padding: 10px 18px;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }

        .game-actions button.active {
            background: linear-gradient(45deg, #00b09b, #96c93d);
        }

        .empty-state {
            text-align: center;
            padding: 40px;
            color: #60efff;
            font-size: 1.1em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📅 Today's MLB Games</h1>
        <div class="top-links">
            <a href="/">⚙️ Control Panel</a>
            <form action="/set_auto" method="post" style="display:inline;">
                <button type="submit" class="btn-success">🔄 Resume Auto Rotation</button>
            </form>
        </div>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {% if not games %}
            <div class="empty-state">No games scheduled today.</div>
        {% endif %}

        {% for game in games %}
        <div class="game-card {{ 'selected' if selected_game_id == game.game_id|string }}">
            <div class="game-info">
                <div>
                    {% if game.status == 'live' %}
                        <span class="badge badge-live">Live</span>
                    {% elif game.status == 'pregame' %}
                        <span class="badge badge-upcoming">Upcoming</span>
                    {% elif game.status == 'final' %}
                        <span class="badge badge-final">Final</span>
                    {% else %}
                        <span class="badge badge-other">{{ game.status }}</span>
                    {% endif %}
                </div>
                <div class="matchup">{{ game.away.code }} @ {{ game.home.code }}</div>
                <div class="game-meta">
                    {% if game.status == 'live' %}
                        {{ game.away.runs }} - {{ game.home.runs }} &middot; {{ game.inning.state }} {{ game.inning.number }}
                    {% elif game.status == 'final' %}
                        Final: {{ game.away.runs }} - {{ game.home.runs }}
                    {% elif game.status == 'pregame' %}
                        First pitch {{ game.start_time_local or 'TBD' }}
                    {% endif %}
                </div>
            </div>
            <div class="game-actions">
                <form action="/select_game" method="post">
                    <input type="hidden" name="game_id" value="{{ game.game_id }}">
                    <button type="submit" class="{{ 'active' if selected_game_id == game.game_id|string }}">
                        {{ '▶ Showing Now' if selected_game_id == game.game_id|string else 'Show on Matrix' }}
                    </button>
                </form>
            </div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
'''

def trigger_reload():
    """Trigger the display manager to reload configuration"""
    # Create reload flag
    with open(RELOAD_FLAG, 'w') as f:
        f.write('reload')
    
    # Find display manager PID and send signal
    try:
        result = subprocess.run(['pgrep', '-f', 'display_manager.py'], 
                               capture_output=True, text=True)
        if result.stdout.strip():
            pid = int(result.stdout.strip())
            os.kill(pid, signal.SIGUSR1)
            return True
    except:
        pass
    return False

def get_display_mode():
    """Get current display mode (auto or manual with specific screen)"""
    try:
        if os.path.exists(MODE_FILE):
            with open(MODE_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {'mode': 'auto', 'screen': None}

def set_display_mode(mode, screen=None, game_id=None):
    """Set display mode"""
    with open(MODE_FILE, 'w') as f:
        json.dump({'mode': mode, 'screen': screen, 'game_id': game_id}, f)

    # Trigger reload
    trigger_reload()

def get_service_status():
    try:
        result = subprocess.run(['systemctl', 'is-active', 'mlb-weather.service'], 
                               capture_output=True, text=True)
        return result.stdout.strip() == 'active'
    except:
        return False

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            "weather": {
                "apikey": "",
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
                "flight_display_time": 8,
                "preferred_team": "SF",
                "currency": "USD",
                "date_format": "MM/DD/YYYY",
                "show_logos": True,
                "chart_period": "1d"
            },
            "tickers": {
                "stocks": ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "UPS"]
            },
            "flight": {
                "home_lat": 41.8781,
                "home_lon": -87.6298,
                "radius_km": 30,
                "min_altitude_ft": 500,
                "max_altitude_ft": 45000
            }
        }

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

@app.route('/')
def index():
    config = load_config()
    mode_data = get_display_mode()
    return render_template_string(
        HTML_TEMPLATE,
        config=config,
        service_status=get_service_status(),
        mode=mode_data['mode'],
        current_screen=mode_data.get('screen', 'weather'),
        teams=TEAMS
    )

@app.route('/set_manual', methods=['POST'])
def set_manual():
    screen = request.form['screen']
    set_display_mode('manual', screen)
    flash(f'✅ Manual mode activated - showing {screen.title()} screen only', 'success')
    return redirect(url_for('index'))

@app.route('/set_auto', methods=['POST'])
def set_auto():
    set_display_mode('auto')
    flash('✅ Auto rotation resumed', 'success')
    return redirect(url_for('index'))

@app.route('/reload', methods=['POST'])
def reload_display():
    if trigger_reload():
        flash('✅ Display reloaded', 'success')
    else:
        flash('⚠️ Could not reload display', 'error')
    return redirect(url_for('index'))

@app.route('/update_weather', methods=['POST'])
def update_weather():
    config = load_config()
    
    config['weather']['apikey'] = request.form['apikey']
    config['weather']['location'] = request.form['location']
    config['weather']['temp'] = request.form['temp']
    config['weather']['humidity'] = request.form['humidity']
    config['weather']['metric_units'] = request.form['metric_units'] == 'true'
    
    save_config(config)
    trigger_reload()
    flash('Weather settings updated!', 'success')
    return redirect(url_for('index'))

@app.route('/update_stocks', methods=['POST'])
def update_stocks():
    config = load_config()
    
    stocks = request.form.getlist('stocks[]')
    config['tickers']['stocks'] = [s.upper().strip() for s in stocks if s.strip()]
    config['options']['stock_display_time'] = int(request.form['stock_display_time'])

    save_config(config)
    trigger_reload()
    flash('Stock settings updated!', 'success')
    return redirect(url_for('index'))

@app.route('/update_baseball', methods=['POST'])
def update_baseball():
    config = load_config()

    config['options']['baseball_display_time'] = int(request.form['baseball_display_time'])
    config['options']['preferred_team'] = request.form['preferred_team']

    save_config(config)
    trigger_reload()
    flash('Baseball settings updated!', 'success')
    return redirect(url_for('index'))

@app.route('/update_display', methods=['POST'])
def update_display():
    config = load_config()
    
    if 'display' not in config:
        config['display'] = {}
    
    config['options']['rotation_rate'] = int(request.form['rotation_rate'])
    config['display']['brightness'] = int(request.form['brightness'])
    
    save_config(config)
    trigger_reload()
    flash('Display settings updated!', 'success')
    return redirect(url_for('index'))

@app.route('/update_flight', methods=['POST'])
def update_flight():
    config = load_config()

    if 'flight' not in config:
        config['flight'] = {}

    config['flight']['home_lat'] = float(request.form['home_lat'])
    config['flight']['home_lon'] = float(request.form['home_lon'])
    config['flight']['radius_km'] = int(request.form['radius_km'])
    config['flight']['min_altitude_ft'] = int(request.form['min_altitude_ft'])
    config['flight']['max_altitude_ft'] = int(request.form['max_altitude_ft'])
    config['options']['flight_display_time'] = int(request.form['flight_display_time'])

    save_config(config)
    trigger_reload()
    flash('Flight tracker settings updated!', 'success')
    return redirect(url_for('index'))

@app.route('/restart', methods=['POST'])
def restart():
    subprocess.run(['sudo', 'systemctl', 'restart', 'mlb-weather.service'])
    flash('Display restarted!', 'success')
    return redirect(url_for('index'))

@app.route('/stop', methods=['POST'])
def stop():
    subprocess.run(['sudo', 'systemctl', 'stop', 'mlb-weather.service'])
    flash('Display stopped!', 'success')
    return redirect(url_for('index'))

@app.route('/start', methods=['POST'])
def start():
    subprocess.run(['sudo', 'systemctl', 'start', 'mlb-weather.service'])
    flash('Display started!', 'success')
    return redirect(url_for('index'))

@app.route('/games')
def games_page():
    games = mlb_fetcher.get_today_games()

    status_order = {'live': 0, 'pregame': 1, 'final': 2}
    games.sort(key=lambda g: (status_order.get(g['status'], 3), g.get('start_time', '')))

    mode_data = get_display_mode()
    selected_game_id = str(mode_data.get('game_id')) if mode_data.get('mode') == 'manual' and mode_data.get('game_id') else None

    return render_template_string(
        GAMES_TEMPLATE,
        games=games,
        selected_game_id=selected_game_id
    )

@app.route('/select_game', methods=['POST'])
def select_game():
    game_id = request.form['game_id']
    set_display_mode('manual', 'baseball', game_id=game_id)
    flash('✅ Showing selected game on the display', 'success')
    return redirect(url_for('games_page'))

@app.route('/api/mode', methods=['GET'])
def api_mode():
    """API endpoint to get current mode"""
    return jsonify(get_display_mode())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
