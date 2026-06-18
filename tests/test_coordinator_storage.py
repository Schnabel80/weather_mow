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
    c._prev_rain_today = 0.0
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

    async def test_saves_prev_rain_today(self):
        """_flush_storage persistiert _prev_rain_today — verhindert Wetness-Sprung nach Reload."""
        c = _bare()
        c._prev_rain_today = 3.7
        await c._flush_storage()
        call_args = c._store_wetness.async_save.call_args[0][0]
        assert "prev_rain_today" in call_args
        assert call_args["prev_rain_today"] == pytest.approx(3.7)


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

    def _make_stores(self, wetness_mm, saved_ago_s, recent_rain=0.0, old_rain=0.0):
        """Hilfsmethode: liefert koordinierten Mock-Zustand.

        recent_rain: mm Regen im LETZTEN Slot (entspricht den letzten 5 Minuten).
        old_rain: mm Regen in ÄLTEREN Slots (8-12h alt, zählt bei kurzem Reload nicht).
        """
        import time

        c = _bare()
        buf = [0.0] * RAIN_BUFFER_MAXLEN
        buf[-1] = recent_rain  # jüngster Slot
        if old_rain > 0:
            buf[20] = old_rain  # alter Slot (~100 Updates = ~500 min ago)
        c._rain_buffer = deque(buf, maxlen=RAIN_BUFFER_MAXLEN)
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
        """Normaler Wert (aktueller Regen > Nässe) wird nicht verändert.

        Szenario: Gerade eben 0.8mm Regen im letzten Slot, Nässe=0.6mm — plausibel.
        """
        # recent_rain=0.8mm im letzten Slot, saved 5 min ago (1 Update = 1 Slot)
        c = self._make_stores(wetness_mm=0.6, saved_ago_s=300, recent_rain=0.8)
        await c._load_storage()
        assert c._wetness_mm == pytest.approx(0.6)

    async def test_restart_preserves_wet_lawn(self):
        """Bug-Repro 2026-06-12: Restart bei nassem Rasen nullte die Nässe.

        Der Regen lag > 12 h zurück (Buffer leer im jungen Teil), wetness 0.485
        war legitimer Restzustand. Die frühere Plausibilitäts-Kappung begrenzte
        den geladenen Wert auf 'Regen+Kondensation seit letztem Speichern'
        (= Restart-Dauer ≈ Minuten) und zerstörte damit gültigen Zustand.
        Gespeicherte Nässe ist ein Zustand, kein Zuwachs — sie muss erhalten bleiben.
        """
        c = self._make_stores(wetness_mm=0.485, saved_ago_s=120, recent_rain=0.0)
        await c._load_storage()
        assert c._wetness_mm == pytest.approx(0.485)

    async def test_restart_preserves_wetness_with_only_old_rain_in_buffer(self):
        """Wie der Vorfall: alter Regen nur im hinteren Buffer-Teil, kurzer Reload."""
        c = self._make_stores(wetness_mm=0.679, saved_ago_s=95, recent_rain=0.0, old_rain=0.8)
        await c._load_storage()
        assert c._wetness_mm == pytest.approx(0.679)

    async def test_overnight_restart_allows_condensation(self):
        """Langer Neustart (8h): Tau-Kondensation ist als Grund für höhere Nässe OK.

        recent_slots = 96 (8h / 5min), Regen war 0.1mm vor ~8h.
        max Kondensation ≈ 0.86mm → Obergrenze ≈ 0.96mm. Nässe=0.9mm → OK.
        """
        # 0.1mm alter Regen (liegt in einem der 96 recent_slots), 8h Pause
        c = self._make_stores(wetness_mm=0.9, saved_ago_s=8 * 3600, recent_rain=0.1)
        await c._load_storage()
        assert c._wetness_mm == pytest.approx(0.9)

    async def test_no_saved_at_uses_fallback(self):
        """Fehlendes saved_at (alter Store b4-Format) → 1 Update Fallback, kein Crash."""
        c = _bare()
        # Letzter Slot = 0.5mm (der Regen der letzten 5 Min) → erlaubt 0.5mm
        buf = [0.0] * RAIN_BUFFER_MAXLEN
        buf[-1] = 0.5
        c._rain_buffer = deque(buf, maxlen=RAIN_BUFFER_MAXLEN)
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        # Kein saved_at → alter Store-Format (b4)
        c._store_wetness.async_load = AsyncMock(
            return_value={"wetness_mm": 0.5, "below_threshold_ts": None}
        )
        await c._load_storage()
        # Muss ohne Exception durchlaufen; Wert ≤ 0.5mm + Kondensation-Allowance
        assert c._wetness_mm >= 0.0
        assert c._wetness_mm <= WETNESS_MAX_MM

    async def test_wetness_capped_to_wetness_max(self):
        """Gespeicherter Wert > WETNESS_MAX_MM wird auf Maximum begrenzt.

        Bei ausreichend Regen im letzten Slot (≥ WETNESS_MAX_MM) bleibt das Limit
        WETNESS_MAX_MM als harte Obergrenze.
        """
        c = self._make_stores(wetness_mm=5.0, saved_ago_s=300, recent_rain=WETNESS_MAX_MM)
        await c._load_storage()
        assert c._wetness_mm == pytest.approx(WETNESS_MAX_MM)


