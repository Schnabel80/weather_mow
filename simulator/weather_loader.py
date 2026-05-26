"""
Download 2 weeks of hourly weather data from Open-Meteo for Meine, DE
and provide 5-minute interpolated ticks.

Location: 38527 Meine, Hauptstr. 18a
Coordinates: lat=52.2548, lon=10.4731
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
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

    times = data["hourly"]["time"]
    rows = []
    for i, t in enumerate(times):
        # Open-Meteo returns local time strings — parse as Berlin time
        dt_local = datetime.fromisoformat(t).replace(tzinfo=berlin)
        dt_utc = dt_local.astimezone(timezone.utc)
        rows.append({
            "time_utc": dt_utc,
            "temperature_2m":        data["hourly"]["temperature_2m"][i] or 15.0,
            "relative_humidity_2m":  data["hourly"]["relative_humidity_2m"][i] or 70.0,
            "precipitation":         data["hourly"]["precipitation"][i] or 0.0,
            "wind_speed_10m":        data["hourly"]["wind_speed_10m"][i] or 0.0,
            "shortwave_radiation":   data["hourly"]["shortwave_radiation"][i] or 0.0,
        })
    return rows


def interpolate_to_5min(hourly: list[dict]) -> list[dict]:
    """
    Linear interpolation of hourly rows to 5-minute resolution.
    Each output dict adds:
      - rain_today_cumulative_mm: cumulative precipitation since midnight (Berlin time)
    """
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

            ticks.append({
                "time_utc": t_utc,
                "temperature_2m":        h0["temperature_2m"] + frac * (h1["temperature_2m"] - h0["temperature_2m"]),
                "relative_humidity_2m":  h0["relative_humidity_2m"] + frac * (h1["relative_humidity_2m"] - h0["relative_humidity_2m"]),
                "wind_speed_10m":        h0["wind_speed_10m"] + frac * (h1["wind_speed_10m"] - h0["wind_speed_10m"]),
                "shortwave_radiation":   max(0.0, h0["shortwave_radiation"] + frac * (h1["shortwave_radiation"] - h0["shortwave_radiation"])),
                "precipitation":         h0["precipitation"],
                "rain_today_cumulative_mm": round(rain_today_mm, 3),
            })
    return ticks


def load_ticks(past_days: int = 14, force: bool = False) -> list[dict]:
    """Main entry point. Returns list of 5-min tick dicts ready for simulation."""
    raw = fetch_weather(past_days=past_days, force=force)
    hourly = parse_hourly(raw)
    return interpolate_to_5min(hourly)
