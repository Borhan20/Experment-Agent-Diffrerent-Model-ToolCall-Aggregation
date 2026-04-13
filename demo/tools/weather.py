"""Demo weather tool handlers — mock data, no external API required."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Dict, List


def _location_hash(location: str) -> int:
    """Deterministic integer hash for a location string."""
    digest = hashlib.md5(location.lower().strip().encode()).hexdigest()
    return int(digest[:8], 16)


_CONDITIONS = [
    "Sunny", "Partly Cloudy", "Overcast", "Light Rain",
    "Heavy Rain", "Thunderstorm", "Foggy", "Hot and Humid",
    "Clear", "Windy",
]

_FORECAST_CONDITIONS = [
    "Sunny", "Partly Cloudy", "Chance of Rain",
    "Thunderstorm", "Clear Skies", "Overcast",
]


async def get_current_weather(location: str) -> Dict[str, Any]:
    """Return mock current weather for a location.

    Args:
        location: City name (e.g., "Dhaka"). Use "FAIL" to trigger error.

    Returns:
        Weather dict with temperature_c, condition, humidity_pct, wind_kph.

    Raises:
        RuntimeError: If location is "FAIL" (for testing NFR-5).
    """
    if location.upper() == "FAIL":
        raise RuntimeError("Simulated weather API failure")

    await asyncio.sleep(0.5)  # Simulate API latency

    h = _location_hash(location)
    temperature_c = round(15.0 + (h % 30), 1)  # 15–44 °C
    condition = _CONDITIONS[h % len(_CONDITIONS)]
    humidity_pct = 40 + (h % 55)               # 40–94 %
    wind_kph = round(5.0 + (h % 40) * 0.5, 1)  # 5–24.5 kph

    return {
        "location": location,
        "temperature_c": temperature_c,
        "condition": condition,
        "humidity_pct": humidity_pct,
        "wind_kph": wind_kph,
    }


async def get_weather_forecast(location: str, days: int = 3) -> Dict[str, Any]:
    """Return a mock multi-day weather forecast.

    Args:
        location: City name (provided via dependency from get_current_weather).
        days: Number of forecast days (default 3).

    Returns:
        Dict with location and list of daily forecasts.
    """
    await asyncio.sleep(0.3)  # Simulate API latency

    h = _location_hash(location)
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    forecasts: List[Dict[str, Any]] = []

    for i in range(days):
        day_h = (h + i * 17) & 0xFFFFFFFF
        high_c = round(18.0 + (day_h % 25), 1)
        low_c = round(high_c - 5.0 - (day_h % 8), 1)
        condition = _FORECAST_CONDITIONS[day_h % len(_FORECAST_CONDITIONS)]
        forecasts.append({
            "day": day_names[(day_h) % 7],
            "high_c": high_c,
            "low_c": low_c,
            "condition": condition,
        })

    return {
        "location": location,
        "forecasts": forecasts,
    }