# ── _prev_rain_today Persistenz ───────────────────────────────────────────────


class TestPrevRainTodayPersistence:
    """Regression: Reset + Reconfigure darf keinen Wetness-Sprung verursachen.

    Root Cause (b6): _prev_rain_today wird nicht persistiert. Nach einem Reload
    startet der neue Coordinator mit _prev_rain_today=0.0. Beim ersten Update
    gilt dann rain_delta_mm = rain_today_total - 0.0 = ganzer heutiger Regen,
    was wetness_mm von 0.0 auf z.B. 0.8mm springen lässt.
    """

    async def test_restores_prev_rain_today(self):
        """_load_storage stellt _prev_rain_today korrekt wieder her."""
        import time

        c = _bare()
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(
            return_value={
                "wetness_mm": 0.0,
                "below_threshold_ts": None,
                "saved_at": time.time() - 30,
                "prev_rain_today": 0.8,
            }
        )
        await c._load_storage()
        assert c._prev_rain_today == pytest.approx(0.8)

    async def test_reload_after_reset_no_rain_spike(self):
        """Kernbug-Regression: Reset, dann Reconfigure → kein Wetness-Sprung.

        Szenario (Ecowitt, heute Nacht kurz geregnet, 0.8mm):
        1. Wetness läuft durch Trocknung auf 0.4mm
        2. User drückt Reset → wetness=0.0, prev_rain_today=0.8mm gespeichert
        3. User startet Reconfigure → 30s später neuer Coordinator
        4. Neuer Coordinator lädt: wetness=0.0, prev_rain_today=0.8mm
        5. Erstes Update: rain_delta_mm = max(0, 0.8 - 0.8) = 0.0 → kein Sprung
        """
        import time

        c = _bare()
        c._prev_rain_today = 0.0  # neuer Coordinator startet bei 0
        c._wetness_mm = 0.0
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(
            return_value={
                "wetness_mm": 0.0,
                "below_threshold_ts": None,
                "saved_at": time.time() - 30,
                "prev_rain_today": 0.8,  # korrekt persistiert nach Reset
            }
        )
        await c._load_storage()
        # Neuer Coordinator kennt jetzt prev_rain_today=0.8
        # → erstes Update: rain_delta = 0.8 - 0.8 = 0 → kein Sprung
        assert c._wetness_mm == pytest.approx(0.0)
        assert c._prev_rain_today == pytest.approx(0.8)

    async def test_missing_prev_rain_today_estimated_from_buffer(self):
        """Upgrade von b6: kein prev_rain_today im Store → aus Rain-Buffer schätzen.

        Szenario: 0.6mm im Buffer (Nachtregentotal), kein prev_rain_today-Key.
        Nach dem Fix: _prev_rain_today ≥ 0.0 (aus Buffer geschätzt, kein Crash).
        Beim ersten Update: rain_delta ≈ 0.6 - 0.6 = 0 → kein Sprung.
        """
        import time
        from collections import deque

        c = _bare()
        # Simuliere 0.6mm Tagesregen verteilt auf die letzten Slots
        buf = [0.0] * RAIN_BUFFER_MAXLEN
        buf[-1] = 0.3
        buf[-2] = 0.3  # je 0.3mm in den letzten 2 Slots = 0.6mm heute
        c._rain_buffer = deque(buf, maxlen=RAIN_BUFFER_MAXLEN)
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(
            return_value={
                "wetness_mm": 0.3,
                "below_threshold_ts": None,
                "saved_at": time.time() - 30,
                # kein prev_rain_today → Upgrade von b6
            }
        )
        await c._load_storage()
        # Muss ≥ 0, kein Crash, und Buffer-Regen widerspiegeln
        assert c._prev_rain_today >= 0.0
        assert c._prev_rain_today <= 50.0  # plausibel für Tagesmenge

    async def test_negative_prev_rain_today_clamped(self):
        """Ungültiger negativer Wert im Store wird auf 0.0 begrenzt."""
        import time

        c = _bare()
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(
            return_value={
                "wetness_mm": 0.0,
                "below_threshold_ts": None,
                "saved_at": time.time() - 30,
                "prev_rain_today": -5.0,
            }
        )
        await c._load_storage()
        assert c._prev_rain_today == pytest.approx(0.0)


