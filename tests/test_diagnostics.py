"""Tests für diagnostics.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.weather_mow.diagnostics import async_get_config_entry_diagnostics


async def _run_executor(fn, *args):
    """Führt die an async_add_executor_job übergebene Funktion echt aus."""
    return fn(*args)


def _make_coordinator(data=None):
    coord = MagicMock()
    coord.data = data or {"wetness_mm": 0.3, "priority": 42}
    coord._rain_buffer = [0.0] * 144
    coord._rain_buffer[-1] = 0.5
    coord._radiation_peak = 750.0
    coord._sunshine_start_utc = None
    coord._duration_today_s = 3600.0
    coord._duration_yesterday_s = 7200.0
    coord._duration_day_before_s = 0.0
    coord._mow_start_ts = None
    coord._last_mow_allowed = False
    coord._auto_resume_blocked = False
    coord._wetness_mm = 0.3
    coord._growth_gdd_accum = 1.5
    coord._mow_since_last_gdd_reset_s = 0.0
    coord._mow_first_allowed_ts = None
    coord._hourly_precip = []
    coord._hourly_radiation = []
    coord.debug_switch_entity = None
    coord.debug_csv_path = MagicMock(return_value="/tmp/test_debug.csv")
    return coord


def _make_entry(entry_id="test_entry"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.domain = "weather_mow"
    entry.title = "Test"
    entry.version = 2
    entry.data = {"name": "Rasenmaeher", "mower_entity_id": "lawn_mower.test"}
    entry.options = {"start_delay_minutes": 5}
    entry.runtime_data = _make_coordinator()
    return entry


class TestDiagnostics:
    @pytest.mark.asyncio
    async def test_returns_dict_with_required_keys(self):
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(return_value=None)
        entry = _make_entry()
        result = await async_get_config_entry_diagnostics(hass, entry)
        assert "entry" in result
        assert "config" in result
        assert "data" in result
        assert "internal" in result
        assert "debug_csv" in result

    @pytest.mark.asyncio
    async def test_entry_section(self):
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(return_value=None)
        entry = _make_entry()
        result = await async_get_config_entry_diagnostics(hass, entry)
        assert result["entry"]["version"] == 2
        assert result["entry"]["domain"] == "weather_mow"
        assert result["entry"]["title"] == "Test"

    @pytest.mark.asyncio
    async def test_internal_section_keys(self):
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(return_value=None)
        entry = _make_entry()
        result = await async_get_config_entry_diagnostics(hass, entry)
        internal = result["internal"]
        assert "rain_buffer_len" in internal
        assert "wetness_mm" in internal
        assert "growth_gdd_accum" in internal
        assert internal["rain_buffer_len"] == 144

    @pytest.mark.asyncio
    async def test_data_serializes_datetime(self):
        import datetime

        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(return_value=None)
        coord = _make_coordinator(
            data={
                "next_mow_expected": datetime.datetime(2026, 6, 1, 10, 0, tzinfo=datetime.UTC),
                "priority": 50,
            }
        )
        entry = _make_entry()
        entry.runtime_data = coord
        result = await async_get_config_entry_diagnostics(hass, entry)
        assert result["data"]["next_mow_expected"] == "2026-06-01T10:00:00+00:00"

    @pytest.mark.asyncio
    async def test_debug_csv_none_when_no_file(self):
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(return_value=None)
        entry = _make_entry()
        result = await async_get_config_entry_diagnostics(hass, entry)
        assert result["debug_csv"] is None

    @pytest.mark.asyncio
    async def test_debug_csv_none_when_file_missing_real_exec(self, tmp_path):
        """Datei fehlt, Executor läuft echt → None (deckt den Early-Return)."""
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(side_effect=_run_executor)
        entry = _make_entry()
        missing = tmp_path / "does_not_exist.csv"
        entry.runtime_data.debug_csv_path = MagicMock(return_value=str(missing))
        result = await async_get_config_entry_diagnostics(hass, entry)
        assert result["debug_csv"] is None

    @pytest.mark.asyncio
    async def test_debug_csv_read_when_file_exists(self, tmp_path):
        """CSV-Datei vorhanden → Inhalt wird gelesen und zurückgegeben."""
        csv_file = tmp_path / "debug.csv"
        csv_file.write_text("col1,col2\n1,2\n", encoding="utf-8")
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(side_effect=_run_executor)
        entry = _make_entry()
        entry.runtime_data.debug_csv_path = MagicMock(return_value=str(csv_file))
        result = await async_get_config_entry_diagnostics(hass, entry)
        assert "col1,col2" in result["debug_csv"]

    @pytest.mark.asyncio
    async def test_debug_csv_oserror_returns_message(self, tmp_path):
        """Lesefehler (OSError) → Fehlermeldung statt Inhalt."""
        csv_file = tmp_path / "debug.csv"
        csv_file.write_text("x", encoding="utf-8")
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(side_effect=_run_executor)
        entry = _make_entry()
        entry.runtime_data.debug_csv_path = MagicMock(return_value=str(csv_file))
        with patch(
            "custom_components.weather_mow.diagnostics.open",
            create=True,
            side_effect=OSError,
        ):
            result = await async_get_config_entry_diagnostics(hass, entry)
        assert result["debug_csv"] == "Fehler beim Lesen der CSV-Datei."

    @pytest.mark.asyncio
    async def test_debug_switch_on(self):
        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(return_value=None)
        entry = _make_entry()
        entry.runtime_data.debug_switch_entity = MagicMock()
        entry.runtime_data.debug_switch_entity.is_on = True
        result = await async_get_config_entry_diagnostics(hass, entry)
        assert result["internal"]["debug_log_active"] is True
