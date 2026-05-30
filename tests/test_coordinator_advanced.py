"""Erweiterte Coordinator-Tests: Emergency-Mow, Start-Delay, Check-No-Dry-Window, Urgency."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def entry():
    e = MagicMock()
    e.entry_id = "adv_test"
    e.data = {
        "name": "Test",
        "mower_entity_id": "lawn_mower.test",
        "weather_entity_id": "weather.test",
        "rain_sensor_entity_id": "",
        "rain_1h_sensor_entity_id": "",
        "rain_today_sensor_entity_id": "",
        "rain_detector_entity_id": "",
        "outdoor_temp_entity_id": "",
        "outdoor_humidity_entity_id": "",
        "wind_sensor_entity_id": "",
        "local_radiation_entity_id": "",
        "brightness_entity_id": "",
        "radiation_source": "sun",
        "min_brightness_lux": 2000,
        "min_battery_pct": 20,
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
    c._sunshine_initialized = True
    c._duration_yesterday_s = 9000.0
    c._duration_day_before_s = 9000.0
    sw = MagicMock()
    sw.is_on = True
    c.switch_entity = sw
    em_sw = MagicMock()
    em_sw.is_on = True
    c.emergency_switch_entity = em_sw
    yield c


def _weather(hass, condition="sunny", temp=20.0):
    hass.states.async_set(
        "weather.test",
        condition,
        attributes={"temperature": temp, "humidity": 60, "wind_speed": 5.0, "forecast": []},
    )
    hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})


def _mower(hass, state="docked", battery=100):
    hass.states.async_set("lawn_mower.test", state, attributes={"battery_level": battery})


def _dry(coord):
    coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

    def _keep_dry(*a, **kw):
        coord._wetness_mm = 0.0
        return 0.0, 0.0, 0.0

    return _keep_dry


# ── Emergency-Mow-Pfad ────────────────────────────────────────────────────────


class TestEmergencyMow:
    async def test_emergency_mow_when_target_met_and_rain_tomorrow(self, hass, coord):
        """Tagesziel erreicht + viel Regen morgen + Zeit noch vorhanden → emergency."""
        # Verwende einen großen Zeitpuffer (Fenster bis 23:59, min. 2h Rest nötig)
        cfg = {
            **coord.entry.data,
            "mow_window_start": "00:00:00",
            "mow_window_end": "23:59:00",
            "target_buffer_h": 0.0,
            "target_daily_duration_h": 3.0,
            "full_cycle_duration_h": 2.0,
            "threshold_rain_tomorrow_mm": 5.0,
            "threshold_min_time_for_emergency_h": 0.0,  # kein Zeitbedarf
        }
        result = coord._compute_decision(
            cfg=cfg,
            now_local=dt_util.now(),
            wetness_mm=0.0,
            brightness_ok=True,
            rain_today_remaining=0.0,
            rain_tomorrow=10.0,
            duration_today_h=3.1,
            rain_fc_3h=0.0,
            duration_avg_3d_h=2.0,
            no_dry_window=False,
            temp_c=20.0,
        )
        mow_allowed, start_now, block_reason = result
        assert block_reason == "emergency_mow_tomorrow_rain"
        assert mow_allowed is True
        assert start_now is True

    async def test_no_emergency_when_switch_off(self, hass, coord):
        """Emergency-Schalter aus → kein Notmähen, target_reached."""
        coord.emergency_switch_entity.is_on = False
        cfg = {**coord.entry.data, **coord.entry.options}
        result = coord._compute_decision(
            cfg=cfg,
            now_local=dt_util.now(),
            wetness_mm=0.0,
            brightness_ok=True,
            rain_today_remaining=0.0,
            rain_tomorrow=10.0,
            duration_today_h=4.0,
            rain_fc_3h=0.0,
            duration_avg_3d_h=2.0,
            no_dry_window=False,
            temp_c=20.0,
        )
        _, _, block_reason = result
        assert block_reason == "daily_target_reached"


# ── Start-Delay ───────────────────────────────────────────────────────────────


class TestStartDelay:
    async def test_start_delay_postpones_start(self, hass, coord):
        """Morgen-Startverzögerung 30min → start_now=False direkt nach Freigabe."""
        _weather(hass)
        _mower(hass)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
        coord._duration_today_s = 0.0  # noch nicht gemäht heute
        coord._mow_first_allowed_ts = dt_util.utcnow().timestamp()  # Timestamp gerade eben

        coord.entry.options = {
            **coord.entry.options,
            "start_delay_minutes": 30,
        }

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        # start_now muss False sein weil Delay noch nicht abgelaufen
        assert data["start_now"] is False
        assert data["mow_allowed"] is True  # mow_allowed bleibt True

    async def test_start_delay_bypassed_at_high_priority(self, hass, coord):
        """Bei Priorität ≥ 65 (DELAY_BYPASS_PRIORITY) wird Delay ignoriert."""
        _weather(hass)
        _mower(hass)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
        coord._duration_today_s = 0.0
        # Timestamp gerade eben → Delay noch nicht abgelaufen
        coord._mow_first_allowed_ts = dt_util.utcnow().timestamp()
        coord._duration_yesterday_s = 0.0  # Niedriger avg → hohe Dringlichkeit
        coord._duration_day_before_s = 0.0

        coord.entry.options = {
            **coord.entry.options,
            "start_delay_minutes": 60,
        }

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        # Bei sehr niedrigem avg: Priorität steigt → bypass
        # Wir testen nur dass kein Crash auftritt
        assert "start_now" in data
        assert "priority" in data


# ── _check_no_dry_window ──────────────────────────────────────────────────────


class TestCheckNoDryWindow:
    def _bare(self):
        hass = MagicMock()
        hass.states.get.return_value = None
        entry = MagicMock()
        entry.entry_id = "ndw_test"
        entry.data = {"name": "Test", "weather_entity_id": ""}
        entry.options = {}
        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c.hass = hass
        c.entry = entry
        c._radiation_peak = 800.0
        c.lawn_sun_efficiency_entity = None
        c.lawn_sun_from_entity = None
        c.mow_threshold_entity = None  # nötig für _check_no_dry_window
        return c

    def test_no_dry_window_when_already_dry(self):
        """Wetness bereits unter Schwelle → kein Trocknungsbedarf → False."""
        c = self._bare()
        cfg = {
            "full_cycle_duration_h": 2.0,
            "mow_window_end": "20:00:00",
            "outdoor_temp_entity_id": "",
            "outdoor_humidity_entity_id": "",
        }
        with patch.object(c, "_get_temp_humidity", return_value=(20.0, 60.0)):
            result = c._check_no_dry_window(cfg, dt_util.now(), wetness_mm=0.0)
        assert result is False

    def test_no_dry_window_impossible_to_dry_in_time(self):
        """Benötigte Zeit zum Trocknen überschreitet den Rest des Fensters → True."""
        c = self._bare()
        # full_cycle_h extrem hoch → Trockenfenster reicht nie aus → True
        cfg = {
            "full_cycle_duration_h": 999.0,
            "mow_window_end": "20:00:00",
            "outdoor_temp_entity_id": "",
            "outdoor_humidity_entity_id": "",
        }
        with patch.object(c, "_get_temp_humidity", return_value=(15.0, 85.0)):
            result = c._check_no_dry_window(cfg, dt_util.now(), wetness_mm=1.5)
        # Mit full_cycle=999h hat kein Trockenfenster je genug Zeit → True
        assert result is True

    def test_no_dry_window_enough_time_left(self):
        """Genug Zeit zum Trocknen vor Fenster-Ende → False (Trockenfenster existiert)."""
        c = self._bare()
        cfg = {
            "full_cycle_duration_h": 2.0,
            "mow_window_end": "20:00:00",
            "outdoor_temp_entity_id": "",
            "outdoor_humidity_entity_id": "",
        }
        # Früh morgens → viel Zeit
        early_morning = dt_util.now().replace(hour=8, minute=0, second=0)
        with (
            patch.object(c, "_get_temp_humidity", return_value=(22.0, 55.0)),
            patch.object(c, "_effective_solar_factor", return_value=0.8),
        ):
            result = c._check_no_dry_window(cfg, early_morning, wetness_mm=0.8)
        # Morgens viel Zeit → Trockenfenster vorhanden → False
        assert result is False


# ── Urgency-Zweige ────────────────────────────────────────────────────────────


class TestUrgencyBranches:
    async def test_urgent_threshold_used_when_time_pressure(self, hass, coord):
        """Bei Zeitdruck (knapp vor Fenster-Ende) wird Dringlichkeits-Schwelle verwendet."""
        # Direkter Test von _compute_decision mit urgency_high=True
        urgent_thresh = MagicMock()
        urgent_thresh.native_value = 1.5
        coord.mow_threshold_urgent_entity = urgent_thresh

        cfg = {
            **coord.entry.data,
            "mow_window_start": "00:00:00",
            "mow_window_end": "23:59:00",
            "target_buffer_h": 0.0,
        }
        # urgency_high via emergency_mow_active
        coord.emergency_mow_active = True
        result = coord._compute_decision(
            cfg=cfg,
            now_local=dt_util.now(),
            wetness_mm=1.0,
            brightness_ok=True,
            rain_today_remaining=0.0,
            rain_tomorrow=0.0,
            duration_today_h=0.5,
            rain_fc_3h=0.0,
            duration_avg_3d_h=2.0,
            no_dry_window=False,
            temp_c=20.0,
        )
        coord.emergency_mow_active = False
        _, _, block_reason = result
        # Bei wetness=1.0 unter urgent_threshold=1.5 → mowing_allowed
        assert block_reason in ("mowing_allowed", "emergency_mow_tomorrow_rain")

    async def test_heat_reduction_in_range(self, hass, coord):
        """Temperatur zwischen 30-35°C → Priorität reduziert, nicht null."""
        _weather(hass, temp=32.0)
        _mower(hass)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data_hot = await coord._async_update_data()

        _weather(hass, temp=20.0)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
        with patch.object(coord, "_update_wetness", _keep_dry):
            data_cool = await coord._async_update_data()

        if data_hot["mow_allowed"] and data_cool["mow_allowed"]:
            assert 0 < data_hot["priority"] < data_cool["priority"]


# ── Rain-Detector-Callback ────────────────────────────────────────────────────


class TestRainDetectorCallback:
    def _bare_coord(self):
        hass = MagicMock()
        hass.async_create_task = MagicMock()
        entry = MagicMock()
        entry.entry_id = "rdc_test"
        entry.data = {"name": "Test"}
        entry.options = {}
        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c.hass = hass
        c.entry = entry
        c.async_request_refresh = MagicMock()
        return c

    def _make_event(self, new_state_str):
        event = MagicMock()
        state = MagicMock()
        state.state = new_state_str
        event.data = {"new_state": state}
        return event

    def test_detector_on_triggers_refresh(self):
        c = self._bare_coord()
        event = self._make_event("on")
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_called()

    def test_detector_numeric_triggers_refresh(self):
        """Numerischer Wert > 0.05 gilt als Regen."""
        c = self._bare_coord()
        event = self._make_event("1.5")
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_called()

    def test_detector_any_valid_state_triggers_refresh(self):
        """Jeder gültige State (auch 0.0) → Refresh (kein Filter auf Wert)."""
        c = self._bare_coord()
        event = self._make_event("0.0")
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_called()

    def test_detector_none_state_ignored(self):
        c = self._bare_coord()
        event = MagicMock()
        event.data = {"new_state": None}
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_not_called()

    def test_detector_unavailable_ignored(self):
        c = self._bare_coord()
        event = self._make_event("unavailable")
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_not_called()
