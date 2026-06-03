"""Config Flow und Options Flow für weather_mow."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_SENSOR,
    CONF_BRIGHTNESS,
    CONF_FULL_CYCLE_H,
    CONF_HUMIDITY,
    CONF_LAST_FERTILIZATION,
    CONF_LOCAL_RADIATION,
    CONF_MAX_GROWTH_MM,
    CONF_MIN_BATTERY_PCT,
    CONF_MIN_BRIGHTNESS,
    CONF_MIN_SUN_H_FOR_DEW,
    CONF_MOW_END,
    CONF_MOW_START,
    CONF_MOWER_ENTITY,
    CONF_PREVENT_AUTO_RESUME,
    CONF_PV_PEAK_KW,
    CONF_PV_POWER,
    CONF_RADIATION_SOURCE,
    CONF_RAIN_1H,
    CONF_RAIN_DETECTOR,
    CONF_RAIN_PROVIDER,
    CONF_RAIN_SENSOR,
    CONF_RAIN_SENSOR_TYPE,
    CONF_RAIN_TODAY,
    CONF_START_DELAY_MIN,
    CONF_TARGET_BUFFER_H,
    CONF_TARGET_DAILY_H,
    CONF_TEMP,
    CONF_THRESH_DEW_OFFSET,
    CONF_THRESH_EMERG_H,
    CONF_THRESH_RAIN_TMRW,
    CONF_THRESH_RAIN_TODAY,
    CONF_THRESH_WETNESS,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    DEFAULT_FULL_CYCLE_H,
    DEFAULT_MAX_GROWTH_MM,
    DEFAULT_MIN_BATTERY,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MIN_SUN_H_FOR_DEW,
    DEFAULT_MOW_END,
    DEFAULT_MOW_START,
    DEFAULT_NAME,
    DEFAULT_PREVENT_AUTO_RESUME,
    DEFAULT_PV_PEAK_KW,
    DEFAULT_START_DELAY_MIN,
    DEFAULT_TARGET_BUFFER_H,
    DEFAULT_TARGET_DAILY_H,
    DEFAULT_THRESH_DEW_OFFSET,
    DEFAULT_THRESH_EMERG_H,
    DEFAULT_THRESH_RAIN_TMRW,
    DEFAULT_THRESH_RAIN_TODAY,
    DEFAULT_THRESH_WETNESS,
    DOMAIN,
    RADIATION_SOURCE_PV,
    RADIATION_SOURCE_SUN,
)
from .rain_input import (
    DEFAULT_RAIN_PROVIDER,
    RAIN_MODE_CUMULATIVE,
    RAIN_MODE_INTERVAL,
    RAIN_MODE_RATE,
    RAIN_PROVIDER_ECOWITT,
    RAIN_PROVIDER_NETATMO,
    RAIN_PROVIDER_NONE,
    RAIN_PROVIDER_OTHER,
)

_LOGGER = logging.getLogger(__name__)


def _with_default(data: dict, key: str, fallback: Any = vol.UNDEFINED) -> dict:
    """Return a dict with 'default' set if a value exists in data, otherwise use fallback."""
    val = data.get(key)
    if val is not None:
        return {"default": val}
    return {} if fallback is vol.UNDEFINED else {"default": fallback}


def _mow_times_schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_MOW_START,
                default=defaults.get(CONF_MOW_START, DEFAULT_MOW_START),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_MOW_END,
                default=defaults.get(CONF_MOW_END, DEFAULT_MOW_END),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_TARGET_DAILY_H,
                default=defaults.get(CONF_TARGET_DAILY_H, DEFAULT_TARGET_DAILY_H),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=12.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_FULL_CYCLE_H,
                default=defaults.get(CONF_FULL_CYCLE_H, DEFAULT_FULL_CYCLE_H),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=8.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_TARGET_BUFFER_H,
                default=defaults.get(CONF_TARGET_BUFFER_H, DEFAULT_TARGET_BUFFER_H),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    max=4.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_THRESH_WETNESS,
                default=defaults.get(CONF_THRESH_WETNESS, DEFAULT_THRESH_WETNESS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10,
                    max=80,
                    step=5,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_THRESH_RAIN_TODAY,
                default=defaults.get(CONF_THRESH_RAIN_TODAY, DEFAULT_THRESH_RAIN_TODAY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    max=30.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_THRESH_RAIN_TMRW,
                default=defaults.get(CONF_THRESH_RAIN_TMRW, DEFAULT_THRESH_RAIN_TMRW),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0,
                    max=50.0,
                    step=1.0,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_THRESH_EMERG_H,
                default=defaults.get(CONF_THRESH_EMERG_H, DEFAULT_THRESH_EMERG_H),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=6.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_THRESH_DEW_OFFSET,
                default=defaults.get(CONF_THRESH_DEW_OFFSET, DEFAULT_THRESH_DEW_OFFSET),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=10.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_MIN_SUN_H_FOR_DEW,
                default=defaults.get(CONF_MIN_SUN_H_FOR_DEW, DEFAULT_MIN_SUN_H_FOR_DEW),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=4.0,
                    step=0.5,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_LAST_FERTILIZATION,
                default=defaults.get(CONF_LAST_FERTILIZATION, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.DATE)
            ),
            vol.Required(
                CONF_MAX_GROWTH_MM,
                default=defaults.get(CONF_MAX_GROWTH_MM, DEFAULT_MAX_GROWTH_MM),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10,
                    max=40,
                    step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_START_DELAY_MIN,
                description={
                    "suggested_value": defaults.get(CONF_START_DELAY_MIN, DEFAULT_START_DELAY_MIN)
                },
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=120,
                    step=5,
                    unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_PREVENT_AUTO_RESUME,
                default=defaults.get(CONF_PREVENT_AUTO_RESUME, DEFAULT_PREVENT_AUTO_RESUME),
            ): selector.BooleanSelector(),
        }
    )


class WeatherMowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """5-stufiger Config Flow für weather_mow."""

    VERSION = 3

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._is_reconfigure: bool = False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> WeatherMowOptionsFlow:
        return WeatherMowOptionsFlow()

    # ── Reconfigure ───────────────────────────────────────────────────────────

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Einstiegspunkt für Neu-Konfiguration — läuft Schritte 1–5 mit vorausgefüllten Werten."""
        self._is_reconfigure = True
        entry = self._get_reconfigure_entry()
        self._data = dict(entry.data)
        return await self.async_step_device()

    def _finish_reconfigure(self) -> config_entries.FlowResult:
        """Speichert geänderte Entitäten und lädt die Integration neu.

        self._data startet als vollständige Kopie von entry.data und wird über
        alle Schritte aktualisiert (inkl. _clear_station_keys, das entfernte
        Sensoren herausnimmt). Daher self._data direkt speichern — ein erneutes
        Mergen über entry.data würde gelöschte Keys wieder einfügen.
        """
        entry = self._get_reconfigure_entry()
        return self.async_update_reload_and_abort(
            entry,
            data=dict(self._data),
        )

    # ── Schritt 1: Gerät ──────────────────────────────────────────────────────

    async def async_step_user(self, user_input: dict | None = None) -> config_entries.FlowResult:
        return await self.async_step_device(user_input)

    async def async_step_device(self, user_input: dict | None = None) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input["name"].strip()
            if not self._is_reconfigure:
                await self.async_set_unique_id(name.lower())
                self._abort_if_unique_id_configured()
            self._data.update(user_input)
            self._data["name"] = name
            return await self.async_step_weather()

        d = self._data
        schema = vol.Schema(
            {
                vol.Required("name", default=d.get("name", DEFAULT_NAME)): selector.TextSelector(),
                vol.Required(
                    CONF_MOWER_ENTITY,
                    **_with_default(d, CONF_MOWER_ENTITY),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="lawn_mower")),
                vol.Optional(
                    CONF_BATTERY_SENSOR,
                    description={"suggested_value": d.get(CONF_BATTERY_SENSOR)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_MIN_BATTERY_PCT,
                    **_with_default(d, CONF_MIN_BATTERY_PCT, DEFAULT_MIN_BATTERY),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50,
                        max=100,
                        step=5,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="device", data_schema=schema, errors=errors)

    # ── Schritt 2: Wettervorhersage ───────────────────────────────────────────────

    async def async_step_weather(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Schritt 2: Wettervorhersage-Entität (OWM, DWD, Met.no, …)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_station()

        d = self._data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_WEATHER_ENTITY,
                    **_with_default(d, CONF_WEATHER_ENTITY),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="weather")),
            }
        )
        return self.async_show_form(step_id="weather", data_schema=schema)

    # ── Schritt 3: Stationstyp ────────────────────────────────────────────────────

    def _clear_station_keys(self) -> None:
        """Verwirft alle stations-abhängigen Sensor-Keys beim Wechsel des Stationstyps."""
        for key in (
            CONF_RAIN_SENSOR,
            CONF_RAIN_1H,
            CONF_RAIN_TODAY,
            CONF_RAIN_DETECTOR,
            CONF_RAIN_SENSOR_TYPE,
            CONF_TEMP,
            CONF_HUMIDITY,
            CONF_WIND_SENSOR,
            CONF_LOCAL_RADIATION,
            CONF_BRIGHTNESS,
        ):
            self._data.pop(key, None)

    async def async_step_station(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Schritt 3a: Welche lokale Wetterstation ist vorhanden?"""
        if user_input is not None:
            provider = user_input[CONF_RAIN_PROVIDER]
            self._data[CONF_RAIN_PROVIDER] = provider
            if provider == RAIN_PROVIDER_ECOWITT:
                return await self.async_step_station_ecowitt()
            if provider == RAIN_PROVIDER_NETATMO:
                return await self.async_step_station_netatmo()
            if provider == RAIN_PROVIDER_OTHER:
                return await self.async_step_station_other()
            return await self.async_step_station_none()

        d = self._data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RAIN_PROVIDER,
                    default=d.get(CONF_RAIN_PROVIDER, DEFAULT_RAIN_PROVIDER),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=RAIN_PROVIDER_ECOWITT,
                                label="Ecowitt-Wetterstation (WS90, WH65, …)",
                            ),
                            selector.SelectOptionDict(
                                value=RAIN_PROVIDER_NETATMO,
                                label="Netatmo-Station",
                            ),
                            selector.SelectOptionDict(
                                value=RAIN_PROVIDER_OTHER,
                                label="Andere lokale Wetterstation",
                            ),
                            selector.SelectOptionDict(
                                value=RAIN_PROVIDER_NONE,
                                label="Keine lokale Wetterstation",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="station", data_schema=schema)

    async def async_step_station_ecowitt(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Schritt 3b: Ecowitt — Regen, Temp/Feuchte, Wind, Strahlung, Helligkeit."""
        if user_input is not None:
            self._clear_station_keys()
            self._data.update(user_input)
            if self._data.get(CONF_LOCAL_RADIATION):
                if self._is_reconfigure:
                    return self._finish_reconfigure()
                return await self.async_step_mow_times()
            return await self.async_step_radiation_fallback()

        d = self._data
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_RAIN_SENSOR,
                    description={"suggested_value": d.get(CONF_RAIN_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", integration="ecowitt")
                ),
                vol.Optional(
                    CONF_RAIN_1H,
                    description={"suggested_value": d.get(CONF_RAIN_1H)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", integration="ecowitt")
                ),
                vol.Optional(
                    CONF_RAIN_TODAY,
                    description={"suggested_value": d.get(CONF_RAIN_TODAY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", integration="ecowitt")
                ),
                vol.Optional(
                    CONF_RAIN_DETECTOR,
                    description={"suggested_value": d.get(CONF_RAIN_DETECTOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "binary_sensor"],
                        integration="ecowitt",
                    )
                ),
                vol.Optional(
                    CONF_TEMP,
                    description={"suggested_value": d.get(CONF_TEMP)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_HUMIDITY,
                    description={"suggested_value": d.get(CONF_HUMIDITY)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_WIND_SENSOR,
                    description={"suggested_value": d.get(CONF_WIND_SENSOR)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_LOCAL_RADIATION,
                    description={"suggested_value": d.get(CONF_LOCAL_RADIATION)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_BRIGHTNESS,
                    description={"suggested_value": d.get(CONF_BRIGHTNESS)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_MIN_BRIGHTNESS,
                    **_with_default(d, CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=500,
                        max=50000,
                        step=100,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="station_ecowitt", data_schema=schema)

    async def async_step_station_netatmo(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Schritt 3b: Netatmo — Regen, Temp/Feuchte, Helligkeit."""
        if user_input is not None:
            self._clear_station_keys()
            self._data.update(user_input)
            return await self.async_step_radiation_fallback()

        d = self._data
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_RAIN_SENSOR,
                    description={"suggested_value": d.get(CONF_RAIN_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", integration="netatmo")
                ),
                vol.Optional(
                    CONF_RAIN_1H,
                    description={"suggested_value": d.get(CONF_RAIN_1H)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", integration="netatmo")
                ),
                vol.Optional(
                    CONF_RAIN_DETECTOR,
                    description={"suggested_value": d.get(CONF_RAIN_DETECTOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "binary_sensor"])
                ),
                vol.Optional(
                    CONF_TEMP,
                    description={"suggested_value": d.get(CONF_TEMP)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_HUMIDITY,
                    description={"suggested_value": d.get(CONF_HUMIDITY)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_BRIGHTNESS,
                    description={"suggested_value": d.get(CONF_BRIGHTNESS)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_MIN_BRIGHTNESS,
                    **_with_default(d, CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=500,
                        max=50000,
                        step=100,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="station_netatmo", data_schema=schema)

    async def async_step_station_other(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Schritt 3b: Andere Wetterstation — alle Felder offen."""
        if user_input is not None:
            self._clear_station_keys()
            self._data.update(user_input)
            if self._data.get(CONF_LOCAL_RADIATION):
                if self._is_reconfigure:
                    return self._finish_reconfigure()
                return await self.async_step_mow_times()
            return await self.async_step_radiation_fallback()

        d = self._data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RAIN_SENSOR_TYPE,
                    **_with_default(d, CONF_RAIN_SENSOR_TYPE, RAIN_MODE_RATE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=RAIN_MODE_RATE, label="Regenrate (mm/h)"
                            ),
                            selector.SelectOptionDict(
                                value=RAIN_MODE_INTERVAL,
                                label="Regenmenge je Messintervall (mm)",
                            ),
                            selector.SelectOptionDict(
                                value=RAIN_MODE_CUMULATIVE,
                                label="Kumulativer Zähler (mm)",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_RAIN_SENSOR,
                    description={"suggested_value": d.get(CONF_RAIN_SENSOR)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_RAIN_1H,
                    description={"suggested_value": d.get(CONF_RAIN_1H)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_RAIN_TODAY,
                    description={"suggested_value": d.get(CONF_RAIN_TODAY)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_RAIN_DETECTOR,
                    description={"suggested_value": d.get(CONF_RAIN_DETECTOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "binary_sensor"])
                ),
                vol.Optional(
                    CONF_TEMP,
                    description={"suggested_value": d.get(CONF_TEMP)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_HUMIDITY,
                    description={"suggested_value": d.get(CONF_HUMIDITY)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_WIND_SENSOR,
                    description={"suggested_value": d.get(CONF_WIND_SENSOR)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_LOCAL_RADIATION,
                    description={"suggested_value": d.get(CONF_LOCAL_RADIATION)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_BRIGHTNESS,
                    description={"suggested_value": d.get(CONF_BRIGHTNESS)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_MIN_BRIGHTNESS,
                    **_with_default(d, CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=500,
                        max=50000,
                        step=100,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="station_other", data_schema=schema)

    async def async_step_station_none(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Schritt 3b: Keine lokale Wetterstation — optionaler Regenmelder + Umgebungssensoren."""
        if user_input is not None:
            self._clear_station_keys()
            self._data.update(user_input)
            return await self.async_step_radiation_fallback()

        d = self._data
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_RAIN_DETECTOR,
                    description={"suggested_value": d.get(CONF_RAIN_DETECTOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "binary_sensor"])
                ),
                vol.Optional(
                    CONF_TEMP,
                    description={"suggested_value": d.get(CONF_TEMP)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_HUMIDITY,
                    description={"suggested_value": d.get(CONF_HUMIDITY)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_BRIGHTNESS,
                    description={"suggested_value": d.get(CONF_BRIGHTNESS)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_MIN_BRIGHTNESS,
                    **_with_default(d, CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=500,
                        max=50000,
                        step=100,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="station_none", data_schema=schema)

    # ── Schritt 4: Strahlungs-Fallback (optional) ─────────────────────────────

    async def async_step_radiation_fallback(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if self._is_reconfigure:
                return self._finish_reconfigure()
            return await self.async_step_mow_times()

        d = self._data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RADIATION_SOURCE,
                    **_with_default(d, CONF_RADIATION_SOURCE, RADIATION_SOURCE_PV),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=RADIATION_SOURCE_PV,
                                label="PV-Leistung der Solaranlage",
                            ),
                            selector.SelectOptionDict(
                                value=RADIATION_SOURCE_SUN,
                                label="Sonnenstand (Position der Sonne am Himmel)",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_PV_POWER,
                    description={"suggested_value": d.get(CONF_PV_POWER)},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_PV_PEAK_KW,
                    **_with_default(d, CONF_PV_PEAK_KW, DEFAULT_PV_PEAK_KW),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1.0,
                        max=100.0,
                        step=0.1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="radiation_fallback", data_schema=schema)

    # ── Schritt 5: Mähzeiten & Schwellwerte ──────────────────────────────────

    async def async_step_mow_times(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._data["name"],
                data=self._data,
                options=user_input,
            )

        schema = _mow_times_schema({})
        return self.async_show_form(step_id="mow_times", data_schema=schema)


# ── Options Flow ──────────────────────────────────────────────────────────────


class WeatherMowOptionsFlow(config_entries.OptionsFlow):
    """Erlaubt nachträgliche Änderung aller Schwellwerte und Mähzeiten."""

    async def async_step_init(self, user_input: dict | None = None) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = _mow_times_schema(self.config_entry.options)
        return self.async_show_form(step_id="init", data_schema=schema)
