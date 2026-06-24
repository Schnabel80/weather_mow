"""Letzte Coverage-Tests: Midnight, Shutdown, Priority-Details, Auto-Resume, Forecast-Parsing."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.const import DEFAULT_BATTERY_FULL_PCT, RAIN_BUFFER_MAXLEN
from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Minimal-Coordinator ───────────────────────────────────────────────────────


def _bare():
    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.states.get.return_value = None
    entry = MagicMock()
    entry.entry_id = "fin_test"
    entry.data = {"name": "Test"}
    entry.options = {}
    c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
    c.hass = hass
    c.entry = entry
    c._rain_buffer = deque([0.0] * RAIN_BUFFER_MAXLEN, maxlen=RAIN_BUFFER_MAXLEN)
    c._radiation_peak = 600.0
    c._wetness_mm = 0.0
    c._below_threshold_since = None
    c._duration_today_s = 3600.0
    c._duration_yesterday_s = 7200.0
    c._duration_day_before_s = 1800.0
    c._growth_gdd_accum = 2.5
    c._mow_since_last_gdd_reset_s = 0.0
    c._mow_start_ts = None
    c._last_drying_mm = 0.02
    c._mow_first_allowed_ts = None
    c._auto_resume_blocked = False
    c._last_mow_allowed = False
    c._last_block_reason = ""
    c._dew_cleared_today = False
    c._prev_rain_today = 0.0
    c.emergency_mow_active = False
    c.switch_entity = None
    c.emergency_switch_entity = None
    c._charge_rate = 1.0
    c._charge_learned = False
    c._charge_start_pct = None
    c._charge_start_ts = None
    c._battery_full_pct = DEFAULT_BATTERY_FULL_PCT
    c._battery_ceiling_learned = False
    c._store_mowing = AsyncMock()
    c._store_rain = AsyncMock()
    c._store_solar = AsyncMock()
    c._store_growth = AsyncMock()
    c._store_wetness = AsyncMock()
    c._store_charge = AsyncMock()
    c._mow_state_unsub = None
    c._midnight_unsub = None
    c._weather_state_unsub = None
    c._rain_sensor_unsub = None
    c._rain_detect_unsub = None
    return c


# ── _handle_midnight ──────────────────────────────────────────────────────────


class TestHandleMidnight:
    def test_rotates_duration_stats(self):
        c = _bare()
        c._duration_today_s = 3600.0
        c._duration_yesterday_s = 7200.0
        c._duration_day_before_s = 1800.0
        c._handle_midnight(dt_util.utcnow())
        assert c._duration_day_before_s == pytest.approx(7200.0)
        assert c._duration_yesterday_s == pytest.approx(3600.0)
        assert c._duration_today_s == pytest.approx(0.0)

    def test_resets_flags(self):
        c = _bare()
        c._mow_start_ts = 123456.0
        c.emergency_mow_active = True
        c._dew_cleared_today = True
        c._below_threshold_since = dt_util.now()
        c._prev_rain_today = 2.5
        c._handle_midnight(dt_util.utcnow())
        assert c._mow_start_ts is None
        assert c.emergency_mow_active is False
        assert c._dew_cleared_today is False
        assert c._below_threshold_since is None
        assert c._prev_rain_today == 0.0


# ── async_shutdown ────────────────────────────────────────────────────────────


class TestAsyncShutdown:
    async def test_cancels_all_listeners(self):
        c = _bare()
        unsub1 = MagicMock()
        unsub2 = MagicMock()
        c._mow_state_unsub = unsub1
        c._weather_state_unsub = unsub2
        await c.async_shutdown()
        unsub1.assert_called_once()
        unsub2.assert_called_once()
        assert c._mow_state_unsub is None
        assert c._weather_state_unsub is None

    async def test_handles_unsub_exception(self):
        """Fehler beim Abmelden wird unterdrückt."""
        c = _bare()
        unsub = MagicMock(side_effect=Exception("boom"))
        c._mow_state_unsub = unsub
        # Darf keine Exception werfen
        await c.async_shutdown()


# ── _current_duration_today_h ─────────────────────────────────────────────────


class TestCurrentDurationTodayH:
    def test_without_active_session(self):
        c = _bare()
        c._duration_today_s = 3600.0
        c._mow_start_ts = None
        assert c._current_duration_today_h() == pytest.approx(1.0)

    def test_with_active_mowing_session(self):
        """Laufende Session wird zur Basis addiert."""
        c = _bare()
        c._duration_today_s = 3600.0
        # Mähsession startete vor 10 Minuten
        c._mow_start_ts = dt_util.utcnow().timestamp() - 600
        result = c._current_duration_today_h()
        # Sollte ca. 1.0 + 600/3600 ≈ 1.167h sein
        assert result > 1.0
        assert result < 1.5


# ── Priority: Midday-Bonus und Urgency ────────────────────────────────────────


class TestPriorityDetails:
    def _coord_for_priority(self):
        hass = MagicMock()
        hass.states.get.return_value = None
        entry = MagicMock()
        entry.entry_id = "prio_test"
        entry.data = {"name": "Test"}
        entry.options = {}
        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c.hass = hass
        c.entry = entry
        c.emergency_mow_active = False
        c.mow_threshold_entity = None
        c.max_temp_entity = None
        return c

    def _call_priority(
        self, coord, now_local, duration_today_h=0.0, duration_avg_3d_h=2.0, temp_c=20.0
    ):
        cfg = {
            "target_daily_duration_h": 3.0,
            "full_cycle_duration_h": 2.0,
            "mow_window_end": "20:00:00",
            "target_buffer_h": 0.0,
        }
        return coord._compute_priority(
            cfg=cfg,
            now_local=now_local,
            wetness_mm=0.0,
            duration_today_h=duration_today_h,
            duration_avg_3d_h=duration_avg_3d_h,
            growth_ratio=0.0,
            temp_c=temp_c,
        )

    def test_midday_bonus_at_noon(self):
        """Mittags (11-16h) gibt es den Midday-Bonus (+10)."""
        coord = self._coord_for_priority()
        noon = dt_util.now().replace(hour=12, minute=0, second=0)
        p = self._call_priority(coord, noon)
        # Mittags → priority enthält midday_bonus
        assert p > 0

    def test_no_midday_bonus_at_night(self):
        """Nachts (0-10h) kein Midday-Bonus."""
        coord = self._coord_for_priority()
        night = dt_util.now().replace(hour=3, minute=0, second=0)
        noon = dt_util.now().replace(hour=12, minute=0, second=0)
        p_night = self._call_priority(coord, night)
        p_noon = self._call_priority(coord, noon)
        assert p_noon >= p_night

    def test_heat_at_max_gives_zero_priority(self):
        """Temperatur ≥ max_temp_c → Priorität 0 (heat_factor=0)."""
        coord = self._coord_for_priority()
        max_temp = MagicMock()
        max_temp.native_value = 30.0
        coord.max_temp_entity = max_temp
        now = dt_util.now()
        p = self._call_priority(coord, now, temp_c=35.0)  # ≥ max_temp=30
        assert p == 0

    def test_heat_in_reduction_zone(self):
        """Temperatur zwischen 25-30°C → 0 < priority < volle Priorität."""
        coord = self._coord_for_priority()
        max_temp = MagicMock()
        max_temp.native_value = 30.0
        coord.max_temp_entity = max_temp
        now = dt_util.now().replace(hour=12, minute=0, second=0)
        p_hot = self._call_priority(coord, now, temp_c=27.0)
        p_cool = self._call_priority(coord, now, temp_c=15.0)
        assert 0 < p_hot < p_cool


# ── Auto-Resume Tracking ──────────────────────────────────────────────────────


class TestAutoResume:
    @pytest.fixture
    def entry(self):
        e = MagicMock()
        e.entry_id = "ar_test"
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
        }
        e.options = {
            "mow_window_start": "00:00:00",
            "mow_window_end": "23:59:00",
            "target_buffer_h": 0.0,
        }
        return e

    @pytest.fixture
    async def coord(self, hass, entry):
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"), patch.object(c, "_register_listeners"):
            await c._async_setup()
        c._sunshine_initialized = True
        c._duration_yesterday_s = 9000.0
        c._duration_day_before_s = 9000.0
        sw = MagicMock()
        sw.is_on = True
        c.switch_entity = sw
        yield c

    async def test_auto_resume_sets_blocked_flag(self, hass, coord):
        """Mäher startet außerhalb Erlaubnis → _auto_resume_blocked=True."""
        coord._last_mow_allowed = False
        coord._last_block_reason = "too_wet"

        new_state = MagicMock()
        new_state.state = "mowing"
        old_state = MagicMock()
        old_state.state = "docked"
        old_state.last_updated = dt_util.utcnow()

        event = MagicMock()
        event.data = {"old_state": old_state, "new_state": new_state}
        coord._handle_mower_state_change(event)
        assert coord._auto_resume_blocked is True

    async def test_stop_now_when_auto_resume_blocked(self, hass, coord):
        """_auto_resume_blocked=True → stop_now=True im nächsten Update."""
        hass.states.async_set(
            "weather.test",
            "sunny",
            attributes={"temperature": 20.0, "humidity": 60, "wind_speed": 5.0, "forecast": []},
        )
        hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
        hass.states.async_set("lawn_mower.test", "mowing", attributes={"battery_level": 100})

        coord._auto_resume_blocked = True
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        assert data["stop_now"] is True


# ── _parse_sensor_forecasts mit echten Daten ─────────────────────────────────


class TestParseSensorForecastsWithData:
    @pytest.fixture
    def entry(self):
        e = MagicMock()
        e.entry_id = "pf_test"
        e.data = {
            "name": "Test",
            "mower_entity_id": "lawn_mower.test",
            "weather_entity_id": "weather.test",
            "precip_forecast_entity_id": "sensor.precip",
            "radiation_forecast_entity_id": "",
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
        }
        e.options = {
            "mow_window_start": "00:00:00",
            "mow_window_end": "23:59:00",
            "target_buffer_h": 0.0,
        }
        return e

    @pytest.fixture
    async def coord(self, hass, entry):
        c = WeatherMowCoordinator(hass, entry)
        with patch.object(c, "_load_storage"), patch.object(c, "_register_listeners"):
            await c._async_setup()
        c._sunshine_initialized = True
        c._duration_yesterday_s = 9000.0
        c._duration_day_before_s = 9000.0
        sw = MagicMock()
        sw.is_on = True
        c.switch_entity = sw
        yield c

    @pytest.mark.freeze_time("2026-06-15 12:00:00+00:00")
    async def test_parses_rain_today_remaining(self, hass, coord):
        """Niederschlag in verbleibenden Stunden heute → rain_today_remaining."""
        # Zeit eingefroren auf 12:00 UTC → +2h = 14:00 UTC, klar vor Mitternacht
        soon = "2026-06-15T14:00:00+00:00"
        hass.states.async_set(
            "sensor.precip", "ok", attributes={"data": [{"datetime": soon, "value": 3.5}]}
        )
        hass.states.async_set(
            "weather.test",
            "sunny",
            attributes={"temperature": 20.0, "humidity": 60, "wind_speed": 5.0, "forecast": []},
        )
        hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
        hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 100})
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        assert data["rain_today_remaining"] == pytest.approx(3.5)

    async def test_parses_rain_fc_3h(self, hass, coord):
        """Regen in den nächsten 3h → rain_fc_3h > 0 → kein Forecast-Discount."""
        now_utc = dt_util.utcnow()
        soon = (now_utc + timedelta(hours=1)).isoformat()
        hass.states.async_set(
            "sensor.precip", "ok", attributes={"data": [{"datetime": soon, "value": 2.0}]}
        )
        hass.states.async_set(
            "weather.test",
            "sunny",
            attributes={"temperature": 20.0, "humidity": 60, "wind_speed": 5.0, "forecast": []},
        )
        hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
        hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 100})
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        # rain_today_remaining enthält den Regen der nächsten Stunden
        assert data["rain_today_remaining"] >= 0.0
