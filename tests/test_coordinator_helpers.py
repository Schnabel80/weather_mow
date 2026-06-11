"""Tests für Helper-Methoden des Coordinators.

Abgedeckt: _get_radiation, _compute_weighted_rain, _build_rain_normalizer,
_load_storage, _get_wind_kmh, _get_sun_elevation.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.weather_mow.const import (
    RAIN_BUFFER_MAXLEN,
    SOLAR_PEAK_MIN,
    WETNESS_MAX_MM,
)
from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Minimal-Koordinator ───────────────────────────────────────────────────────


def _bare(hass=None):
    if hass is None:
        hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "hlp_test"
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
    return c


# ── _get_sun_elevation ────────────────────────────────────────────────────────


class TestGetSunElevation:
    def test_returns_elevation_from_sun_entity(self):
        hass = MagicMock()
        hass.states.get.return_value = MagicMock(attributes={"elevation": 42.5})
        c = _bare(hass)
        assert c._get_sun_elevation() == pytest.approx(42.5)

    def test_returns_zero_when_no_sun_entity(self):
        hass = MagicMock()
        hass.states.get.return_value = None
        c = _bare(hass)
        assert c._get_sun_elevation() == 0.0


# ── _get_radiation ────────────────────────────────────────────────────────────


class TestGetRadiation:
    def _cfg(self, **kw):
        return {
            "local_radiation_entity_id": "",
            "radiation_forecast_entity_id": "",
            "radiation_source": "sun",
            "pv_power_entity_id": "",
            "pv_peak_kw": 6.4,
            **kw,
        }

    def test_local_sensor_first_priority(self):
        hass = MagicMock()
        hass.states.get = lambda eid: MagicMock(state="650.0") if eid == "sensor.solar" else None
        c = _bare(hass)
        cfg = self._cfg(local_radiation_entity_id="sensor.solar")
        assert c._get_radiation(cfg, sun_elev=0.0) == pytest.approx(650.0)

    def test_forecast_sensor_second_priority(self):
        hass = MagicMock()
        hass.states.get = lambda eid: MagicMock(state="400.0") if eid == "sensor.rad_fc" else None
        c = _bare(hass)
        cfg = self._cfg(radiation_forecast_entity_id="sensor.rad_fc")
        assert c._get_radiation(cfg, sun_elev=0.0) == pytest.approx(400.0)

    def test_pv_power_fallback(self):
        hass = MagicMock()
        # PV leistet 3200W bei 6.4kWp → 3200/(6400) * 1000 = 500 W/m²
        hass.states.get = lambda eid: MagicMock(state="3200.0") if eid == "sensor.pv" else None
        c = _bare(hass)
        cfg = self._cfg(
            radiation_source="pv",
            pv_power_entity_id="sensor.pv",
            pv_peak_kw=6.4,
        )
        result = c._get_radiation(cfg, sun_elev=0.0)
        assert result == pytest.approx(500.0)

    def test_sun_elevation_fallback(self):
        """Kein Sensor → sin(elevation) × 800."""
        import math

        hass = MagicMock()
        hass.states.get.return_value = None
        c = _bare(hass)
        cfg = self._cfg()
        elev = 30.0
        expected = math.sin(math.radians(elev)) * 800
        assert c._get_radiation(cfg, sun_elev=elev) == pytest.approx(expected)

    def test_negative_values_clamped_to_zero(self):
        hass = MagicMock()
        hass.states.get = lambda eid: MagicMock(state="-10.0") if eid == "sensor.solar" else None
        c = _bare(hass)
        cfg = self._cfg(local_radiation_entity_id="sensor.solar")
        assert c._get_radiation(cfg, sun_elev=0.0) == 0.0


# ── _compute_weighted_rain ────────────────────────────────────────────────────


class TestComputeWeightedRain:
    def test_empty_buffer_returns_zero(self):
        c = _bare()
        c._rain_buffer = deque([0.0] * RAIN_BUFFER_MAXLEN, maxlen=RAIN_BUFFER_MAXLEN)
        assert c._compute_weighted_rain() == 0.0

    def test_recent_rain_has_highest_weight(self):
        """Regen im neuesten Slot (Index 0 bei reversed) hat Gewicht 1.0."""
        c = _bare()
        buf = [0.0] * RAIN_BUFFER_MAXLEN
        buf[0] = 1.0  # ältester Slot (Index 0 im Buffer)
        buf[-1] = 1.0  # neuester Slot
        c._rain_buffer = deque(buf, maxlen=RAIN_BUFFER_MAXLEN)
        total = c._compute_weighted_rain()
        # Ältester Slot: Gewicht 0.1, Neuester: Gewicht 1.0 → total ≈ 1.1
        assert total == pytest.approx(1.1, abs=0.05)

    def test_weighted_sum_correct(self):
        """Nur neuester Slot mit 2.0mm → Beitrag = 2.0 × 1.0 = 2.0."""
        c = _bare()
        buf = [0.0] * RAIN_BUFFER_MAXLEN
        buf[-1] = 2.0  # neuester Slot
        c._rain_buffer = deque(buf, maxlen=RAIN_BUFFER_MAXLEN)
        result = c._compute_weighted_rain()
        assert result == pytest.approx(2.0, abs=0.01)


# ── _build_rain_normalizer ────────────────────────────────────────────────────


class TestBuildRainNormalizer:
    def test_ecowitt_builds_cumulative_normalizer(self):
        c = _bare()
        cfg = {"rain_provider": "ecowitt", "rain_sensor_entity_id": "sensor.rain"}
        normalizer = c._build_rain_normalizer(cfg)
        assert normalizer is not None

    def test_no_sensor_returns_none(self):
        c = _bare()
        cfg = {"rain_provider": "ecowitt", "rain_sensor_entity_id": ""}
        normalizer = c._build_rain_normalizer(cfg)
        assert normalizer is None

    def test_none_provider_returns_none(self):
        c = _bare()
        cfg = {"rain_provider": "none", "rain_sensor_entity_id": "sensor.rain"}
        normalizer = c._build_rain_normalizer(cfg)
        assert normalizer is None


# ── _load_storage ─────────────────────────────────────────────────────────────


class TestLoadStorage:
    async def test_loads_mowing_data(self):
        c = _bare()
        c._store_mowing.async_load = AsyncMock(
            return_value={"today_s": 3600.0, "yesterday_s": 7200.0, "day_before_s": 1800.0}
        )
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(return_value=None)
        with patch.object(c, "_migrate_from_v3", AsyncMock()):
            await c._load_storage()
        assert c._duration_today_s == pytest.approx(3600.0)
        assert c._duration_yesterday_s == pytest.approx(7200.0)

    async def test_loads_rain_buffer(self):
        c = _bare()
        buf = [0.1, 0.2, 0.0] + [0.0] * (RAIN_BUFFER_MAXLEN - 3)
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value={"buffer": buf})
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(return_value=None)
        with patch.object(c, "_migrate_from_v3", AsyncMock()):
            await c._load_storage()
        assert list(c._rain_buffer)[:3] == pytest.approx([0.1, 0.2, 0.0])

    async def test_loads_solar_peak(self):
        c = _bare()
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value={"peak": 750.0})
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(return_value=None)
        with patch.object(c, "_migrate_from_v3", AsyncMock()):
            await c._load_storage()
        assert c._radiation_peak == pytest.approx(750.0)

    async def test_solar_peak_clamped_to_minimum(self):
        c = _bare()
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value={"peak": 1.0})  # zu niedrig
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(return_value=None)
        with patch.object(c, "_migrate_from_v3", AsyncMock()):
            await c._load_storage()
        assert c._radiation_peak >= SOLAR_PEAK_MIN

    async def test_loads_wetness(self):
        import time
        from collections import deque

        c = _bare()
        # Letzter Slot = 0.8mm (frischer Regen) → Plausibilitätscheck erlaubt 0.8mm
        buf = [0.0] * RAIN_BUFFER_MAXLEN
        buf[-1] = 0.8
        c._rain_buffer = deque(buf, maxlen=RAIN_BUFFER_MAXLEN)
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(
            return_value={
                "wetness_mm": 0.8,
                "below_threshold_ts": None,
                "saved_at": time.time() - 300,  # 5 min ago → 1 Slot relevant
            }
        )
        await c._load_storage()
        assert c._wetness_mm == pytest.approx(0.8)

    async def test_wetness_clamped_to_max(self):
        import time
        from collections import deque

        c = _bare()
        # Letzter Slot = WETNESS_MAX_MM → upper_bound = WETNESS_MAX_MM
        # Gespeicherter Wert 99.0 wird zuerst auf WETNESS_MAX_MM begrenzt
        buf = [0.0] * RAIN_BUFFER_MAXLEN
        buf[-1] = WETNESS_MAX_MM
        c._rain_buffer = deque(buf, maxlen=RAIN_BUFFER_MAXLEN)
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(
            return_value={
                "wetness_mm": 99.0,
                "below_threshold_ts": None,
                "saved_at": time.time() - 300,
            }
        )
        await c._load_storage()
        assert c._wetness_mm == pytest.approx(WETNESS_MAX_MM)

    async def test_empty_stores_keep_defaults(self):
        c = _bare()
        for store in [
            c._store_mowing,
            c._store_rain,
            c._store_solar,
            c._store_growth,
            c._store_wetness,
        ]:
            store.async_load = AsyncMock(return_value=None)
        with patch.object(c, "_migrate_from_v3", AsyncMock()):
            await c._load_storage()
        assert c._duration_today_s == 0.0
        assert c._wetness_mm == 0.0


# ── _get_wind_kmh ─────────────────────────────────────────────────────────────


class TestGetWindKmh:
    def test_reads_from_wind_sensor(self):
        hass = MagicMock()
        hass.states.get = lambda eid: MagicMock(state="12.5") if eid == "sensor.wind" else None
        c = _bare(hass)
        cfg = {"wind_sensor_entity_id": "sensor.wind"}
        assert c._get_wind_kmh(cfg) == pytest.approx(12.5)

    def test_falls_back_to_weather_entity(self):
        hass = MagicMock()
        hass.states.get = lambda eid: (
            MagicMock(state="sunny", attributes={"wind_speed": 8.0})
            if eid == "weather.test"
            else None
        )
        c = _bare(hass)
        cfg = {"wind_sensor_entity_id": "", "weather_entity_id": "weather.test"}
        result = c._get_wind_kmh(cfg)
        assert result == pytest.approx(8.0)

    def test_negative_clamped_to_zero(self):
        hass = MagicMock()
        hass.states.get = lambda eid: MagicMock(state="-5.0") if eid == "sensor.wind" else None
        c = _bare(hass)
        cfg = {"wind_sensor_entity_id": "sensor.wind"}
        assert c._get_wind_kmh(cfg) >= 0.0
