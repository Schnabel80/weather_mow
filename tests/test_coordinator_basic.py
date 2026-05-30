"""Erste Coordinator-Tests mit echter hass-Fixture.

Diese Tests laufen mit einem echten in-memory Home Assistant (kein Docker).
Der hass-Fixture kommt von pytest-homeassistant-custom-component und stellt
das komplette HA-Core-Framework bereit: State Machine, Event Bus, Storage usw.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.weather_mow.coordinator import WeatherMowCoordinator


# ── Minimale Config Entry ─────────────────────────────────────────────────────

@pytest.fixture
def minimal_entry(hass):
    """Config Entry mit dem absoluten Minimum — nur weather entity."""
    from unittest.mock import MagicMock
    entry = MagicMock()
    entry.entry_id = "test_coord_entry"
    entry.data = {
        "name": "Testmaher",
        "mower_entity_id": "lawn_mower.test",
        "weather_entity_id": "weather.test",
        # Alle optionalen Sensoren leer lassen
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
    }
    entry.options = {}
    return entry


@pytest.fixture
async def coordinator(hass, minimal_entry):
    """Fertig initialisierter Coordinator für Tests."""
    coord = WeatherMowCoordinator(hass, minimal_entry)

    # Storage-Calls und Listener unterdrücken — wir testen nur die Logik
    with patch.object(coord, "_load_storage"):
        with patch.object(coord, "_register_listeners"):
            await coord._async_setup()

    # Sunshine-Init überspringen (braucht Recorder)
    coord._sunshine_initialized = True

    # Recorder-basierte Inits überspringen
    with patch.object(coord, "_init_rain_buffer_from_recorder"):
        with patch.object(coord, "_init_duration_from_recorder"):
            with patch.object(coord, "_init_solar_peak_from_recorder"):
                with patch.object(coord, "_init_sunshine_from_recorder"):
                    coord._sunshine_initialized = True
                    yield coord


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRainingDetection:
    """Regen-Erkennung: lokaler Sensor vs. Weather-Condition."""

    async def test_raining_false_when_no_sources(self, hass, coordinator):
        """Kein Regen wenn weder Sensor noch Condition aktiv."""
        hass.states.async_set("weather.test", "sunny")
        hass.states.async_set("lawn_mower.test", "docked")

        data = await coordinator._async_update_data()

        assert data["raining"] is False

    async def test_raining_by_condition_when_no_local_sensor(self, hass, coordinator):
        """Ohne lokalen Sensor: Weather-Condition 'rainy' setzt raining=True."""
        hass.states.async_set("weather.test", "rainy",
                               attributes={"temperature": 18.0, "humidity": 80,
                                           "wind_speed": 5.0, "forecast": []})
        hass.states.async_set("lawn_mower.test", "docked")

        data = await coordinator._async_update_data()

        assert data["raining"] is True

    async def test_condition_suppressed_by_local_rain_detector(self, hass, coordinator):
        """Lokaler Detektor verfügbar + off → Condition wird ignoriert."""
        # Weather sagt rainy, aber lokaler Detektor sagt kein Regen
        hass.states.async_set("weather.test", "rainy",
                               attributes={"temperature": 20.0, "humidity": 75,
                                           "wind_speed": 3.0, "forecast": []})
        hass.states.async_set("binary_sensor.rain_state", "off")
        hass.states.async_set("lawn_mower.test", "docked")

        # Detektor in Config eintragen
        coordinator.entry.data = {
            **coordinator.entry.data,
            "rain_detector_entity_id": "binary_sensor.rain_state",
        }

        data = await coordinator._async_update_data()

        # Lokaler Detektor hat Vorrang — raining=False trotz "rainy" condition
        assert data["raining"] is False

    async def test_local_detector_on_sets_raining(self, hass, coordinator):
        """Lokaler Detektor auf 'on' → raining=True, unabhängig von Condition."""
        hass.states.async_set("weather.test", "sunny")
        hass.states.async_set("binary_sensor.rain_state", "on")
        hass.states.async_set("lawn_mower.test", "docked")

        coordinator.entry.data = {
            **coordinator.entry.data,
            "rain_detector_entity_id": "binary_sensor.rain_state",
        }

        data = await coordinator._async_update_data()

        assert data["raining"] is True


class TestBlockReason:
    """Entscheidungslogik: Sperrgründe."""

    async def test_outside_window_before_start(self, hass, coordinator):
        """Außerhalb des Mähfensters → block_reason outside_time_window."""
        from unittest.mock import patch as mpatch
        import datetime

        hass.states.async_set("weather.test", "sunny",
                               attributes={"temperature": 20.0, "humidity": 60,
                                           "wind_speed": 5.0, "forecast": []})
        hass.states.async_set("lawn_mower.test", "docked",
                               attributes={"battery_level": 100})

        # Zeit auf 06:00 setzen — vor dem Default-Fenster (08:00)
        fake_now = datetime.datetime(2026, 6, 1, 6, 0, 0,
                                     tzinfo=datetime.timezone.utc)
        with mpatch("homeassistant.util.dt.now", return_value=fake_now):
            with mpatch("homeassistant.util.dt.utcnow", return_value=fake_now):
                data = await coordinator._async_update_data()

        assert data["mow_allowed"] is False
        assert "window" in data["block_reason"]

    async def test_integration_disabled(self, hass, coordinator):
        """Hauptschalter off → blocked."""
        hass.states.async_set("weather.test", "sunny")
        hass.states.async_set("lawn_mower.test", "docked")

        # Hauptschalter auf off setzen
        switch_mock = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        switch_mock.is_on = False
        coordinator.switch_entity = switch_mock

        data = await coordinator._async_update_data()

        assert data["mow_allowed"] is False
        assert data["block_reason"] == "disabled"
