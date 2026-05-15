"""Sensoren für weather_mow."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WeatherMowCoordinator


@dataclass(frozen=True)
class WeatherMowSensorDescription(SensorEntityDescription):
    data_key: str = ""


SENSOR_DESCRIPTIONS: tuple[WeatherMowSensorDescription, ...] = (
    WeatherMowSensorDescription(
        key="wetness_score",
        data_key="wetness_score",
        name="Wetness Score",
        icon="mdi:water-percent",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="priority",
        data_key="priority",
        name="Priority",
        icon="mdi:speedometer",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="duration_today_h",
        data_key="duration_today_h",
        name="Duration Today",
        icon="mdi:timer",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="duration_avg_3d_h",
        data_key="duration_avg_3d_h",
        name="Duration Avg 3d",
        icon="mdi:timer-outline",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="rain_last_1h_mm",
        data_key="rain_last_1h_mm",
        name="Rain Last 1h",
        icon="mdi:weather-rainy",
        native_unit_of_measurement="mm",
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="rain_weighted_12h",
        data_key="rain_weighted_12h",
        name="Rain Weighted 12h",
        icon="mdi:weather-pouring",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="rain_today_mm",
        data_key="rain_today_mm",
        name="Rain Today Total",
        icon="mdi:weather-rainy",
        native_unit_of_measurement="mm",
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="rain_today_remaining",
        data_key="rain_today_remaining",
        name="Rain Today Remaining",
        icon="mdi:weather-rainy",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="rain_tomorrow",
        data_key="rain_tomorrow",
        name="Rain Tomorrow",
        icon="mdi:weather-rainy",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="radiation_peak",
        data_key="radiation_peak",
        name="Solar Peak",
        icon="mdi:weather-sunny",
        native_unit_of_measurement="W/m²",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="dew_point",
        data_key="dew_point",
        name="Dew Point",
        icon="mdi:thermometer-water",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="block_reason",
        data_key="block_reason",
        name="Block Reason",
        icon="mdi:information",
    ),
    WeatherMowSensorDescription(
        key="growth_mm",
        data_key="growth_mm",
        name="Grass Growth",
        icon="mdi:grass",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    WeatherMowSensorDescription(
        key="next_mow_expected",
        data_key="next_mow_expected",
        name="Next Mow Expected",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WeatherMowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        WeatherMowSensor(coordinator, entry, desc)
        for desc in SENSOR_DESCRIPTIONS
    )


class WeatherMowSensor(CoordinatorEntity[WeatherMowCoordinator], SensorEntity):
    """Ein Sensor der weather_mow Integration."""

    _attr_has_entity_name = True
    entity_description: WeatherMowSensorDescription

    def __init__(
        self,
        coordinator: WeatherMowCoordinator,
        entry: ConfigEntry,
        description: WeatherMowSensorDescription,
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
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)