class TestChargePersistence:
    async def test_flush_saves_charge(self):
        c = _bare()
        c._charge_rate = 1.7
        c._charge_learned = True
        await c._flush_storage()
        args = c._store_charge.async_save.call_args[0][0]
        assert args["charge_rate_pct_per_min"] == pytest.approx(1.7)
        assert args["learned"] is True

    async def test_load_restores_charge(self):
        c = _bare()
        c._store_mowing.async_load = AsyncMock(return_value=None)
        c._store_rain.async_load = AsyncMock(return_value=None)
        c._store_solar.async_load = AsyncMock(return_value=None)
        c._store_growth.async_load = AsyncMock(return_value=None)
        c._store_wetness.async_load = AsyncMock(return_value=None)
        c._store_charge.async_load = AsyncMock(
            return_value={"charge_rate_pct_per_min": 2.1, "learned": True}
        )
        await c._load_storage()
        assert c._charge_rate == pytest.approx(2.1)
        assert c._charge_learned is True

    async def test_load_charge_default_when_empty(self):
        c = _bare()
        c._charge_rate = 99.0  # soll überschrieben werden
        c._charge_learned = True
        for s in [
            c._store_mowing,
            c._store_rain,
            c._store_solar,
            c._store_growth,
            c._store_wetness,
        ]:
            s.async_load = AsyncMock(return_value=None)
        c._store_charge.async_load = AsyncMock(return_value=None)
        await c._load_storage()
        assert c._charge_rate == pytest.approx(1.0)
        assert c._charge_learned is False


# ── _write_debug_csv ──────────────────────────────────────────────────────────


class TestWriteDebugCsv:
    def test_charge_rate_column_present(self):
        c = _bare()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            tmp = f.name
        os.unlink(tmp)
        try:
            c.hass.config.path = lambda name: tmp
            data = dict.fromkeys(
                [
                    "wetness_mm",
                    "wetness_score",
                    "drying_mm",
                    "cond_mm",
                    "rain_delta_mm",
                    "condition_slot_mm",
                    "temp_c",
                    "dew_point",
                    "vpd_c",
                    "wind_kmh",
                    "solar_factor",
                    "eff_solar",
                    "priority",
                    "start_now",
                    "mow_allowed",
                    "stop_now",
                    "block_reason",
                    "emergency_mow_active",
                    "raining",
                    "dew_present",
                    "brightness_ok",
                    "sun_elevation",
                    "rain_last_1h_mm",
                    "rain_weighted_12h",
                    "rain_today_mm",
                    "rain_today_remaining",
                    "rain_tomorrow",
                    "radiation_peak",
                    "battery_pct",
                    "duration_today_h",
                    "duration_avg_3d_h",
                    "growth_mm",
                    "growth_ratio",
                    "fertilizer_active",
                    "irrigation_active",
                    "next_mow_expected",
                    "charge_rate_pct_per_min",
                ],
                0,
            )
            c._write_debug_csv(data)
            with open(tmp) as fh:
                header = fh.readline()
            assert "charge_rate_pct_per_min" in header
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

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
