"""Number-Entitäten für weather_mow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEFAULT_LAWN_SUN_EFFICIENCY,
    DEFAULT_MOW_THRESHOLD_MM,
    DEFAULT_MOW_THRESHOLD_URGENT_MM,
    DOMAIN,
    LAWN_SUN_EFFICIENCY_MAX,
    LAWN_SUN_EFFICIENCY_MIN,
    LAWN_SUN_EFFICIENCY_STEP,
    MOW_THRESHOLD_MAX_MM,
    MOW_THRESHOLD_MIN_MM,
    MOW_THRESHOLD_STEP_MM,
    MOW_THRESHOLD_URGENT_MAX_MM,
    MOW_THRESHOLD_URGENT_MIN_MM,
    MOW_THRESHOLD_URGENT_STEP_MM,
)
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
    coordinator: WeatherMowCoordinator = entry.runtime_data

    sun_eff = WeatherMowLawnSunEfficiency(coordinator, entry)
    coordinator.lawn_sun_efficiency_entity = sun_eff

    mow_thresh = WeatherMowMowThreshold(coordinator, entry)
    coordinator.mow_threshold_entity = mow_thresh

    mow_thresh_urgent = WeatherMowUrgentThreshold(coordinator, entry)
    coordinator.mow_threshold_urgent_entity = mow_thresh_urgent

    async_add_entities([sun_eff, mow_thresh, mow_thresh_urgent])


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
    _attr_translation_key = "lawn_sun_efficiency"
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
        if last_state and last_state.state not in (
            "unknown",
            "unavailable",
            "none",
            "",
        ):
            try:
                value = float(last_state.state)
                # Defensiv: NaN aus korruptem Restore-State darf den Coordinator nicht vergiften
                if value == value:  # NaN-Check (NaN != NaN)
                    self._value = max(
                        LAWN_SUN_EFFICIENCY_MIN,
                        min(LAWN_SUN_EFFICIENCY_MAX, value),
                    )
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = max(LAWN_SUN_EFFICIENCY_MIN, min(LAWN_SUN_EFFICIENCY_MAX, value))
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class WeatherMowMowThreshold(
    CoordinatorEntity[WeatherMowCoordinator], NumberEntity, RestoreEntity
):
    """Erlaubte Restfeuchte zum Mähstart in mm (0.1–3.0, Default 0.5)."""

    _attr_has_entity_name = True
    _attr_translation_key = "mow_threshold_mm"
    _attr_icon = "mdi:water-percent"
    _attr_native_min_value = MOW_THRESHOLD_MIN_MM
    _attr_native_max_value = MOW_THRESHOLD_MAX_MM
    _attr_native_step = MOW_THRESHOLD_STEP_MM
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "mm"
    _attr_entity_category = None

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_mow_threshold_mm"
        name = entry.data.get("name", entry.entry_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="WeatherMow",
            model="weather_mow",
        )
        self._value: float = DEFAULT_MOW_THRESHOLD_MM

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (
            "unknown",
            "unavailable",
            "none",
            "",
        ):
            try:
                value = float(last_state.state)
                if value == value:  # NaN-Check
                    self._value = max(MOW_THRESHOLD_MIN_MM, min(MOW_THRESHOLD_MAX_MM, value))
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = max(MOW_THRESHOLD_MIN_MM, min(MOW_THRESHOLD_MAX_MM, value))
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class WeatherMowUrgentThreshold(
    CoordinatorEntity[WeatherMowCoordinator], NumberEntity, RestoreEntity
):
    """Feuchte-Schwelle bei Dringlichkeit (Zeitdruck oder Notmähen)."""

    _attr_has_entity_name = True
    _attr_translation_key = "mow_threshold_urgent_mm"
    _attr_icon = "mdi:water-alert"
    _attr_native_min_value = MOW_THRESHOLD_URGENT_MIN_MM
    _attr_native_max_value = MOW_THRESHOLD_URGENT_MAX_MM
    _attr_native_step = MOW_THRESHOLD_URGENT_STEP_MM
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "mm"
    _attr_entity_category = None

    def __init__(self, coordinator: WeatherMowCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_mow_threshold_urgent_mm"
        name = entry.data.get("name", entry.entry_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="WeatherMow",
            model="weather_mow",
        )
        self._value: float = DEFAULT_MOW_THRESHOLD_URGENT_MM

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (
            "unknown",
            "unavailable",
            "none",
            "",
        ):
            try:
                value = float(last_state.state)
                if value == value:  # NaN-Check
                    self._value = max(
                        MOW_THRESHOLD_URGENT_MIN_MM,
                        min(MOW_THRESHOLD_URGENT_MAX_MM, value),
                    )
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = max(
            MOW_THRESHOLD_URGENT_MIN_MM,
            min(MOW_THRESHOLD_URGENT_MAX_MM, value),
        )
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
