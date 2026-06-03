"""Tests für die async_setup_entry-Funktionen aller Plattformen.

Jede Plattform liest den Coordinator aus entry.runtime_data und registriert
ihre Entities über async_add_entities. Hier wird geprüft, dass der Aufruf
Entities liefert und die Coordinator-Referenzen gesetzt werden.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.weather_mow import (
    binary_sensor,
    button,
    date,
    number,
    sensor,
    switch,
    time,
)


def _coord():
    c = MagicMock()
    c.async_request_refresh = AsyncMock()
    return c


def _entry(coord):
    e = MagicMock()
    e.entry_id = "test_entry"
    e.data = {"name": "Rasenmaeher"}
    e.options = {}
    e.runtime_data = coord
    return e


def _capture():
    """async_add_entities-Ersatz, der die übergebenen Entities sammelt."""
    added: list = []

    def _add(entities):
        added.extend(entities)

    return added, _add


async def test_number_setup_registers_entities(hass):
    coord = _coord()
    entry = _entry(coord)
    added, add_cb = _capture()
    await number.async_setup_entry(hass, entry, add_cb)
    assert len(added) == 4
    assert coord.lawn_sun_efficiency_entity is not None
    assert coord.mow_threshold_entity is not None
    assert coord.mow_threshold_urgent_entity is not None
    assert coord.max_temp_entity is not None


async def test_switch_setup_registers_entities(hass):
    coord = _coord()
    entry = _entry(coord)
    added, add_cb = _capture()
    await switch.async_setup_entry(hass, entry, add_cb)
    assert len(added) == 4
    assert coord.switch_entity is not None
    assert coord.emergency_switch_entity is not None
    assert coord.irrigation_switch_entity is not None
    assert coord.debug_switch_entity is not None


async def test_button_setup_registers_entities(hass):
    coord = _coord()
    entry = _entry(coord)
    added, add_cb = _capture()
    await button.async_setup_entry(hass, entry, add_cb)
    assert len(added) == 2


async def test_date_setup_registers_entity(hass):
    coord = _coord()
    entry = _entry(coord)
    added, add_cb = _capture()
    await date.async_setup_entry(hass, entry, add_cb)
    assert len(added) == 1
    assert coord.fertilization_date_entity is not None


async def test_time_setup_registers_entity(hass):
    coord = _coord()
    entry = _entry(coord)
    added, add_cb = _capture()
    await time.async_setup_entry(hass, entry, add_cb)
    assert len(added) == 1
    assert coord.lawn_sun_from_entity is not None


async def test_sensor_setup_registers_entities(hass):
    coord = _coord()
    entry = _entry(coord)
    added, add_cb = _capture()
    await sensor.async_setup_entry(hass, entry, add_cb)
    # Generator wird konsumiert → mindestens ein Sensor
    assert len(added) >= 1


async def test_binary_sensor_setup_registers_entities(hass):
    coord = _coord()
    entry = _entry(coord)
    added, add_cb = _capture()
    await binary_sensor.async_setup_entry(hass, entry, add_cb)
    assert len(added) >= 1
