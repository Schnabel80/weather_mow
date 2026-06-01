"""Tests für _flush_storage, _migrate_from_v3, _write_debug_csv und Grace-Period-Restore."""

from __future__ import annotations

import os
import tempfile
from collections import deque
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.const import (
    RAIN_BUFFER_MAXLEN,
    WETNESS_MAX_MM,
)
from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Minimal-Coordinator ───────────────────────────────────────────────────────


def _bare():
    hass = MagicMock()
    hass.config.path = lambda f: f"/tmp/{f}"
    entry = MagicMock()
    entry.entry_id = "st_test"
    entry.data = {"name": "Test"}
    entry.options = {}
    c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
    c.hass = hass
    c.entry = entry
    c._rain_buffer = deque([0.0] * RAIN_BUFFER_MAXLEN, maxlen=RAIN_BUFFER_MAXLEN)
    c._radiation_peak = 600.0
    c._wetness_mm = 0.5
    c._below_threshold_since = None
    c._duration_today_s = 3600.0
    c._duration_yesterday_s = 7200.0
    c._duration_day_before_s = 1800.0
    c._growth_gdd_accum = 2.5
    c._mow_since_last_gdd_reset_s = 1200.0
    c._last_drying_mm = 0.02
    c._store_mowing = AsyncMock()
    c._store_rain = AsyncMock()
    c._store_solar = AsyncMock()
    c._store_growth = AsyncMock()
    c._store_wetness = AsyncMock()
    return c


# ── _flush_storage ────────────────────────────────────────────────────────────


class TestFlushStorage:
    async def test_saves_mowing_data(self):
        c = _bare()
        await c._flush_storage()
        call_args = c._store_mowing.async_save.call_args[0][0]
        assert call_args["today_s"] == pytest.approx(3600.0)
        assert call_args["yesterday_s"] == pytest.approx(7200.0)
        assert call_args["day_before_s"] == pytest.approx(1800.0)

    async def test_saves_rain_buffer(self):
        c = _bare()
        c._rain_buffer[-1] = 0.5
        await c._flush_storage()
        call_args = c._store_rain.async_save.call_args[0][0]
        assert "buffer" in call_args
        assert call_args["buffer"][-1] == pytest.approx(0.5)

    async def test_saves_solar_peak(self):
        c = _bare()
        c._radiation_peak = 850.0
        await c._flush_storage()
        call_args = c._store_solar.async_save.call_args[0][0]
        assert call_args["peak"] == pytest.approx(850.0)

    async def test_saves_growth(self):
        c = _bare()
        await c._flush_storage()
        call_args = c._store_growth.async_save.call_args[0][0]
        assert call_args["gdd_accum"] == pytest.approx(2.5)
        assert call_args["mow_since_reset_s"] == pytest.approx(1200.0)

    async def test_saves_wetness_with_none_threshold(self):
        c = _bare()
        c._below_threshold_since = None
        await c._flush_storage()
        call_args = c._store_wetness.async_save.call_args[0][0]
        assert call_args["wetness_mm"] == pytest.approx(0.5)
        assert call_args["below_threshold_ts"] is None

    async def test_saves_wetness_with_threshold_timestamp(self):
        c = _bare()
        c._below_threshold_since = dt_util.now() - timedelta(minutes=10)
        await c._flush_storage()
        call_args = c._store_wetness.async_save.call_args[0][0]
        assert call_args["below_threshold_ts"] is not None
        assert isinstance(call_args["below_threshold_ts"], float)

    async def test_saves_wetness_with_saved_at_timestamp(self):
        """_flush_storage schreibt saved_at-Timestamp für Plausibilitätsprüfung beim Laden."""
        c = _bare()
        await c._flush_storage()
        call_args = c._store_wetness.async_save.call_args[0][0]
        assert "saved_at" in call_args
        assert isinstance(call_args["saved_at"], float)
        # saved_at sollte etwa jetzt sein (< 5s Abstand)
        import time

        assert abs(call_args["saved_at"] - time.time()) < 5.0


# ── _migrate_from_v3 ──────────────────────────────────────────────────────────


