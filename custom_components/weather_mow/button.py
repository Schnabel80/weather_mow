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
    """Bucht die eingestellte Bewässerungsmenge auf wetness_mm.

    Workflow: Bewässerungsmenge im Slider setzen → diesen Button drücken.
    0 mm eingeben → Button drücken = Fehlbedienung rückgängig machen.
    """

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
        amount_mm = 0.0
        if self.coordinator.irrigation_amount_entity is not None:
            val = self.coordinator.irrigation_amount_entity.native_value
            if val is not None:
                amount_mm = float(val)
        self.coordinator.apply_irrigation(amount_mm)
        await self.coordinator.async_request_refresh()
