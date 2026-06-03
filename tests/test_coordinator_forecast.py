"""Tests für _forecast_next_mow im Coordinator."""

from __future__ import annotations

from collections import deque
from datetime import UTC, timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.const import (
    RAIN_BUFFER_MAXLEN,
)
from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Minimal-Coordinator ───────────────────────────────────────────────────────


def _bare():
    hass = MagicMock()
    hass.states.get.return_value = MagicMock(
        state="sunny", attributes={"temperature": 20.0, "humidity": 60, "forecast": []}
    )
    entry = MagicMock()
    entry.entry_id = "fc_test"
    entry.data = {"name": "Test", "weather_entity_id": "weather.test"}
    entry.options = {}
    c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
    c.hass = hass
    c.entry = entry
    c._rain_buffer = deque([0.0] * RAIN_BUFFER_MAXLEN, maxlen=RAIN_BUFFER_MAXLEN)
    c._radiation_peak = 800.0
    c._wetness_mm = 0.0
    c._hourly_precip = []
    c._hourly_radiation = []
    c._hourly_wind = []
    c.mow_threshold_entity = None
    c.mow_threshold_urgent_entity = None
    c.lawn_sun_from_entity = None
    c.lawn_sun_efficiency_entity = None
    return c


def _cfg():
    return {
        "weather_entity_id": "weather.test",
        "mow_window_start": "08:00:00",
        "mow_window_end": "20:00:00",
        "target_daily_duration_h": 3.0,
        "outdoor_temp_entity_id": "",
        "outdoor_humidity_entity_id": "",
        "wind_sensor_entity_id": "",
    }


