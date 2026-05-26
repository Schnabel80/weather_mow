"""Button-Entitäten für weather_mow."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WeatherMowCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WeatherMowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WeatherMowIrrigationApply(coordinator, entry)])


class WeatherMowIrrigationApply(
    CoordinatorEntity[WeatherMowCoordinator], ButtonEntity
):
    """Bucht IRRIGATION_FIXED_MM (2 mm) einmalig auf wetness_mm."""

    _attr_has_entity_name = True
    _attr_translation_key = "irrigation_apply"
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_irrigation_apply"
        name = entry.data.get("name", entry.entry_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="WeatherMow",
            model="weather_mow",
        )

    async def async_press(self) -> None:
        self.coordinator.apply_irrigation()
        await self.coordinator.async_request_refresh()
