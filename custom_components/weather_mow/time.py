"""Time-Entitäten für weather_mow."""

from __future__ import annotations

import contextlib
from datetime import time as dt_time
from typing import TYPE_CHECKING

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_LAWN_SUN_FROM, DOMAIN
from .coordinator import WeatherMowCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WeatherMowCoordinator = entry.runtime_data
    entity = WeatherMowLawnSunFrom(coordinator, entry)
    coordinator.lawn_sun_from_entity = entity
    async_add_entities([entity])


class WeatherMowLawnSunFrom(CoordinatorEntity[WeatherMowCoordinator], TimeEntity, RestoreEntity):
    """Lokale Uhrzeit, ab der die Sonne den Rasen erreicht.

    Vor dieser Uhrzeit zählt die Sonnenstrahlung NICHT für die Trocknungs-
    berechnung — typisch für Gärten mit langem Morgenschatten durch Bäume
    oder Häuser im Osten. Default 00:00 deaktiviert die Korrektur (Sonne
    zählt ab Tagesanbruch wie bisher).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "lawn_sun_from"
    _attr_icon = "mdi:weather-sunset-up"

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_lawn_sun_from"
        name = entry.data.get("name", entry.entry_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="WeatherMow",
            model="weather_mow",
        )
        self._value: dt_time = dt_time.fromisoformat(DEFAULT_LAWN_SUN_FROM)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (
            "unknown",
            "unavailable",
            "none",
            "",
        ):
            with contextlib.suppress(ValueError, TypeError):
                self._value = dt_time.fromisoformat(last_state.state)

    @property
    def native_value(self) -> dt_time | None:
        return self._value

    async def async_set_value(self, value: dt_time) -> None:
        self._value = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
