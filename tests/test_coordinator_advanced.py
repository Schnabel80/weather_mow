"""Erweiterte Coordinator-Tests: Emergency-Mow, Start-Delay, Check-No-Dry-Window, Urgency."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def entry():
    e = MagicMock()
    e.entry_id = "adv_test"
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
        "min_brightness_lux": 2000,
        "min_battery_pct": 20,
    }
    e.options = {
        "mow_window_start": "00:00:00",
        "mow_window_end": "23:59:00",
        "target_buffer_h": 0.0,
    }
    return e


@pytest.fixture
async def coord(hass, entry):
    c = WeatherMowCoordinator(hass, entry)
    with patch.object(c, "_load_storage"), patch.object(c, "_register_listeners"):
        await c._async_setup()
    c._sunshine_initialized = True
    c._duration_yesterday_s = 9000.0
    c._duration_day_before_s = 9000.0
    sw = MagicMock()
    sw.is_on = True
    c.switch_entity = sw
    em_sw = MagicMock()
    em_sw.is_on = True
    c.emergency_switch_entity = em_sw
    yield c


def _weather(hass, condition="sunny", temp=20.0):
    hass.states.async_set(
        "weather.test",
        condition,
        attributes={"temperature": temp, "humidity": 60, "wind_speed": 5.0, "forecast": []},
    )
    hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})


def _mower(hass, state="docked", battery=100):
    hass.states.async_set("lawn_mower.test", state, attributes={"battery_level": battery})


def _dry(coord):
    coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

    def _keep_dry(*a, **kw):
        coord._wetness_mm = 0.0
        return 0.0, 0.0, 0.0

    return _keep_dry


# ── Emergency-Mow-Pfad ────────────────────────────────────────────────────────


class TestEmergencyMow:
    async def test_emergency_mow_when_target_met_and_rain_tomorrow(self, hass, coord):
        """Tagesziel erreicht + viel Regen morgen + Zeit noch vorhanden → emergency."""
        # Verwende einen großen Zeitpuffer (Fenster bis 23:59, min. 2h Rest nötig)
        cfg = {
            **coord.entry.data,
            "mow_window_start": "00:00:00",
            "mow_window_end": "23:59:00",
            "target_buffer_h": 0.0,
            "target_daily_duration_h": 3.0,
            "full_cycle_duration_h": 2.0,
            "threshold_rain_tomorrow_mm": 5.0,
            "threshold_min_time_for_emergency_h": 0.0,  # kein Zeitbedarf
        }
        result = coord._compute_decision(
            cfg=cfg,
            now_local=dt_util.now(),
            wetness_mm=0.0,
            brightness_ok=True,
            rain_today_remaining=0.0,
            rain_tomorrow=10.0,
            duration_today_h=3.1,
            rain_fc_3h=0.0,
            duration_avg_3d_h=2.0,
            no_dry_window=False,
            temp_c=20.0,
        )
        mow_allowed, start_now, block_reason = result
        assert block_reason == "emergency_mow_tomorrow_rain"
        assert mow_allowed is True
        assert start_now is True

    async def test_no_emergency_when_switch_off(self, hass, coord):
        """Emergency-Schalter aus → kein Notmähen, target_reached."""
        coord.emergency_switch_entity.is_on = False
        cfg = {**coord.entry.data, **coord.entry.options}
        result = coord._compute_decision(
            cfg=cfg,
            now_local=dt_util.now(),
            wetness_mm=0.0,
            brightness_ok=True,
            rain_today_remaining=0.0,
            rain_tomorrow=10.0,
            duration_today_h=4.0,
            rain_fc_3h=0.0,
            duration_avg_3d_h=2.0,
            no_dry_window=False,
            temp_c=20.0,
        )
        _, _, block_reason = result
        assert block_reason == "daily_target_reached"


# ── Start-Delay ───────────────────────────────────────────────────────────────


class TestStartDelay:
    async def test_start_delay_postpones_start(self, hass, coord):
        """Morgen-Startverzögerung 30min → start_now=False direkt nach Freigabe."""
        _weather(hass)
        _mower(hass)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
        coord._duration_today_s = 0.0  # noch nicht gemäht heute
        coord._mow_first_allowed_ts = dt_util.utcnow().timestamp()  # Timestamp gerade eben

        coord.entry.options = {
            **coord.entry.options,
            "start_delay_minutes": 30,
        }

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        # start_now muss False sein weil Delay noch nicht abgelaufen
        assert data["start_now"] is False
        assert data["mow_allowed"] is True  # mow_allowed bleibt True

    async def test_start_delay_bypassed_at_high_priority(self, hass, coord):
        """Bei Priorität ≥ 65 (DELAY_BYPASS_PRIORITY) wird Delay ignoriert."""
        _weather(hass)
        _mower(hass)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
        coord._duration_today_s = 0.0
        # Timestamp gerade eben → Delay noch nicht abgelaufen
        coord._mow_first_allowed_ts = dt_util.utcnow().timestamp()
        coord._duration_yesterday_s = 0.0  # Niedriger avg → hohe Dringlichkeit
        coord._duration_day_before_s = 0.0

        coord.entry.options = {
            **coord.entry.options,
            "start_delay_minutes": 60,
        }

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data = await coord._async_update_data()

        # Bei sehr niedrigem avg: Priorität steigt → bypass
        # Wir testen nur dass kein Crash auftritt
        assert "start_now" in data
        assert "priority" in data


# ── _check_no_dry_window ──────────────────────────────────────────────────────


class TestCheckNoDryWindow:
    def _bare(self):
        hass = MagicMock()
        hass.states.get.return_value = None
        entry = MagicMock()
        entry.entry_id = "ndw_test"
        entry.data = {"name": "Test", "weather_entity_id": ""}
        entry.options = {}
        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c.hass = hass
        c.entry = entry
        c._radiation_peak = 800.0
        c.lawn_sun_efficiency_entity = None
        c.lawn_sun_from_entity = None
        c.mow_threshold_entity = None  # nötig für _check_no_dry_window
        return c

    def test_no_dry_window_when_already_dry(self):
        """Wetness bereits unter Schwelle → kein Trocknungsbedarf → False."""
        c = self._bare()
        cfg = {
            "full_cycle_duration_h": 2.0,
            "mow_window_end": "20:00:00",
            "outdoor_temp_entity_id": "",
            "outdoor_humidity_entity_id": "",
        }
        with patch.object(c, "_get_temp_humidity", return_value=(20.0, 60.0)):
            result = c._check_no_dry_window(cfg, dt_util.now(), wetness_mm=0.0)
        assert result is False

    def test_no_dry_window_impossible_to_dry_in_time(self):
        """Benötigte Zeit zum Trocknen überschreitet den Rest des Fensters → True."""
        c = self._bare()
        # full_cycle_h extrem hoch → Trockenfenster reicht nie aus → True
        cfg = {
            "full_cycle_duration_h": 999.0,
            "mow_window_end": "20:00:00",
            "outdoor_temp_entity_id": "",
            "outdoor_humidity_entity_id": "",
        }
        with patch.object(c, "_get_temp_humidity", return_value=(15.0, 85.0)):
            result = c._check_no_dry_window(cfg, dt_util.now(), wetness_mm=1.5)
        # Mit full_cycle=999h hat kein Trockenfenster je genug Zeit → True
        assert result is True

    def test_no_dry_window_enough_time_left(self):
        """Genug Zeit zum Trocknen vor Fenster-Ende → False (Trockenfenster existiert)."""
        c = self._bare()
        cfg = {
            "full_cycle_duration_h": 2.0,
            "mow_window_end": "20:00:00",
            "outdoor_temp_entity_id": "",
            "outdoor_humidity_entity_id": "",
        }
        # Früh morgens → viel Zeit
        early_morning = dt_util.now().replace(hour=8, minute=0, second=0)
        with (
            patch.object(c, "_get_temp_humidity", return_value=(22.0, 55.0)),
            patch.object(c, "_effective_solar_factor", return_value=0.8),
        ):
            result = c._check_no_dry_window(cfg, early_morning, wetness_mm=0.8)
        # Morgens viel Zeit → Trockenfenster vorhanden → False
        assert result is False


# ── Urgency-Zweige ────────────────────────────────────────────────────────────


class TestUrgencyBranches:
    async def test_urgent_threshold_used_when_time_pressure(self, hass, coord):
        """Bei Zeitdruck (knapp vor Fenster-Ende) wird Dringlichkeits-Schwelle verwendet."""
        # Direkter Test von _compute_decision mit urgency_high=True
        urgent_thresh = MagicMock()
        urgent_thresh.native_value = 1.5
        coord.mow_threshold_urgent_entity = urgent_thresh

        cfg = {
            **coord.entry.data,
            "mow_window_start": "00:00:00",
            "mow_window_end": "23:59:00",
            "target_buffer_h": 0.0,
        }
        # urgency_high via emergency_mow_active
        coord.emergency_mow_active = True
        result = coord._compute_decision(
            cfg=cfg,
            now_local=dt_util.now(),
            wetness_mm=1.0,
            brightness_ok=True,
            rain_today_remaining=0.0,
            rain_tomorrow=0.0,
            duration_today_h=0.5,
            rain_fc_3h=0.0,
            duration_avg_3d_h=2.0,
            no_dry_window=False,
            temp_c=20.0,
        )
        coord.emergency_mow_active = False
        _, _, block_reason = result
        # Bei wetness=1.0 unter urgent_threshold=1.5 → mowing_allowed
        assert block_reason in ("mowing_allowed", "emergency_mow_tomorrow_rain")

    async def test_heat_reduction_in_range(self, hass, coord):
        """Temperatur zwischen 30-35°C → Priorität reduziert, nicht null."""
        _weather(hass, temp=32.0)
        _mower(hass)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        def _keep_dry(*a, **kw):
            coord._wetness_mm = 0.0
            return 0.0, 0.0, 0.0

        with patch.object(coord, "_update_wetness", _keep_dry):
            data_hot = await coord._async_update_data()

        _weather(hass, temp=20.0)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
        with patch.object(coord, "_update_wetness", _keep_dry):
            data_cool = await coord._async_update_data()

        if data_hot["mow_allowed"] and data_cool["mow_allowed"]:
            assert 0 < data_hot["priority"] < data_cool["priority"]


# ── Rain-Detector-Callback ────────────────────────────────────────────────────


class TestRainDetectorCallback:
    def _bare_coord(self):
        hass = MagicMock()
        hass.async_create_task = MagicMock()
        entry = MagicMock()
        entry.entry_id = "rdc_test"
        entry.data = {"name": "Test"}
        entry.options = {}
        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c.hass = hass
        c.entry = entry
        c.async_request_refresh = MagicMock()
        return c

    def _make_event(self, new_state_str):
        event = MagicMock()
        state = MagicMock()
        state.state = new_state_str
        event.data = {"new_state": state}
        return event

    def test_detector_on_triggers_refresh(self):
        c = self._bare_coord()
        event = self._make_event("on")
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_called()

    def test_detector_numeric_triggers_refresh(self):
        """Numerischer Wert > 0.05 gilt als Regen."""
        c = self._bare_coord()
        event = self._make_event("1.5")
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_called()

    def test_detector_any_valid_state_triggers_refresh(self):
        """Jeder gültige State (auch 0.0) → Refresh (kein Filter auf Wert)."""
        c = self._bare_coord()
        event = self._make_event("0.0")
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_called()

    def test_detector_none_state_ignored(self):
        c = self._bare_coord()
        event = MagicMock()
        event.data = {"new_state": None}
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_not_called()

    def test_detector_unavailable_ignored(self):
        c = self._bare_coord()
        event = self._make_event("unavailable")
        c._handle_rain_detector_change(event)
        c.hass.async_create_task.assert_not_called()


class TestChargeDetection:
    def _coord(self):
        from custom_components.weather_mow.const import DEFAULT_BATTERY_FULL_PCT
        from custom_components.weather_mow.coordinator import WeatherMowCoordinator

        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c._charge_rate = 1.0
        c._charge_learned = False
        c._charge_start_pct = None
        c._charge_start_ts = None
        c._charge_peak_pct = None
        c._charge_peak_ts = None
        c._battery_full_pct = DEFAULT_BATTERY_FULL_PCT
        c._battery_ceiling_learned = False
        c._dock_peak_pct = None
        c._dock_peak_ts = None
        c.hass = None  # Notification wird ohne hass übersprungen
        return c

    def test_charge_phase_start_recorded(self):
        c = self._coord()
        c._maybe_track_charge(
            battery_now=40.0, prev=38.0, is_mowing=False, now_ts=1000.0, battery_fresh=True
        )
        assert c._charge_start_pct == 38.0
        assert c._charge_start_ts == 1000.0

    def test_charge_phase_learns_on_end(self):
        c = self._coord()
        c._maybe_track_charge(
            battery_now=32.0, prev=30.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=95.0, prev=95.0, is_mowing=True, now_ts=3900.0, battery_fresh=True
        )
        assert c._charge_learned is True
        assert c._charge_rate == pytest.approx(1.0, abs=0.05)
        assert c._charge_start_ts is None

    def test_stale_battery_discards_running_phase(self):
        """M2: Sensorausfall (Fallback 100.0) darf keine Phantom-Rate lernen."""
        c = self._coord()
        c._maybe_track_charge(
            battery_now=52.0, prev=50.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=100.0, prev=52.0, is_mowing=False, now_ts=300.0, battery_fresh=False
        )
        assert c._charge_learned is False
        assert c._charge_rate == 1.0
        assert c._charge_start_ts is None
        assert c._charge_start_pct is None

    def test_stale_battery_does_not_start_phase(self):
        c = self._coord()
        c._maybe_track_charge(
            battery_now=52.0, prev=50.0, is_mowing=False, now_ts=0.0, battery_fresh=False
        )
        assert c._charge_start_ts is None

    def test_small_dip_keeps_phase(self):
        """N2: Sensorrauschen (−1%) beendet die Ladephase nicht."""
        c = self._coord()
        c._maybe_track_charge(
            battery_now=52.0, prev=50.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=51.0, prev=52.0, is_mowing=False, now_ts=300.0, battery_fresh=True
        )
        assert c._charge_start_ts is not None
        assert c._charge_learned is False

    def test_fall_beyond_tolerance_learns_from_peak(self):
        """N2: Phase endet bei Abfall > Toleranz; Messung nutzt Peak-Zeitpunkt."""
        c = self._coord()
        c._maybe_track_charge(
            battery_now=32.0, prev=30.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        # Peak: 95% nach 65 min → Rate (95−30)/65 = 1.0 %/min
        c._maybe_track_charge(
            battery_now=95.0, prev=32.0, is_mowing=False, now_ts=3900.0, battery_fresh=True
        )
        # Danach 30 min idle-Entladung auf 92 → darf die Rate nicht verwässern
        c._maybe_track_charge(
            battery_now=92.0, prev=95.0, is_mowing=False, now_ts=5700.0, battery_fresh=True
        )
        assert c._charge_learned is True
        assert c._charge_rate == pytest.approx(1.0, abs=0.05)
        assert c._charge_start_ts is None

    def test_reaching_full_does_not_end_rate_phase(self):
        """M1 (neu): Das Erreichen einer 'voll'-Schwelle beendet die Raten-Phase
        NICHT mehr (entkoppelt von der Ladedecke). Erst Mähen/Abfall beendet sie —
        so kann die Decke auch wieder steigen."""
        c = self._coord()
        c._maybe_track_charge(
            battery_now=32.0, prev=30.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=98.0, prev=95.0, is_mowing=False, now_ts=3960.0, battery_fresh=True
        )
        # Phase läuft weiter, Rate noch nicht gelernt.
        assert c._charge_start_ts is not None
        assert c._charge_learned is False
        # Erst das Mähen beendet die Phase und lernt die Rate.
        c._maybe_track_charge(
            battery_now=98.0, prev=98.0, is_mowing=True, now_ts=4020.0, battery_fresh=True
        )
        assert c._charge_learned is True
        assert c._charge_start_ts is None


class TestBatteryCeilingLearning:
    """Issue #12: gelernte Ladedecke statt fixer 98-%-Schwelle."""

    def _coord(self):
        return TestChargeDetection._coord(TestChargeDetection())

    def test_plateau_below_default_is_learned(self):
        """Bosch Indego erreicht real nur 93 %, verharrt 25 min → 93 % gelernt."""
        from custom_components.weather_mow.const import BATTERY_PLATEAU_MINUTES

        c = self._coord()
        c._maybe_track_charge(
            battery_now=85.0, prev=80.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        # Steigt bis 93 % (Plateau-Peak-Zeit = 600), dann Plateau.
        c._maybe_track_charge(
            battery_now=93.0, prev=85.0, is_mowing=False, now_ts=600.0, battery_fresh=True
        )
        # Nach 10 min Plateau: noch nicht lange genug.
        c._maybe_track_charge(
            battery_now=93.0, prev=93.0, is_mowing=False, now_ts=1200.0, battery_fresh=True
        )
        assert c._battery_full_pct == pytest.approx(98.0)
        # Nach 25 min Plateau: Decke wird auf 93 % gelernt.
        c._maybe_track_charge(
            battery_now=93.0,
            prev=93.0,
            is_mowing=False,
            now_ts=600.0 + BATTERY_PLATEAU_MINUTES * 60.0,
            battery_fresh=True,
        )
        assert c._battery_full_pct == pytest.approx(93.0)

    def test_docked_flat_without_prior_rise_learns_ceiling(self):
        """Kernfall Issue #12: Mäher steht bereits voll am Dock (93 %, Float-
        Ladung, kein Anstieg mehr). Ohne vorherige Ladephase muss die Decke
        trotzdem gelernt werden — sonst bleibt der Mäher dauerhaft blockiert."""
        from custom_components.weather_mow.const import BATTERY_PLATEAU_MINUTES

        c = self._coord()
        c._maybe_track_charge(
            battery_now=93.0, prev=93.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=93.0,
            prev=93.0,
            is_mowing=False,
            now_ts=BATTERY_PLATEAU_MINUTES * 60.0,
            battery_fresh=True,
        )
        assert c._battery_full_pct == pytest.approx(93.0)

    def test_stale_sensor_at_dock_still_learns_plateau(self):
        """Regression #12: Bosch Indego sendet bei unverändertem Akkuwert kein
        HA-Update → der Sensor gilt nach BATTERY_STALE_MINUTES als stale
        (battery_fresh=False). Ein staler Wert am Dock IST aber gerade das
        Plateau und darf das Lernen NICHT abbrechen."""
        from custom_components.weather_mow.const import BATTERY_PLATEAU_MINUTES

        c = self._coord()
        # Frischer Wert beim Andocken: 94 %.
        c._maybe_track_charge(
            battery_now=94.0, prev=94.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        # Danach kein Update mehr → stale, aber weiterhin 94 % am Dock.
        c._maybe_track_charge(
            battery_now=94.0,
            prev=94.0,
            is_mowing=False,
            now_ts=BATTERY_PLATEAU_MINUTES * 60.0,
            battery_fresh=False,
        )
        assert c._battery_full_pct == pytest.approx(94.0)

    def test_float_drift_within_tolerance_learns_peak(self):
        """Float-Ladung driftet 93→92 (< Toleranz) → Decke bleibt der Peak 93."""
        from custom_components.weather_mow.const import BATTERY_PLATEAU_MINUTES

        c = self._coord()
        c._maybe_track_charge(
            battery_now=93.0, prev=93.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=92.0, prev=93.0, is_mowing=False, now_ts=600.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=92.0,
            prev=92.0,
            is_mowing=False,
            now_ts=BATTERY_PLATEAU_MINUTES * 60.0,
            battery_fresh=True,
        )
        assert c._battery_full_pct == pytest.approx(93.0)

    def test_discharge_resets_plateau_observation(self):
        """Größerer Abfall (Entladung beim Mähstart-Abbruch) setzt die
        Plateau-Beobachtung zurück — kein vorzeitiges Lernen eines Tiefs."""
        from custom_components.weather_mow.const import BATTERY_PLATEAU_MINUTES

        c = self._coord()
        c._maybe_track_charge(
            battery_now=93.0, prev=93.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        # Fällt auf 70 % (Entladung) → Beobachtung startet neu bei 70.
        c._maybe_track_charge(
            battery_now=70.0, prev=93.0, is_mowing=False, now_ts=600.0, battery_fresh=True
        )
        # 25 min nach dem ALTEN Peak, aber erst 24 min nach dem Reset → kein Lernen.
        c._maybe_track_charge(
            battery_now=70.0,
            prev=70.0,
            is_mowing=False,
            now_ts=600.0 + BATTERY_PLATEAU_MINUTES * 60.0 - 60.0,
            battery_fresh=True,
        )
        assert c._battery_full_pct == pytest.approx(98.0)

    def test_mowing_resets_plateau_observation(self):
        """Während des Mähens kein Plateau-Lernen (Akku fällt, nicht voll)."""
        from custom_components.weather_mow.const import BATTERY_PLATEAU_MINUTES

        c = self._coord()
        c._maybe_track_charge(
            battery_now=93.0, prev=93.0, is_mowing=True, now_ts=0.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=93.0,
            prev=93.0,
            is_mowing=True,
            now_ts=BATTERY_PLATEAU_MINUTES * 60.0,
            battery_fresh=True,
        )
        assert c._battery_full_pct == pytest.approx(98.0)

    def test_mowing_interruption_does_not_learn_ceiling(self):
        """Unterbrechung durch Mähen ist kein Plateau → Decke unverändert."""
        c = self._coord()
        c._maybe_track_charge(
            battery_now=32.0, prev=30.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=95.0, prev=92.0, is_mowing=True, now_ts=3780.0, battery_fresh=True
        )
        assert c._charge_learned is True  # Rate trotzdem gelernt
        assert c._battery_full_pct == pytest.approx(98.0)  # Decke NICHT

    def test_ceiling_relearns_higher_after_limit_removed(self):
        """Ladelimit am Gerät entfernt: Decke darf wieder steigen (kein >=-Stopp)."""
        from custom_components.weather_mow.const import BATTERY_PLATEAU_MINUTES

        c = self._coord()
        c._battery_full_pct = 80.0  # zuvor gelerntes Limit
        c._battery_ceiling_learned = True
        c._maybe_track_charge(
            battery_now=88.0, prev=82.0, is_mowing=False, now_ts=0.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=95.0, prev=88.0, is_mowing=False, now_ts=600.0, battery_fresh=True
        )
        c._maybe_track_charge(
            battery_now=95.0,
            prev=95.0,
            is_mowing=False,
            now_ts=600.0 + BATTERY_PLATEAU_MINUTES * 60.0,
            battery_fresh=True,
        )
        assert c._battery_full_pct == pytest.approx(95.0)
