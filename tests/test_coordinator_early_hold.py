"""Coordinator-Tests: Morgen-Zurückhaltung ("so früh wie nötig, so spät wie möglich").

Hintergrund (22.08.2026): Der Mäher startete um 07:22 Uhr bei 13 °C, trocken und
ohne Regenprognose — obwohl noch der ganze Tag Zeit war. Ursache: das Tagesdefizit
ist morgens per Definition maximal (40 Punkte = exakt die Start-Schwelle).

Alle Tests frieren die Zeit ein. Die HA-Test-Fixture läuft in US/Pacific (UTC−7),
darum ist die eingefrorene UTC-Zeit jeweils 7 Stunden vor der gemeinten Ortszeit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# 07:22 Ortszeit (US/Pacific) am 22.08.2026 — der reale Startzeitpunkt des Bugs.
FROZEN_0722_LOCAL = "2026-08-22 14:22:00+00:00"
# 11:00 Ortszeit — nach der Wunsch-Startzeit (10:00).
FROZEN_1100_LOCAL = "2026-08-22 18:00:00+00:00"


@pytest.fixture
def entry():
    e = MagicMock()
    e.entry_id = "hold_test"
    e.data = {
        "name": "Testmaher",
        "mower_entity_id": "lawn_mower.test",
        "weather_entity_id": "weather.test",
        "rain_sensor_entity_id": "",
        "rain_1h_sensor_entity_id": "",
        "rain_today_sensor_entity_id": "",
        "rain_detector_entity_id": "",
        "outdoor_temp_entity_id": "",
        "outdoor_humidity_entity_id": "",
        "wind_sensor_entity_id": "",
        "local_radiation_entity_id": "",
        "brightness_entity_id": "",
        "radiation_source": "sun",
        "min_brightness_lux": 2000,
        "min_battery_pct": 20,
    }
    # Fenster ab 06:00 → Wunsch-Startzeit = 06:00 + 4 h = 10:00 Ortszeit.
    e.options = {
        "mow_window_start": "06:00:00",
        "mow_window_end": "22:00:00",
        "target_buffer_h": 0.0,
        "target_daily_duration_h": 3.0,
    }
    return e


@pytest.fixture
async def coord(hass, entry):
    c = WeatherMowCoordinator(hass, entry)
    with patch.object(c, "_load_storage"), patch.object(c, "_register_listeners"):
        await c._async_setup()
    c._sunshine_initialized = True
    sw = MagicMock()
    sw.is_on = True
    c.switch_entity = sw
    c._duration_yesterday_s = 9000.0
    c._duration_day_before_s = 9000.0
    yield c


def _weather(hass, temp=13.0):
    hass.states.async_set(
        "weather.test",
        "sunny",
        attributes={"temperature": temp, "humidity": 60, "wind_speed": 5.0, "forecast": []},
    )
    hass.states.async_set(
        "sun.sun", "above_horizon", attributes={"elevation": 30.0, "azimuth": 120.0}
    )


def _mower(hass, state="docked", battery=100):
    hass.states.async_set("lawn_mower.test", state, attributes={"battery_level": battery})


def _forecast(coord, rain_mm=0.0, temp_c=18.0, first_local_hour=10, hours=12):
    """Setzt eine stündliche Prognose ab first_local_hour Ortszeit (US/Pacific)."""
    coord._hourly_precip = []
    coord._hourly_temp = []
    # Ortszeit → UTC (+7 h in US/Pacific Sommerzeit)
    base = datetime(2026, 8, 22, 0, 0, tzinfo=UTC) + timedelta(hours=first_local_hour + 7)
    for i in range(hours):
        dt_h = base + timedelta(hours=i)
        coord._hourly_precip.append((dt_h, rain_mm))
        coord._hourly_temp.append((dt_h, temp_c))


async def _run(coord, hass):
    """Ein Update-Zyklus mit trockenem Rasen und stabiler Prognose."""

    def _keep_dry(*a, **kw):
        coord._wetness_mm = 0.0
        return 0.0, 0.0, 0.0

    coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
    with (
        patch.object(coord, "_update_wetness", _keep_dry),
        # _parse_forecasts darf die gesetzte Prognose nicht überschreiben
        patch.object(coord, "_parse_forecasts", return_value=(0.0, 0.0, 0.0, 0.0)),
    ):
        return await coord._async_update_data()


class TestEarlyHold:
    @pytest.mark.freeze_time(FROZEN_0722_LOCAL)
    async def test_regression_cool_dry_morning_holds(self, hass, coord):
        """Kernfall 22.08.: kühl, trocken, kein Regen → NICHT um 07:22 starten.

        mow_allowed bleibt True und stop_now False, damit ein manuell gestarteter
        Mäher weiterlaufen darf."""
        _weather(hass)
        _mower(hass)
        _forecast(coord, rain_mm=0.0, temp_c=18.0)

        data = await _run(coord, hass)

        assert data["block_reason"] == "waiting_optimal_time"
        assert data["start_now"] is False
        assert data["mow_allowed"] is True
        assert data["stop_now"] is False

    @pytest.mark.freeze_time(FROZEN_0722_LOCAL)
    async def test_persistent_rain_starts_early(self, hass, coord):
        """Ab der Wunschzeit dauerhaft Regen → jetzt losfahren."""
        _weather(hass)
        _mower(hass)
        _forecast(coord, rain_mm=1.0, temp_c=18.0)

        data = await _run(coord, hass)

        assert data["block_reason"] == "mowing_allowed"
        assert data["start_now"] is True

    @pytest.mark.freeze_time(FROZEN_0722_LOCAL)
    async def test_afternoon_heat_starts_early(self, hass, coord):
        """Ab Mittag zu heiß → die heißen Stunden sind unbrauchbar → jetzt losfahren."""
        _weather(hass)
        _mower(hass)
        _forecast(coord, rain_mm=0.0, temp_c=36.0)

        data = await _run(coord, hass)

        assert data["block_reason"] == "mowing_allowed"
        assert data["start_now"] is True

    @pytest.mark.freeze_time(FROZEN_1100_LOCAL)
    async def test_after_preferred_time_no_hold(self, hass, coord):
        """Nach der Wunsch-Startzeit greift die Zurückhaltung nicht mehr."""
        _weather(hass)
        _mower(hass)
        _forecast(coord, rain_mm=0.0, temp_c=18.0, first_local_hour=11, hours=11)

        data = await _run(coord, hass)

        assert data["block_reason"] == "mowing_allowed"
        assert data["start_now"] is True

    @pytest.mark.freeze_time(FROZEN_0722_LOCAL)
    async def test_no_forecast_holds(self, hass, coord):
        """Ohne Stundenprognose fehlt der Grund für einen frühen Start → warten."""
        _weather(hass)
        _mower(hass)
        coord._hourly_precip = []
        coord._hourly_temp = []

        data = await _run(coord, hass)

        assert data["block_reason"] == "waiting_optimal_time"
        assert data["start_now"] is False

    @pytest.mark.freeze_time(FROZEN_0722_LOCAL)
    async def test_high_priority_bypasses_hold(self, hass, coord):
        """Hohe Dringlichkeit (≥ DELAY_BYPASS_PRIORITY) übersteuert die Zurückhaltung."""
        _weather(hass)
        _mower(hass)
        _forecast(coord, rain_mm=0.0, temp_c=18.0)

        with patch.object(coord, "_compute_priority", return_value=80):
            data = await _run(coord, hass)

        assert data["block_reason"] == "mowing_allowed"
        assert data["start_now"] is True

    @pytest.mark.freeze_time(FROZEN_0722_LOCAL)
    async def test_no_dry_window_bypasses_hold(self, hass, coord):
        """Kein Trockenfenster mehr heute → warten wäre sinnlos.

        no_dry_window ist zusätzlich an das Gras-Defizit gekoppelt (avg der letzten
        3 Tage < 50 % des Tagesziels), daher hier ohne Mähhistorie."""
        _weather(hass)
        _mower(hass)
        _forecast(coord, rain_mm=0.0, temp_c=18.0)
        coord._duration_yesterday_s = 0.0
        coord._duration_day_before_s = 0.0

        with patch.object(coord, "_check_no_dry_window", return_value=True):
            data = await _run(coord, hass)

        assert data["block_reason"] == "mowing_allowed"
        assert data["start_now"] is True

    @pytest.mark.freeze_time(FROZEN_0722_LOCAL)
    async def test_next_mow_expected_points_at_preferred_time(self, hass, coord):
        """Während der Zurückhaltung zeigt die Prognose die Wunsch-Startzeit (10:00)."""
        _weather(hass)
        _mower(hass)
        _forecast(coord, rain_mm=0.0, temp_c=18.0)

        data = await _run(coord, hass)

        nme = data["next_mow_expected"]
        assert nme is not None
        assert dt_util.as_local(nme).hour == 10

    @pytest.mark.freeze_time(FROZEN_0722_LOCAL)
    async def test_narrow_window_never_blocks_whole_day(self, hass, coord):
        """Läge die Wunschzeit am/hinter dem Fensterende, darf nicht dauerhaft
        blockiert werden (schmales Mähfenster)."""
        coord.entry.options = {
            **coord.entry.options,
            "mow_window_start": "06:00:00",
            "mow_window_end": "09:00:00",  # Wunschzeit 10:00 läge dahinter
        }
        _weather(hass)
        _mower(hass)
        _forecast(coord, rain_mm=0.0, temp_c=18.0)

        data = await _run(coord, hass)

        assert data["block_reason"] != "waiting_optimal_time"
