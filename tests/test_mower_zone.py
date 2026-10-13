"""Tests für den Mehrflächenbetrieb: ein Mäher, eine Instanz pro Rasenfläche."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

from homeassistant.util import dt as dt_util

from custom_components.weather_mow.coordinator import WeatherMowCoordinator

ZONE_ENTITY = "input_number.mower_zone"


def _make_coord(zone_state: str | None, own_zone: int = 2, zone_entity: str | None = ZONE_ENTITY):
    hass = MagicMock()
    hass.async_create_task = MagicMock()
    states = {}
    if zone_state is not None:
        s = MagicMock()
        s.state = zone_state
        states[ZONE_ENTITY] = s
    hass.states.get = lambda entity_id: states.get(entity_id)

    entry = MagicMock()
    entry.entry_id = "zone_test"
    data = {
        "name": "Test",
        "mower_entity_id": "lawn_mower.test",
        "prevent_auto_resume": True,
        "zone_id": own_zone,
    }
    if zone_entity:
        data["zone_entity_id"] = zone_entity
    entry.data = data
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


def _state(state_str, last_updated=None):
    s = MagicMock()
    s.state = state_str
    s.last_updated = last_updated or dt_util.utcnow()
    return s


def _event(old, new):
    e = MagicMock()
    e.data = {"old_state": old, "new_state": new}
    return e


def _cfg(coord):
    return {**coord.entry.data, **coord.entry.options}


# ── Zuordnung ─────────────────────────────────────────────────────────────────


def test_without_zone_entity_every_session_counts():
    coord = _make_coord(None, zone_entity=None)
    assert coord._mower_on_this_zone(_cfg(coord)) is True


def test_matching_zone_is_own():
    assert _make_coord("2")._mower_on_this_zone(_cfg(_make_coord("2"))) is True


def test_float_zone_state_matches():
    coord = _make_coord("2.0")
    assert coord._mower_on_this_zone(_cfg(coord)) is True


def test_other_zone_is_foreign():
    coord = _make_coord("1")
    assert coord._mower_on_this_zone(_cfg(coord)) is False


def test_unavailable_zone_is_not_attributed():
    for bad in ("unavailable", "unknown", "garden", None):
        coord = _make_coord(bad)
        assert coord._mower_on_this_zone(_cfg(coord)) is False, bad


# ── Session-Tracking ──────────────────────────────────────────────────────────


def test_session_in_own_zone_is_counted():
    coord = _make_coord("2")
    coord._handle_mower_state_change(_event(_state("docked"), _state("mowing")))
    assert coord._mow_start_ts is not None
    coord._mow_start_ts = dt_util.utcnow().timestamp() - 600
    coord._handle_mower_state_change(_event(_state("mowing"), _state("docked")))
    assert coord._duration_today_s >= 590


def test_session_in_foreign_zone_is_ignored():
    coord = _make_coord("1")
    coord._handle_mower_state_change(_event(_state("docked"), _state("mowing")))
    assert coord._mow_start_ts is None
    assert coord._auto_resume_blocked is False  # kein Stopp für fremde Zone
    # Ende: selbst der last_updated-Fallback darf nichts zählen
    old = _state("mowing", dt_util.utcnow() - datetime.timedelta(minutes=30))
    coord._handle_mower_state_change(_event(old, _state("docked")))
    assert coord._duration_today_s == 0.0
    assert coord._mow_foreign_session is False


def test_zone_change_after_foreign_session_counts_next_session():
    coord = _make_coord("1")
    coord._handle_mower_state_change(_event(_state("docked"), _state("mowing")))
    coord._handle_mower_state_change(_event(_state("mowing"), _state("docked")))
    # Nutzer-Automation stellt auf Zone 2, nächster Start zählt
    coord.hass.states.get = lambda _eid: _state("2")
    coord._handle_mower_state_change(_event(_state("docked"), _state("mowing")))
    assert coord._mow_start_ts is not None


def test_unauthorized_start_in_own_zone_still_blocks():
    coord = _make_coord("2")
    coord._handle_mower_state_change(_event(_state("docked"), _state("mowing")))
    assert coord._auto_resume_blocked is True
