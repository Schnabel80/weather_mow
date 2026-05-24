"""Number-Entitäten für weather_mow."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEFAULT_LAWN_SUN_EFFICIENCY,
    DOMAIN,
    LAWN_SUN_EFFICIENCY_MAX,
    LAWN_SUN_EFFICIENCY_MIN,
    LAWN_SUN_EFFICIENCY_STEP,
)
from .coordinator import WeatherMowCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WeatherMowCoordinator = hass.data[DOMAIN][entry.entry_id]
    entity = WeatherMowLawnSunEfficiency(coordinator, entry)
    coordinator.lawn_sun_efficiency_entity = entity
    async_add_entities([entity])


class WeatherMowLawnSunEfficiency(
    CoordinatorEntity[WeatherMowCoordinator], NumberEntity, RestoreEntity
):
    """Effizienz-Faktor für die am Rasen effektiv ankommende Sonnenstrahlung.

    1.0 = freier Rasen ohne Schatten. 0.7 = leichter bis mittlerer Schatten
    (Default). 0.3 = stark verschatteter Garten. Niedrige Werte verlängern
    die geschätzte Trocknungszeit nach Regen/Bewässerung proportional.

    Beschreibbar im UI als Slider — Änderungen wirken ab dem nächsten
    5-Minuten-Update des Coordinators.
    """

    _attr_has_entity_name = True
    _attr_name = "Lawn Sun Efficiency"
    _attr_icon = "mdi:weather-sunny-alert"
    _attr_native_min_value = LAWN_SUN_EFFICIENCY_MIN
    _attr_native_max_value = LAWN_SUN_EFFICIENCY_MAX
    _attr_native_step = LAWN_SUN_EFFICIENCY_STEP
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = None  # dimensionsloser Anteil
    _attr_entity_category = None  # bewusst keine config_category → bleibt im Haupt-Dashboard

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_lawn_sun_efficiency"
        name = entry.data.get("name", entry.entry_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="WeatherMow",
            model="weather_mow",
        )
        self._value: float = DEFAULT_LAWN_SUN_EFFICIENCY

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable", "none", ""):
            try:
                value = float(last_state.state)
                # Defensiv: NaN aus korruptem Restore-State darf den Coordinator nicht vergiften
                if value == value:  # NaN-Check (NaN != NaN)
                    self._value = max(
                        LAWN_SUN_EFFICIENCY_MIN, min(LAWN_SUN_EFFICIENCY_MAX, value)
                    )
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = max(
            LAWN_SUN_EFFICIENCY_MIN, min(LAWN_SUN_EFFICIENCY_MAX, value)
        )
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
