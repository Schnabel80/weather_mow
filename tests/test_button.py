"""Tests für button.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.weather_mow.button import (
    WeatherMowIrrigationApply,
    WeatherMowWetnessReset,
)


def _make_coordinator():
    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    coord.apply_irrigation = MagicMock()
    coord.reset_wetness = MagicMock()
    return coord


def _make_entry(entry_id="test_entry", name="Rasenmaeher"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name}
    return entry


class TestWeatherMowIrrigationApply:
    def test_unique_id(self):
        btn = WeatherMowIrrigationApply(_make_coordinator(), _make_entry())
        assert btn.unique_id == "test_entry_irrigation_apply"

    def test_has_entity_name(self):
        btn = WeatherMowIrrigationApply(_make_coordinator(), _make_entry())
        assert btn.has_entity_name is True

    def test_device_info_set(self):
        btn = WeatherMowIrrigationApply(_make_coordinator(), _make_entry())
        assert btn.device_info is not None

    @pytest.mark.asyncio
    async def test_press_calls_apply_and_refresh(self):
        coord = _make_coordinator()
        btn = WeatherMowIrrigationApply(coord, _make_entry())
        await btn.async_press()
        coord.apply_irrigation.assert_called_once()
        coord.async_request_refresh.assert_awaited_once()


class TestWeatherMowWetnessReset:
    def test_unique_id(self):
        btn = WeatherMowWetnessReset(_make_coordinator(), _make_entry())
        assert btn.unique_id == "test_entry_wetness_reset"

    def test_has_entity_name(self):
        btn = WeatherMowWetnessReset(_make_coordinator(), _make_entry())
        assert btn.has_entity_name is True

    @pytest.mark.asyncio
    async def test_press_calls_reset_and_refresh(self):
        coord = _make_coordinator()
        btn = WeatherMowWetnessReset(coord, _make_entry())
        await btn.async_press()
        coord.reset_wetness.assert_called_once()
        coord.async_request_refresh.assert_awaited_once()
