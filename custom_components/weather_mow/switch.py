"""Switches für weather_mow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WeatherMowCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WeatherMowCoordinator = hass.data[DOMAIN][entry.entry_id]
    main_switch = WeatherMowSwitch(coordinator, entry)
    emergency_switch = WeatherMowEmergencySwitch(coordinator, entry)
    irrigation_switch = WeatherMowIrrigationSwitch(coordinator, entry)
    coordinator.switch_entity = main_switch
    coordinator.emergency_switch_entity = emergency_switch
    coordinator.irrigation_switch_entity = irrigation_switch
    debug_switch = WeatherMowDebugSwitch(coordinator, entry)
    coordinator.debug_switch_entity = debug_switch
    async_add_entities([main_switch, emergency_switch, irrigation_switch, debug_switch])


class _WeatherMowSwitchBase(CoordinatorEntity[WeatherMowCoordinator], SwitchEntity, RestoreEntity):
    """Gemeinsame Basis für alle weather_mow Switches."""

    _attr_has_entity_name = True
    _default_on: bool = True

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        name = entry.data.get("name", entry.entry_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="WeatherMow",
            model="weather_mow",
        )
        self._is_on: bool = self._default_on

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == STATE_ON

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: object) -> None:
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        self._is_on = False
        self.async_write_ha_state()


class WeatherMowSwitch(_WeatherMowSwitchBase):
    """Hauptschalter — bei OFF wird kein Mähen empfohlen."""

    _attr_name = "Enabled"
    _attr_icon = "mdi:robot-mower"

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_enabled"


class WeatherMowEmergencySwitch(_WeatherMowSwitchBase):
    """Notmäh-Schalter — aktiviert zusätzliche Mähsession bei Regenprognose."""

    _attr_name = "Emergency Mow"
    _attr_icon = "mdi:weather-lightning-rainy"
    _default_on = True

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_emergency_mow"


class WeatherMowIrrigationSwitch(_WeatherMowSwitchBase):
    """Bewässerungs-Schalter — schickt Mäher zur Ladestation.

    Wetness wird in v0.4 nicht mehr hier gebucht, sondern über den
    irrigation_apply-Button und apply_irrigation() im Coordinator.
    """

    _attr_name = "Irrigation Active"
    _attr_icon = "mdi:sprinkler"
    _default_on = False

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_irrigation"


class WeatherMowDebugSwitch(_WeatherMowSwitchBase):
    """Debug-Log-Schalter — schreibt bei aktivem Log alle 5 Min eine CSV-Zeile."""

    _attr_name = "Debug Log"
    _attr_icon = "mdi:text-box-outline"
    _default_on = False

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_debug_log"
