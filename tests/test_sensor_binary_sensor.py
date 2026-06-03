"""Tests für sensor.py und binary_sensor.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.weather_mow.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    WeatherMowBinarySensor,
)
from custom_components.weather_mow.sensor import (
    SENSOR_DESCRIPTIONS,
    WeatherMowSensor,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_coordinator(data=None, last_update_success=True):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = last_update_success
    return coord


def _make_entry(entry_id="test_entry", name="Rasenmaeher"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name}
    return entry


# ── WeatherMowSensor ──────────────────────────────────────────────────────────


class TestWeatherMowSensor:
    def _make_sensor(self, key="wetness_mm", data=None, last_update_success=True):
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
        coord = _make_coordinator(data=data, last_update_success=last_update_success)
        entry = _make_entry()
        return WeatherMowSensor(coord, entry, desc)

    def test_unique_id(self):
        s = self._make_sensor()
        assert s.unique_id == "test_entry_wetness_mm"

    def test_has_entity_name(self):
        s = self._make_sensor()
        assert s.has_entity_name is True

    def test_device_info_set(self):
        s = self._make_sensor()
        assert s.device_info is not None

    def test_available_when_data_present(self):
        s = self._make_sensor(data={"wetness_mm": 0.3})
        assert s.available is True

    def test_unavailable_when_data_none(self):
        s = self._make_sensor(data=None, last_update_success=True)
        assert s.available is False

    def test_unavailable_when_coordinator_failed(self):
        s = self._make_sensor(data={"wetness_mm": 0.3}, last_update_success=False)
        assert s.available is False

    def test_native_value_returns_data(self):
        s = self._make_sensor(key="priority", data={"priority": 42})
        assert s.native_value == 42

    def test_native_value_none_when_no_data(self):
        s = self._make_sensor(data=None)
        assert s.native_value is None

    def test_native_value_none_when_key_missing(self):
        s = self._make_sensor(key="priority", data={"wetness_mm": 0.5})
        assert s.native_value is None

    @pytest.mark.parametrize("desc", SENSOR_DESCRIPTIONS)
    def test_all_descriptions_create_sensor(self, desc):
        """Jede Sensor-Description muss instanziierbar sein."""
        coord = _make_coordinator(data={desc.data_key: 1.0})
        entry = _make_entry()
        s = WeatherMowSensor(coord, entry, desc)
        assert s.unique_id == f"test_entry_{desc.key}"

    def test_next_mow_expected_start_now(self):
        """Bei start_now=True gibt next_mow_expected die aktuelle Zeit zurück."""
        from homeassistant.util import dt as dt_util

        s = self._make_sensor(
            key="next_mow_expected",
            data={"start_now": True, "next_mow_expected": None},
        )
        val = s.native_value
        # Sollte dt_util.now() sein, also nahe der aktuellen Zeit
        assert val is not None
        diff = abs((val - dt_util.now()).total_seconds())
        assert diff < 5

    def test_next_mow_expected_no_start(self):
        """Ohne start_now=True wird der gespeicherte Wert zurückgegeben."""
        import datetime

        expected = datetime.datetime(2026, 6, 1, 10, 0, tzinfo=datetime.UTC)
        s = self._make_sensor(
            key="next_mow_expected",
            data={"start_now": False, "next_mow_expected": expected},
        )
        assert s.native_value == expected


# ── WeatherMowBinarySensor ────────────────────────────────────────────────────


class TestWeatherMowBinarySensor:
    def _make_sensor(self, key="raining", data=None, last_update_success=True):
        desc = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == key)
        coord = _make_coordinator(data=data, last_update_success=last_update_success)
        entry = _make_entry()
        return WeatherMowBinarySensor(coord, entry, desc)

    def test_unique_id(self):
        s = self._make_sensor()
        assert s.unique_id == "test_entry_raining"

    def test_has_entity_name(self):
        s = self._make_sensor()
        assert s.has_entity_name is True

    def test_available_when_data_present(self):
        s = self._make_sensor(data={"raining": True})
        assert s.available is True

    def test_unavailable_when_data_none(self):
        s = self._make_sensor(data=None)
        assert s.available is False

    def test_unavailable_when_coordinator_failed(self):
        s = self._make_sensor(data={"raining": False}, last_update_success=False)
        assert s.available is False

    def test_is_on_true(self):
        s = self._make_sensor(key="raining", data={"raining": True})
        assert s.is_on is True

    def test_is_on_false(self):
        s = self._make_sensor(key="raining", data={"raining": False})
        assert s.is_on is False

    def test_is_on_none_when_no_data(self):
        s = self._make_sensor(data=None)
        assert s.is_on is None

    def test_is_on_none_when_key_missing(self):
        s = self._make_sensor(key="raining", data={"start_now": True})
        assert s.is_on is None

    @pytest.mark.parametrize("desc", BINARY_SENSOR_DESCRIPTIONS)
    def test_all_descriptions_create_sensor(self, desc):
        """Jede BinarySensor-Description muss instanziierbar sein."""
        coord = _make_coordinator(data={desc.data_key: False})
        entry = _make_entry()
        s = WeatherMowBinarySensor(coord, entry, desc)
        assert s.unique_id == f"test_entry_{desc.key}"

    def test_is_on_converts_truthy_value(self):
        s = self._make_sensor(key="mow_allowed", data={"mow_allowed": 1})
        assert s.is_on is True

    def test_is_on_converts_falsy_value(self):
        s = self._make_sensor(key="mow_allowed", data={"mow_allowed": 0})
        assert s.is_on is False