class TestMigrateFromV3:
    async def test_empty_buffer_sets_zero(self):
        c = _bare()
        c._rain_buffer = deque([0.0] * RAIN_BUFFER_MAXLEN, maxlen=RAIN_BUFFER_MAXLEN)
        await c._migrate_from_v3()
        assert c._wetness_mm == 0.0

    async def test_recent_rain_sets_wetness(self):
        c = _bare()
        buf = [0.0] * RAIN_BUFFER_MAXLEN
        buf[-1] = 2.0  # frischer Regen
        c._rain_buffer = deque(buf, maxlen=RAIN_BUFFER_MAXLEN)
        await c._migrate_from_v3()
        assert c._wetness_mm > 0.0
        assert c._wetness_mm <= WETNESS_MAX_MM


# ── Grace-Period-Restore in _load_storage ────────────────────────────────────


class TestGracePeriodRestore:
    async def test_restores_valid_below_threshold_ts(self):
        """Gültiger Timestamp von heute wird als _below_threshold_since geladen."""
        c = _bare()
        # Timestamp von 20 Minuten her (heute, gültig)
        ts = (dt_util.utcnow() - timedelta(minutes=20)).timestamp()
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(
            return_value={"wetness_mm": 0.3, "below_threshold_ts": ts}
        )
        await c._load_storage()
        assert c._below_threshold_since is not None

    async def test_ignores_yesterday_timestamp(self):
        """Timestamp von gestern wird ignoriert (Grace Period abgelaufen)."""
        c = _bare()
        ts = (dt_util.utcnow() - timedelta(days=1)).timestamp()
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(
            return_value={"wetness_mm": 0.3, "below_threshold_ts": ts}
        )
        await c._load_storage()
        # Gestern → nicht wiederhergestellt
        assert c._below_threshold_since is None

    async def test_loads_growth_data(self):
        c = _bare()
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(
            return_value={"gdd_accum": 4.2, "mow_since_reset_s": 3600.0}
        )
        c._store_wetness.async_load = AsyncMock(return_value=None)
        with patch.object(c, "_migrate_from_v3", AsyncMock()):
            await c._load_storage()
        assert c._growth_gdd_accum == pytest.approx(4.2)
        assert c._mow_since_last_gdd_reset_s == pytest.approx(3600.0)


# ── Wetness Plausibilitätsprüfung beim Laden ─────────────────────────────────


class TestWetnessPlausibilityOnLoad:
    """Regression: Schnelle Reloads dürfen keine inkonsistente wetness laden."""

    def _make_stores(self, wetness_mm, saved_ago_s, rain_buffer_sum=0.0):
        """Hilfsmethode: liefert koordinierten Mock-Zustand."""
        import time

        c = _bare()
        # Regen-Puffer mit gegebener Summe füllen (alle Slots gleich)
        slot_val = rain_buffer_sum / RAIN_BUFFER_MAXLEN
        c._rain_buffer = deque(
            [slot_val] * RAIN_BUFFER_MAXLEN, maxlen=RAIN_BUFFER_MAXLEN
        )
        saved_at = time.time() - saved_ago_s
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(
            return_value={
                "wetness_mm": wetness_mm,
                "below_threshold_ts": None,
                "saved_at": saved_at,
            }
        )
        return c

    async def test_plausible_wetness_not_capped(self):
        """Normaler Wert (Regen > Nässe) wird nicht verändert."""
        # 0.8mm Regen in Buffer, 0.6mm Nässe gespeichert — plausibel
        c = self._make_stores(wetness_mm=0.6, saved_ago_s=300, rain_buffer_sum=0.8)
        await c._load_storage()
        assert c._wetness_mm == pytest.approx(0.6)

    async def test_rapid_reload_caps_implausible_wetness(self):
        """Schneller Reload (5min): zu hohe Nässe wird auf Regen+Tau-Allowance gekürzt."""
        # 0.8mm Regen in Buffer, aber 1.56mm gespeichert — Inkonsistenz wie am 31.05.
        # Bei 5 min elapsed: max Kondensation ≈ 0.009mm → Obergrenze ≈ 0.809mm
        c = self._make_stores(wetness_mm=1.56, saved_ago_s=300, rain_buffer_sum=0.8)
        await c._load_storage()
        # Muss deutlich unter 1.56mm liegen (nahe 0.8mm)
        assert c._wetness_mm < 1.0
        assert c._wetness_mm >= 0.0

    async def test_overnight_restart_allows_condensation(self):
        """Langer Neustart (8h): Tau-Kondensation ist als Grund für höhere Nässe OK."""
        # 0.1mm Regen, 8h Pause → max Kondensation ≈ 0.86mm → Obergrenze ≈ 0.96mm
        # Gespeichert: 0.9mm → plausibel, darf nicht gekürzt werden
        c = self._make_stores(
            wetness_mm=0.9, saved_ago_s=8 * 3600, rain_buffer_sum=0.1
        )
        await c._load_storage()
        assert c._wetness_mm == pytest.approx(0.9)

    async def test_no_saved_at_uses_fallback(self):
        """Fehlendes saved_at (alter Store) → Fallback-Toleranz, kein Crash."""
        c = _bare()
        c._rain_buffer = deque([0.0] * RAIN_BUFFER_MAXLEN, maxlen=RAIN_BUFFER_MAXLEN)
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        # Kein saved_at → alter Store-Format
        c._store_wetness.async_load = AsyncMock(
            return_value={"wetness_mm": 0.5, "below_threshold_ts": None}
        )
        await c._load_storage()
        # Muss ohne Exception durchlaufen; Wert zumindest ≥ 0
        assert c._wetness_mm >= 0.0

    async def test_wetness_capped_to_wetness_max(self):
        """Gespeicherter Wert > WETNESS_MAX_MM wird immer auf Maximum begrenzt."""
        c = self._make_stores(
            wetness_mm=5.0, saved_ago_s=0, rain_buffer_sum=10.0
        )
        await c._load_storage()
        assert c._wetness_mm <= WETNESS_MAX_MM


