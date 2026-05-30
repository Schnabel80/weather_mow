"""Tests für Coordinator-Listener-Callbacks und Mow-Session-Tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.util import dt as dt_util

from custom_components.weather_mow.coordinator import WeatherMowCoordinator


# ── Minimal-Coordinator für Callback-Tests ────────────────────────────────────

def _make_coord_for_callbacks():
    """Minimal-Coordinator für synchrone Callback-Tests."""
    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.async_request_refresh = AsyncMock()

    entry = MagicMock()
    entry.entry_id = "cb_test"
    entry.data = {
        "name": "Test",
        "mower_entity_id": "lawn_mower.test",
        "prevent_auto_resume": True,
    }
    entry.options = {}

    coord = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
    coord.hass = hass
    coord.entry = entry
    coord._mow_start_ts = None
    coord._duration_today_s = 0.0
    coord._mow_since_last_gdd_reset_s = 0.0
    coord._growth_gdd_accum = 5.0
    coord._auto_resume_blocked = False
    coord._last_mow_allowed = False
    coord._last_block_reason = "too_wet"
    coord.switch_entity = MagicMock()
    coord.switch_entity.is_on = True
    coord.async_request_refresh = AsyncMock()
    return coord


def _make_event(old_state=None, new_state=None):
    event = MagicMock()
    event.data = {"old_state": old_state, "new_state": new_state}
    return event


def _make_state(state_str, last_updated=None):
    s = MagicMock()
    s.state = state_str
    if last_updated is None:
        last_updated = dt_util.utcnow()
    s.last_updated = last_updated
    return s


# ── Mow-Session Tracking ──────────────────────────────────────────────────────

class TestMowSessionTracking:

    def test_mowing_start_sets_timestamp(self):
        """new_state=mowing → _mow_start_ts gesetzt."""
        coord = _make_coord_for_callbacks()
        event = _make_event(
            old_state=_make_state("docked"),
            new_state=_make_state("mowing"),
        )
        coord._handle_mower_state_change(event)
        assert coord._mow_start_ts is not None

    def test_mowing_end_accumulates_duration(self):
        """old_state=mowing + _mow_start_ts → Dauer zu duration_today_s addiert."""
        coord = _make_coord_for_callbacks()
        now = dt_util.utcnow().timestamp()
        coord._mow_start_ts = now - 600  # 10 Minuten Mähsession

        event = _make_event(
            old_state=_make_state("mowing"),
            new_state=_make_state("docked"),
        )
        coord._handle_mower_state_change(event)

        assert coord._duration_today_s >= 590  # ~600s abzüglich Toleranz
        assert coord._mow_start_ts is None

    def test_mowing_end_without_start_ts_uses_fallback(self):
        """Mähende ohne _mow_start_ts → last_updated als Fallback."""
        coord = _make_coord_for_callbacks()
        coord._mow_start_ts = None  # kein Timestamp
        import datetime
        old = _make_state("mowing",
                          last_updated=dt_util.utcnow() - datetime.timedelta(minutes=5))
        event = _make_event(old_state=old, new_state=_make_state("docked"))
        coord._handle_mower_state_change(event)
        assert coord._duration_today_s > 0

    def test_full_cycle_resets_gdd(self):
        """Nach einem vollen Zyklus (2h) wird GDD-Akkumulator zurückgesetzt."""
        coord = _make_coord_for_callbacks()
        now = dt_util.utcnow().timestamp()
        coord._mow_start_ts = now - 7300  # 2h+ Session
        coord._growth_gdd_accum = 3.0

        event = _make_event(
            old_state=_make_state("mowing"),
            new_state=_make_state("docked"),
        )
        coord._handle_mower_state_change(event)

        assert coord._growth_gdd_accum == 0.0
        assert coord._mow_since_last_gdd_reset_s == 0.0

    def test_short_session_no_gdd_reset(self):
        """Kurze Session (< full_cycle) → GDD bleibt."""
        coord = _make_coord_for_callbacks()
        now = dt_util.utcnow().timestamp()
        coord._mow_start_ts = now - 300  # nur 5 Minuten
        coord._growth_gdd_accum = 3.0

        event = _make_event(
            old_state=_make_state("mowing"),
            new_state=_make_state("docked"),
        )
        coord._handle_mower_state_change(event)

        assert coord._growth_gdd_accum == 3.0  # unverändert

    def test_auto_resume_blocked_on_unauthorized_start(self):
        """Mähstart trotz too_wet → _auto_resume_blocked=True."""
        coord = _make_coord_for_callbacks()
        coord._last_mow_allowed = False
        coord._last_block_reason = "too_wet"

        event = _make_event(
            old_state=_make_state("docked"),
            new_state=_make_state("mowing"),
        )
        coord._handle_mower_state_change(event)

        assert coord._auto_resume_blocked is True

    def test_no_auto_resume_block_when_switch_off(self):
        """Haupt-Switch aus → kein auto_resume_blocked."""
        coord = _make_coord_for_callbacks()
        coord.switch_entity.is_on = False
        coord._last_mow_allowed = False
        coord._last_block_reason = "too_wet"

        event = _make_event(
            old_state=_make_state("docked"),
            new_state=_make_state("mowing"),
        )
        coord._handle_mower_state_change(event)

        assert coord._auto_resume_blocked is False

    def test_no_auto_resume_when_mow_was_allowed(self):
        """Mähen war erlaubt → kein auto_resume_blocked."""
        coord = _make_coord_for_callbacks()
        coord._last_mow_allowed = True
        coord._last_block_reason = ""

        event = _make_event(
            old_state=_make_state("docked"),
            new_state=_make_state("mowing"),
        )
        coord._handle_mower_state_change(event)

        assert coord._auto_resume_blocked is False


# ── Rain-Sensor-Listener ──────────────────────────────────────────────────────

class TestRainSensorListener:

    def test_rain_start_triggers_refresh(self):
        """Regen-Sensor: 0 → >0.1 → async_request_refresh."""
        coord = _make_coord_for_callbacks()
        event = _make_event(
            old_state=_make_state("0.0"),
            new_state=_make_state("0.5"),
        )
        coord._handle_rain_sensor_change(event)
        coord.hass.async_create_task.assert_called()

    def test_rain_stop_triggers_refresh(self):
        """Regen-Sensor: >0.1 → 0 → async_request_refresh."""
        coord = _make_coord_for_callbacks()
        event = _make_event(
            old_state=_make_state("0.5"),
            new_state=_make_state("0.0"),
        )
        coord._handle_rain_sensor_change(event)
        coord.hass.async_create_task.assert_called()

    def test_no_threshold_crossing_no_refresh(self):
        """Regen-Sensor bleibt über 0.1 → kein Refresh."""
        coord = _make_coord_for_callbacks()
        event = _make_event(
            old_state=_make_state("0.3"),
            new_state=_make_state("0.8"),
        )
        coord._handle_rain_sensor_change(event)
        coord.hass.async_create_task.assert_not_called()

    def test_none_new_state_ignored(self):
        """Kein neuer State → kein Refresh."""
        coord = _make_coord_for_callbacks()
        event = _make_event(old_state=_make_state("0.5"), new_state=None)
        coord._handle_rain_sensor_change(event)
        coord.hass.async_create_task.assert_not_called()


# ── Weather-Condition-Listener ────────────────────────────────────────────────

class TestWeatherConditionListener:

    def test_rainy_condition_triggers_refresh(self):
        """Wetter wechselt zu 'rainy' → Refresh."""
        coord = _make_coord_for_callbacks()
        event = _make_event(
            old_state=_make_state("sunny"),
            new_state=_make_state("rainy"),
        )
        coord._handle_weather_state_change(event)
        coord.hass.async_create_task.assert_called()

    def test_rainy_to_sunny_triggers_refresh(self):
        """Wetter wechselt von 'rainy' → Refresh."""
        coord = _make_coord_for_callbacks()
        event = _make_event(
            old_state=_make_state("rainy"),
            new_state=_make_state("sunny"),
        )
        coord._handle_weather_state_change(event)
        coord.hass.async_create_task.assert_called()

    def test_sunny_to_cloudy_no_refresh(self):
        """Nicht-Regen zu nicht-Regen → kein Refresh."""
        coord = _make_coord_for_callbacks()
        event = _make_event(
            old_state=_make_state("sunny"),
            new_state=_make_state("cloudy"),
        )
        coord._handle_weather_state_change(event)
        coord.hass.async_create_task.assert_not_called()

    def test_none_new_state_ignored(self):
        coord = _make_coord_for_callbacks()
        event = _make_event(old_state=_make_state("rainy"), new_state=None)
        coord._handle_weather_state_change(event)
        coord.hass.async_create_task.assert_not_called()
