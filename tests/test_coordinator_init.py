"""Tests für _register_listeners, _parse_sensor_forecasts und _init_*_from_recorder."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.util import dt as dt_util

from custom_components.weather_mow.const import RAIN_BUFFER_MAXLEN, SOLAR_PEAK_MIN
from custom_components.weather_mow.coordinator import WeatherMowCoordinator


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def entry():
    e = MagicMock()
    e.entry_id = "init_test"
    e.data = {
        "name": "Test",
        "mower_entity_id": "lawn_mower.test",
        "weather_entity_id": "weather.test",
        "rain_sensor_entity_id": "sensor.rain",
        "rain_detector_entity_id": "binary_sensor.rain_det",
        "outdoor_temp_entity_id": "",
        "outdoor_humidity_entity_id": "",
        "wind_sensor_entity_id": "",
        "local_radiation_entity_id": "",
        "radiation_forecast_entity_id": "",
        "precip_forecast_entity_id": "",
        "pv_power_entity_id": "",
        "brightness_entity_id": "",
        "radiation_source": "sun",
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
    with patch.object(c, "_load_storage"):
        with patch.object(c, "_register_listeners"):
            await c._async_setup()
    c._sunshine_initialized = True
    c._duration_yesterday_s = 9000.0
    c._duration_day_before_s = 9000.0
    sw = MagicMock()
    sw.is_on = True
    c.switch_entity = sw
    yield c


# ── _register_listeners ───────────────────────────────────────────────────────

class TestRegisterListeners:
    """Listener-Registration testen — Midnight-Timer wird gemockt um Cleanup-Fehler zu vermeiden."""

    async def test_registers_mower_listener(self, hass, entry):
        """Mäher-Entity → State-Change-Listener registriert."""
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"):
            with patch("custom_components.weather_mow.coordinator.async_track_time_change"):
                await c._async_setup()
        assert c._mow_state_unsub is not None

    async def test_registers_weather_listener(self, hass, entry):
        """Weather-Entity → State-Change-Listener registriert."""
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"):
            with patch("custom_components.weather_mow.coordinator.async_track_time_change"):
                await c._async_setup()
        assert c._weather_state_unsub is not None

    async def test_registers_rain_sensor_listener(self, hass, entry):
        """Regen-Sensor → State-Change-Listener registriert."""
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"):
            with patch("custom_components.weather_mow.coordinator.async_track_time_change"):
                await c._async_setup()
        assert c._rain_sensor_unsub is not None

    async def test_registers_rain_detector_listener(self, hass, entry):
        """Regen-Detektor → State-Change-Listener registriert."""
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"):
            with patch("custom_components.weather_mow.coordinator.async_track_time_change"):
                await c._async_setup()
        assert c._rain_detect_unsub is not None

    async def test_no_mower_listener_without_entity(self, hass, entry):
        """Kein Listener wenn keine Mäher-Entity konfiguriert."""
        entry.data = {**entry.data, "mower_entity_id": ""}
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"):
            with patch("custom_components.weather_mow.coordinator.async_track_time_change"):
                await c._async_setup()
        assert c._mow_state_unsub is None


# ── _parse_sensor_forecasts ───────────────────────────────────────────────────

class TestParseSensorForecasts:

    async def test_empty_precip_sensor_returns_zeros(self, hass, coord):
        """Kein Niederschlags-Sensor → alle Werte 0."""
        hass.states.async_set("weather.test", "sunny",
                               attributes={"temperature": 20.0, "humidity": 60,
                                           "wind_speed": 5.0, "forecast": []})
        hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
        hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 100})

        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        assert data["rain_today_remaining"] == 0.0
        assert data["rain_tomorrow"] == 0.0

    async def test_precip_sensor_with_forecast_data(self, hass, coord):
        """Niederschlags-Sensor mit Forecast-Daten → Regen wird erkannt."""
        now_utc = dt_util.utcnow()
        tomorrow = now_utc + timedelta(hours=20)
        # Stündliche Niederschlagsdaten: 5mm morgen
        precip_data = [
            {"datetime": tomorrow.isoformat(), "value": 5.0},
        ]
        hass.states.async_set(
            "sensor.precip_fc", "ok",
            attributes={"data": precip_data}
        )
        coord.entry.data = {
            **coord.entry.data,
            "precip_forecast_entity_id": "sensor.precip_fc",
        }
        hass.states.async_set("weather.test", "sunny",
                               attributes={"temperature": 20.0, "humidity": 60,
                                           "wind_speed": 5.0, "forecast": []})
        hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
        hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 100})

        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        # Morgen-Regen sollte erkannt werden
        assert data["rain_tomorrow"] > 0.0


# ── _init_*_from_recorder (mit gemocktem Recorder) ───────────────────────────

class TestInitFromRecorder:

    async def test_init_rain_buffer_no_radiation_entity(self, hass, entry):
        """Ohne Strahlungs-Entity → _init_rain_buffer_from_recorder tut nichts."""
        entry.data = {**entry.data, "local_radiation_entity_id": ""}
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"):
            with patch.object(c, "_register_listeners"):
                await c._async_setup()

        # Sollte ohne Fehler laufen (frühzeitiger Return wenn keine Entity)
        await c._init_rain_buffer_from_recorder(
            {**entry.data, **entry.options}, dt_util.utcnow()
        )
        # Kein Crash = Test bestanden

    async def test_init_rain_buffer_with_empty_recorder(self, hass, entry):
        """Recorder gibt leeres Ergebnis → kein Crash."""
        entry.data = {**entry.data, "local_radiation_entity_id": "sensor.solar"}
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"):
            with patch.object(c, "_register_listeners"):
                await c._async_setup()

        mock_instance = MagicMock()
        mock_instance.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_instance,
        ):
            await c._init_rain_buffer_from_recorder(
                {**entry.data, **entry.options}, dt_util.utcnow()
            )

    async def test_init_solar_peak_with_empty_recorder(self, hass, entry):
        """Solar-Peak Recorder mit leerem Ergebnis → SOLAR_PEAK_MIN bleibt."""
        entry.data = {**entry.data, "local_radiation_entity_id": "sensor.solar"}
        c = WeatherMowCoordinator(hass, entry)
        c._radiation_peak = SOLAR_PEAK_MIN
        with patch.object(c, "_load_storage"):
            with patch.object(c, "_register_listeners"):
                await c._async_setup()

        mock_instance = MagicMock()
        mock_instance.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_instance,
        ):
            await c._init_solar_peak_from_recorder(
                {**entry.data, **entry.options}, dt_util.utcnow()
            )
        assert c._radiation_peak >= SOLAR_PEAK_MIN

    async def test_init_duration_with_empty_recorder(self, hass, entry):
        """Duration Recorder mit leerem Ergebnis → keine Änderung."""
        c = WeatherMowCoordinator(hass, entry)
        c._duration_today_s = 0.0
        with patch.object(c, "_load_storage"):
            with patch.object(c, "_register_listeners"):
                await c._async_setup()

        mock_instance = MagicMock()
        mock_instance.async_add_executor_job = AsyncMock(return_value={})

        with patch(
            "homeassistant.components.recorder.get_instance",
            return_value=mock_instance,
        ):
            await c._init_duration_from_recorder(
                {**entry.data, **entry.options}, dt_util.utcnow(), dt_util.now()
            )

    async def test_init_sunshine_no_radiation_entity(self, hass, entry):
        """Ohne Strahlungs-Entity → _init_sunshine_from_recorder tut nichts."""
        entry.data = {**entry.data, "local_radiation_entity_id": ""}
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"):
            with patch.object(c, "_register_listeners"):
                await c._async_setup()

        await c._init_sunshine_from_recorder(
            {**entry.data, **entry.options}, dt_util.utcnow()
        )
        # Kein Crash = Test bestanden
