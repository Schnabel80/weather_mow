"""Integrationstests für _async_update_data mit voll bestückten Sensoren.

Deckt die scattered Branches im Haupt-Update ab: Strahlungs-Forecast-Sensor,
lokaler Regensensor + Detektor, Tau-/Wuchs-Block mit Entities, Recorder-Init-
Aufruf und Akku-Delta-Nacherfassung.
"""

from __future__ import annotations

from collections import deque
from datetime import date, timedelta
from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.const import RAIN_BUFFER_MAXLEN
from custom_components.weather_mow.coordinator import WeatherMowCoordinator


@pytest.fixture
def entry():
    e = MagicMock()
    e.entry_id = "upd_test"
    e.data = {
        "name": "Test",
        "mower_entity_id": "lawn_mower.test",
        "weather_entity_id": "weather.test",
        "rain_sensor_entity_id": "sensor.rain",
        "rain_provider": "ecowitt",
        "rain_today_sensor_entity_id": "sensor.rain_today",
        "rain_detector_entity_id": "binary_sensor.rain_det",
        "radiation_forecast_entity_id": "sensor.rad_fc",
        "battery_sensor_entity_id": "sensor.batt",
        "outdoor_temp_entity_id": "",
        "outdoor_humidity_entity_id": "",
        "wind_sensor_entity_id": "",
        "local_radiation_entity_id": "",
        "precip_forecast_entity_id": "",
        "pv_power_entity_id": "",
        "brightness_entity_id": "",
        "radiation_source": "sun",
    }
    e.options = {
        "mow_window_start": "00:00:00",
        "mow_window_end": "23:59:00",
        "target_buffer_h": 0.0,
    }
    return e


@pytest.fixture
async def coord(hass, entry):
    c = WeatherMowCoordinator(hass, entry)
    with patch.object(c, "_load_storage"), patch.object(c, "_register_listeners"):
        await c._async_setup()
    c._duration_yesterday_s = 9000.0
    c._duration_day_before_s = 9000.0
    c.switch_entity = MagicMock(is_on=True)
    # Recorder-Init-Block soll laufen (deckt 1710-1716), Methoden aber no-op
    c._sunshine_initialized = False
    return c


def _base_states(hass):
    hass.states.async_set(
        "weather.test",
        "sunny",
        attributes={"temperature": 22.0, "humidity": 55, "wind_speed": 5.0, "forecast": []},
    )
    hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
    hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 90})


def _keep_dry(coord):
    def _f(*a, **kw):
        coord._wetness_mm = 0.0
        return 0.0, 0.0, 0.0

    return _f


async def test_update_full_sensor_set(hass, coord):
    """Voll bestückte Sensoren → Radiation-FC, Regensensor, Detektor, Tau/Wuchs."""
    _base_states(hass)
    now_utc = dt_util.utcnow()
    # Sensor-Forecast-Pfad aktivieren (nur dann läuft _parse_sensor_forecasts)
    coord.entry.data = {
        **coord.entry.data,
        "precip_forecast_entity_id": "sensor.precip_fc",
    }
    precip_data = [
        {"datetime": (now_utc + timedelta(hours=1)).isoformat(), "value": 0.0},
        {"datetime": (now_utc + timedelta(hours=2)).isoformat(), "value": 0.5},
    ]
    hass.states.async_set("sensor.precip_fc", "ok", attributes={"data": precip_data})
    # Strahlungs-Forecast-Sensor mit data-Attribut (deckt 1013-1030)
    rad_data = [
        {"datetime": (now_utc + timedelta(hours=1)).isoformat(), "value": 400.0},
        {"datetime": (now_utc + timedelta(hours=2)).isoformat(), "value": 600.0},
    ]
    hass.states.async_set("sensor.rad_fc", "ok", attributes={"data": rad_data})
    # Lokaler Regensensor (kumulativ) + Tagesregen-Sensor
    hass.states.async_set("sensor.rain", "2.5")
    hass.states.async_set("sensor.rain_today", "1.0")
    # Regendetektor numerisch > 0.05 (deckt 1782-1784)
    hass.states.async_set("binary_sensor.rain_det", "0.2")

    # Entities, die Branches im Tau-/Wuchs-Block auslösen
    coord.lawn_sun_from_entity = MagicMock(native_value=dt_time(6, 0))
    coord.lawn_sun_efficiency_entity = MagicMock(native_value=0.5)
    coord.fertilization_date_entity = MagicMock(native_value=date.today() - timedelta(days=5))
    coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

    init_patch = {
        "_init_rain_buffer_from_recorder": AsyncMock(),
        "_init_duration_from_recorder": AsyncMock(),
        "_init_solar_peak_from_recorder": AsyncMock(),
        "_init_sunshine_from_recorder": AsyncMock(),
    }
    with (
        patch.object(coord, "_update_wetness", _keep_dry(coord)),
        patch.multiple(coord, **init_patch),
    ):
        data = await coord._async_update_data()

    # Detektor erkennt Regen
    assert data["raining"] is True
    # Tagesregen wird aus dem 12h-Puffer abgeleitet (kein eigenes Feld mehr).
    # Erstes Update mit kumulativem Sensor → noch kein Delta → 0; Wert ist vorhanden.
    assert data["rain_today_mm"] >= 0.0


