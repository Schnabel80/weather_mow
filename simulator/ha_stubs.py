"""
Inject fake homeassistant.* modules so coordinator.py can be imported
without a real Home Assistant installation.

Call install_stubs() once before importing anything from weather_mow.
"""

from __future__ import annotations

import asyncio
import sys
import types
import zoneinfo
from datetime import UTC, date, datetime, time

_BERLIN = zoneinfo.ZoneInfo("Europe/Berlin")

# ── Time control ─────────────────────────────────────────────────────────────

_sim_time_utc: datetime | None = None


def set_sim_time(dt_utc: datetime) -> None:
    """Set the simulated current time (UTC). Called each tick by run_simulation."""
    global _sim_time_utc
    _sim_time_utc = dt_utc


def _utcnow() -> datetime:
    if _sim_time_utc is not None:
        return _sim_time_utc
    return datetime.now(UTC)


def _now() -> datetime:
    return _utcnow().astimezone(_BERLIN)


# ── Mock classes ──────────────────────────────────────────────────────────────


class MockState:
    def __init__(
        self, state: str, attributes: dict | None = None, last_updated: datetime | None = None
    ):
        self.state = str(state)
        self.attributes = attributes or {}
        self.last_updated = last_updated or _utcnow()


class MockEvent:
    """Minimal event wrapper for _on_mow_state_change."""

    def __init__(self, data: dict):
        self.data = data


class MockStates:
    def __init__(self):
        self._store: dict[str, MockState] = {}

    def get(self, entity_id: str) -> MockState | None:
        return self._store.get(entity_id)

    def set(
        self,
        entity_id: str,
        state: str,
        attributes: dict | None = None,
        last_updated: datetime | None = None,
    ) -> None:
        self._store[entity_id] = MockState(state, attributes, last_updated)


class MockConfig:
    def path(self, *parts: str) -> str:
        import os

        p = os.path.join("/tmp/weather_mow_sim", *parts)
        os.makedirs(
            os.path.dirname(p) if os.path.dirname(p) else "/tmp/weather_mow_sim", exist_ok=True
        )
        return p


class MockServices:
    async def async_call(self, *args, **kwargs) -> None:
        pass


class MockHass:
    """Minimal hass object the coordinator calls into."""

    def __init__(self):
        self.states = MockStates()
        self.config = MockConfig()
        self.services = MockServices()
        self._pending: list = []

    def async_create_task(self, coro) -> None:
        self._pending.append(coro)

    async def async_add_executor_job(self, func, *args):
        return func(*args)

    async def drain_tasks(self) -> None:
        while self._pending:
            batch = self._pending[:]
            self._pending.clear()
            await asyncio.gather(*batch, return_exceptions=True)


class MockStore:
    def __init__(self, hass, version, key):
        self._data: dict | None = None

    async def async_load(self) -> dict | None:
        return self._data

    async def async_save(self, data: dict) -> None:
        self._data = data


class MockConfigEntry:
    def __init__(self, data: dict, options: dict | None = None):
        self.entry_id = "sim_entry_001"
        self.data = data
        self.options = options or {}


class _DataUpdateCoordinator[T]:
    def __init__(self, hass, logger, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data: dict | None = None

    async def async_request_refresh(self) -> None:
        pass  # no-op — simulation calls _async_update_data directly


class _UpdateFailed(Exception):
    pass


# ── Module factories ──────────────────────────────────────────────────────────


def _make_dt_util() -> types.ModuleType:
    m = types.ModuleType("homeassistant.util.dt")

    m.now = _now
    m.utcnow = _utcnow

    def as_local(dt: datetime) -> datetime:
        return dt.astimezone(_BERLIN)

    def as_utc(dt: datetime) -> datetime:
        return dt.astimezone(UTC)

    def parse_time(s: str) -> time:
        return time.fromisoformat(s)

    def parse_datetime(s: str) -> datetime | None:
        try:
            return datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    def parse_date(s: str) -> date | None:
        try:
            return date.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    m.as_local = as_local
    m.as_utc = as_utc
    m.parse_time = parse_time
    m.parse_datetime = parse_datetime
    m.parse_date = parse_date
    return m


def install_stubs() -> None:
    """
    Inject all required homeassistant.* stubs into sys.modules.
    Must be called before any weather_mow import.
    """
    const = types.ModuleType("homeassistant.const")
    const.STATE_ON = "on"
    const.STATE_UNAVAILABLE = "unavailable"
    const.STATE_UNKNOWN = "unknown"

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = MockHass
    core.callback = lambda f: f

    ha_util = types.ModuleType("homeassistant.util")
    dt_util = _make_dt_util()
    ha_util.dt = dt_util

    ha_helpers = types.ModuleType("homeassistant.helpers")

    event_mod = types.ModuleType("homeassistant.helpers.event")
    event_mod.async_track_state_change_event = lambda hass, ids, fn: lambda: None
    event_mod.async_track_time_change = lambda hass, fn, **kw: lambda: None

    storage_mod = types.ModuleType("homeassistant.helpers.storage")
    storage_mod.Store = MockStore

    coord_mod = types.ModuleType("homeassistant.helpers.update_coordinator")
    coord_mod.DataUpdateCoordinator = _DataUpdateCoordinator
    coord_mod.UpdateFailed = _UpdateFailed

    config_entries_mod = types.ModuleType("homeassistant.config_entries")
    config_entries_mod.ConfigEntry = MockConfigEntry

    components_mod = types.ModuleType("homeassistant.components")
    persistent_notification_mod = types.ModuleType(
        "homeassistant.components.persistent_notification"
    )
    components_mod.persistent_notification = persistent_notification_mod

    ha = types.ModuleType("homeassistant")

    modules = {
        "homeassistant": ha,
        "homeassistant.const": const,
        "homeassistant.core": core,
        "homeassistant.util": ha_util,
        "homeassistant.util.dt": dt_util,
        "homeassistant.helpers": ha_helpers,
        "homeassistant.helpers.event": event_mod,
        "homeassistant.helpers.storage": storage_mod,
        "homeassistant.helpers.update_coordinator": coord_mod,
        "homeassistant.config_entries": config_entries_mod,
        "homeassistant.components": components_mod,
        "homeassistant.components.persistent_notification": persistent_notification_mod,
    }
    for name, mod in modules.items():
        sys.modules.setdefault(name, mod)
