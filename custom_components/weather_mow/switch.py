"""Switches für weather_mow."""
from __future__ import annotations

import time

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, IRRIGATION_WETNESS_BOOST
from .coordinator import WeatherMowCoordinator

_MANUAL_THRESHOLD_S = 300   # < 5 min → manueller Toggle → 30-min-Äquivalent
_IRRIGATION_REF_MIN = 30.0  # Referenzdauer für Boost-Maximum


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WeatherMowCoordinator = hass.data[DOMAIN][entry.entry_id]
    main_switch      = WeatherMowSwitch(coordinator, entry)
    emergency_switch = WeatherMowEmergencySwitch(coordinator, entry)
    irrigation_switch = WeatherMowIrrigationSwitch(coordinator, entry)
    coordinator.switch_entity            = main_switch
    coordinator.emergency_switch_entity  = emergency_switch
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
    """Bewässerungs-Schalter — schickt Mäher zur Ladestation, hebt Wetness-Score.

    Kurzer Toggle (< 5 min): 30-Minuten-Äquivalent (= IRRIGATION_WETNESS_BOOST).
    Automation (Switch bleibt an): Boost proportional zur tatsächlichen Dauer,
    maximal IRRIGATION_WETNESS_BOOST bei ≥ 30 min.
    """

    _attr_name = "Irrigation Active"
    _attr_icon = "mdi:sprinkler"
    _default_on = False

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_irrigation"
        self._turned_on_at: float | None = None

    async def async_turn_on(self, **kwargs: object) -> None:
        self._turned_on_at = time.monotonic()
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        duration_s = (
            time.monotonic() - self._turned_on_at
            if self._turned_on_at is not None
            else _MANUAL_THRESHOLD_S  # HA-Restore: Dauer unbekannt → voller Boost
        )
        self._turned_on_at = None
        self._is_on = False
        self.async_write_ha_state()

        # Boost berechnen und direkt auf den Coordinator schreiben
        if duration_s < _MANUAL_THRESHOLD_S:
            # Manueller Toggle → feste 30-Minuten-Nassmenge
            effective_min = _IRRIGATION_REF_MIN
        else:
            effective_min = max(_IRRIGATION_REF_MIN, duration_s / 60.0)

        boost = min(
            float(IRRIGATION_WETNESS_BOOST),
            IRRIGATION_WETNESS_BOOST * effective_min / _IRRIGATION_REF_MIN,
        )
        # max() statt = : mehrfaches Togglen und bereits nasser Rasen summieren sich nicht
        self.coordinator._irrigation_wetness_boost = max(
            self.coordinator._irrigation_wetness_boost, boost
        )


class WeatherMowDebugSwitch(_WeatherMowSwitchBase):
    """Debug-Log-Schalter — schreibt bei aktivem Log alle 5 Min eine CSV-Zeile."""

    _attr_name = "Debug Log"
    _attr_icon = "mdi:text-box-outline"
    _default_on = False

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_debug_log"
