"""Tests für date.py und time.py."""

from __future__ import annotations

from datetime import date
from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.weather_mow.date import WeatherMowFertilizationDate
from custom_components.weather_mow.time import WeatherMowLawnSunFrom


def _make_coordinator():
    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    return coord


def _make_entry(entry_id="test_entry", name="Rasenmaeher"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name}
    return entry


# ── WeatherMowFertilizationDate ───────────────────────────────────────────────


class TestWeatherMowFertilizationDate:
    def test_unique_id(self):
        e = WeatherMowFertilizationDate(_make_coordinator(), _make_entry())
        assert e.unique_id == "test_entry_last_fertilization"

    def test_has_entity_name(self):
        e = WeatherMowFertilizationDate(_make_coordinator(), _make_entry())
        assert e.has_entity_name is True

    def test_default_native_value_is_none(self):
        e = WeatherMowFertilizationDate(_make_coordinator(), _make_entry())
        assert e.native_value is None

    @pytest.mark.asyncio
    async def test_set_value(self):
        coord = _make_coordinator()
        e = WeatherMowFertilizationDate(coord, _make_entry())
        e.async_write_ha_state = MagicMock()
        d = date(2026, 5, 1)
        await e.async_set_value(d)
        assert e.native_value == d
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_valid_date(self):
        e = WeatherMowFertilizationDate(_make_coordinator(), _make_entry())
        last_state = MagicMock()
        last_state.state = "2026-04-15"
        with (
            patch.object(e, "async_get_last_state", AsyncMock(return_value=last_state)),
            patch.object(e.__class__.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await e.async_added_to_hass()
        assert e.native_value == date(2026, 4, 15)

    @pytest.mark.asyncio
    async def test_restore_unknown_state_keeps_none(self):
        e = WeatherMowFertilizationDate(_make_coordinator(), _make_entry())
        last_state = MagicMock()
        last_state.state = "unknown"
        with (
            patch.object(e, "async_get_last_state", AsyncMock(return_value=last_state)),
            patch.object(e.__class__.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await e.async_added_to_hass()
        assert e.native_value is None

    @pytest.mark.asyncio
    async def test_restore_invalid_state_keeps_none(self):
        e = WeatherMowFertilizationDate(_make_coordinator(), _make_entry())
        last_state = MagicMock()
        last_state.state = "not-a-date"
        with (
            patch.object(e, "async_get_last_state", AsyncMock(return_value=last_state)),
            patch.object(e.__class__.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await e.async_added_to_hass()
        assert e.native_value is None

    @pytest.mark.asyncio
    async def test_restore_none_state_keeps_none(self):
        e = WeatherMowFertilizationDate(_make_coordinator(), _make_entry())
        with (
            patch.object(e, "async_get_last_state", AsyncMock(return_value=None)),
            patch.object(e.__class__.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await e.async_added_to_hass()
        assert e.native_value is None


# ── WeatherMowLawnSunFrom ─────────────────────────────────────────────────────


class TestWeatherMowLawnSunFrom:
    def test_unique_id(self):
        e = WeatherMowLawnSunFrom(_make_coordinator(), _make_entry())
        assert e.unique_id == "test_entry_lawn_sun_from"

    def test_has_entity_name(self):
        e = WeatherMowLawnSunFrom(_make_coordinator(), _make_entry())
        assert e.has_entity_name is True

    def test_default_value_is_midnight(self):
        e = WeatherMowLawnSunFrom(_make_coordinator(), _make_entry())
        assert e.native_value == dt_time(0, 0, 0)

    @pytest.mark.asyncio
    async def test_set_value(self):
        coord = _make_coordinator()
        e = WeatherMowLawnSunFrom(coord, _make_entry())
        e.async_write_ha_state = MagicMock()
        t = dt_time(7, 30, 0)
        await e.async_set_value(t)
        assert e.native_value == t
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_valid_time(self):
        e = WeatherMowLawnSunFrom(_make_coordinator(), _make_entry())
        last_state = MagicMock()
        last_state.state = "07:30:00"
        with (
            patch.object(e, "async_get_last_state", AsyncMock(return_value=last_state)),
            patch.object(e.__class__.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await e.async_added_to_hass()
        assert e.native_value == dt_time(7, 30, 0)

    @pytest.mark.asyncio
    async def test_restore_unknown_keeps_default(self):
        e = WeatherMowLawnSunFrom(_make_coordinator(), _make_entry())
        last_state = MagicMock()
        last_state.state = "unavailable"
        with (
            patch.object(e, "async_get_last_state", AsyncMock(return_value=last_state)),
            patch.object(e.__class__.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await e.async_added_to_hass()
        assert e.native_value == dt_time(0, 0, 0)

    @pytest.mark.asyncio
    async def test_restore_invalid_keeps_default(self):
        e = WeatherMowLawnSunFrom(_make_coordinator(), _make_entry())
        last_state = MagicMock()
        last_state.state = "not-a-time"
        with (
            patch.object(e, "async_get_last_state", AsyncMock(return_value=last_state)),
            patch.object(e.__class__.__bases__[0], "async_added_to_hass", AsyncMock()),
        ):
            await e.async_added_to_hass()
        assert e.native_value == dt_time(0, 0, 0)
