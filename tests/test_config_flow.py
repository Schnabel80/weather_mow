"""Config-Flow-Tests für die weather_mow Integration.

Abgedeckte Pfade:
  • Vollständiger Flow mit allen vier Stations-Varianten (none / ecowitt / netatmo / other)
  • Ecowitt + Other: Verzweigung mit / ohne lokaler Strahlung (radiation_fallback übersprungen?)
  • Duplikat-Abort bei gleicher unique_id
  • Options-Flow (Mähzeiten-Anpassung)
  • Reconfigure-Flow
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.weather_mow.const import (
    CONF_MIN_BATTERY_PCT,
    CONF_MIN_BRIGHTNESS,
    CONF_MOWER_ENTITY,
    CONF_RADIATION_SOURCE,
    CONF_RAIN_PROVIDER,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    DEFAULT_MIN_BATTERY,
    DEFAULT_MIN_BRIGHTNESS,
    DOMAIN,
    RADIATION_SOURCE_PV,
)
from custom_components.weather_mow.rain_input import (
    RAIN_MODE_RATE,
    RAIN_PROVIDER_ECOWITT,
    RAIN_PROVIDER_NETATMO,
    RAIN_PROVIDER_NONE,
    RAIN_PROVIDER_OTHER,
)

# ── Wiederverwendbare Eingabe-Dicts ───────────────────────────────────────────

DEVICE_INPUT = {
    "name": "Testmäher",
    CONF_MOWER_ENTITY: "lawn_mower.husqvarna",
    CONF_MIN_BATTERY_PCT: DEFAULT_MIN_BATTERY,
}

WEATHER_INPUT = {
    CONF_WEATHER_ENTITY: "weather.home",
}

RADIATION_FALLBACK_INPUT = {
    CONF_RADIATION_SOURCE: RADIATION_SOURCE_PV,
    # CONF_PV_POWER und CONF_PV_PEAK_KW sind optional → weggelassen
}

MOW_TIMES_INPUT = {
    "mow_window_start": "08:00:00",
    "mow_window_end": "20:00:00",
    "target_daily_duration_h": 2.5,
    "full_cycle_duration_h": 2.0,
    "target_buffer_h": 2.0,
    "threshold_wetness_score": 30,
    "threshold_rain_today_remaining_mm": 5.0,
    "threshold_rain_tomorrow_mm": 8.0,
    "threshold_min_time_for_emergency_h": 2.0,
    "threshold_dew_temp_offset": 3.0,
    "min_sun_h_for_dew": 1.0,
    "last_fertilization_date": "",
    "max_growth_mm": 20,
    "prevent_auto_resume": True,
}

# ── Interne Hilfsfunktionen ───────────────────────────────────────────────────


async def _init_flow(hass: HomeAssistant) -> dict:
    """Startet einen neuen User-Flow und gibt das Ergebnis von Schritt 1 zurück."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "device"
    return result


async def _submit_device_and_weather(hass: HomeAssistant) -> dict:
    """Durchläuft Schritt 1 (device) und Schritt 2 (weather).

    Gibt das Ergebnis des station-Schritts zurück (step_id == 'station').
    """
    result = await _init_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=DEVICE_INPUT
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "weather"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=WEATHER_INPUT
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "station"
    return result


# ── Vollständige Flows (Happy Path) ──────────────────────────────────────────


