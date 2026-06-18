"""Tests für __init__.py: Setup, Unload, Migration, Reconfigure-Notify."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.weather_mow import (
    _async_update_options,
    _notify_rain_reconfigure,
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.weather_mow.const import DOMAIN


def _entry(hass, *, version=2, data=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=version,
        data=data or {"name": "Test", "weather_entity_id": "weather.test"},
        options={},
        title="Test Mow",
    )
    entry.add_to_hass(hass)
    return entry


# ── Migration ─────────────────────────────────────────────────────────────────


class TestMigration:
    async def test_migrate_v1_renames_dwd_keys(self, hass):
        """v1 → v4: DWD-Keys gemappt, precip entfernt, Regenfelder bereinigt."""
        entry = _entry(
            hass,
            version=1,
            data={
                "dwd_weather_entity_id": "weather.dwd",
                "dwd_radiation_entity_id": "sensor.rad",
                "keep_me": "x",
            },
        )
        result = await async_migrate_entry(hass, entry)
        assert result is True
        assert entry.version == 4
        assert entry.data["weather_entity_id"] == "weather.dwd"
        assert entry.data["radiation_forecast_entity_id"] == "sensor.rad"
        assert entry.data["keep_me"] == "x"
        assert "dwd_weather_entity_id" not in entry.data

    async def test_migrate_v1_dwd_precip_is_removed(self, hass):
        """v1 → v4: dwd_precip umbenannt (v2), entfernt (v3), Regenfelder bereinigt (v4)."""
        entry = _entry(
            hass,
            version=1,
            data={
                "dwd_weather_entity_id": "weather.dwd",
                "dwd_precip_entity_id": "sensor.dwd_niederschlag",
                "keep_me": "x",
            },
        )
        result = await async_migrate_entry(hass, entry)
        assert result is True
        assert entry.version == 4
        # precip_forecast_entity_id darf NICHT mehr vorhanden sein
        assert "precip_forecast_entity_id" not in entry.data
        assert "dwd_precip_entity_id" not in entry.data
        assert entry.data["weather_entity_id"] == "weather.dwd"
        assert entry.data["keep_me"] == "x"

    async def test_migrate_v2_removes_orphaned_precip(self, hass):
        """v2 → v4: precip entfernt (v3), Regenfelder bereinigt (v4)."""
        entry = _entry(
            hass,
            version=2,
            data={
                "weather_entity_id": "weather.owm",
                "precip_forecast_entity_id": "sensor.dwd_meine_niederschlag",
                "rain_provider": "ecowitt",
            },
        )
        result = await async_migrate_entry(hass, entry)
        assert result is True
        assert entry.version == 4
        assert "precip_forecast_entity_id" not in entry.data
        # Andere Felder bleiben unangetastet
        assert entry.data["weather_entity_id"] == "weather.owm"
        assert entry.data["rain_provider"] == "ecowitt"

    async def test_migrate_v3_to_v4_strips_rain_fields(self, hass):
        """v3 → v4: Verwaiste rain_1h/rain_today-Felder werden entfernt."""
        entry = _entry(
            hass,
            version=3,
            data={
                "weather_entity_id": "weather.x",
                "rain_sensor_entity_id": "sensor.daily_rain",
                "rain_1h_sensor_entity_id": "sensor.hourly",
                "rain_today_sensor_entity_id": "sensor.daily",
            },
        )
        result = await async_migrate_entry(hass, entry)
        assert result is True
        assert entry.version == 4
        assert "rain_1h_sensor_entity_id" not in entry.data
        assert "rain_today_sensor_entity_id" not in entry.data
        assert entry.data["rain_sensor_entity_id"] == "sensor.daily_rain"
        assert entry.data["weather_entity_id"] == "weather.x"

    async def test_migrate_v4_is_noop(self, hass):
        """Bereits v4 → keine Änderung, True."""
        entry = _entry(hass, version=4, data={"weather_entity_id": "weather.x"})
        result = await async_migrate_entry(hass, entry)
        assert result is True
        assert entry.version == 4
        assert entry.data["weather_entity_id"] == "weather.x"


# ── Setup / Unload ────────────────────────────────────────────────────────────


class TestSetupUnload:
    async def test_setup_entry_success(self, hass):
        """Setup baut Coordinator, setzt runtime_data, forwarded Plattformen."""
        entry = _entry(hass)
        coord = MagicMock()
        coord.async_config_entry_first_refresh = AsyncMock()
        with (
            patch(
                "custom_components.weather_mow.WeatherMowCoordinator",
                return_value=coord,
            ),
            patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()) as fwd,
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        assert entry.runtime_data is coord
        coord.async_config_entry_first_refresh.assert_awaited_once()
        fwd.assert_awaited_once()

    async def test_unload_entry_calls_shutdown(self, hass):
        """Erfolgreiches Unload → async_shutdown des Coordinators."""
        entry = _entry(hass)
        coord = MagicMock()
        coord.async_shutdown = AsyncMock()
        entry.runtime_data = coord
        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            AsyncMock(return_value=True),
        ):
            result = await async_unload_entry(hass, entry)

        assert result is True
        coord.async_shutdown.assert_awaited_once()

    async def test_unload_entry_failed_no_shutdown(self, hass):
        """Unload schlägt fehl → kein Shutdown, False."""
        entry = _entry(hass)
        coord = MagicMock()
        coord.async_shutdown = AsyncMock()
        entry.runtime_data = coord
        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            AsyncMock(return_value=False),
        ):
            result = await async_unload_entry(hass, entry)

        assert result is False
        coord.async_shutdown.assert_not_awaited()

    async def test_update_options_reloads(self, hass):
        """Options-Update → Entry wird neu geladen."""
        entry = _entry(hass)
        with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
            await _async_update_options(hass, entry)
        reload.assert_awaited_once_with(entry.entry_id)


# ── Reconfigure-Notify ────────────────────────────────────────────────────────


class TestRainReconfigureNotify:
    async def test_notify_created_when_sensor_without_provider(self, hass):
        """Regensensor ohne Provider → persistente Benachrichtigung erstellt."""
        entry = _entry(
            hass,
            data={
                "name": "Test",
                "rain_sensor_entity_id": "sensor.rain",
            },
        )
        with patch("custom_components.weather_mow.persistent_notification.async_create") as create:
            _notify_rain_reconfigure(hass, entry)
        create.assert_called_once()

    async def test_notify_dismissed_when_provider_present(self, hass):
        """Provider vorhanden → Benachrichtigung wird entfernt (nicht erstellt)."""
        entry = _entry(
            hass,
            data={
                "name": "Test",
                "rain_sensor_entity_id": "sensor.rain",
                "rain_provider": "ecowitt",
            },
        )
        with (
            patch("custom_components.weather_mow.persistent_notification.async_create") as create,
            patch(
                "custom_components.weather_mow.persistent_notification.async_dismiss"
            ) as dismiss,
        ):
            _notify_rain_reconfigure(hass, entry)
        create.assert_not_called()
        dismiss.assert_called_once()
