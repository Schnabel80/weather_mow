"""Binärsensoren für weather_mow."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WeatherMowCoordinator


@dataclass(frozen=True)
class WeatherMowBinarySensorDescription(BinarySensorEntityDescription):
    data_key: str = ""


BINARY_SENSOR_DESCRIPTIONS: tuple[WeatherMowBinarySensorDescription, ...] = (
    WeatherMowBinarySensorDescription(
        key="mow_allowed",
        data_key="mow_allowed",
        name="Allowed",
        icon="mdi:check-circle",
    ),
    WeatherMowBinarySensorDescription(
        key="start_now",
        data_key="start_now",
        name="Start Now",
        icon="mdi:robot-mower",
    ),
    WeatherMowBinarySensorDescription(
        key="stop_now",
        data_key="stop_now",
        name="Stop Now",
        icon="mdi:robot-mower-off",
    ),
    WeatherMowBinarySensorDescription(
        key="emergency_mow_active",
        data_key="emergency_mow_active",
        name="Emergency Mow",
        icon="mdi:alert",
    ),
    WeatherMowBinarySensorDescription(
        key="raining",
        data_key="raining",
        name="Raining",
        device_class=BinarySensorDeviceClass.MOISTURE,
        icon="mdi:weather-rainy",
    ),
    WeatherMowBinarySensorDescription(
        key="dew_present",
        data_key="dew_present",
        name="Dew Present",
        icon="mdi:water-outline",
    ),
    WeatherMowBinarySensorDescription(
        key="brightness_ok",
        data_key="brightness_ok",
        name="Brightness OK",
        device_class=BinarySensorDeviceClass.LIGHT,
        icon="mdi:brightness-6",
    ),
    WeatherMowBinarySensorDescription(
        key="auto_resume_blocked",
        data_key="auto_resume_blocked",
        name="Auto Resume Blocked",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:robot-mower-outline",
    ),
    WeatherMowBinarySensorDescription(
        key="irrigation_active",
        data_key="irrigation_active",
        name="Irrigation Active",
        device_class=BinarySensorDeviceClass.MOISTURE,
        icon="mdi:sprinkler",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WeatherMowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        WeatherMowBinarySensor(coordinator, entry, desc)
        for desc in BINARY_SENSOR_DESCRIPTIONS
    )


class WeatherMowBinarySensor(CoordinatorEntity[WeatherMowCoordinator], BinarySensorEntity):
    """Ein Binärsensor der weather_mow Integration."""

    _attr_has_entity_name = True
    entity_description: WeatherMowBinarySensorDescription

    def __init__(
        self,
        coordinator: WeatherMowCoordinator,
        entry: ConfigEntry,
        description: WeatherMowBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        name = entry.data.get("name", entry.entry_id)
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="WeatherMow",
            model="weather_mow",
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self.entity_description.data_key)
        if val is None:
            return None
        return bool(val)