async def test_full_flow_station_none(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Flow ohne lokale Wetterstation.

    Pfad: device → weather → station(none) → station_none → radiation_fallback → mow_times
    """
    with patch("custom_components.weather_mow.async_setup_entry", return_value=True) as mock_setup:
        result = await _submit_device_and_weather(hass)
        flow_id = result["flow_id"]

        # Schritt 3a: Stationstyp = none
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_NONE}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "station_none"

        # Schritt 3b: station_none (alle Felder optional, nur min_brightness required)
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "radiation_fallback"

        # Schritt 4: Strahlungs-Fallback
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=RADIATION_FALLBACK_INPUT
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "mow_times"

        # Schritt 5: Mähzeiten → Entry erstellt
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=MOW_TIMES_INPUT
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Testmäher"
    assert result["data"][CONF_MOWER_ENTITY] == "lawn_mower.husqvarna"
    assert result["data"][CONF_RAIN_PROVIDER] == RAIN_PROVIDER_NONE
    assert result["data"][CONF_WEATHER_ENTITY] == "weather.home"
    mock_setup.assert_called_once()


async def test_full_flow_station_ecowitt_no_local_radiation(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Ecowitt-Station ohne lokalen Strahlungssensor.

    Pfad: … → station(ecowitt) → station_ecowitt → radiation_fallback → mow_times → CREATE_ENTRY
    """
    with patch("custom_components.weather_mow.async_setup_entry", return_value=True):
        result = await _submit_device_and_weather(hass)
        flow_id = result["flow_id"]

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_ECOWITT}
        )
        assert result["step_id"] == "station_ecowitt"

        # Kein local_radiation gesetzt → weiter zu radiation_fallback
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS}
        )
        assert result["step_id"] == "radiation_fallback"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=RADIATION_FALLBACK_INPUT
        )
        assert result["step_id"] == "mow_times"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=MOW_TIMES_INPUT
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_RAIN_PROVIDER] == RAIN_PROVIDER_ECOWITT


async def test_full_flow_station_ecowitt_with_local_radiation(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Ecowitt-Station MIT lokalem Strahlungssensor → überspringt radiation_fallback.

    Pfad: … → station_ecowitt (local_radiation gesetzt) → mow_times → CREATE_ENTRY
    """
    with patch("custom_components.weather_mow.async_setup_entry", return_value=True):
        result = await _submit_device_and_weather(hass)
        flow_id = result["flow_id"]

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_ECOWITT}
        )
        assert result["step_id"] == "station_ecowitt"

        # Mit local_radiation → direkt zu mow_times (radiation_fallback übersprungen)
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                "local_radiation_entity_id": "sensor.ecowitt_solar_radiation",
                CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS,
            },
        )
        assert result["step_id"] == "mow_times"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=MOW_TIMES_INPUT
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["local_radiation_entity_id"] == "sensor.ecowitt_solar_radiation"


async def test_full_flow_station_netatmo(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Netatmo-Station → geht immer über radiation_fallback (kein local_radiation-Feld).

    Pfad: … → station(netatmo) → station_netatmo → radiation_fallback → mow_times → CREATE_ENTRY
    """
    with patch("custom_components.weather_mow.async_setup_entry", return_value=True):
        result = await _submit_device_and_weather(hass)
        flow_id = result["flow_id"]

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_NETATMO}
        )
        assert result["step_id"] == "station_netatmo"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS}
        )
        assert result["step_id"] == "radiation_fallback"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=RADIATION_FALLBACK_INPUT
        )
        assert result["step_id"] == "mow_times"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=MOW_TIMES_INPUT
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_RAIN_PROVIDER] == RAIN_PROVIDER_NETATMO


async def test_full_flow_station_other_no_local_radiation(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Andere Station ohne lokalen Strahlungssensor → über radiation_fallback.

    Pfad: … → station(other) → station_other → radiation_fallback → mow_times → CREATE_ENTRY
    """
    with patch("custom_components.weather_mow.async_setup_entry", return_value=True):
        result = await _submit_device_and_weather(hass)
        flow_id = result["flow_id"]

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_OTHER}
        )
        assert result["step_id"] == "station_other"

        # Kein local_radiation → weiter zu radiation_fallback
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                "rain_sensor_type": RAIN_MODE_RATE,
                CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS,
            },
        )
        assert result["step_id"] == "radiation_fallback"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=RADIATION_FALLBACK_INPUT
        )
        assert result["step_id"] == "mow_times"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=MOW_TIMES_INPUT
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_RAIN_PROVIDER] == RAIN_PROVIDER_OTHER


async def test_full_flow_station_other_with_local_radiation(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Andere Station MIT lokalem Strahlungssensor → überspringt radiation_fallback.

    Pfad: … → station_other (local_radiation gesetzt) → mow_times → CREATE_ENTRY
    """
    with patch("custom_components.weather_mow.async_setup_entry", return_value=True):
        result = await _submit_device_and_weather(hass)
        flow_id = result["flow_id"]

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_OTHER}
        )
        assert result["step_id"] == "station_other"

        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                "rain_sensor_type": RAIN_MODE_RATE,
                "local_radiation_entity_id": "sensor.solar_radiation",
                CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS,
            },
        )
        # Mit local_radiation → direkt zu mow_times
        assert result["step_id"] == "mow_times"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=MOW_TIMES_INPUT
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["local_radiation_entity_id"] == "sensor.solar_radiation"


