"""Gezielte Tests für verbleibende Branches in coordinator.py.

Direkte Aufrufe der Helper-/Decision-/Priority-Methoden mit einem minimalen
Coordinator (ohne vollen HA-Setup), um die scattered Edge-Branches abzudecken:
Battery-Fallbacks, effective_solar, _check_no_dry_window, _compute_decision-
und _compute_priority-Fallbacks.
"""

from __future__ import annotations

from collections import deque
from datetime import time as dt_time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.util import dt as dt_util

from custom_components.weather_mow.const import (
    CONF_BATTERY_SENSOR,
    CONF_MOW_END,
    CONF_MOW_START,
    CONF_MOWER_ENTITY,
    CONF_TARGET_DAILY_H,
    CONF_WEATHER_ENTITY,
    RAIN_BUFFER_MAXLEN,
    SOLAR_PEAK_MIN,
)
from custom_components.weather_mow.coordinator import WeatherMowCoordinator


def _bare(hass=None):
    if hass is None:
        hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "br_test"
    entry.data = {"name": "Test"}
    entry.options = {}
    c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
    c.hass = hass
    c.entry = entry
    c._rain_buffer = deque([0.0] * RAIN_BUFFER_MAXLEN, maxlen=RAIN_BUFFER_MAXLEN)
    c._radiation_peak = SOLAR_PEAK_MIN
    c._wetness_mm = 0.0
    c._below_threshold_since = None
    c._duration_today_s = 0.0
    c._duration_yesterday_s = 0.0
    c._duration_day_before_s = 0.0
    c._growth_gdd_accum = 0.0
    c._mow_since_last_gdd_reset_s = 0.0
    c._charge_rate = 1.0
    c._charge_learned = False
    c._charge_start_pct = None
    c._charge_start_ts = None
    c._store_mowing = AsyncMock()
    c._store_rain = AsyncMock()
    c._store_solar = AsyncMock()
    c._store_growth = AsyncMock()
    c._store_wetness = AsyncMock()
    c._store_charge = AsyncMock()
    # Entity-Slots default None
    c.switch_entity = None
    c.emergency_switch_entity = None
    c.max_temp_entity = None
    c.mow_threshold_entity = None
    c.lawn_sun_efficiency_entity = None
    c.lawn_sun_from_entity = None
    c.fertilization_date_entity = None
    c.emergency_mow_active = False
    return c


def _states_map(mapping):
    """hass.states.get-Ersatz aus {entity_id: State}."""

    def _get(eid):
        return mapping.get(eid)

    return _get


def _state(value, age_s=0):
    s = MagicMock()
    s.state = value
    s.last_updated = dt_util.utcnow() - timedelta(seconds=age_s)
    s.attributes = {}
    return s


# ── _current_battery_pct ──────────────────────────────────────────────────────


class TestCurrentBatteryPct:
    def test_fresh_sensor(self):
        hass = MagicMock()
        hass.states.get = _states_map({"sensor.batt": _state("80", age_s=10)})
        c = _bare(hass)
        val, fresh = c._current_battery_pct({CONF_BATTERY_SENSOR: "sensor.batt"})
        assert val == 80.0
        assert fresh is True

    def test_stale_sensor(self):
        hass = MagicMock()
        # 20 min alt → veraltet (BATTERY_STALE_MINUTES=10)
        hass.states.get = _states_map({"sensor.batt": _state("65", age_s=1200)})
        c = _bare(hass)
        val, fresh = c._current_battery_pct({CONF_BATTERY_SENSOR: "sensor.batt"})
        assert val == 65.0
        assert fresh is False

    def test_mower_attribute_fallback(self):
        hass = MagicMock()
        mower = _state("docked")
        mower.attributes = {"battery_level": 55}
        hass.states.get = _states_map({"lawn_mower.x": mower})
        c = _bare(hass)
        val, fresh = c._current_battery_pct(
            {CONF_BATTERY_SENSOR: "sensor.absent", CONF_MOWER_ENTITY: "lawn_mower.x"}
        )
        assert val == 55.0
        assert fresh is False

    def test_mower_attribute_invalid_returns_default(self):
        hass = MagicMock()
        mower = _state("docked")
        mower.attributes = {"battery_level": "not-a-number"}
        hass.states.get = _states_map({"lawn_mower.x": mower})
        c = _bare(hass)
        val, fresh = c._current_battery_pct(
            {CONF_BATTERY_SENSOR: "sensor.absent", CONF_MOWER_ENTITY: "lawn_mower.x"}
        )
        assert val == 100.0
        assert fresh is False


# ── _effective_solar_factor ───────────────────────────────────────────────────


class TestEffectiveSolarFactor:
    def test_reads_entity_values(self):
        c = _bare()
        c.lawn_sun_efficiency_entity = MagicMock(native_value=0.5)
        c.lawn_sun_from_entity = MagicMock(native_value=dt_time(6, 0))
        now_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
        result = c._effective_solar_factor(0.8, now_local)
        assert 0.0 <= result <= 1.0

    def test_before_sun_from_is_zero(self):
        c = _bare()
        c.lawn_sun_efficiency_entity = MagicMock(native_value=1.0)
        c.lawn_sun_from_entity = MagicMock(native_value=dt_time(10, 0))
        now_local = dt_util.now().replace(hour=7, minute=0, second=0, microsecond=0)
        result = c._effective_solar_factor(0.9, now_local)
        assert result == 0.0


