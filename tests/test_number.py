"""Tests für number.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.weather_mow.const import (
    DEFAULT_LAWN_SUN_EFFICIENCY,
    DEFAULT_MAX_TEMP_C,
    DEFAULT_MOW_THRESHOLD_MM,
    DEFAULT_MOW_THRESHOLD_URGENT_MM,
    LAWN_SUN_EFFICIENCY_MAX,
    LAWN_SUN_EFFICIENCY_MIN,
    MAX_TEMP_MAX_C,
    MAX_TEMP_MIN_C,
    MOW_THRESHOLD_MAX_MM,
    MOW_THRESHOLD_MIN_MM,
    MOW_THRESHOLD_URGENT_MAX_MM,
)
from custom_components.weather_mow.number import (
    WeatherMowLawnSunEfficiency,
    WeatherMowMaxTempC,
    WeatherMowMowThreshold,
    WeatherMowUrgentThreshold,
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


# ── Helper für Restore-Tests ──────────────────────────────────────────────────


async def _restore(entity, state_str):
    last_state = MagicMock()
    last_state.state = state_str
    parent = entity.__class__.__bases__[0]
    with (
        patch.object(entity, "async_get_last_state", AsyncMock(return_value=last_state)),
        patch.object(parent, "async_added_to_hass", AsyncMock()),
    ):
        await entity.async_added_to_hass()


async def _restore_none(entity):
    parent = entity.__class__.__bases__[0]
    with (
        patch.object(entity, "async_get_last_state", AsyncMock(return_value=None)),
        patch.object(parent, "async_added_to_hass", AsyncMock()),
    ):
        await entity.async_added_to_hass()


# ── WeatherMowLawnSunEfficiency ───────────────────────────────────────────────


class TestLawnSunEfficiency:
    def test_unique_id(self):
        e = WeatherMowLawnSunEfficiency(_make_coordinator(), _make_entry())
        assert e.unique_id == "test_entry_lawn_sun_efficiency"

    def test_default_value(self):
        e = WeatherMowLawnSunEfficiency(_make_coordinator(), _make_entry())
        assert e.native_value == DEFAULT_LAWN_SUN_EFFICIENCY

    @pytest.mark.asyncio
    async def test_set_value(self):
        coord = _make_coordinator()
        e = WeatherMowLawnSunEfficiency(coord, _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(0.5)
        assert e.native_value == 0.5
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_value_clamped_to_max(self):
        e = WeatherMowLawnSunEfficiency(_make_coordinator(), _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(99.0)
        assert e.native_value == LAWN_SUN_EFFICIENCY_MAX

    @pytest.mark.asyncio
    async def test_set_value_clamped_to_min(self):
        e = WeatherMowLawnSunEfficiency(_make_coordinator(), _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(-1.0)
        assert e.native_value == LAWN_SUN_EFFICIENCY_MIN

    @pytest.mark.asyncio
    async def test_restore_valid(self):
        e = WeatherMowLawnSunEfficiency(_make_coordinator(), _make_entry())
        await _restore(e, "0.4")
        assert e.native_value == 0.4

    @pytest.mark.asyncio
    async def test_restore_unknown_keeps_default(self):
        e = WeatherMowLawnSunEfficiency(_make_coordinator(), _make_entry())
        await _restore(e, "unknown")
        assert e.native_value == DEFAULT_LAWN_SUN_EFFICIENCY

    @pytest.mark.asyncio
    async def test_restore_none_keeps_default(self):
        e = WeatherMowLawnSunEfficiency(_make_coordinator(), _make_entry())
        await _restore_none(e)
        assert e.native_value == DEFAULT_LAWN_SUN_EFFICIENCY

    @pytest.mark.asyncio
    async def test_restore_out_of_range_clamped(self):
        e = WeatherMowLawnSunEfficiency(_make_coordinator(), _make_entry())
        await _restore(e, "99.9")
        assert e.native_value == LAWN_SUN_EFFICIENCY_MAX

    @pytest.mark.asyncio
    async def test_restore_invalid_keeps_default(self):
        e = WeatherMowLawnSunEfficiency(_make_coordinator(), _make_entry())
        await _restore(e, "garbage")
        assert e.native_value == DEFAULT_LAWN_SUN_EFFICIENCY


# ── WeatherMowMowThreshold ────────────────────────────────────────────────────


class TestMowThreshold:
    def test_unique_id(self):
        e = WeatherMowMowThreshold(_make_coordinator(), _make_entry())
        assert e.unique_id == "test_entry_mow_threshold_mm"

    def test_default_value(self):
        e = WeatherMowMowThreshold(_make_coordinator(), _make_entry())
        assert e.native_value == DEFAULT_MOW_THRESHOLD_MM

    @pytest.mark.asyncio
    async def test_set_value(self):
        coord = _make_coordinator()
        e = WeatherMowMowThreshold(coord, _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(1.2)
        assert e.native_value == 1.2

    @pytest.mark.asyncio
    async def test_set_value_clamped(self):
        e = WeatherMowMowThreshold(_make_coordinator(), _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(100.0)
        assert e.native_value == MOW_THRESHOLD_MAX_MM

    @pytest.mark.asyncio
    async def test_set_value_min_clamp(self):
        e = WeatherMowMowThreshold(_make_coordinator(), _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(0.0)
        assert e.native_value == MOW_THRESHOLD_MIN_MM

    @pytest.mark.asyncio
    async def test_restore_valid(self):
        e = WeatherMowMowThreshold(_make_coordinator(), _make_entry())
        await _restore(e, "0.8")
        assert e.native_value == 0.8

    @pytest.mark.asyncio
    async def test_restore_invalid_keeps_default(self):
        e = WeatherMowMowThreshold(_make_coordinator(), _make_entry())
        await _restore(e, "not_a_number")
        assert e.native_value == DEFAULT_MOW_THRESHOLD_MM


# ── WeatherMowUrgentThreshold ─────────────────────────────────────────────────


class TestUrgentThreshold:
    def test_unique_id(self):
        e = WeatherMowUrgentThreshold(_make_coordinator(), _make_entry())
        assert e.unique_id == "test_entry_mow_threshold_urgent_mm"

    def test_default_value(self):
        e = WeatherMowUrgentThreshold(_make_coordinator(), _make_entry())
        assert e.native_value == DEFAULT_MOW_THRESHOLD_URGENT_MM

    @pytest.mark.asyncio
    async def test_set_and_clamp(self):
        e = WeatherMowUrgentThreshold(_make_coordinator(), _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(999.0)
        assert e.native_value == MOW_THRESHOLD_URGENT_MAX_MM

    @pytest.mark.asyncio
    async def test_restore_valid(self):
        e = WeatherMowUrgentThreshold(_make_coordinator(), _make_entry())
        await _restore(e, "2.0")
        assert e.native_value == 2.0

    @pytest.mark.asyncio
    async def test_restore_invalid_keeps_default(self):
        e = WeatherMowUrgentThreshold(_make_coordinator(), _make_entry())
        await _restore(e, "garbage")
        assert e.native_value == DEFAULT_MOW_THRESHOLD_URGENT_MM


# ── WeatherMowMaxTempC ────────────────────────────────────────────────────────


class TestMaxTempC:
    def test_unique_id(self):
        e = WeatherMowMaxTempC(_make_coordinator(), _make_entry())
        assert e.unique_id == "test_entry_max_mow_temp_c"

    def test_default_value(self):
        e = WeatherMowMaxTempC(_make_coordinator(), _make_entry())
        assert e.native_value == DEFAULT_MAX_TEMP_C

    @pytest.mark.asyncio
    async def test_set_value(self):
        coord = _make_coordinator()
        e = WeatherMowMaxTempC(coord, _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(38.0)
        assert e.native_value == 38.0
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_value_clamped_to_max(self):
        e = WeatherMowMaxTempC(_make_coordinator(), _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(99.0)
        assert e.native_value == MAX_TEMP_MAX_C

    @pytest.mark.asyncio
    async def test_set_value_clamped_to_min(self):
        e = WeatherMowMaxTempC(_make_coordinator(), _make_entry())
        e.async_write_ha_state = MagicMock()
        await e.async_set_native_value(10.0)
        assert e.native_value == MAX_TEMP_MIN_C

    @pytest.mark.asyncio
    async def test_restore_valid(self):
        e = WeatherMowMaxTempC(_make_coordinator(), _make_entry())
        await _restore(e, "38.0")
        assert e.native_value == 38.0

    @pytest.mark.asyncio
    async def test_restore_unknown_keeps_default(self):
        e = WeatherMowMaxTempC(_make_coordinator(), _make_entry())
        await _restore(e, "unavailable")
        assert e.native_value == DEFAULT_MAX_TEMP_C

    @pytest.mark.asyncio
    async def test_restore_out_of_range_clamped(self):
        e = WeatherMowMaxTempC(_make_coordinator(), _make_entry())
        await _restore(e, "99.0")
        assert e.native_value == MAX_TEMP_MAX_C

    @pytest.mark.asyncio
    async def test_restore_invalid_keeps_default(self):
        e = WeatherMowMaxTempC(_make_coordinator(), _make_entry())
        await _restore(e, "garbage")
        assert e.native_value == DEFAULT_MAX_TEMP_C
