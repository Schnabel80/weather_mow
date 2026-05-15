"""Date-Entität für das letzte Düngedatum (weather_mow)."""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WeatherMowCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WeatherMowCoordinator = hass.data[DOMAIN][entry.entry_id]
    entity = WeatherMowFertilizationDate(coordinator, entry)
    coordinator.fertilization_date_entity = entity
    async_add_entities([entity])


class WeatherMowFertilizationDate(
    CoordinatorEntity[WeatherMowCoordinator], DateEntity, RestoreEntity
):
    """Beschreibbare Datums-Entität für das letzte Düngen.

    Kann im Dashboard direkt per Date-Picker gesetzt werden.
    Der Coordinator liest den Wert für das Graswachstums-Modell (GDD-Boost).
    """

    _attr_has_entity_name = True
    _attr_name = "Last Fertilization"
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_last_fertilization"
        name = entry.data.get("name", entry.entry_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="WeatherMow",
            model="weather_mow",
        )
        self._value: date | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable", "none", ""):
            try:
                self._value = date.fromisoformat(last_state.state)
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> date | None:
        return self._value

    async def async_set_value(self, value: date) -> None:
        self._value = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
