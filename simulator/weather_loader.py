"""
Download 2 weeks of hourly weather data from Open-Meteo for Meine, DE
and provide 5-minute interpolated ticks.

Location: 38527 Meine, Hauptstr. 18a
Coordinates: lat=52.2548, lon=10.4731
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

LAT = 52.2548
LON = 10.4731
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_FILE = CACHE_DIR / "openmeteo.json"


def fetch_weather(past_days: int = 14, force: bool = False) -> dict:
    """
    Fetch hourly data from Open-Meteo. Returns raw API response dict.
    Caches to disk — set force=True to re-download.
    """
    if not force and CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&hourly=temperature_2m,relative_humidity_2m,"
        "precipitation,wind_speed_10m,shortwave_radiation"
        f"&past_days={past_days}"
        "&timezone=Europe%2FBerlin"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    CACHE_DIR.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)
    return data


def parse_hourly(data: dict) -> list[dict]:
    """
    Convert Open-Meteo response into a list of dicts, one per hour.
    Each dict has keys: time (datetime UTC), temperature_2m, relative_humidity_2m,
    precipitation, wind_speed_10m, shortwave_radiation.
    """
    import zoneinfo

    berlin = zoneinfo.ZoneInfo("Europe/Berlin")

    # Guard: check for required hourly structure
    hourly = data.get("hourly")
    if not hourly or "time" not in hourly:
        raise ValueError(f"Open-Meteo response missing 'hourly.time': {list(data.keys())}")

    times = hourly["time"]
    rows = []
    for i, t in enumerate(times):
        # Open-Meteo returns local time strings — parse as Berlin time
        dt_local = datetime.fromisoformat(t).replace(tzinfo=berlin)
        dt_utc = dt_local.astimezone(UTC)

        # Use explicit None checks instead of 'or' to preserve valid 0.0 values
        temp_val = hourly["temperature_2m"][i]
        temp = temp_val if temp_val is not None else 15.0

        humidity_val = hourly["relative_humidity_2m"][i]
        humidity = humidity_val if humidity_val is not None else 70.0

        precip_val = hourly["precipitation"][i]
        precip = precip_val if precip_val is not None else 0.0

        wind_val = hourly["wind_speed_10m"][i]
        wind = wind_val if wind_val is not None else 0.0

        radiation_val = hourly["shortwave_radiation"][i]
        radiation = radiation_val if radiation_val is not None else 0.0

        rows.append(
            {
                "time_utc": dt_utc,
                "temperature_2m": temp,
                "relative_humidity_2m": humidity,
                "precipitation": precip,
                "wind_speed_10m": wind,
                "shortwave_radiation": radiation,
            }
        )
    return rows


def interpolate_to_5min(hourly: list[dict]) -> list[dict]:
    """
    Linear interpolation of hourly rows to 5-minute resolution.
    Each output dict adds:
      - rain_today_cumulative_mm: cumulative precipitation since midnight (Berlin time)
    """
    # Guard: need at least 2 entries to interpolate
    if len(hourly) < 2:
        raise ValueError(f"Need at least 2 hourly entries to interpolate, got {len(hourly)}")

    import zoneinfo

    berlin = zoneinfo.ZoneInfo("Europe/Berlin")

    ticks = []
    rain_today_mm = 0.0
    current_date = None

    for i in range(len(hourly) - 1):
        h0 = hourly[i]
        h1 = hourly[i + 1]
        # 12 ticks per hour (0, 5, 10, ..., 55 minutes)
        for step in range(12):
            frac = step / 12.0
            t_utc = h0["time_utc"] + timedelta(minutes=step * 5)
            t_local = t_utc.astimezone(berlin)

            # Reset daily rain counter at midnight Berlin time
            if t_local.date() != current_date:
                current_date = t_local.date()
                rain_today_mm = 0.0

            # precipitation is mm/h — distribute evenly across 5-min slots
            slot_rain_mm = h0["precipitation"] * (5 / 60)
            rain_today_mm += slot_rain_mm

            def lerp(key: str, h0=h0, h1=h1, frac=frac) -> float:
                return h0[key] + frac * (h1[key] - h0[key])

            ticks.append(
                {
                    "time_utc": t_utc,
                    "temperature_2m": lerp("temperature_2m"),
                    "relative_humidity_2m": lerp("relative_humidity_2m"),
                    "wind_speed_10m": lerp("wind_speed_10m"),
                    "shortwave_radiation": max(0.0, lerp("shortwave_radiation")),
                    "precipitation": h0["precipitation"],
                    "rain_today_cumulative_mm": round(rain_today_mm, 3),
                }
            )
    return ticks


def load_ticks(past_days: int = 14, force: bool = False) -> list[dict]:
    """Main entry point. Returns list of 5-min tick dicts ready for simulation."""
    raw = fetch_weather(past_days=past_days, force=force)
    hourly = parse_hourly(raw)
    return interpolate_to_5min(hourly)