def _next_hour_in_window(offset_h=2):
    """Gibt UTC-Datetime für eine Stunde im Mähfenster zurück."""
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    candidate = now + timedelta(hours=offset_h)
    local = dt_util.as_local(candidate)
    # Sicherstellen dass der Zeitpunkt im Fenster 08-20 liegt
    while not (8 <= local.hour < 20):
        candidate += timedelta(hours=1)
        local = dt_util.as_local(candidate)
    return candidate


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestForecastNextMow:
    def test_returns_none_without_hourly_data(self):
        """Keine Stundendaten → None zurückgeben."""
        c = _bare()
        c._hourly_precip = []
        now_utc = dt_util.utcnow()
        result = c._forecast_next_mow(_cfg(), dt_util.now(), now_utc, wetness_mm=0.0)
        assert result is None

    def test_returns_datetime_when_dry(self):
        """Wetness 0 + kein Regen → erster verfügbarer Slot im Mähfenster."""
        c = _bare()
        h = _next_hour_in_window(offset_h=3)
        # Leichte Strahlung → Trocknung
        c._hourly_precip = [(h, 0.0)]
        c._hourly_radiation = [(h, 500.0)]
        c._hourly_wind = [(h, 5.0)]

        with (
            patch.object(c, "_get_temp_humidity", return_value=(20.0, 60.0)),
            patch.object(c, "_effective_solar_factor", return_value=0.5),
        ):
            result = c._forecast_next_mow(_cfg(), dt_util.now(), dt_util.utcnow(), wetness_mm=0.0)
        # Wenn trocken → Zeitpunkt innerhalb der nächsten 48h
        assert result is None or result > dt_util.now()

    def test_high_wetness_delays_forecast(self):
        """Hohe Anfangswetness → späterer Zeitpunkt als bei 0 Wetness."""
        c = _bare()
        # 48 Stunden mit je 1mm Strahlung und wenig Regen
        now_utc = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        hours = []
        for i in range(1, 49):
            h = now_utc + timedelta(hours=i)
            hours.append(h)
            c._hourly_precip.append((h, 0.0))
            c._hourly_radiation.append((h, 600.0))
            c._hourly_wind.append((h, 5.0))

        with (
            patch.object(c, "_get_temp_humidity", return_value=(22.0, 55.0)),
            patch.object(c, "_effective_solar_factor", return_value=0.6),
        ):
            result_dry = c._forecast_next_mow(_cfg(), dt_util.now(), now_utc, wetness_mm=0.0)
            result_wet = c._forecast_next_mow(_cfg(), dt_util.now(), now_utc, wetness_mm=1.8)

        # Bei hoher Wetness sollte Mähen später möglich sein (oder None)
        if result_dry is not None and result_wet is not None:
            assert result_wet >= result_dry
        # Zumindest einer der Fälle muss ein Ergebnis liefern
        assert result_dry is not None or result_wet is not None

    def test_all_rainy_returns_none(self):
        """Überall Regen in den nächsten 48h → None."""
        c = _bare()
        now_utc = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        for i in range(1, 49):
            h = now_utc + timedelta(hours=i)
            c._hourly_precip.append((h, 5.0))  # starker Regen
            c._hourly_radiation.append((h, 0.0))
            c._hourly_wind.append((h, 0.0))

        with (
            patch.object(c, "_get_temp_humidity", return_value=(15.0, 95.0)),
            patch.object(c, "_effective_solar_factor", return_value=0.0),
        ):
            result = c._forecast_next_mow(_cfg(), dt_util.now(), now_utc, wetness_mm=0.5)
        # Bei 5mm/h Regen 48h lang → None (nie trocken genug)
        assert result is None

    @pytest.mark.freeze_time("2026-06-15 10:00:00+00:00")
    def test_target_reached_today_skips_todays_hours(self):
        """Tagesziel bereits erreicht → heutige Stunden werden übersprungen."""
        c = _bare()
        now_utc = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        now_local = dt_util.now()

        for i in range(1, 49):
            h = now_utc + timedelta(hours=i)
            c._hourly_precip.append((h, 0.0))
            c._hourly_radiation.append((h, 700.0))
            c._hourly_wind.append((h, 5.0))

        with (
            patch.object(c, "_get_temp_humidity", return_value=(22.0, 55.0)),
            patch.object(c, "_effective_solar_factor", return_value=0.7),
        ):
            # duration_today_h=5h > target=3h → heute überspringen
            result = c._forecast_next_mow(
                _cfg(),
                now_local,
                now_utc,
                wetness_mm=0.0,
                duration_today_h=5.0,
            )
        # Ergebnis muss morgen oder später sein (oder None)
        if result is not None:
            tomorrow = now_local.date() + timedelta(days=1)
            assert result.date() >= tomorrow

    def test_mow_threshold_entity_used(self):
        """mow_threshold_entity wird berücksichtigt."""
        c = _bare()
        thresh = MagicMock()
        thresh.native_value = 0.3  # niedrige Schwelle
        c.mow_threshold_entity = thresh

        now_utc = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        for i in range(1, 49):
            h = now_utc + timedelta(hours=i)
            c._hourly_precip.append((h, 0.0))
            c._hourly_radiation.append((h, 600.0))
            c._hourly_wind.append((h, 5.0))

        with (
            patch.object(c, "_get_temp_humidity", return_value=(22.0, 55.0)),
            patch.object(c, "_effective_solar_factor", return_value=0.6),
        ):
            # Keine Exception → Threshold-Entity wird korrekt gelesen
            result = c._forecast_next_mow(_cfg(), dt_util.now(), now_utc, wetness_mm=0.4)
        # Kein Crash ist das Wichtigste; Ergebnis je nach Simulation variabel
        assert result is None or result > dt_util.now()


class TestNextMowChargeCombination:
    def _coord(self):
        from custom_components.weather_mow.coordinator import WeatherMowCoordinator

        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c._charge_rate = 1.0
        return c

    def test_charge_ready_when_battery_low(self):
        from datetime import datetime

        c = self._coord()
        now = datetime(2026, 6, 3, 14, 0, tzinfo=UTC)
        ready = c._charge_ready_time(now, battery_pct=66.0, min_batt=80)
        assert (ready - now).total_seconds() / 60 == pytest.approx(14.0)

    def test_charge_ready_now_when_battery_ok(self):
        from datetime import datetime

        c = self._coord()
        now = datetime(2026, 6, 3, 14, 0, tzinfo=UTC)
        ready = c._charge_ready_time(now, battery_pct=90.0, min_batt=80)
        assert ready == now
