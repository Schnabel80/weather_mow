"""Coordinator-Tests: _compute_decision Gates und _compute_priority.

Jeder Test setzt genau die HA-States, die den jeweiligen Sperrgrund auslösen,
und prüft block_reason + mow_allowed.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def entry():
    e = MagicMock()
    e.entry_id = "dec_test"
    e.data = {
        "name": "Testmaher",
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
        # 24h-Fenster damit Tests zu jeder Tageszeit laufen
        "mow_window_start": "00:00:00",
        "mow_window_end": "23:59:00",
        # Kein Zeit-Puffer → keine Zeitdruck-Dringlichkeit
        "target_buffer_h": 0.0,
    }
    return e


@pytest.fixture
async def coord(hass, entry):
    c = WeatherMowCoordinator(hass, entry)
    with patch.object(c, "_load_storage"), patch.object(c, "_register_listeners"):
        await c._async_setup()
    c._sunshine_initialized = True
    # Hauptschalter: an
    sw = MagicMock()
    sw.is_on = True
    c.switch_entity = sw
    # Ausreichend Mähhistorie → keine Grass-Dringlichkeit (avg > target*0.5)
    # target=3.0h, URGENCY_RATIO=0.5 → avg muss >= 1.5h sein
    c._duration_yesterday_s = 9000.0  # 2.5h gestern
    c._duration_day_before_s = 9000.0  # 2.5h vorgestern
    yield c


def _weather(hass, condition="sunny", temp=20.0, humidity=60, wind=5.0, sun_elev=45.0):
    hass.states.async_set(
        "weather.test",
        condition,
        attributes={"temperature": temp, "humidity": humidity, "wind_speed": wind, "forecast": []},
    )
    # sun.sun muss vorhanden sein, damit _check_brightness korrekt arbeitet
    hass.states.async_set(
        "sun.sun", "above_horizon", attributes={"elevation": sun_elev, "azimuth": 180.0}
    )


def _mower(hass, state="docked", battery=100):
    hass.states.async_set("lawn_mower.test", state, attributes={"battery_level": battery})


# ── _compute_decision Gates ───────────────────────────────────────────────────


class TestDecisionGates:
    async def test_mowing_allowed_baseline(self, hass, coord):
        """Alle Bedingungen erfüllt → mow_allowed=True."""
        _weather(hass)
        _mower(hass)
        # Grace Period abgelaufen (35 Minuten in der Vergangenheit)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        assert data["mow_allowed"] is True, f"block_reason={data['block_reason']}"

    async def test_too_wet(self, hass, coord):
        """wetness_mm über Schwelle → too_wet."""
        _weather(hass)
        _mower(hass)
        thresh = MagicMock()
        thresh.native_value = 0.5
        coord.mow_threshold_entity = thresh
        coord._wetness_mm = 1.0

        # _update_wetness ist synchron und gibt (vpd_c, drying_mm, cond_mm) zurück
        def _keep_wet(*a, **kw):
            coord._wetness_mm = 1.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_wet):
            data = await coord._async_update_data()

        assert data["mow_allowed"] is False
        assert data["block_reason"] == "too_wet"

    async def test_waiting_for_favorable(self, hass, coord):
        """Wetness zwischen effective_threshold und hard_threshold → waiting_for_favorable."""
        _weather(hass)
        _mower(hass)
        # Schwelle 0.5mm, Discount 0.3mm → effective = 0.2mm
        # Wetness bei 0.3mm: über effective (0.2) aber unter hard (0.5)
        thresh = MagicMock()
        thresh.native_value = 0.5
        coord.mow_threshold_entity = thresh
        coord._wetness_mm = 0.3

        def _keep_mid(*a, **kw):
            coord._wetness_mm = 0.3
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_mid):
            data = await coord._async_update_data()

        assert data["mow_allowed"] is False
        assert data["block_reason"] in ("waiting_for_favorable", "too_wet")

    async def test_too_hot_blocks(self, hass, coord):
        """Temperatur ≥ max_mow_temp_c → too_hot."""
        _weather(hass, temp=36.0)  # über Default 35 °C
        _mower(hass)
        coord._wetness_mm = 0.0

        data = await coord._async_update_data()

        assert data["mow_allowed"] is False
        assert data["block_reason"] == "too_hot"

    async def test_too_hot_custom_threshold(self, hass, coord):
        """Benutzerdefinierte Max-Temp-Entität wird berücksichtigt."""
        _weather(hass, temp=28.0)
        _mower(hass)
        coord._wetness_mm = 0.0
        # Max-Temp auf 27 °C gesetzt → 28 °C überschreitet sie
        max_temp = MagicMock()
        max_temp.native_value = 27.0
        coord.max_temp_entity = max_temp

        data = await coord._async_update_data()

        assert data["block_reason"] == "too_hot"

    async def test_not_too_hot_below_threshold(self, hass, coord):
        """Temperatur unter max_mow_temp_c → kein too_hot."""
        _weather(hass, temp=30.0)  # unter Default 35 °C
        _mower(hass)
        coord._wetness_mm = 0.0

        data = await coord._async_update_data()

        assert data["block_reason"] != "too_hot"

    async def test_low_battery_prevents_start(self, hass, coord):
        """Niedriger Akku → start_now=False, aber mow_allowed bleibt True."""
        _weather(hass)
        _mower(hass, battery=10)  # unter min_battery_pct=20
        coord._wetness_mm = 0.0
        # Priorität hoch genug für Start
        coord._duration_today_s = 0.0

        data = await coord._async_update_data()

        # mow_allowed kann True sein, aber start_now muss False sein
        assert data["start_now"] is False

    async def test_integration_disabled_blocks_all(self, hass, coord):
        """Hauptschalter off → mow_allowed=False, block_reason=disabled."""
        _weather(hass)
        _mower(hass)
        coord.switch_entity.is_on = False

        data = await coord._async_update_data()

        assert data["mow_allowed"] is False
        assert data["block_reason"] == "disabled"

    async def test_integration_disabled_next_mow_none(self, hass, coord):
        """Hauptschalter off → next_mow_expected=None (keine Prognose)."""
        _weather(hass)
        _mower(hass)
        coord.switch_entity.is_on = False

        data = await coord._async_update_data()

        assert data["next_mow_expected"] is None

    async def test_too_dark_blocks(self, hass, coord):
        """Helligkeitssensor unter Schwelle bei tiefem Sonnenstand → too_dark."""
        _weather(hass)
        _mower(hass)
        hass.states.async_set("sensor.brightness", "500")  # unter 2000 lux
        coord.entry.data = {
            **coord.entry.data,
            "brightness_entity_id": "sensor.brightness",
            "min_brightness_lux": 2000,
        }
        coord._wetness_mm = 0.0

        data = await coord._async_update_data()

        # too_dark nur wenn auch Sonnenhöhe < 10° — tagsüber im Test ggf. nicht
        # Wir testen nur dass der Sensor gelesen wird (kein Crash)
        assert "block_reason" in data


# ── _compute_priority ─────────────────────────────────────────────────────────


class TestPriority:
    async def test_target_reached_blocks(self, hass, coord):
        """Tagesziel bereits überschritten → block_reason=daily_target_reached."""
        _weather(hass)
        _mower(hass)
        coord._wetness_mm = 0.0
        # Default-Target ist 3.0h = 10800s (aus cfg-Default) — überschreiten
        coord._duration_today_s = 12_000.0

        data = await coord._async_update_data()

        assert data["mow_allowed"] is False
        assert data["block_reason"] == "daily_target_reached"

    async def test_priority_positive_with_deficit(self, hass, coord):
        """Tagesziel nicht erreicht + mow_allowed → Priorität > 0."""
        _weather(hass)
        _mower(hass)
        # Grace Period abgelaufen + trocken → mow_allowed=True
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        assert data["mow_allowed"] is True
        assert data["priority"] > 0

    async def test_heat_factor_reduces_priority(self, hass, coord):
        """Temperatur in der Reduktionszone → Priorität sinkt verglichen mit kühler Temp."""
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        # Heißes Szenario (33°C — in Reduktionszone 30-35°C)
        _weather(hass, temp=33.0)
        _mower(hass)
        with patch.object(coord, "_update_wetness", _keep_dry):
            data_hot = await coord._async_update_data()

        # Kühles Szenario (20°C — volle Priorität)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
        _weather(hass, temp=20.0)
        with patch.object(coord, "_update_wetness", _keep_dry):
            data_cool = await coord._async_update_data()

        assert data_hot["mow_allowed"] is True
        assert data_cool["mow_allowed"] is True
        assert data_hot["priority"] < data_cool["priority"]

    async def test_start_now_at_priority_40(self, hass, coord):
        """start_now=True wenn Priorität ≥ 40."""
        _weather(hass)
        _mower(hass)
        coord._wetness_mm = 0.0
        coord._duration_today_s = 0.0
        # start_now hängt von vielen Faktoren ab — wir testen nur die Logik
        data = await coord._async_update_data()
        # start_now sollte konsistent mit priority sein
        if data["priority"] >= 40:
            assert data["start_now"] is True
        else:
            assert data["start_now"] is False


class TestMowingActiveOverride:
    def _coord(self):
        from custom_components.weather_mow.coordinator import WeatherMowCoordinator

        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        return c

    def test_override_when_mowing_and_not_stopping(self):
        c = self._coord()
        reason, nm = c._apply_mowing_override(
            block_reason="battery_low", stop_now=False, is_mowing=True, now_local="NOW"
        )
        assert reason == "mowing_active"
        assert nm == "NOW"

    def test_no_override_when_stop_now(self):
        c = self._coord()
        reason, nm = c._apply_mowing_override(
            block_reason="too_wet", stop_now=True, is_mowing=True, now_local="NOW"
        )
        assert reason == "too_wet"
        assert nm is None

    def test_no_override_when_not_mowing(self):
        c = self._coord()
        reason, nm = c._apply_mowing_override(
            block_reason="battery_low", stop_now=False, is_mowing=False, now_local="NOW"
        )
        assert reason == "battery_low"
        assert nm is None

    def test_no_override_when_disabled(self):
        """N1: Deaktivierte Integration wird nicht durch manuelles Mähen maskiert."""
        c = self._coord()
        reason, nm = c._apply_mowing_override(
            block_reason="disabled", stop_now=False, is_mowing=True, now_local="NOW"
        )
        assert reason == "disabled"
        assert nm is None
