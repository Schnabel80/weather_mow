"""Diagnostics support for weather_mow."""
from __future__ import annotations

import os
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import WeatherMowCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: WeatherMowCoordinator = hass.data[DOMAIN][entry.entry_id]

    data = coordinator.data or {}

    # Serialize datetime values
    def _serialize(val: Any) -> Any:
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return val

    serialized_data = {k: _serialize(v) for k, v in data.items()}

    # Internal state snapshot
    rain_buffer = list(coordinator._rain_buffer)
    internal = {
        "rain_buffer_len": len(rain_buffer),
        "rain_buffer_sum": round(sum(rain_buffer), 3),
        "rain_buffer_tail_10": [round(v, 3) for v in rain_buffer[-10:]],
        "solar_peak_wm2": round(coordinator._radiation_peak, 1),
        "sunshine_start_utc": (
            coordinator._sunshine_start_utc.isoformat()
            if coordinator._sunshine_start_utc else None
        ),
        "duration_today_s": round(coordinator._duration_today_s, 1),
        "duration_yesterday_s": round(coordinator._duration_yesterday_s, 1),
        "duration_day_before_s": round(coordinator._duration_day_before_s, 1),
        "mow_start_ts": coordinator._mow_start_ts,
        "last_mow_allowed": coordinator._last_mow_allowed,
        "auto_resume_blocked": coordinator._auto_resume_blocked,
        "irrigation_wetness_boost": round(coordinator._irrigation_wetness_boost, 1),
        "growth_gdd_accum": round(coordinator._growth_gdd_accum, 2),
        "mow_since_last_gdd_reset_s": round(coordinator._mow_since_last_gdd_reset_s, 1),
        "mow_first_allowed_ts": coordinator._mow_first_allowed_ts,
        "start_delay_min": entry.options.get("start_delay_minutes", 0),
        "hourly_precip_entries": len(coordinator._dwd_hourly_precip),
        "hourly_radiation_entries": len(coordinator._dwd_hourly_radiation),
        "debug_log_active": (
            coordinator.debug_switch_entity.is_on
            if coordinator.debug_switch_entity is not None else False
        ),
    }

    # Config
    cfg = dict(entry.data)

    # Debug-CSV — Inhalt einlesen wenn vorhanden
    csv_path = hass.config.path("weather_mow_debug.csv")
    debug_csv: str | None = None
    if os.path.isfile(csv_path):
        try:
            with open(csv_path, encoding="utf-8") as f:
                debug_csv = f.read()
        except OSError:
            debug_csv = "Fehler beim Lesen der CSV-Datei."

    return {
        "entry": {
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
        },
        "config": cfg,
        "data": serialized_data,
        "internal": internal,
        "debug_csv": debug_csv,
    }