# ── _write_debug_csv ──────────────────────────────────────────────────────────


class TestWriteDebugCsv:
    def test_creates_csv_with_header(self):
        c = _bare()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            tmp_path = f.name
        os.unlink(tmp_path)  # Datei löschen damit _write_debug_csv den Header schreibt
        try:
            c.hass.config.path = lambda name: tmp_path
            data = {
                "wetness_mm": 0.5,
                "wetness_score": 25,
                "priority": 42,
                "start_now": True,
                "mow_allowed": True,
                "stop_now": False,
                "block_reason": "mowing_allowed",
                "emergency_mow_active": False,
                "raining": False,
                "dew_present": False,
                "brightness_ok": True,
                "sun_elevation": 45.0,
                "rain_last_1h_mm": 0.0,
                "rain_weighted_12h": 0.1,
                "rain_today_mm": 0.0,
                "rain_today_remaining": 0.0,
                "rain_tomorrow": 0.0,
                "radiation_peak": 700.0,
                "battery_pct": 100.0,
                "duration_today_h": 1.5,
                "duration_avg_3d_h": 2.0,
                "growth_mm": 3.0,
                "growth_ratio": 0.15,
                "fertilizer_active": False,
                "irrigation_active": False,
                "next_mow_expected": None,
                "wind_kmh": 5.0,
                "vpd_c": 8.0,
                "eff_solar": 0.6,
                "drying_mm": 0.025,
                "cond_mm": 0.0,
                "rain_delta_mm": 0.0,
                "condition_slot_mm": 0.0,
                "temp_c": 22.0,
            }
            # Erst aufrufen (schreibt Header + erste Zeile)
            c._write_debug_csv(data)
            # Zweites Mal (kein Header, nur Zeile)
            c._write_debug_csv(data)

            with open(tmp_path, encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) >= 2  # Header + mind. 1 Datenzeile
            assert "timestamp" in lines[0]
            assert "wetness_mm" in lines[0]
        finally:
            os.unlink(tmp_path)

    def test_handles_oserror_gracefully(self):
        """OSError beim Schreiben → kein Absturz."""
        c = _bare()
        c.hass.config.path = lambda f: "/nonexistent_dir/test.csv"
        data = {"wetness_mm": 0.5}
        # Darf keine Exception werfen
        c._write_debug_csv(data)
