"""Tests für die _init_*_from_recorder-Methoden mit gemocktem HA-Recorder.

Der Recorder wird über homeassistant.components.recorder.get_instance gemockt;
async_add_executor_job liefert eine states_map {entity: [FakeState, ...]}.
Damit werden die Logik-Zweige (nicht nur die Early-Return-Pfade) abgedeckt.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.const import (
    RADIATION_SUN_THRESHOLD,
    SOLAR_PEAK_MIN,
)
from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Helfer ────────────────────────────────────────────────────────────────────


class FakeState:
    """Minimaler Ersatz für ha.core.State (nur .state und .last_updated)."""

    def __init__(self, state: str, last_updated: datetime):
        self.state = state
        self.last_updated = last_updated


def _patch_recorder(states_map: dict):
    """Patcht get_instance so, dass async_add_executor_job die states_map liefert."""
    mock_instance = MagicMock()
    mock_instance.async_add_executor_job = AsyncMock(return_value=states_map)
    return patch(
        "homeassistant.components.recorder.get_instance",
        return_value=mock_instance,
    )


@pytest.fixture
def entry():
    e = MagicMock()
    e.entry_id = "rec_test"
    e.data = {
        "name": "Test",
        "mower_entity_id": "lawn_mower.test",
        "weather_entity_id": "weather.test",
        "rain_sensor_entity_id": "sensor.rain",
        "rain_provider": "ecowitt",
        "rain_detector_entity_id": "",
        "outdoor_temp_entity_id": "",
        "outdoor_humidity_entity_id": "",
        "wind_sensor_entity_id": "",
        "local_radiation_entity_id": "sensor.solar",
        "radiation_forecast_entity_id": "",
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
    return c


def _cfg(coord) -> dict:
    return {**coord.entry.data, **coord.entry.options}


# ── _init_sunshine_from_recorder ──────────────────────────────────────────────


class TestSunshineFromRecorder:
    async def test_current_chain_sets_sunshine_start(self, hass, coord):
        """Durchgehende Sonne bis jetzt → _sunshine_start_utc gesetzt, dew_cleared."""
        now_utc = dt_util.utcnow()
        # 90 min durchgehend Sonne ≥ 200 W/m² (oldest → newest)
        states = [
            FakeState("0.0", now_utc - timedelta(minutes=120)),
            FakeState(str(RADIATION_SUN_THRESHOLD + 100), now_utc - timedelta(minutes=90)),
            FakeState(str(RADIATION_SUN_THRESHOLD + 200), now_utc - timedelta(minutes=45)),
            FakeState(str(RADIATION_SUN_THRESHOLD + 150), now_utc - timedelta(minutes=5)),
        ]
        with _patch_recorder({"sensor.solar": states}):
            await coord._init_sunshine_from_recorder(_cfg(coord), now_utc)

        assert coord._sunshine_start_utc is not None
        # 90 min Sonne ≥ DEFAULT_MIN_SUN_H_FOR_DEW (1.0 h) → Tau-Latch gesetzt
        assert coord._dew_cleared_today is True

    async def test_short_current_chain_no_dew_clear(self, hass, coord):
        """Nur 20 min Sonne → sunshine_start gesetzt, aber dew_cleared bleibt False."""
        now_utc = dt_util.utcnow()
        states = [
            FakeState("0.0", now_utc - timedelta(minutes=60)),
            FakeState(str(RADIATION_SUN_THRESHOLD + 50), now_utc - timedelta(minutes=20)),
            FakeState(str(RADIATION_SUN_THRESHOLD + 50), now_utc - timedelta(minutes=2)),
        ]
        coord._dew_cleared_today = False
        with _patch_recorder({"sensor.solar": states}):
            await coord._init_sunshine_from_recorder(_cfg(coord), now_utc)

        assert coord._sunshine_start_utc is not None
        assert coord._dew_cleared_today is False

    async def test_past_period_sets_dew_latch(self, hass, coord):
        """Keine aktuelle Kette, aber früher ≥ 1h Sonne → dew_cleared via Phase 2."""
        now_utc = dt_util.utcnow()
        # Sonne vormittags 2h, danach unter Schwelle (newest state = dunkel)
        states = [
            FakeState(str(RADIATION_SUN_THRESHOLD + 100), now_utc - timedelta(hours=5)),
            FakeState(str(RADIATION_SUN_THRESHOLD + 100), now_utc - timedelta(hours=4)),
            FakeState(str(RADIATION_SUN_THRESHOLD + 100), now_utc - timedelta(hours=3)),
            FakeState("10.0", now_utc - timedelta(minutes=30)),  # jetzt dunkel
        ]
        coord._dew_cleared_today = False
        with _patch_recorder({"sensor.solar": states}):
            await coord._init_sunshine_from_recorder(_cfg(coord), now_utc)

        # Keine aktuelle Kette → _sunshine_start_utc bleibt None
        assert coord._sunshine_start_utc is None
        # Aber vergangene 2h-Periode → Tau-Latch
        assert coord._dew_cleared_today is True

    async def test_invalid_state_breaks_chain(self, hass, coord):
        """Nicht-numerischer State (unavailable) bricht die Kette ab, kein Crash."""
        now_utc = dt_util.utcnow()
        states = [
            FakeState("unavailable", now_utc - timedelta(minutes=30)),
            FakeState(str(RADIATION_SUN_THRESHOLD + 100), now_utc - timedelta(minutes=10)),
        ]
        with _patch_recorder({"sensor.solar": states}):
            await coord._init_sunshine_from_recorder(_cfg(coord), now_utc)
        # newest state ist gültig (Sonne) → sunshine_start gesetzt; "unavailable"
        # davor bricht die Rückwärts-Kette ab → kein Crash
        assert coord._sunshine_start_utc is not None

    async def test_empty_states_returns_early(self, hass, coord):
        """Leere states_map → kein Crash, keine Änderung."""
        now_utc = dt_util.utcnow()
        coord._sunshine_start_utc = None
        with _patch_recorder({"sensor.solar": []}):
            await coord._init_sunshine_from_recorder(_cfg(coord), now_utc)
        assert coord._sunshine_start_utc is None


# ── _init_rain_buffer_from_recorder ───────────────────────────────────────────


class TestRainBufferFromRecorder:
    async def test_buffer_rebuilt_from_states(self, hass, coord):
        """Regen-States → Puffer rekonstruiert, Normalizer geprimt."""
        # Normalizer wird erst im Live-Update gebaut → hier explizit setzen
        coord._rain_normalizer = coord._build_rain_normalizer(_cfg(coord))
        assert coord._rain_normalizer is not None
        now_utc = dt_util.utcnow()
        # Ecowitt Daily Rain = kumulativer Zähler (steigt über den Tag)
        states = [
            FakeState("0.0", now_utc - timedelta(hours=6)),
            FakeState("1.0", now_utc - timedelta(hours=4)),
            FakeState("2.5", now_utc - timedelta(hours=2)),
            FakeState("3.0", now_utc - timedelta(minutes=10)),
        ]
        with _patch_recorder({"sensor.rain": states}):
            await coord._init_rain_buffer_from_recorder(_cfg(coord), now_utc)

        # Puffer wurde befüllt (deque mit maxlen) und enthält Regen
        assert len(coord._rain_buffer) > 0
        assert sum(coord._rain_buffer) >= 0.0

    async def test_no_valid_states_returns(self, hass, coord):
        """Nur ungültige States → kein Crash, Puffer unverändert leerbar."""
        now_utc = dt_util.utcnow()
        states = [
            FakeState("unavailable", now_utc - timedelta(hours=2)),
            FakeState("unknown", now_utc - timedelta(minutes=5)),
        ]
        with _patch_recorder({"sensor.rain": states}):
            await coord._init_rain_buffer_from_recorder(_cfg(coord), now_utc)
        # Kein Crash = bestanden

    async def test_no_normalizer_returns_early(self, hass, coord):
        """Ohne Normalizer → früher Return."""
        now_utc = dt_util.utcnow()
        coord._rain_normalizer = None
        # Sollte ohne Recorder-Zugriff zurückkehren
        await coord._init_rain_buffer_from_recorder(_cfg(coord), now_utc)


# ── _init_duration_from_recorder ──────────────────────────────────────────────


class TestDurationFromRecorder:
    async def test_completed_sessions_summed(self, hass, coord):
        """Zwei abgeschlossene Mähsessions → Dauer summiert."""
        now_utc = dt_util.utcnow()
        now_local = dt_util.now()
        # Session 1: 30 min, Session 2: 45 min (beide heute, abgeschlossen)
        states = [
            FakeState("docked", now_utc - timedelta(hours=6)),
            FakeState("mowing", now_utc - timedelta(hours=5)),
            FakeState("docked", now_utc - timedelta(hours=5) + timedelta(minutes=30)),
            FakeState("mowing", now_utc - timedelta(hours=3)),
            FakeState("docked", now_utc - timedelta(hours=3) + timedelta(minutes=45)),
        ]
        coord._duration_today_s = 0.0
        with _patch_recorder({"lawn_mower.test": states}):
            await coord._init_duration_from_recorder(_cfg(coord), now_utc, now_local)

        # 30 + 45 = 75 min = 4500 s
        assert coord._duration_today_s == pytest.approx(4500.0, abs=5.0)

    async def test_ongoing_session_sets_mow_start(self, hass, coord):
        """Laufende Session + aktueller State 'mowing' → _mow_start_ts gesetzt."""
        now_utc = dt_util.utcnow()
        now_local = dt_util.now()
        states = [
            FakeState("docked", now_utc - timedelta(hours=2)),
            FakeState("mowing", now_utc - timedelta(minutes=20)),
        ]
        coord._mow_start_ts = None
        coord._duration_today_s = 0.0
        # Aktueller Mäher-State muss "mowing" sein (Race-Condition-Schutz)
        hass.states.async_set("lawn_mower.test", "mowing", attributes={})
        with _patch_recorder({"lawn_mower.test": states}):
            await coord._init_duration_from_recorder(_cfg(coord), now_utc, now_local)

        assert coord._mow_start_ts is not None

    async def test_ongoing_in_recorder_but_now_docked(self, hass, coord):
        """Session laut Recorder offen, Mäher aber nicht mehr 'mowing' → als
        abgeschlossen gewertet, _mow_start_ts bleibt None (Recorder-Lag)."""
        now_utc = dt_util.utcnow()
        now_local = dt_util.now()
        states = [
            FakeState("docked", now_utc - timedelta(hours=2)),
            FakeState("mowing", now_utc - timedelta(minutes=40)),
        ]
        coord._mow_start_ts = None
        coord._duration_today_s = 0.0
        # Aktueller State = docked → Session wird geschlossen
        hass.states.async_set("lawn_mower.test", "docked", attributes={})
        with _patch_recorder({"lawn_mower.test": states}):
            await coord._init_duration_from_recorder(_cfg(coord), now_utc, now_local)

        assert coord._mow_start_ts is None
        # Abgeschlossene Dauer wurde übernommen (> 0)
        assert coord._duration_today_s > 0.0

    async def test_empty_states_no_change(self, hass, coord):
        """Keine States → Dauer unverändert."""
        now_utc = dt_util.utcnow()
        now_local = dt_util.now()
        coord._duration_today_s = 1234.0
        with _patch_recorder({"lawn_mower.test": []}):
            await coord._init_duration_from_recorder(_cfg(coord), now_utc, now_local)
        assert coord._duration_today_s == 1234.0


# ── _init_solar_peak_from_recorder ────────────────────────────────────────────


class TestSolarPeakFromRecorder:
    async def test_peak_restored_from_local_sensor(self, hass, coord):
        """Lokaler Strahlungssensor → Maximum wird zum Peak."""
        now_utc = dt_util.utcnow()
        states = [
            FakeState("300.0", now_utc - timedelta(days=3)),
            FakeState("850.0", now_utc - timedelta(days=2)),
            FakeState("500.0", now_utc - timedelta(days=1)),
        ]
        coord._radiation_peak = SOLAR_PEAK_MIN
        with _patch_recorder({"sensor.solar": states}):
            await coord._init_solar_peak_from_recorder(_cfg(coord), now_utc)

        assert coord._radiation_peak == pytest.approx(850.0)

    async def test_peak_not_lowered(self, hass, coord):
        """Recorder-Max kleiner als gespeicherter Peak → kein Rückwärtsüberschreiben."""
        now_utc = dt_util.utcnow()
        states = [
            FakeState("300.0", now_utc - timedelta(days=1)),
        ]
        coord._radiation_peak = 900.0
        with _patch_recorder({"sensor.solar": states}):
            await coord._init_solar_peak_from_recorder(_cfg(coord), now_utc)

        assert coord._radiation_peak == 900.0

    async def test_pv_conversion_path(self, hass, entry):
        """PV-Quelle (keine lokale/Forecast-Strahlung) → Watt-Umrechnung greift."""
        # Entry ohne lokalen Sensor, dafür PV-Power
        entry.data = {
            **entry.data,
            "local_radiation_entity_id": "",
            "radiation_forecast_entity_id": "",
            "pv_power_entity_id": "sensor.pv",
            "pv_peak_kw": 6.4,
        }
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"), patch.object(c, "_register_listeners"):
            await c._async_setup()

        now_utc = dt_util.utcnow()
        # PV-Leistung in Watt (z.B. 3200 W)
        states = [
            FakeState("3200.0", now_utc - timedelta(days=1)),
        ]
        c._radiation_peak = SOLAR_PEAK_MIN
        with _patch_recorder({"sensor.pv": states}):
            await c._init_solar_peak_from_recorder({**entry.data, **entry.options}, now_utc)
        # Umrechnung: 3200 / (6.4*1000) * 1000 = 500 W/m²
        assert c._radiation_peak == pytest.approx(500.0)

    async def test_invalid_states_ignored(self, hass, coord):
        """Ungültige States werden übersprungen, Peak bleibt Minimum."""
        now_utc = dt_util.utcnow()
        states = [
            FakeState("unavailable", now_utc - timedelta(days=1)),
            FakeState("unknown", now_utc - timedelta(hours=12)),
        ]
        coord._radiation_peak = SOLAR_PEAK_MIN
        with _patch_recorder({"sensor.solar": states}):
            await coord._init_solar_peak_from_recorder(_cfg(coord), now_utc)
        assert coord._radiation_peak == SOLAR_PEAK_MIN


# ── Recorder-Ausnahmen (Exception-Handler) ────────────────────────────────────


def _patch_recorder_raises():
    """get_instance wirft → deckt die except-Blöcke der Recorder-Methoden."""
    return patch(
        "homeassistant.components.recorder.get_instance",
        side_effect=RuntimeError("Recorder nicht verfügbar"),
    )


class TestRecorderExceptionHandling:
    async def test_sunshine_recorder_exception(self, hass, coord):
        now_utc = dt_util.utcnow()
        with _patch_recorder_raises():
            await coord._init_sunshine_from_recorder(_cfg(coord), now_utc)
        # Kein Crash = Exception-Handler greift

    async def test_rain_buffer_recorder_exception(self, hass, coord):
        coord._rain_normalizer = coord._build_rain_normalizer(_cfg(coord))
        now_utc = dt_util.utcnow()
        with _patch_recorder_raises():
            await coord._init_rain_buffer_from_recorder(_cfg(coord), now_utc)

    async def test_duration_recorder_exception(self, hass, coord):
        now_utc = dt_util.utcnow()
        with _patch_recorder_raises():
            await coord._init_duration_from_recorder(_cfg(coord), now_utc, dt_util.now())

    async def test_solar_peak_recorder_exception(self, hass, coord):
        now_utc = dt_util.utcnow()
        with _patch_recorder_raises():
            await coord._init_solar_peak_from_recorder(_cfg(coord), now_utc)