# ── Fehler-/Grenzfälle ────────────────────────────────────────────────────────


async def test_duplicate_entry_aborts(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Ein zweiter Eintrag mit demselben Namen (unique_id) wird abgebrochen."""
    with patch("custom_components.weather_mow.async_setup_entry", return_value=True):
        # Ersten Eintrag vollständig anlegen
        result = await _submit_device_and_weather(hass)
        flow_id = result["flow_id"]

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_NONE}
        )
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS}
        )
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=RADIATION_FALLBACK_INPUT
        )
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=MOW_TIMES_INPUT
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY

        # Zweiten Flow mit identischem Namen starten → Abort
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            user_input=DEVICE_INPUT,  # gleicher Name "Testmäher" → unique_id-Konflikt
        )

    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


# ── Options Flow ──────────────────────────────────────────────────────────────


def _options_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Testmäher",
            CONF_MOWER_ENTITY: "lawn_mower.husqvarna",
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_RAIN_PROVIDER: RAIN_PROVIDER_NONE,
            CONF_MIN_BATTERY_PCT: DEFAULT_MIN_BATTERY,
            CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS,
            CONF_RADIATION_SOURCE: RADIATION_SOURCE_PV,
        },
        options=MOW_TIMES_INPUT,
        version=2,
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_flow(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    """Options Flow: Menü → Mähzeiten-Formular → speichert Änderungen."""
    entry = _options_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    # Issue #7: Der Konfigurieren-Button zeigt jetzt ein Menü statt nur Mähzeiten
    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "init"
    assert set(result["menu_options"]) == {"mow_times", "sensors"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "mow_times"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mow_times"

    # Mähfenster auf 07:00 vorverlegen
    updated = {**MOW_TIMES_INPUT, "mow_window_start": "07:00:00"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=updated
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["mow_window_start"] == "07:00:00"
    # Alle anderen Werte unverändert
    assert entry.options["mow_window_end"] == "20:00:00"
    assert entry.options["target_daily_duration_h"] == 2.5


async def test_options_flow_sensors_path(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Issue #7: Über den Konfigurieren-Button sind ALLE Sensoren änderbar.

    Menü → 'sensors' → durchläuft device/weather/station/…, schreibt entry.data
    und lässt die Optionen unangetastet.
    """
    entry = _options_entry(hass)

    with patch("custom_components.weather_mow.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"next_step_id": "sensors"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "device"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=DEVICE_INPUT
        )
        assert result["step_id"] == "weather"

        # Wetter-Entität ÄNDERN — der Kern von Issue #7
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_WEATHER_ENTITY: "weather.neue_station"}
        )
        assert result["step_id"] == "station"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_NONE}
        )
        assert result["step_id"] == "station_none"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS}
        )
        assert result["step_id"] == "radiation_fallback"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=RADIATION_FALLBACK_INPUT
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY

    assert entry.data[CONF_WEATHER_ENTITY] == "weather.neue_station"
    # Optionen (Mähzeiten) bleiben unverändert
    assert entry.options["mow_window_start"] == "08:00:00"


async def test_station_ecowitt_selectors_not_integration_filtered(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Issue #7: Ecowitt-Selektoren dürfen nicht auf integration='ecowitt' gefiltert sein.

    Stationen, die z. B. via ecowitt2mqtt (Integration 'mqtt') eingebunden sind,
    wären sonst nicht auswählbar.
    """
    result = await _submit_device_and_weather(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_ECOWITT}
    )
    assert result["step_id"] == "station_ecowitt"

    for key, sel in result["data_schema"].schema.items():
        config = getattr(sel, "config", None)
        if config is not None:
            assert not config.get("integration"), f"{key} ist integration-gefiltert"


async def test_station_netatmo_selectors_not_integration_filtered(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Issue #7: Auch Netatmo-Selektoren ohne integration-Filter."""
    result = await _submit_device_and_weather(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_NETATMO}
    )
    assert result["step_id"] == "station_netatmo"

    for key, sel in result["data_schema"].schema.items():
        config = getattr(sel, "config", None)
        if config is not None:
            assert not config.get("integration"), f"{key} ist integration-gefiltert"


