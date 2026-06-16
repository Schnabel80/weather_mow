"""Tests für Wetness-Modell, Irrigation und Helper-Methoden im Coordinator.

_update_wetness ist synchrone Penman-Logik — kein hass-Fixture nötig.
_get_temp_humidity, _get_wind_kmh etc. lesen HA-States — brauchen hass.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.const import (
    IRRIGATION_FIXED_MM,
    WETNESS_MAX_MM,
)
from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Minimal-Coordinator ohne hass (für synchrone Methoden) ───────────────────


def _make_bare_coordinator():
    """Coordinator-Instanz mit gemocktem hass für synchrone Methoden."""
    hass = MagicMock()
    hass.async_create_task = MagicMock()

    entry = MagicMock()
    entry.entry_id = "wet_test"
    entry.data = {"name": "Test"}
    entry.options = {}

    coord = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
    coord.hass = hass
    coord.entry = entry
    coord._wetness_mm = 0.0
    coord._last_drying_mm = 0.0
    coord._below_threshold_since = None
    return coord


# ── Fixture für hass-basierte Tests ──────────────────────────────────────────


@pytest.fixture
def entry():
    e = MagicMock()
    e.entry_id = "wet_hass_test"
    e.data = {
        "name": "Test",
        "mower_entity_id": "lawn_mower.test",
        "weather_entity_id": "weather.test",
        "outdoor_temp_entity_id": "",
        "outdoor_humidity_entity_id": "",
        "wind_sensor_entity_id": "",
        "local_radiation_entity_id": "",
        "brightness_entity_id": "",
        "radiation_source": "sun",
        "rain_sensor_entity_id": "",
        "rain_1h_sensor_entity_id": "",
        "rain_today_sensor_entity_id": "",
        "rain_detector_entity_id": "",
    }
    e.options = {
        "mow_window_start": "00:00:00",
        "mow_window_end": "23:59:00",
        "target_buffer_h": 0.0,
    }
    return e


@pytest.fixture
async def coord(hass, entry):
    c = WeatherMowCoordinator(hass, entry)
    with patch.object(c, "_load_storage"), patch.object(c, "_register_listeners"):
        await c._async_setup()
    c._sunshine_initialized = True
    c._duration_yesterday_s = 9000.0
    c._duration_day_before_s = 9000.0
    sw = MagicMock()
    sw.is_on = True
    c.switch_entity = sw
    yield c


# ── _update_wetness (direkt, kein hass) ──────────────────────────────────────


class TestUpdateWetness:
    def test_rain_increases_wetness(self):
        c = _make_bare_coordinator()
        c._wetness_mm = 0.0
        _vpd, _dry, _cond = c._update_wetness(
            rain_delta_mm=0.5,
            eff_solar=0.0,  # keine Sonne → kein Trocknen
            temp_c=15.0,
            dew_point_c=15.0,  # vpd=0 → kein Trocknen, kein Kondensieren
            wind_kmh=0.0,
        )
        assert c._wetness_mm > 0.0
        assert c._wetness_mm == pytest.approx(0.5, abs=0.01)

    def test_solar_reduces_wetness(self):
        c = _make_bare_coordinator()
        c._wetness_mm = 1.0
        _, dry, _ = c._update_wetness(
            rain_delta_mm=0.0,
            eff_solar=1.0,  # volle Sonne → maximales Trocknen
            temp_c=25.0,
            dew_point_c=10.0,  # vpd = 15°C
            wind_kmh=10.0,
        )
        assert dry > 0.0
        assert c._wetness_mm < 1.0

    def test_condensation_increases_wetness(self):
        """Temp unter Taupunkt → Kondensation erhöht Wetness."""
        c = _make_bare_coordinator()
        c._wetness_mm = 0.0
        _, _, cond = c._update_wetness(
            rain_delta_mm=0.0,
            eff_solar=0.0,
            temp_c=8.0,
            dew_point_c=12.0,  # vpd = 8 - 12 = -4°C → Kondensation
            wind_kmh=0.0,
        )
        assert cond > 0.0
        assert c._wetness_mm > 0.0

    def test_wetness_clamped_at_max(self):
        """Wetness kann WETNESS_MAX_MM nicht überschreiten."""
        c = _make_bare_coordinator()
        c._wetness_mm = WETNESS_MAX_MM - 0.1
        c._update_wetness(
            rain_delta_mm=2.0,  # viel Regen
            eff_solar=0.0,
            temp_c=15.0,
            dew_point_c=15.0,
            wind_kmh=0.0,
        )
        assert c._wetness_mm == pytest.approx(WETNESS_MAX_MM)

    def test_wetness_clamped_at_zero(self):
        """Wetness kann nicht negativ werden."""
        c = _make_bare_coordinator()
        c._wetness_mm = 0.01
        c._update_wetness(
            rain_delta_mm=0.0,
            eff_solar=1.0,  # starkes Trocknen
            temp_c=35.0,
            dew_point_c=5.0,  # vpd = 30°C
            wind_kmh=20.0,
        )
        assert c._wetness_mm >= 0.0

    def test_rain_delta_capped(self):
        """Rain-Delta ist auf WETNESS_DELTA_CAP_MM begrenzt."""
        from custom_components.weather_mow.const import WETNESS_DELTA_CAP_MM

        c = _make_bare_coordinator()
        c._wetness_mm = 0.0
        c._update_wetness(
            rain_delta_mm=99.0,  # extremer Regen
            eff_solar=0.0,
            temp_c=15.0,
            dew_point_c=15.0,
            wind_kmh=0.0,
        )
        assert c._wetness_mm <= WETNESS_DELTA_CAP_MM

    def test_returns_vpd_drying_cond(self):
        """Rückgabe-Tuple muss 3 Werte haben."""
        c = _make_bare_coordinator()
        result = c._update_wetness(0.0, 0.5, 20.0, 10.0, 5.0)
        assert len(result) == 3
        vpd, _dry, _cond = result
        assert vpd == pytest.approx(10.0)  # temp - dew_point

    def test_last_drying_mm_updated(self):
        """_last_drying_mm wird nach jedem Update gesetzt."""
        c = _make_bare_coordinator()
        c._wetness_mm = 1.0
        _, dry, _ = c._update_wetness(0.0, 0.8, 25.0, 10.0, 8.0)
        assert c._last_drying_mm == pytest.approx(dry)


# ── apply_irrigation und reset_wetness ───────────────────────────────────────


class TestIrrigationReset:
    def test_apply_irrigation_increases_wetness(self):
        # IRRIGATION_FIXED_MM == WETNESS_MAX_MM == 2.0 → immer geclampt
        c = _make_bare_coordinator()
        c._wetness_mm = 0.0
        c.apply_irrigation()
        assert c._wetness_mm == pytest.approx(IRRIGATION_FIXED_MM)

    def test_apply_irrigation_capped_at_max(self):
        c = _make_bare_coordinator()
        c._wetness_mm = WETNESS_MAX_MM - 0.1
        c.apply_irrigation()
        assert c._wetness_mm == pytest.approx(WETNESS_MAX_MM)

    def test_reset_wetness_sets_zero(self):
        c = _make_bare_coordinator()
        c._wetness_mm = 1.5
        c._below_threshold_since = dt_util.now()
        c.reset_wetness()
        assert c._wetness_mm == 0.0
        assert c._below_threshold_since is None


# ── _get_temp_humidity (liest HA-States) ─────────────────────────────────────


class TestGetTempHumidity:
    async def test_reads_from_sensor(self, hass, coord):
        """Temp/Feuchte aus lokalen Sensoren wenn konfiguriert."""
        hass.states.async_set("sensor.temp", "22.5")
        hass.states.async_set("sensor.humidity", "65.0")
        coord.entry.data = {
            **coord.entry.data,
            "outdoor_temp_entity_id": "sensor.temp",
            "outdoor_humidity_entity_id": "sensor.humidity",
        }
        temp, humidity = coord._get_temp_humidity({**coord.entry.data, **coord.entry.options})
        assert temp == pytest.approx(22.5)
        assert humidity == pytest.approx(65.0)

    async def test_falls_back_to_weather(self, hass, coord):
        """Ohne Sensor → Fallback auf Wetter-Entity-Attribute."""
        hass.states.async_set(
            "weather.test", "sunny", attributes={"temperature": 18.0, "humidity": 70.0}
        )
        temp, humidity = coord._get_temp_humidity({**coord.entry.data, **coord.entry.options})
        assert temp == pytest.approx(18.0)
        assert humidity == pytest.approx(70.0)


# ── Voller Wetness-Zyklus über hass-Fixture ──────────────────────────────────


class TestWetnessCycleIntegration:
    async def test_irrigation_reflected_in_data(self, hass, coord):
        """apply_irrigation → nächstes Update zeigt erhöhte wetness_mm."""
        hass.states.async_set(
            "weather.test",
            "sunny",
            attributes={"temperature": 20.0, "humidity": 60, "wind_speed": 5.0, "forecast": []},
        )
        hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
        hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 100})

        coord._wetness_mm = 0.0
        coord.apply_irrigation()
        wetness_after_irrigation = coord._wetness_mm
        assert wetness_after_irrigation == pytest.approx(IRRIGATION_FIXED_MM)

        data = await coord._async_update_data()
        # Nach Update leicht verändert (Trocknung), aber deutlich > 0
        assert data["wetness_mm"] > 0.0

    async def test_reset_wetness_reflected_in_data(self, hass, coord):
        """reset_wetness → nächstes Update zeigt ~0 wetness_mm."""
        hass.states.async_set(
            "weather.test",
            "sunny",
            attributes={"temperature": 20.0, "humidity": 60, "wind_speed": 5.0, "forecast": []},
        )
        hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
        hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 100})

        coord._wetness_mm = 1.5
        coord.reset_wetness()

        data = await coord._async_update_data()
        assert data["wetness_mm"] < 0.1  # nahe 0 (leichte Trocknung)


# ── rain_last_1h / rain_today aus Puffer (v0.4.3b4) ──────────────────────────


class TestRainFromBuffer:
    def test_rain_last_60min_sums_last_12_slots(self):
        """rain_last_1h kommt aus den jüngsten 12 Pufferslots (60 min)."""
        from collections import deque

        coord = _make_bare_coordinator()
        coord._rain_buffer = deque([0.0] * 132 + [0.1] * 12)  # 11 h trocken, 60 min × 0.1
        assert coord._rain_last_60min() == pytest.approx(1.2)

    def test_rain_last_60min_empty_buffer(self):
        from collections import deque

        coord = _make_bare_coordinator()
        coord._rain_buffer = deque()
        assert coord._rain_last_60min() == 0.0
