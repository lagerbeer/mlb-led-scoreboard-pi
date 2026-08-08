#!/usr/bin/env python3
"""
Flight Tracker Integration - nearby aircraft via the unofficial FlightRadar24 API
"""

import json
import math

CONFIG_FILE = '/home/pi/mlb_scoreboard_pro/config.json'

DEFAULT_RADIUS_KM = 30
DEFAULT_MIN_ALTITUDE_FT = 500
DEFAULT_MAX_ALTITUDE_FT = 45000


def _load_flight_config():
    """Reads the flight section fresh from config.json on every call, same
    reload-free pattern as mlb_integration's preferred-team lookup."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
        return cfg.get('flight', {})
    except Exception:
        return {}


def _distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km (haversine)."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class FlightFetcher:
    def get_nearby_flights(self):
        """Aircraft within the configured radius/altitude band around home,
        sorted by distance. Hits the API fresh on every call - like
        mlb_integration's get_today_games(), caching is the caller's job.
        The unofficial FR24 API rate-limits (returns empty results) if
        called too frequently, so callers should cache for at least ~60s."""
        cfg = _load_flight_config()
        lat = cfg.get('home_lat')
        lon = cfg.get('home_lon')
        if lat is None or lon is None:
            print("⚠️ Flight tracker: no home_lat/home_lon configured")
            return []

        radius_km = cfg.get('radius_km', DEFAULT_RADIUS_KM)
        min_alt = cfg.get('min_altitude_ft', DEFAULT_MIN_ALTITUDE_FT)
        max_alt = cfg.get('max_altitude_ft', DEFAULT_MAX_ALTITUDE_FT)

        try:
            # Lazy import - pulls in curl_cffi/brotli, only needed when this
            # screen is actually in use.
            from FlightRadar24.api import FlightRadar24API

            api = FlightRadar24API()
            bounds = api.get_bounds_by_point(lat, lon, radius_km * 1000)
            flights = api.get_flights(bounds=bounds)
        except Exception as e:
            print(f"⚠️ Flight fetch error: {e}")
            return []

        results = []
        for f in flights:
            try:
                altitude = f.altitude
                if not isinstance(altitude, (int, float)):
                    continue
                if not (min_alt <= altitude <= max_alt):
                    continue
                if not isinstance(f.latitude, (int, float)) or not isinstance(f.longitude, (int, float)):
                    continue

                callsign = (f.callsign or f.registration or '').strip()
                if not callsign:
                    continue

                results.append({
                    'callsign': callsign,
                    'altitude_ft': int(altitude),
                    'ground_speed_kt': int(f.ground_speed) if isinstance(f.ground_speed, (int, float)) else 0,
                    'heading': int(f.heading) if isinstance(f.heading, (int, float)) else 0,
                    'origin': (f.origin_airport_iata or '').strip(),
                    'destination': (f.destination_airport_iata or '').strip(),
                    'distance_km': round(_distance_km(lat, lon, f.latitude, f.longitude), 1)
                })
            except Exception:
                continue

        results.sort(key=lambda r: r['distance_km'])
        return results


# Global instance
flight_fetcher = FlightFetcher()
