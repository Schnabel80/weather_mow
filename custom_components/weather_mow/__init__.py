"""WeatherMow — wetterabhängige Mähroboter-Steuerung."""
from __future__ import annotations

import logging

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_RAIN_PROVIDER, CONF_RAIN_SENSOR, DOMAIN, PLATFORMS
from .coordinator import WeatherMowCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migriert alte Config-Entry-Formate auf das aktuelle Schema."""
    if config_entry.version < 2:
        # v0.4.0b1: DWD-spezifische Storage-Keys → generische Namen
        key_map = {
            "dwd_weather_entity_id":    "weather_entity_id",
            "dwd_radiation_entity_id":  "radiation_forecast_entity_id",
            "dwd_precip_entity_id":     "precip_forecast_entity_id",
            "dwd_wind_entity_id":       "wind_sensor_entity_id",
        }
        new_data = {key_map.get(k, k): v for k, v in config_entry.data.items()}
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
        _LOGGER.info("weather_mow: Config Entry auf Version 2 migriert")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = WeatherMowCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    _notify_rain_reconfigure(hass, entry)
    return True


def _notify_rain_reconfigure(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Weist Bestandsnutzer auf die nötige Neukonfiguration der Regenquelle hin.

    Einträge von vor 0.3.0b10 haben einen Regensensor, aber kein 'rain_provider'.
    Ihr lokaler Sensor wird erst nach einer Neukonfiguration wieder ausgewertet.
    """
    notification_id = f"{DOMAIN}_rain_reconfigure_{entry.entry_id}"
    if entry.data.get(CONF_RAIN_SENSOR) and not entry.data.get(CONF_RAIN_PROVIDER):
        persistent_notification.async_create(
            hass,
            (
                f"Die Regenmessung von WeatherMow ({entry.title}) wurde überarbeitet. "
                "Dein lokaler Regensensor wird erst nach einer Neukonfiguration wieder "
                "ausgewertet — bis dahin läuft die Regenerkennung nur über die "
                "Wettervorhersage.\n\n"
                "Bitte öffne **Einstellungen → Geräte & Dienste → WeatherMow → "
                "Neu konfigurieren** und wähle deine Regenquelle aus."
            ),
            title="WeatherMow: Regenquelle neu konfigurieren",
            notification_id=notification_id,
        )
    else:
        persistent_notification.async_dismiss(hass, notification_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: WeatherMowCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
