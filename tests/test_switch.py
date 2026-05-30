"""Tests für switch.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.weather_mow.switch import (
    WeatherMowDebugSwitch,
    WeatherMowEmergencySwitch,
    WeatherMowIrrigationSwitch,
    WeatherMowSwitch,
    _WeatherMowSwitchBase,
)


def _make_coordinator():
    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    return coord


def _make_entry(entry_id="test_entry", name="Rasenmaeher"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name}
    return entry


class TestWeatherMowSwitch:
    def test_unique_id(self):
        s = WeatherMowSwitch(_make_coordinator(), _make_entry())
        assert s.unique_id == "test_entry_enabled"

    def test_default_on(self):
        s = WeatherMowSwitch(_make_coordinator(), _make_entry())
        assert s.is_on is True

    @pytest.mark.asyncio
    async def test_turn_off(self):
        s = WeatherMowSwitch(_make_coordinator(), _make_entry())
        s.async_write_ha_state = MagicMock()
        await s.async_turn_off()
        assert s.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on(self):
        s = WeatherMowSwitch(_make_coordinator(), _make_entry())
        s.async_write_ha_state = MagicMock()
        await s.async_turn_off()
        await s.async_turn_on()
        assert s.is_on is True

    @pytest.mark.asyncio
    async def test_restore_on_state(self):
        s = WeatherMowSwitch(_make_coordinator(), _make_entry())
        last_state = MagicMock()
        last_state.state = "on"
        with (
            patch.object(s, "async_get_last_state", AsyncMock(return_value=last_state)),
            patch.object(_WeatherMowSwitchBase.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await s.async_added_to_hass()
        assert s.is_on is True

    @pytest.mark.asyncio
    async def test_restore_off_state(self):
        s = WeatherMowSwitch(_make_coordinator(), _make_entry())
        last_state = MagicMock()
        last_state.state = "off"
        with (
            patch.object(s, "async_get_last_state", AsyncMock(return_value=last_state)),
            patch.object(_WeatherMowSwitchBase.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await s.async_added_to_hass()
        assert s.is_on is False

    @pytest.mark.asyncio
    async def test_restore_none_keeps_default(self):
        s = WeatherMowSwitch(_make_coordinator(), _make_entry())
        with (
            patch.object(s, "async_get_last_state", AsyncMock(return_value=None)),
            patch.object(_WeatherMowSwitchBase.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await s.async_added_to_hass()
        assert s.is_on is True  # default_on=True


class TestWeatherMowEmergencySwitch:
    def test_unique_id(self):
        s = WeatherMowEmergencySwitch(_make_coordinator(), _make_entry())
        assert s.unique_id == "test_entry_emergency_mow"

    def test_default_on(self):
        s = WeatherMowEmergencySwitch(_make_coordinator(), _make_entry())
        assert s.is_on is True


class TestWeatherMowIrrigationSwitch:
    def test_unique_id(self):
        s = WeatherMowIrrigationSwitch(_make_coordinator(), _make_entry())
        assert s.unique_id == "test_entry_irrigation"

    def test_default_off(self):
        s = WeatherMowIrrigationSwitch(_make_coordinator(), _make_entry())
        assert s.is_on is False


class TestWeatherMowDebugSwitch:
    def test_unique_id(self):
        s = WeatherMowDebugSwitch(_make_coordinator(), _make_entry())
        assert s.unique_id == "test_entry_debug_log"

    def test_default_off(self):
        s = WeatherMowDebugSwitch(_make_coordinator(), _make_entry())
        assert s.is_on is False