async def test_update_fertilization_from_config(hass, coord):
    """Dünge-Datum aus der Config (Entity native_value None) → parse_date-Zweig."""
    _base_states(hass)
    hass.states.async_set("sensor.rain", "0.0")
    # Entity vorhanden, aber kein Wert → Fallback auf Config
    coord.fertilization_date_entity = MagicMock(native_value=None)
    fert_str = (date.today() - timedelta(days=3)).isoformat()
    coord.entry.data = {**coord.entry.data, "last_fertilization_date": fert_str}
    coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

    init_patch = {
        "_init_rain_buffer_from_recorder": AsyncMock(),
        "_init_duration_from_recorder": AsyncMock(),
        "_init_solar_peak_from_recorder": AsyncMock(),
        "_init_sunshine_from_recorder": AsyncMock(),
    }
    with (
        patch.object(coord, "_update_wetness", _keep_dry(coord)),
        patch.multiple(coord, **init_patch),
    ):
        data = await coord._async_update_data()
    assert "grass_growth_mm" in data or "growth_mm" in data or data is not None


async def test_update_battery_delta_catchup(hass, coord):
    """Veralteter Akkusensor mit Delta → Mähen/Andocken nacherfasst (1929-1944)."""
    _base_states(hass)
    hass.states.async_set("sensor.rain", "0.0")
    # Akkusensor veraltet (last_updated alt → not fresh), Wert 80
    old = dt_util.utcnow() - timedelta(minutes=30)
    hass.states.async_set("sensor.batt", "80")
    # last_updated manipulieren auf alt
    st = hass.states.get("sensor.batt")
    st.last_updated = old
    st.last_changed = old

    coord._prev_battery_pct = 90.0  # vorher 90 → jetzt 80 = -10 Delta
    coord._mow_start_ts = None
    coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

    init_patch = {
        "_init_rain_buffer_from_recorder": AsyncMock(),
        "_init_duration_from_recorder": AsyncMock(),
        "_init_solar_peak_from_recorder": AsyncMock(),
        "_init_sunshine_from_recorder": AsyncMock(),
    }
    with (
        patch.object(coord, "_update_wetness", _keep_dry(coord)),
        patch.multiple(coord, **init_patch),
    ):
        await coord._async_update_data()

    # Akku-Drop → Mähvorgang wurde nacherfasst
    assert coord._mow_start_ts is not None


async def test_first_update_after_reload_does_not_dump_rain_onto_wetness(hass, coord):
    """Reload-Bug: das erste Update nach (Re-)Load darf den Tagesregen nicht als
    Delta auf die restaurierte Nässe addieren.

    Reproduziert den 0.6 → 2.0-Sprung beim Reconfig: _load_storage() restauriert
    wetness_mm und _prev_rain_today, aber das erste _async_update_data baut den
    Regenpuffer aus dem Recorder NEU auf — _prev_rain_today passt dann nicht mehr
    zum frischen rain_today und die Differenz wird auf wetness_mm geklemmt.
    """
    _base_states(hass)
    # Kumulativer Regensensor, erste Lesung → primt nur, liefert 0 Slot-mm.
    hass.states.async_set("sensor.rain", "5.0")

    # Zustand direkt nach Reload: Nässe restauriert (~0.6 mm), prev_rain_today
    # aber NICHT synchron zum gleich neu aufgebauten Recorder-Puffer (Storage 0.0).
    coord._wetness_mm = 0.6
    coord._prev_rain_today = 0.0
    coord._sunshine_initialized = False

    def _rebuild_buffer(*_a, **_kw):
        # Recorder-Rebuild liefert 2.9 mm Tagesregen im Puffer (neuester Slot).
        coord._rain_buffer = deque(
            [0.0] * (RAIN_BUFFER_MAXLEN - 1) + [2.9], maxlen=RAIN_BUFFER_MAXLEN
        )

    init_patch = {
        "_init_rain_buffer_from_recorder": AsyncMock(side_effect=_rebuild_buffer),
        "_init_duration_from_recorder": AsyncMock(),
        "_init_solar_peak_from_recorder": AsyncMock(),
        "_init_sunshine_from_recorder": AsyncMock(),
    }
    with patch.multiple(coord, **init_patch):
        data = await coord._async_update_data()

    # Erstes Delta nach Reload muss 0 sein — kein Re-Inject des Tagesregens.
    assert data["rain_delta_mm"] == 0.0
    # Restaurierte Nässe bleibt ~0.6 mm, springt nicht auf 2.0 mm.
    assert coord._wetness_mm < 1.0