# ── _check_no_dry_window ──────────────────────────────────────────────────────


class TestCheckNoDryWindow:
    def test_below_threshold_returns_false(self):
        c = _bare()
        c.mow_threshold_entity = MagicMock(native_value=0.5)
        cfg = {CONF_WEATHER_ENTITY: "weather.x"}
        # wetness <= threshold → Trockenfenster ist jetzt
        assert c._check_no_dry_window(cfg, dt_util.now(), wetness_mm=0.3) is False

    def test_reads_entities_and_computes(self):
        c = _bare()
        c.mow_threshold_entity = MagicMock(native_value=0.5)
        c.lawn_efficiency_entity = MagicMock(native_value=0.6)
        c.wind_entity = MagicMock(native_value=10.0)
        cfg = {CONF_WEATHER_ENTITY: "weather.x", CONF_MOW_END: "20:00:00"}
        with patch.object(c, "_get_temp_humidity", return_value=(25.0, 50.0)):
            morning = dt_util.now().replace(hour=8, minute=0, second=0, microsecond=0)
            result = c._check_no_dry_window(cfg, morning, wetness_mm=1.5)
        assert isinstance(result, bool)

    def test_invalid_mow_end_uses_fallback(self):
        c = _bare()
        c.mow_threshold_entity = MagicMock(native_value=0.5)
        cfg = {CONF_WEATHER_ENTITY: "weather.x", CONF_MOW_END: None}
        with patch.object(c, "_get_temp_humidity", return_value=(25.0, 50.0)):
            morning = dt_util.now().replace(hour=8, minute=0, second=0, microsecond=0)
            result = c._check_no_dry_window(cfg, morning, wetness_mm=1.5)
        assert isinstance(result, bool)


# ── _compute_decision ─────────────────────────────────────────────────────────


class TestComputeDecisionBranches:
    def test_too_dark_hedgehog(self):
        c = _bare()
        now_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
        allowed, _start, reason = c._compute_decision(
            {CONF_MOW_START: "08:00:00", CONF_MOW_END: "20:00:00"},
            now_local,
            wetness_mm=0.0,
            brightness_ok=False,
            rain_today_remaining=0.0,
            rain_tomorrow=0.0,
            duration_today_h=0.0,
        )
        assert allowed is False
        assert reason == "too_dark_hedgehog"

    def test_disabled_switch_blocks(self):
        """Switch aus → disabled (erster Gate)."""
        c = _bare()
        c.switch_entity = MagicMock(is_on=False)
        now_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
        allowed, _start, reason = c._compute_decision(
            {CONF_MOW_START: "08:00:00", CONF_MOW_END: "20:00:00"},
            now_local,
            wetness_mm=0.0,
            brightness_ok=True,
            rain_today_remaining=0.0,
            rain_tomorrow=0.0,
            duration_today_h=0.0,
        )
        assert allowed is False
        assert reason == "disabled"

    def test_too_hot_blocks(self):
        """Temperatur ≥ max_temp_entity → too_hot."""
        c = _bare()
        c.max_temp_entity = MagicMock(native_value=35.0)
        now_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
        allowed, _start, reason = c._compute_decision(
            {CONF_MOW_START: "08:00:00", CONF_MOW_END: "20:00:00"},
            now_local,
            wetness_mm=0.0,
            brightness_ok=True,
            rain_today_remaining=0.0,
            rain_tomorrow=0.0,
            duration_today_h=0.0,
            temp_c=38.0,
        )
        assert allowed is False
        assert reason == "too_hot"


# ── _compute_priority ─────────────────────────────────────────────────────────


class TestComputePriorityBranches:
    def test_not_allowed_returns_zero(self):
        c = _bare()
        assert c._compute_priority({}, dt_util.now(), 0.0, 0.0, 0.0, mow_allowed=False) == 0

    def test_midday_bonus_morning_ramp(self):
        """Stunde 10–11 → linearer Midday-Bonus-Anstieg."""
        c = _bare()
        now_local = dt_util.now().replace(hour=10, minute=30, second=0, microsecond=0)
        p = c._compute_priority(
            {CONF_TARGET_DAILY_H: 3.0, CONF_MOW_END: "20:00:00"},
            now_local,
            wetness_mm=0.0,
            duration_today_h=0.0,
            duration_avg_3d_h=0.0,
            mow_allowed=True,
        )
        assert 0 <= p <= 100

    def test_midday_bonus_afternoon_ramp(self):
        """Stunde 16–17 → linearer Midday-Bonus-Abfall."""
        c = _bare()
        now_local = dt_util.now().replace(hour=16, minute=30, second=0, microsecond=0)
        p = c._compute_priority(
            {CONF_TARGET_DAILY_H: 3.0, CONF_MOW_END: "20:00:00"},
            now_local,
            wetness_mm=0.0,
            duration_today_h=0.0,
            duration_avg_3d_h=0.0,
            mow_allowed=True,
        )
        assert 0 <= p <= 100

    def test_invalid_mow_end_uses_fallback(self):
        """CONF_MOW_END=None → time_to_target_h-Fallback (4.0)."""
        c = _bare()
        now_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
        p = c._compute_priority(
            {CONF_TARGET_DAILY_H: 3.0, CONF_MOW_END: None},
            now_local,
            wetness_mm=0.0,
            duration_today_h=0.0,
            duration_avg_3d_h=0.0,
            mow_allowed=True,
        )
        assert 0 <= p <= 100