# ── Reconfigure Flow ──────────────────────────────────────────────────────────


async def test_reconfigure_flow(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    """Reconfigure Flow durchläuft alle Schritte und aktualisiert den Eintrag."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Testmäher",
            CONF_MOWER_ENTITY: "lawn_mower.husqvarna",
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_RAIN_PROVIDER: RAIN_PROVIDER_NONE,
            CONF_MIN_BATTERY_PCT: DEFAULT_MIN_BATTERY,
            CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS,
            CONF_RADIATION_SOURCE: RADIATION_SOURCE_PV,
        },
        options=MOW_TIMES_INPUT,
        version=2,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.weather_mow.async_setup_entry", return_value=True),
        patch("custom_components.weather_mow.async_unload_entry", return_value=True),
    ):
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "device"

        flow_id = result["flow_id"]

        # Schritt 1: Gerät — Mäher-Entität bleibt gleich
        result = await hass.config_entries.flow.async_configure(flow_id, user_input=DEVICE_INPUT)
        assert result["step_id"] == "weather"

        # Schritt 2: Wetterquelle
        result = await hass.config_entries.flow.async_configure(flow_id, user_input=WEATHER_INPUT)
        assert result["step_id"] == "station"

        # Schritt 3a: Stationstyp
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_NONE}
        )
        assert result["step_id"] == "station_none"

        # Schritt 3b: station_none
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS}
        )
        assert result["step_id"] == "radiation_fallback"

        # Schritt 4: radiation_fallback → _finish_reconfigure() → ABORT
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=RADIATION_FALLBACK_INPUT
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    # Eintrag wurde mit neuem weather_entity_id aktualisiert
    assert entry.data[CONF_WEATHER_ENTITY] == "weather.home"


async def test_reconfigure_clears_wind_sensor(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Reconfigure: ein zuvor gesetzter Wind-Sensor lässt sich entfernen.

    Regression für den Bug, dass _finish_reconfigure die alten entry.data über
    self._data merge-te und gelöschte Keys dadurch wieder einfügte.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Testmäher",
            CONF_MOWER_ENTITY: "lawn_mower.husqvarna",
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_RAIN_PROVIDER: RAIN_PROVIDER_ECOWITT,
            CONF_WIND_SENSOR: "sensor.wetterstation_wind_speed",
            "local_radiation_entity_id": "sensor.ecowitt_solar",
            CONF_MIN_BATTERY_PCT: DEFAULT_MIN_BATTERY,
            CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS,
            CONF_RADIATION_SOURCE: RADIATION_SOURCE_PV,
        },
        options=MOW_TIMES_INPUT,
        version=2,
    )
    entry.add_to_hass(hass)
    # Vorbedingung: Wind-Sensor ist gesetzt
    assert entry.data[CONF_WIND_SENSOR] == "sensor.wetterstation_wind_speed"

    with (
        patch("custom_components.weather_mow.async_setup_entry", return_value=True),
        patch("custom_components.weather_mow.async_unload_entry", return_value=True),
    ):
        result = await entry.start_reconfigure_flow(hass)
        flow_id = result["flow_id"]

        result = await hass.config_entries.flow.async_configure(flow_id, user_input=DEVICE_INPUT)
        result = await hass.config_entries.flow.async_configure(flow_id, user_input=WEATHER_INPUT)
        assert result["step_id"] == "station"

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_RAIN_PROVIDER: RAIN_PROVIDER_ECOWITT}
        )
        assert result["step_id"] == "station_ecowitt"

        # Wind-Sensor NICHT erneut angeben (= im UI gelöscht), local_radiation behalten
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                "local_radiation_entity_id": "sensor.ecowitt_solar",
                CONF_MIN_BRIGHTNESS: DEFAULT_MIN_BRIGHTNESS,
            },
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    # Der Wind-Sensor wurde tatsächlich entfernt (Bug: kam vorher zurück)
    assert CONF_WIND_SENSOR not in entry.data
    # Andere Keys bleiben erhalten
    assert entry.data["local_radiation_entity_id"] == "sensor.ecowitt_solar"
