"""DataUpdateCoordinator für weather_mow."""
from __future__ import annotations

import csv
import logging
import math
import os
from collections import deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_BRIGHTNESS,
    CONF_DWD_PRECIP,
    CONF_DWD_RADIATION,
    CONF_DWD_WEATHER,
    CONF_DWD_WIND,
    CONF_FULL_CYCLE_H,
    CONF_HUMIDITY,
    CONF_MIN_BATTERY_PCT,
    CONF_MIN_BRIGHTNESS,
    CONF_MOW_END,
    CONF_MOW_START,
    CONF_MOWER_ENTITY,
    CONF_PV_PEAK_KW,
    CONF_PV_POWER,
    CONF_RADIATION_SOURCE,
    CONF_RAIN_1H,
    CONF_RAIN_DETECTOR,
    CONF_RAIN_PROVIDER,
    CONF_RAIN_SENSOR,
    CONF_RAIN_SENSOR_TYPE,
    CONF_RAIN_TODAY,
    CONF_TARGET_DAILY_H,
    CONF_TEMP,
    BATTERY_STALE_MINUTES,
    CONF_BATTERY_SENSOR,
    DEFAULT_BATTERY_SENSOR,
    CONF_PREVENT_AUTO_RESUME,
    CONF_LAST_FERTILIZATION,
    CONF_MAX_GROWTH_MM,
    DEFAULT_MAX_GROWTH_MM,
    FERTILIZER_ACTIVE_DAYS,
    FERTILIZER_BOOST_FACTOR,
    GDD_BASE_TEMP_C,
    GROWTH_MM_PER_GDD,
    STORAGE_KEY_GROWTH,
    IRRIGATION_WETNESS_BOOST,
    IRRIGATION_DECAY_PER_UPDATE,
    CONF_THRESH_DEW_OFFSET,
    CONF_THRESH_EMERG_H,
    CONF_THRESH_RAIN_TODAY,
    CONF_THRESH_RAIN_TMRW,
    CONF_THRESH_WETNESS,
    CONF_MIN_SUN_H_FOR_DEW,
    CONF_START_DELAY_MIN,
    CONF_TARGET_BUFFER_H,
    CONF_LOCAL_RADIATION,
    CONDITION_RAIN_RATE,
    DECAY_PER_UPDATE,
    DEFAULT_MIN_BATTERY,
    DEFAULT_FULL_CYCLE_H,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MIN_SUN_H_FOR_DEW,
    DEFAULT_START_DELAY_MIN,
    DEFAULT_TARGET_BUFFER_H,
    DEFAULT_PREVENT_AUTO_RESUME,
    DEFAULT_PV_PEAK_KW,
    DEFAULT_THRESH_DEW_OFFSET,
    DOMAIN,
    RAINING_NOW_THRESHOLD_MM,
    RAIN_BUFFER_MAXLEN,
    RAIN_SCORE_PER_MM,
    RAIN_WEIGHT_MAP,
    DEFAULT_LAWN_SUN_EFFICIENCY,
    DEFAULT_LAWN_SUN_FROM,
    DELAY_BYPASS_PRIORITY,
    RADIATION_SOURCE_PV,
    RADIATION_SUN_THRESHOLD,
    RADIATION_INSTANT_CLEAR,
    SOLAR_PEAK_MIN,
    STORAGE_KEY_MOWING,
    STORAGE_KEY_RAIN_BUF,
    STORAGE_KEY_SOLAR,
    STORAGE_VERSION,
    UPDATE_INTERVAL_MINUTES,
)
from .drying import effective_solar_factor
from .rain_input import RainNormalizer, rain_since_midnight, rate_to_slot_mm, rebuild_slots, resolve_rain_mode

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = {STATE_UNAVAILABLE, STATE_UNKNOWN, "unavailable", "unknown", "none", "None"}


def _safe_float(state_str: str | None) -> float | None:
    if state_str is None or state_str in _UNAVAILABLE:
        return None
    try:
        return float(state_str)
    except (ValueError, TypeError):
        return None


def _state_float(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return _safe_float(state.state)


def _attr_float(hass: HomeAssistant, entity_id: str, attr: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return _safe_float(str(state.attributes.get(attr, "")))


class WeatherMowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Koordiniert alle Berechnungen und Zustandsverfolgung."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data.get('name', entry.entry_id)}",
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.entry = entry

        # Storage-Objekte (werden in _async_setup initialisiert)
        self._store_mowing:  Store | None = None
        self._store_rain:    Store | None = None
        self._store_solar:   Store | None = None
        self._store_growth:  Store | None = None
        self._initialized = False

        # Listener-Handles
        self._mow_state_unsub     = None
        self._midnight_unsub      = None
        self._weather_state_unsub = None
        self._rain_sensor_unsub   = None
        self._rain_detect_unsub   = None

        # Mähdauer-Tracking
        self._mow_start_ts: float | None = None
        self._duration_today_s:      float = 0.0
        self._duration_yesterday_s:  float = 0.0
        self._duration_day_before_s: float = 0.0

        # Regen-Buffer
        self._rain_buffer: deque[float] = deque(maxlen=RAIN_BUFFER_MAXLEN)
        self._rain_normalizer: RainNormalizer | None = None

        # Solar Peak
        self._radiation_peak: float = SOLAR_PEAK_MIN
        # Wann hat der aktuelle Dauersonnenschein begonnen (für Tau-Prognose)
        # Wird beim ersten Update aus dem HA-Recorder initialisiert, danach in-memory getracked
        self._sunshine_start_utc: datetime | None = None
        self._sunshine_initialized: bool = False

        # Entscheidungszustand
        self.emergency_mow_active: bool = False

        # Auto-Dock-Schutz
        self._last_mow_allowed: bool = False
        self._last_block_reason: str = ""
        self._auto_resume_blocked: bool = False

        # Akku-Plausibilisierung
        self._prev_battery_pct: float | None = None

        # Wuchsmodell (GDD-Akkumulator, reset nach vollständigem Mähzyklus)
        self._growth_gdd_accum: float = 0.0
        self._mow_since_last_gdd_reset_s: float = 0.0  # kumulierte Mähzeit seit letztem GDD-Reset

        # Morgen-Startverzögerung
        self._mow_first_allowed_ts: float | None = None  # Timestamp erste start_now=True heute

        # Tau-Freigabe-Latch: True sobald Tau einmal verdunstet — bleibt True bis Mitternacht.
        # Verhindert, dass sinkende Abend-Strahlung erneut "Tau vorhanden" meldet.
        self._dew_cleared_today: bool = False

        # Bewässerungs-Boost (unabhängig vom Regen-Buffer)
        self._irrigation_wetness_boost: float = 0.0

        # Referenzen auf Switches (werden von switch.py gesetzt)
        self.switch_entity:            Any = None
        self.emergency_switch_entity:  Any = None
        self.irrigation_switch_entity: Any = None
        self.lawn_sun_efficiency_entity: Any = None
        self.lawn_sun_from_entity: Any = None
        self.debug_switch_entity:      Any | None = None

        # Referenz auf Dünge-Datums-Entität (wird von date.py gesetzt)
        self.fertilization_date_entity: Any = None

        # Stündliche DWD-Prognoselisten (für next_mow_expected)
        self._dwd_hourly_precip:    list[tuple[datetime, float]] = []
        self._dwd_hourly_radiation: list[tuple[datetime, float]] = []

    # ── Setup & Storage ──────────────────────────────────────────────────────

    async def _async_setup(self) -> None:
        """Wird einmalig vor dem ersten Update aufgerufen."""
        entry_id = self.entry.entry_id
        self._store_mowing = Store(
            self.hass, STORAGE_VERSION,
            STORAGE_KEY_MOWING.format(entry_id=entry_id),
        )
        self._store_rain = Store(
            self.hass, STORAGE_VERSION,
            STORAGE_KEY_RAIN_BUF.format(entry_id=entry_id),
        )
        self._store_solar = Store(
            self.hass, STORAGE_VERSION,
            STORAGE_KEY_SOLAR.format(entry_id=entry_id),
        )
        self._store_growth = Store(
            self.hass, STORAGE_VERSION,
            STORAGE_KEY_GROWTH.format(entry_id=entry_id),
        )
        await self._load_storage()
        self._register_listeners()
        self._initialized = True

    async def _load_storage(self) -> None:
        def _sf(val: object, default: float) -> float:
            try:
                return float(val)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default

        mowing_data = await self._store_mowing.async_load()
        if mowing_data:
            self._duration_today_s      = _sf(mowing_data.get("today_s"),      0.0)
            self._duration_yesterday_s  = _sf(mowing_data.get("yesterday_s"),  0.0)
            self._duration_day_before_s = _sf(mowing_data.get("day_before_s"), 0.0)

        rain_data = await self._store_rain.async_load()
        if rain_data and isinstance(rain_data.get("buffer"), list):
            self._rain_buffer = deque(rain_data["buffer"], maxlen=RAIN_BUFFER_MAXLEN)

        solar_data = await self._store_solar.async_load()
        if solar_data:
            self._radiation_peak = max(
                SOLAR_PEAK_MIN,
                _sf(solar_data.get("peak"), SOLAR_PEAK_MIN),
            )

        growth_data = await self._store_growth.async_load()
        if growth_data:
            self._growth_gdd_accum = _sf(growth_data.get("gdd_accum"), 0.0)
            self._mow_since_last_gdd_reset_s = _sf(growth_data.get("mow_since_reset_s"), 0.0)

    async def _flush_storage(self) -> None:
        if self._store_mowing:
            await self._store_mowing.async_save(
                {
                    "today_s":      self._duration_today_s,
                    "yesterday_s":  self._duration_yesterday_s,
                    "day_before_s": self._duration_day_before_s,
                }
            )
        if self._store_rain:
            await self._store_rain.async_save({"buffer": list(self._rain_buffer)})
        if self._store_solar:
            await self._store_solar.async_save({"peak": self._radiation_peak})
        if self._store_growth:
            await self._store_growth.async_save({
                "gdd_accum": self._growth_gdd_accum,
                "mow_since_reset_s": self._mow_since_last_gdd_reset_s,
            })

    def debug_csv_path(self) -> str:
        """Pfad der instanz-spezifischen Debug-CSV (entry_id im Dateinamen)."""
        return self.hass.config.path(f"weather_mow_debug_{self.entry.entry_id}.csv")

    def _write_debug_csv(self, data: dict) -> None:
        """Schreibt eine Zeile in die Debug-CSV-Datei.

        Wird via hass.async_add_executor_job aufgerufen — File-I/O blockiert
        sonst den Event Loop (relevant bei langsamer SD-Karte am Pi).
        """
        path = self.debug_csv_path()
        file_exists = os.path.isfile(path)

        columns = [
            "timestamp",
            "wetness_score", "priority", "start_now", "mow_allowed",
            "stop_now", "block_reason", "emergency_mow_active",
            "raining", "dew_present", "brightness_ok",
            "rain_last_1h_mm", "rain_weighted_12h", "rain_today_mm",
            "rain_today_remaining", "rain_tomorrow",
            "radiation_peak", "solar_factor", "sun_elevation",
            "dew_point", "battery_pct",
            "duration_today_h", "duration_avg_3d_h",
            "growth_mm", "growth_ratio", "fertilizer_active",
            "irrigation_active", "irrigation_boost",
            "next_mow_expected",
        ]

        row = {"timestamp": dt_util.now().isoformat(timespec="seconds")}
        for col in columns[1:]:
            val = data.get(col, "")
            if hasattr(val, "isoformat"):
                val = val.isoformat(timespec="seconds")
            row[col] = val

        try:
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        except OSError as exc:
            _LOGGER.warning("weather_mow: CSV-Debug-Log konnte nicht geschrieben werden: %s", exc)

    async def _init_sunshine_from_recorder(self, cfg: dict, now_utc: datetime) -> None:
        """Liest HA-Recorder-Historie des Strahlungssensors (max. 3h) um zu bestimmen,
        seit wann durchgehend Sonnenschein herrscht. Einmalig beim ersten Update aufgerufen.
        Kein eigener Storage nötig — HA speichert den Sensorverlauf bereits.
        """
        # Priorität: lokal → DWD → PV (für History-Rekonstruktion des Sonnenschein-Trackings)
        radiation_entity = (
            cfg.get(CONF_LOCAL_RADIATION)
            or cfg.get(CONF_DWD_RADIATION)
            or cfg.get(CONF_PV_POWER)
        )
        if not radiation_entity:
            return
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import state_changes_during_period

            start = now_utc - timedelta(hours=3)
            states_map = await get_instance(self.hass).async_add_executor_job(
                state_changes_during_period,
                self.hass, start, now_utc, radiation_entity, False, False,
            )
            entity_states = states_map.get(radiation_entity, [])
            if not entity_states:
                return

            min_sun_h = float(cfg.get(CONF_MIN_SUN_H_FOR_DEW, DEFAULT_MIN_SUN_H_FOR_DEW))

            # Phase 1: Aktuelle zusammenhängende Kette (newest → oldest)
            sunshine_start: datetime | None = None
            for state in reversed(entity_states):
                try:
                    if float(state.state) >= RADIATION_SUN_THRESHOLD:
                        sunshine_start = state.last_updated
                    else:
                        break  # Kette unterbrochen
                except (ValueError, TypeError):
                    break

            if sunshine_start is not None:
                self._sunshine_start_utc = sunshine_start
                sunshine_h_restored = (now_utc - sunshine_start).total_seconds() / 3600
                if sunshine_h_restored >= min_sun_h:
                    self._dew_cleared_today = True
                _LOGGER.debug(
                    "Sunshine start restored from recorder: %s (%.1f h ago, dew_cleared=%s)",
                    sunshine_start.isoformat(),
                    sunshine_h_restored,
                    self._dew_cleared_today,
                )
            else:
                # Phase 2: Keine aktuelle Kette (z.B. Abend-Neustart nach Sonnenuntergang).
                # Prüfe ob heute irgendwann ≥ min_sun_h zusammenhängender Sonnenschein war.
                # Verhindert falsches dew_present=True nach Neustart wenn Sonne gerade unter 200 W/m²
                period_start: datetime | None = None
                for state in entity_states:  # oldest → newest
                    try:
                        if float(state.state) >= RADIATION_SUN_THRESHOLD:
                            if period_start is None:
                                period_start = state.last_updated
                            if (state.last_updated - period_start).total_seconds() / 3600 >= min_sun_h:
                                self._dew_cleared_today = True
                                _LOGGER.debug(
                                    "Dew-Latch aus vergangener Sonnenperiode (≥ %.1f h) gesetzt",
                                    min_sun_h,
                                )
                                break
                        else:
                            period_start = None
                    except (ValueError, TypeError):
                        period_start = None
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Could not read sunshine history from recorder: %s", exc)

    async def _init_rain_buffer_from_recorder(self, cfg: dict, now_utc: datetime) -> None:
        """Rekonstruiert den 12h-Regenpuffer aus dem HA-Recorder.

        Beim Neustart / Update / Neuinstallation: direkt korrekte Wetness statt
        leerem Puffer. Die Recorder-States werden mit derselben anbieterabhängigen
        Logik wie im Live-Update in Slot-mm umgerechnet.
        """
        rain_entity = cfg.get(CONF_RAIN_SENSOR)
        if not rain_entity or self._rain_normalizer is None:
            return
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import state_changes_during_period

            start = now_utc - timedelta(hours=12)
            states_map = await get_instance(self.hass).async_add_executor_job(
                state_changes_during_period,
                self.hass, start, now_utc, rain_entity, True, False,
            )
            entity_states = states_map.get(rain_entity, [])
            if not entity_states:
                return

            tuples: list[tuple[float, float]] = []
            for st in entity_states:
                v = _safe_float(st.state)
                if v is not None:
                    tuples.append((st.last_updated.timestamp(), max(0.0, v)))
            if not tuples:
                return

            slots = rebuild_slots(
                self._rain_normalizer.mode,
                tuples,
                start.timestamp(),
                RAIN_BUFFER_MAXLEN,
                UPDATE_INTERVAL_MINUTES,
            )
            self._rain_buffer = deque(slots, maxlen=RAIN_BUFFER_MAXLEN)
            # Normalizer-Zustand setzen, damit das erste Live-Update korrekt anschließt.
            self._rain_normalizer.prime(tuples[-1][1], tuples[-1][0])
            _LOGGER.debug(
                "Rain buffer restored from recorder: %d slots, weighted_12h=%.2f mm",
                len(self._rain_buffer),
                self._compute_weighted_rain(),
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Could not restore rain buffer from recorder: %s", exc)

    async def _init_duration_from_recorder(
        self, cfg: dict, now_utc: datetime, now_local: datetime
    ) -> None:
        """Rekonstruiert die heutige Mähdauer aus dem HA-Recorder.

        Akkurater als eigener Storage, da alle State-Änderungen erfasst werden.
        Erkennt auch eine noch laufende Mähsession nach Neustart während des Mähens.
        """
        mower_entity = cfg.get(CONF_MOWER_ENTITY)
        if not mower_entity:
            return
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import state_changes_during_period

            # Heute seit Mitternacht (lokale Zeit → UTC)
            midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            midnight_utc   = dt_util.as_utc(midnight_local)

            states_map = await get_instance(self.hass).async_add_executor_job(
                state_changes_during_period,
                self.hass, midnight_utc, now_utc, mower_entity, True, False,
            )
            entity_states = states_map.get(mower_entity, [])
            if not entity_states:
                return

            # Alle abgeschlossenen Mähsessions summieren
            total_s        = 0.0
            session_start: float | None = None
            last_is_mowing = False

            for state in entity_states:
                ts = state.last_updated.timestamp()
                if state.state == "mowing":
                    if session_start is None:
                        session_start = ts
                    last_is_mowing = True
                else:
                    if session_start is not None:
                        total_s += ts - session_start
                        session_start = None
                    last_is_mowing = False

            # Abgeschlossene Dauer: Recorder-Wert ist akkurater als Storage
            if total_s > self._duration_today_s:
                self._duration_today_s = total_s
                _LOGGER.debug(
                    "Mowing duration restored from recorder: %.1f min",
                    total_s / 60,
                )

            # Läuft der Mäher noch? → _mow_start_ts setzen falls noch nicht getrackt
            if last_is_mowing and session_start is not None and self._mow_start_ts is None:
                # Wichtig: aktuellen Mäher-State prüfen bevor _mow_start_ts gesetzt wird.
                # Race Condition: State-Change-Listener kann vor der Recorder-Init feuern
                # ("mowing → docked" mit _mow_start_ts=None → kein Clear).
                # Würde _mow_start_ts dann trotzdem gesetzt, zählt Duration endlos hoch.
                current_state = self.hass.states.get(mower_entity)
                if current_state and current_state.state == "mowing":
                    # Mäher mäht wirklich noch → Session tracken
                    self._mow_start_ts = session_start
                    _LOGGER.debug(
                        "Ongoing mowing session detected (started %.1f min ago)",
                        (now_utc.timestamp() - session_start) / 60,
                    )
                else:
                    # Session laut Recorder offen, aber Mäher ist nicht mehr in 'mowing'
                    # → als abgeschlossene Session werten (Ende ≈ jetzt oder last_updated)
                    end_ts = (
                        current_state.last_updated.timestamp()
                        if current_state
                        else now_utc.timestamp()
                    )
                    completed_s = max(0.0, end_ts - session_start)
                    if total_s + completed_s > self._duration_today_s:
                        self._duration_today_s = total_s + completed_s
                    _LOGGER.debug(
                        "Mowing session closed (recorder lag): +%.1f min → total %.1f min",
                        completed_s / 60,
                        self._duration_today_s / 60,
                    )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Could not restore mowing duration from recorder: %s", exc)

    async def _init_solar_peak_from_recorder(self, cfg: dict, now_utc: datetime) -> None:
        """Ermittelt den Solar-Peak der letzten 7 Tage aus dem HA-Recorder.

        Verhindert, dass ein frischer Start oder ein Update die Peak-Referenz verliert.
        Nur relevant wenn Recorder-Maximum > gespeicherter Peak (kein Rückwärtsüberschreiben).

        Priorität spiegelt _get_radiation(): lokaler Sensor → DWD → PV. Damit ist der
        Peak im selben Wertebereich wie die Laufzeit-Strahlung — sonst systematisch
        zu kleiner solar_factor wenn Peak gegen DWD kalibriert ist, Live gegen lokal.
        """
        radiation_entity = (
            cfg.get(CONF_LOCAL_RADIATION)
            or cfg.get(CONF_DWD_RADIATION)
            or cfg.get(CONF_PV_POWER)
        )
        if not radiation_entity:
            return
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import state_changes_during_period

            start = now_utc - timedelta(days=7)
            states_map = await get_instance(self.hass).async_add_executor_job(
                state_changes_during_period,
                self.hass, start, now_utc, radiation_entity, True, False,
            )
            entity_states = states_map.get(radiation_entity, [])
            if not entity_states:
                return

            # PV-Umrechnung nur, wenn weder lokaler Sensor noch DWD vorhanden
            is_pv = (
                not cfg.get(CONF_LOCAL_RADIATION)
                and not cfg.get(CONF_DWD_RADIATION)
                and bool(cfg.get(CONF_PV_POWER))
            )
            peak_kw  = float(cfg.get(CONF_PV_PEAK_KW, DEFAULT_PV_PEAK_KW))
            max_val  = SOLAR_PEAK_MIN

            for state in entity_states:
                v = _safe_float(state.state)
                if v is None:
                    continue
                if is_pv and peak_kw > 0:
                    v = max(0.0, v / (peak_kw * 1000) * 1000)
                else:
                    v = max(0.0, v)
                if v > max_val:
                    max_val = v

            if max_val > self._radiation_peak:
                old_peak = self._radiation_peak
                self._radiation_peak = max_val
                _LOGGER.debug(
                    "Solar peak restored from recorder: %.1f W/m² (was %.1f)",
                    max_val,
                    old_peak,
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Could not restore solar peak from recorder: %s", exc)

    # ── Listener ─────────────────────────────────────────────────────────────

    def _register_listeners(self) -> None:
        mower_id = self.entry.data.get(CONF_MOWER_ENTITY)
        if mower_id:
            self._mow_state_unsub = async_track_state_change_event(
                self.hass, mower_id, self._handle_mower_state_change
            )
        self._midnight_unsub = async_track_time_change(
            self.hass, self._handle_midnight, hour=0, minute=0, second=5
        )
        # Sofort-Refresh bei Regen-Erkennung — alle konfigurierten Quellen
        weather_id = self.entry.data.get(CONF_DWD_WEATHER)
        if weather_id:
            self._weather_state_unsub = async_track_state_change_event(
                self.hass, weather_id, self._handle_weather_state_change
            )
        rain_sensor_id = self.entry.data.get(CONF_RAIN_SENSOR)
        if rain_sensor_id:
            self._rain_sensor_unsub = async_track_state_change_event(
                self.hass, rain_sensor_id, self._handle_rain_sensor_change
            )
        detector_id = self.entry.data.get(CONF_RAIN_DETECTOR)
        if detector_id:
            self._rain_detect_unsub = async_track_state_change_event(
                self.hass, detector_id, self._handle_rain_detector_change
            )

    @callback
    def _handle_mower_state_change(self, event: Any) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        now_ts = dt_util.utcnow().timestamp()

        if old_state and old_state.state == "mowing":
            if self._mow_start_ts is not None:
                session_s = now_ts - self._mow_start_ts
            else:
                # Race Condition: _mow_start_ts war beim Mähbeginn noch nicht gesetzt
                # (z. B. Listener feuerte vor Recorder-Init beim HA-Start).
                # old_state.last_updated = Zeitpunkt des Eintritts in "mowing" → guter Fallback.
                session_s = now_ts - old_state.last_updated.timestamp()
                _LOGGER.debug(
                    "weather_mow: Mähende ohne _mow_start_ts — old_state.last_updated als Fallback (%.1f min)",
                    session_s / 60,
                )
            self._duration_today_s += max(0.0, session_s)
            self._mow_start_ts = None
            # GDD-Reset nur nach vollständigem Mähzyklus (kumulierte Sessions)
            cfg = {**self.entry.data, **self.entry.options}
            full_cycle_s = float(cfg.get(CONF_FULL_CYCLE_H, DEFAULT_FULL_CYCLE_H)) * 3600
            self._mow_since_last_gdd_reset_s += session_s
            if self._mow_since_last_gdd_reset_s >= full_cycle_s:
                self._growth_gdd_accum = 0.0
                self._mow_since_last_gdd_reset_s = 0.0
                _LOGGER.debug(
                    "weather_mow: GDD-Akkumulator zurückgesetzt nach %.1f min kumulierter Mähzeit",
                    full_cycle_s / 60,
                )

        if new_state and new_state.state == "mowing":
            self._mow_start_ts = now_ts
            cfg = {**self.entry.data, **self.entry.options}
            # auto_resume_blocked nur wenn:
            #   1. Haupt-Switch ist AN (wenn AUS: Nutzer steuert manuell, kein Stop)
            #   2. Prevent-Auto-Resume aktiviert
            #   3. mow_allowed war False wegen Wetter/Natur (nicht wegen Zeitfenster/Tagesziel)
            _STOP_WORTHY_BLOCKS = {"dew_present", "too_wet", "too_dark_hedgehog"}
            _switch_is_off = (self.switch_entity is not None and not self.switch_entity.is_on)
            if (
                not _switch_is_off
                and cfg.get(CONF_PREVENT_AUTO_RESUME, DEFAULT_PREVENT_AUTO_RESUME)
                and not self._last_mow_allowed
                and self._last_block_reason in _STOP_WORTHY_BLOCKS
            ):
                _LOGGER.warning(
                    "weather_mow: Unerlaubter Mähstart erkannt (block_reason=%s) → stop_now=True",
                    self._last_block_reason,
                )
                self._auto_resume_blocked = True

    @callback
    def _handle_weather_state_change(self, event: Any) -> None:
        """Sofort-Refresh wenn Weather-Condition zu/von Regen wechselt."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        new_cond = new_state.state
        old_cond = old_state.state if old_state else ""
        if new_cond in CONDITION_RAIN_RATE or old_cond in CONDITION_RAIN_RATE:
            self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _handle_rain_sensor_change(self, event: Any) -> None:
        """Sofort-Refresh wenn Regen-Sensor den 0.1-Schwellwert kreuzt (Netatmo, Ecowitt)."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        new_val = _safe_float(new_state.state)
        old_val = _safe_float(old_state.state) if old_state else None
        if new_val is None:
            return
        was_raining = (old_val or 0.0) > 0.1
        is_raining  = new_val > 0.1
        if was_raining != is_raining:  # Schwellwert-Übergang → sofort aktualisieren
            self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _handle_rain_detector_change(self, event: Any) -> None:
        """Sofort-Refresh bei jedem Wechsel des Regen-Detektors (binary_sensor oder Sensor)."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in _UNAVAILABLE:
            return
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _handle_midnight(self, now: datetime) -> None:
        self._duration_day_before_s = self._duration_yesterday_s
        self._duration_yesterday_s  = self._duration_today_s
        self._duration_today_s      = 0.0
        self._mow_start_ts          = None
        self.emergency_mow_active   = False
        self._dew_cleared_today     = False  # Tau-Latch täglich zurücksetzen
        self.hass.async_create_task(self._flush_storage())

    # ── Shutdown ─────────────────────────────────────────────────────────────

    async def async_shutdown(self) -> None:
        for attr in (
            "_mow_state_unsub", "_midnight_unsub",
            "_weather_state_unsub", "_rain_sensor_unsub", "_rain_detect_unsub",
        ):
            unsub = getattr(self, attr, None)
            if unsub:
                try:
                    unsub()
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, attr, None)
        await self._flush_storage()

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _current_duration_today_h(self) -> float:
        base = self._duration_today_s
        if self._mow_start_ts is not None:
            base += dt_util.utcnow().timestamp() - self._mow_start_ts
        return base / 3600

    def _get_sun_elevation(self) -> float:
        sun = self.hass.states.get("sun.sun")
        if sun is None:
            return 0.0
        return _safe_float(str(sun.attributes.get("elevation", 0))) or 0.0

    def _get_radiation(self, cfg: dict, sun_elev: float) -> float:
        # Höchste Priorität: lokaler Sensor (präzisester Echtzeit-Wert, direkt am Standort)
        if cfg.get(CONF_LOCAL_RADIATION):
            val = _state_float(self.hass, cfg[CONF_LOCAL_RADIATION])
            if val is not None:
                return max(0.0, val)

        # DWD Strahlungssensor (regional interpoliert, aber mit Prognose-Daten)
        if cfg.get(CONF_DWD_RADIATION):
            val = _state_float(self.hass, cfg[CONF_DWD_RADIATION])
            if val is not None:
                return max(0.0, val)

        # Fallback PV
        source = cfg.get(CONF_RADIATION_SOURCE, RADIATION_SOURCE_PV)
        if source == RADIATION_SOURCE_PV and cfg.get(CONF_PV_POWER):
            pv_w = _state_float(self.hass, cfg[CONF_PV_POWER])
            if pv_w is not None:
                peak_kw = float(cfg.get(CONF_PV_PEAK_KW, DEFAULT_PV_PEAK_KW))
                if peak_kw > 0:
                    return max(0.0, pv_w / (peak_kw * 1000) * 1000)

        # Fallback Sonnenhöhe
        return max(0.0, math.sin(math.radians(sun_elev)) * 800)

    def _build_rain_normalizer(self, cfg: dict) -> RainNormalizer | None:
        """Erzeugt den Normalizer passend zur konfigurierten Regenquelle."""
        mode = resolve_rain_mode(
            cfg.get(CONF_RAIN_PROVIDER, ""),
            cfg.get(CONF_RAIN_SENSOR_TYPE),
        )
        if mode is None or not cfg.get(CONF_RAIN_SENSOR):
            return None
        return RainNormalizer(mode)

    def _compute_weighted_rain(self) -> float:
        buf = list(self._rain_buffer)
        total = 0.0
        for i, val in enumerate(buf):
            weight = 0.1
            for r, w in RAIN_WEIGHT_MAP:
                if i in r:
                    weight = w
                    break
            total += val * weight
        return total

    def _parse_dwd_forecasts(self, cfg: dict, now_utc: datetime) -> tuple[float, float, float, float]:
        """
        Gibt zurück: (rain_today_remaining, rain_tomorrow, rain_fc_3h, radiation_fc_3h)
        Liest stündliche Prognosen aus state_attr(entity, "data").
        """
        # Mitternacht in Lokalzeit berechnen — DWD-Timestamps sind UTC, aber
        # "heute" / "morgen" bezieht sich auf den lokalen Kalendertag.
        now_local = dt_util.as_local(now_utc)
        midnight_today    = dt_util.as_utc(now_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
        midnight_tomorrow = midnight_today + timedelta(days=1)

        # Niederschlags-Prognose
        rain_today_remaining = 0.0
        rain_tomorrow        = 0.0
        rain_fc_3h           = 0.0

        hourly_precip: list[tuple[datetime, float]] = []
        precip_state = self.hass.states.get(cfg.get(CONF_DWD_PRECIP, ""))
        if precip_state:
            data_list = precip_state.attributes.get("data") or []
            for entry in data_list:
                try:
                    dt_str = entry.get("datetime", "")
                    # DWD liefert Z-Suffix oder ISO-Format
                    dt_str = dt_str.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(dt_str)
                    val = float(entry.get("value") or 0)
                    if now_utc <= dt < midnight_today:
                        rain_today_remaining += val
                    if midnight_today <= dt < midnight_tomorrow:
                        rain_tomorrow += val
                    if now_utc <= dt <= now_utc + timedelta(hours=3):
                        rain_fc_3h += val
                    hourly_precip.append((dt, val))
                except (ValueError, TypeError, AttributeError):
                    continue
        self._dwd_hourly_precip = hourly_precip

        # Strahlungs-Prognose (nächste 3h, für Wetness Score nicht direkt genutzt)
        radiation_fc_3h = 0.0
        hourly_radiation: list[tuple[datetime, float]] = []
        if cfg.get(CONF_DWD_RADIATION):
            rad_state = self.hass.states.get(cfg[CONF_DWD_RADIATION])
            if rad_state:
                rad_data = rad_state.attributes.get("data") or []
                count = 0
                total = 0.0
                for entry in rad_data:
                    try:
                        dt_str = entry.get("datetime", "").replace("Z", "+00:00")
                        dt = datetime.fromisoformat(dt_str)
                        val = float(entry.get("value") or 0)
                        if now_utc <= dt <= now_utc + timedelta(hours=3):
                            total += val
                            count += 1
                        hourly_radiation.append((dt, val))
                    except (ValueError, TypeError, AttributeError):
                        continue
                if count:
                    radiation_fc_3h = total / count
        self._dwd_hourly_radiation = hourly_radiation

        return rain_today_remaining, rain_tomorrow, rain_fc_3h, radiation_fc_3h

    async def _parse_owm_forecasts(
        self, cfg: dict, now_utc: datetime
    ) -> tuple[float, float, float, float]:
        """Liest stündliche Prognosen aus der weather entity via HA service call.

        Funktioniert mit OpenWeatherMap, met.no, AccuWeather und jeder anderen
        weather-Integration die den Standard-HA-Forecast-Service unterstützt.
        Strahlung wird aus cloud_coverage geschätzt (OWM liefert keine W/m²).
        """
        weather_entity = cfg.get(CONF_DWD_WEATHER, "")
        if not weather_entity:
            return 0.0, 0.0, 0.0, 0.0

        try:
            result = await self.hass.services.async_call(
                "weather", "get_forecasts",
                {"entity_id": weather_entity, "type": "hourly"},
                blocking=True, return_response=True,
            )
            forecast_list = (result or {}).get(weather_entity, {}).get("forecast", [])
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("OWM forecast service call failed: %s", exc)
            return 0.0, 0.0, 0.0, 0.0

        # Mitternacht in Lokalzeit — forecast-Daten sind UTC, aber "heute"/"morgen"
        # bezieht sich auf den lokalen Kalendertag (z.B. UTC+2: Mitternacht = 22:00 UTC).
        now_local_owm = dt_util.as_local(now_utc)
        midnight_today    = dt_util.as_utc(now_local_owm.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
        midnight_tomorrow = midnight_today + timedelta(days=1)

        rain_today_remaining = rain_tomorrow = rain_fc_3h = radiation_fc_3h = 0.0
        hourly_precip:    list[tuple[datetime, float]] = []
        hourly_radiation: list[tuple[datetime, float]] = []

        for fc in forecast_list:
            try:
                dt_str = str(fc.get("datetime", "")).replace("Z", "+00:00")
                dt = datetime.fromisoformat(dt_str)
                precip = float(fc.get("native_precipitation") or 0.0)  # mm/h
                cloud  = float(fc.get("cloud_coverage") or 0.0)        # %

                # Cloud-Coverage → Strahlungsschätzung W/m²
                # Tageszeit-basierter Kosinus (Mittagsmaximum 12:00 lokal = 0°, 6h/18h = 90°).
                # Besser als aktuelle Sonnenhöhe, die für Prognosestunden falsch wäre.
                dt_local = dt_util.as_local(dt) if dt.tzinfo else dt
                hour_local = dt_local.hour + dt_local.minute / 60.0
                noon_diff_deg = (hour_local - 12.0) * 15.0   # 15°/h → 90° bei ±6h
                sun_factor = max(0.0, math.cos(math.radians(noon_diff_deg)))
                rad_est = max(0.0, (1.0 - cloud / 100.0) * sun_factor * 800.0)

                hourly_precip.append((dt, precip))
                hourly_radiation.append((dt, rad_est))

                if now_utc <= dt < midnight_today:
                    rain_today_remaining += precip
                if midnight_today <= dt < midnight_tomorrow:
                    rain_tomorrow += precip
                if now_utc <= dt <= now_utc + timedelta(hours=3):
                    rain_fc_3h     += precip
                    radiation_fc_3h = max(radiation_fc_3h, rad_est)
            except (ValueError, TypeError, AttributeError):
                continue

        self._dwd_hourly_precip    = hourly_precip
        self._dwd_hourly_radiation = hourly_radiation
        return rain_today_remaining, rain_tomorrow, rain_fc_3h, radiation_fc_3h

    async def _parse_forecasts(
        self, cfg: dict, now_utc: datetime
    ) -> tuple[float, float, float, float]:
        """Dispatcher: DWD (Sensor mit data-Attribut) oder OWM/generisch (weather service)."""
        if cfg.get(CONF_DWD_PRECIP):
            # DWD-Pfad: dedizierter Sensor mit stündlichem data-Attribut
            return self._parse_dwd_forecasts(cfg, now_utc)
        # OWM/generischer Pfad: weather.get_forecasts Service
        return await self._parse_owm_forecasts(cfg, now_utc)

    def _get_temp_humidity(self, cfg: dict) -> tuple[float, float]:
        temp = None
        if cfg.get(CONF_TEMP):
            temp = _state_float(self.hass, cfg[CONF_TEMP])
        if temp is None and cfg.get(CONF_DWD_WEATHER):
            temp = _attr_float(self.hass, cfg[CONF_DWD_WEATHER], "temperature")
        temp = temp if temp is not None else 15.0

        humidity = None
        if cfg.get(CONF_HUMIDITY):
            humidity = _state_float(self.hass, cfg[CONF_HUMIDITY])
        if humidity is None and cfg.get(CONF_DWD_WEATHER):
            humidity = _attr_float(self.hass, cfg[CONF_DWD_WEATHER], "humidity")
        humidity = humidity if humidity is not None else 70.0

        return temp, humidity

    def _current_battery_pct(self, cfg: dict) -> tuple[float, bool]:
        """Akkustand und ob der Wert frisch ist (< BATTERY_STALE_MINUTES alt).

        Returns:
            (battery_pct, is_fresh)
        """
        batt_entity = cfg.get(CONF_BATTERY_SENSOR, DEFAULT_BATTERY_SENSOR)
        state = self.hass.states.get(batt_entity)
        if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                val = float(state.state)
                age_s = (dt_util.utcnow() - state.last_updated).total_seconds()
                is_fresh = age_s < BATTERY_STALE_MINUTES * 60
                return val, is_fresh
            except (ValueError, TypeError, AttributeError):
                pass
        # Fallback: Attribut der lawn_mower-Entity (immer als veraltet markiert)
        mower_state = self.hass.states.get(cfg.get(CONF_MOWER_ENTITY, ""))
        if mower_state:
            batt = mower_state.attributes.get("battery_level")
            if batt is not None:
                try:
                    return float(batt), False
                except (ValueError, TypeError):
                    pass
        return 100.0, False  # unbekannt → kein Blockieren, als veraltet behandeln

    def _check_brightness(self, cfg: dict, sun_elev: float) -> bool:
        if sun_elev >= 10:
            return True
        if cfg.get(CONF_BRIGHTNESS):
            brightness = _state_float(self.hass, cfg[CONF_BRIGHTNESS])
            if brightness is not None:
                return brightness >= int(cfg.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS))
        return False

    def _get_wind_drying(self, cfg: dict) -> float:
        # Primär: dedizierter Wind-Sensor (DWD oder lokal)
        if cfg.get(CONF_DWD_WIND):
            kmh = _state_float(self.hass, cfg[CONF_DWD_WIND])
            if kmh is not None:
                return min(1.0, kmh / 30.0) * 5.0

        # Fallback: wind_speed-Attribut der weather-Entity (OWM, met.no, …)
        if cfg.get(CONF_DWD_WEATHER):
            kmh = _attr_float(self.hass, cfg[CONF_DWD_WEATHER], "wind_speed")
            if kmh is not None:
                return min(1.0, kmh / 30.0) * 5.0

        return 0.0

    @property
    def _switch_enabled(self) -> bool:
        if self.switch_entity is not None:
            return self.switch_entity.is_on
        return True

    @property
    def _emergency_switch_enabled(self) -> bool:
        if self.emergency_switch_entity is not None:
            return self.emergency_switch_entity.is_on
        return True

    def _effective_solar_factor(
        self, solar_factor: float, now_local: datetime
    ) -> float:
        """Auf den Rasen tatsächlich ankommender Anteil des Solar-Faktors.

        Liest die Live-Werte der beiden UI-Entitäten (`lawn_sun_efficiency`,
        `lawn_sun_from`); fällt auf die Defaults zurück, falls die Entitäten
        während des ersten Refreshs noch nicht verdrahtet sind.
        """
        efficiency = DEFAULT_LAWN_SUN_EFFICIENCY
        if self.lawn_sun_efficiency_entity is not None:
            val = self.lawn_sun_efficiency_entity.native_value
            if val is not None:
                efficiency = float(val)

        from datetime import time as dt_time
        sun_from = dt_time.fromisoformat(DEFAULT_LAWN_SUN_FROM)
        if self.lawn_sun_from_entity is not None:
            val = self.lawn_sun_from_entity.native_value
            if val is not None:
                sun_from = val

        return effective_solar_factor(
            solar_factor, efficiency, sun_from, now_local.time()
        )

    def _compute_wetness(
        self,
        rain_weighted_12h: float,
        rain_today: float,
        solar_factor: float,
        dew_present: bool,
        wind_drying: float,
        rain_fc_3h: float,
        precip_nowcast: float,
    ) -> int:
        rain_score      = rain_weighted_12h * RAIN_SCORE_PER_MM
        morning_penalty = min(40.0, rain_today * 1.5) * (1 - solar_factor)
        dew_score       = 35 if dew_present else 0
        drying          = solar_factor * 15
        wind_dry        = wind_drying
        future_score    = rain_fc_3h * 8

        score = max(0.0, rain_score + morning_penalty + dew_score - drying - wind_dry + future_score)
        if precip_nowcast > 0.1:
            score = max(score, 70.0)
        return min(100, round(score))

    def _compute_decision(
        self,
        cfg: dict,
        now_local: datetime,
        wetness_score: int,
        brightness_ok: bool,
        dew_present: bool,
        rain_today_remaining: float,
        rain_tomorrow: float,
        duration_today_h: float,
    ) -> tuple[bool, bool, str]:
        # 1. Switch
        if not self._switch_enabled:
            return False, False, "disabled"

        # 2. Mähfenster
        mow_start_str = cfg.get(CONF_MOW_START, "08:00:00")
        mow_end_str   = cfg.get(CONF_MOW_END,   "20:00:00")
        try:
            mow_start = dt_util.parse_time(mow_start_str)
            mow_end   = dt_util.parse_time(mow_end_str)
        except (ValueError, AttributeError):
            mow_start = dt_util.parse_time("08:00:00")
            mow_end   = dt_util.parse_time("20:00:00")

        current_time = now_local.time()
        if not (mow_start <= current_time <= mow_end):
            return False, False, "outside_time_window"

        # 3. Helligkeit / Igelschutz
        if not brightness_ok:
            return False, False, "too_dark_hedgehog"

        # 4. Akku-Check wurde hieraus entfernt:
        # Akku verhindert nur neue Starts (start_now), niemals stop_now.
        # Der Mäher beendet laufende Sessions selbst (eigene Firmware).
        # → Akku-Block erfolgt in _async_update_data() nach Prioritätsberechnung.

        # 5 & 6. Tagesziel + Notmähen (vor Tau-Check: Notmähen übersteuert Tau)
        target     = float(cfg.get(CONF_TARGET_DAILY_H, 3.0))
        full_cycle = float(cfg.get(CONF_FULL_CYCLE_H,   2.0))
        thresh_tmrw  = float(cfg.get(CONF_THRESH_RAIN_TMRW,  8.0))
        thresh_em_h  = float(cfg.get(CONF_THRESH_EMERG_H,    2.0))

        if duration_today_h >= target:
            if self._emergency_switch_enabled and rain_tomorrow >= thresh_tmrw:
                end_dt = now_local.replace(
                    hour=mow_end.hour, minute=mow_end.minute, second=0, microsecond=0
                )
                time_remaining_h = max(0.0, (end_dt - now_local).total_seconds() / 3600)
                if (time_remaining_h >= thresh_em_h
                        and duration_today_h < (target + full_cycle)):
                    self.emergency_mow_active = True
                    return True, True, "emergency_mow_tomorrow_rain"
            # Bedingungen für Notmähen nicht mehr erfüllt → Flag zurücksetzen
            self.emergency_mow_active = False
            return False, False, "daily_target_reached"

        # 7. Tau (harte Sperre, aber nach Notmäh-Check)
        if dew_present:
            return False, False, "dew_present"

        # 8. Nässeprüfung
        thresh_wet = float(cfg.get(CONF_THRESH_WETNESS, 30))
        if wetness_score >= thresh_wet:
            return False, False, "too_wet"

        # 9. Regenprognose heute
        thresh_rain_today = float(cfg.get(CONF_THRESH_RAIN_TODAY, 5.0))
        if rain_today_remaining >= thresh_rain_today:
            return False, False, "rain_expected_today"

        # 10. Erlaubt
        return True, False, "mowing_allowed"

    def _compute_priority(
        self,
        cfg: dict,
        now_local: datetime,
        wetness_score: int,
        duration_today_h: float,
        duration_avg_3d_h: float,
        mow_allowed: bool,
        growth_ratio: float = 0.0,
    ) -> int:
        if not mow_allowed:
            return 0

        target = float(cfg.get(CONF_TARGET_DAILY_H, 3.0))
        deficit_ratio = max(0.0, 1 - duration_today_h / target) if target > 0 else 0.0
        deficit_score = deficit_ratio * 40
        avg_deficit   = max(0.0, 1 - duration_avg_3d_h / target) if target > 0 else 0.0
        avg_score     = avg_deficit * 20
        emergency_bonus = 40 if self.emergency_mow_active else 0
        growth_bonus    = round(growth_ratio * 15)   # bis +15 Punkte (0→6mm ignoriert, linear bis 20mm)
        wetness_penalty = min(30.0, wetness_score * 0.3)

        mow_end_str = cfg.get(CONF_MOW_END, "20:00:00")
        target_buffer_h = float(cfg.get(CONF_TARGET_BUFFER_H, DEFAULT_TARGET_BUFFER_H))
        try:
            mow_end = dt_util.parse_time(mow_end_str)
            end_dt = now_local.replace(hour=mow_end.hour, minute=mow_end.minute, second=0, microsecond=0)
            # Effektive Fertig-Deadline: target_buffer_h vor Fenster-Ende
            target_end_dt = end_dt - timedelta(hours=target_buffer_h)
            time_to_target_h = max(0.0, (target_end_dt - now_local).total_seconds() / 3600)
        except (ValueError, AttributeError):
            time_to_target_h = 4.0
        # Urgency-Fenster wächst mit verbleibendem Defizit:
        # Bei vollem Defizit (nichts gemäht): 8h Fenster → Druck ab ~10:00
        # Bei leerem Defizit (alles gemäht):  3h Fenster → kaum Urgency
        urgency_window_h = 3.0 + deficit_ratio * 5.0
        urgency_bonus = min(15.0, max(0.0, urgency_window_h - time_to_target_h) * 5)
        hour = now_local.hour + now_local.minute / 60.0
        if 11.0 <= hour < 16.0:
            midday_bonus = 10.0
        elif 10.0 <= hour < 11.0:
            midday_bonus = (hour - 10.0) * 10.0
        elif 16.0 <= hour < 17.0:
            midday_bonus = (17.0 - hour) * 10.0
        else:
            midday_bonus = 0.0

        priority = min(100, max(0, int(
            deficit_score + avg_score + emergency_bonus + growth_bonus
            + urgency_bonus + midday_bonus - wetness_penalty
        )))
        return priority

    def _forecast_next_mow(
        self,
        cfg: dict,
        now_local: datetime,
        now_utc: datetime,
        current_wetness: int,
        dew_present: bool,
        radiation_now: float = 0.0,
        duration_today_h: float = 0.0,
    ) -> datetime | None:
        """Stündliche Vorausschau (max. 48h): wann wäre Mähen das nächste Mal möglich?

        Vereinfachtes Modell: kein Akkustand, kein Switch-Status.
        Berücksichtigt: Mähfenster + geschätzte Wetness + Regenprognose + Tau + Tagesziel.
        """
        if not self._dwd_hourly_precip:
            return None

        mow_start_str = cfg.get(CONF_MOW_START, "08:00:00")
        mow_end_str   = cfg.get(CONF_MOW_END, "20:00:00")
        try:
            mow_start = dt_util.parse_time(mow_start_str)
            mow_end   = dt_util.parse_time(mow_end_str)
        except (ValueError, AttributeError):
            mow_start = dt_util.parse_time("08:00:00")
            mow_end   = dt_util.parse_time("20:00:00")

        thresh_wetness    = int(cfg.get(CONF_THRESH_WETNESS, 30))
        thresh_rain_today = float(cfg.get(CONF_THRESH_RAIN_TODAY, 5.0))
        min_sun_h         = float(cfg.get(CONF_MIN_SUN_H_FOR_DEW, DEFAULT_MIN_SUN_H_FOR_DEW))
        radiation_peak    = max(self._radiation_peak, SOLAR_PEAK_MIN)
        target_h          = float(cfg.get(CONF_TARGET_DAILY_H, 3.0))

        # Stunden-Lookups aufbauen
        precip_by_hour: dict[datetime, float] = {}
        for dt_h, val in self._dwd_hourly_precip:
            h = dt_h.replace(minute=0, second=0, microsecond=0)
            precip_by_hour[h] = precip_by_hour.get(h, 0.0) + val

        rad_by_hour: dict[datetime, float] = {}
        for dt_h, val in self._dwd_hourly_radiation:
            h = dt_h.replace(minute=0, second=0, microsecond=0)
            rad_by_hour[h] = max(rad_by_hour.get(h, 0.0), val)

        # Basis-Wetness: aktuellen Score "entdrying" — den bereits abgezogenen
        # Trocknungsterm (solar_factor × 15) wieder addieren, damit wetness_base
        # den Rohwert des Regen-Buffers repräsentiert. Jede Prognosestunde wendet
        # ihren eigenen Trocknungsterm an (kein kumulativer Doppelabzug mehr).
        dew_score_now = 35.0 if dew_present else 0.0
        current_drying = min(1.0, radiation_now / radiation_peak) * 15.0
        wetness_base = max(0.0, float(current_wetness) - dew_score_now + current_drying)
        dew_still_present = dew_present

        # Sonnenstunden-Zähler aus persistierter Startzeit initialisieren
        # → nach Neustart/Update sofort korrekter Ausgangswert (Schwellwert 200 W/m²)
        if radiation_now >= RADIATION_SUN_THRESHOLD and self._sunshine_start_utc is not None:
            consecutive_sun_h = (now_utc - self._sunshine_start_utc).total_seconds() / 3600
        elif radiation_now >= RADIATION_SUN_THRESHOLD:
            consecutive_sun_h = 0.0  # gerade begonnen, noch keine volle Stunde
        else:
            consecutive_sun_h = 0.0

        # Wenn Sonne schon lange genug schien, Tau direkt als weg markieren
        if consecutive_sun_h >= min_sun_h:
            dew_still_present = False

        start_h = (now_utc + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

        for step in range(48):
            h_utc   = start_h + timedelta(hours=step)
            h_local = dt_util.as_local(h_utc)

            # Tagesziel heute schon erreicht → restliche heutige Stunden überspringen
            if target_h > 0 and duration_today_h >= target_h and h_local.date() == now_local.date():
                continue

            rad    = rad_by_hour.get(h_utc, 0.0)
            rain_h = precip_by_hour.get(h_utc, 0.0)

            # Tau-Tracking (wirkt auch außerhalb Mähfenster; Schwellwert 200 W/m²)
            if rad >= RADIATION_SUN_THRESHOLD:
                consecutive_sun_h += 1.0  # jeder Schritt = 1 Stunde
            else:
                consecutive_sun_h = 0.0
            if consecutive_sun_h >= min_sun_h:
                dew_still_present = False

            # Neuer Regen in dieser Stunde erhöht den Buffer-Score
            wetness_base = max(0.0, wetness_base + rain_h * 8.0)

            # Trocknungsterm dieser Stunde (einmalig, kein kumulativer Abzug)
            solar_factor_h = min(1.0, rad / radiation_peak)
            drying_h = solar_factor_h * 15.0

            # Regenprognose nächste 3h (future_score wie im echten Wetness-Score)
            rain_next_3h = sum(
                precip_by_hour.get(h_utc + timedelta(hours=i), 0.0)
                for i in range(1, 4)
            )
            future_score_h = min(60.0, rain_next_3h * 8.0)

            # Mähfenster-Check
            if not (mow_start <= h_local.time() <= mow_end):
                continue

            # Geschätzte Gesamtwetness: Buffer + Tau + Regenprognose − Trocknungsterm
            estimated = max(0.0, wetness_base + (35.0 if dew_still_present else 0.0) + future_score_h - drying_h)

            # Regenprognose von H bis Mitternacht (lokale Mitternacht)
            midnight_utc = h_utc.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            rain_to_midnight = sum(v for t, v in precip_by_hour.items() if h_utc <= t < midnight_utc)

            if estimated < thresh_wetness and rain_to_midnight < thresh_rain_today:
                return h_local

        return None

    # ── Haupt-Update ─────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        # Sicherheitsnetz falls _async_setup nicht aufgerufen wurde
        if not self._initialized:
            await self._async_setup()

        cfg = {**self.entry.data, **self.entry.options}
        now_utc   = dt_util.utcnow()
        now_local = dt_util.now()

        # ── Einmalige Initialisierung aus HA-Recorder ─────────────────────────
        # Beim ersten Update: alle persistierten Werte aus dem HA-Recorder
        # rekonstruieren — akkurater als eigener Storage, funktioniert auch
        # nach Neuinstallation oder HA-Abstürzen während des Betriebs.
        if not self._sunshine_initialized:
            self._sunshine_initialized = True
            self._rain_normalizer = self._build_rain_normalizer(cfg)
            await self._init_rain_buffer_from_recorder(cfg, now_utc)
            await self._init_duration_from_recorder(cfg, now_utc, now_local)
            await self._init_solar_peak_from_recorder(cfg, now_utc)
            await self._init_sunshine_from_recorder(cfg, now_utc)

        # 1. Regendaten — Sensorwert anbieterabhängig in Slot-mm normalisieren
        sensor_slot_mm = 0.0
        rain_state = self.hass.states.get(cfg.get(CONF_RAIN_SENSOR, ""))
        if (
            self._rain_normalizer is not None
            and rain_state is not None
            and rain_state.state not in _UNAVAILABLE
        ):
            val = _safe_float(rain_state.state)
            if val is not None:
                sensor_slot_mm = self._rain_normalizer.slot_mm(
                    val,
                    rain_state.last_updated.timestamp(),
                    UPDATE_INTERVAL_MINUTES,
                )

        rain_1h    = _state_float(self.hass, cfg.get(CONF_RAIN_1H,    "")) or 0.0
        rain_today_sensor = _state_float(self.hass, cfg.get(CONF_RAIN_TODAY, ""))
        if rain_today_sensor is not None:
            rain_today = rain_today_sensor
        else:
            # Kein Tagesregen-Sensor → aus dem Slot-Puffer ableiten (mm seit Mitternacht).
            minutes_since_midnight = now_local.hour * 60 + now_local.minute
            rain_today = rain_since_midnight(
                list(self._rain_buffer), minutes_since_midnight, UPDATE_INTERVAL_MINUTES
            )

        # Weather-Condition als zusätzliche Regen-Quelle (erkennt Niesel auch ohne
        # lokalen Sensor). Condition-Werte sind Raten (mm/h) → in Slot-mm umrechnen.
        condition_slot_mm = 0.0
        raining_by_condition = False
        if cfg.get(CONF_DWD_WEATHER):
            weather_state = self.hass.states.get(cfg[CONF_DWD_WEATHER])
            if weather_state and weather_state.state not in _UNAVAILABLE:
                condition_rate = CONDITION_RAIN_RATE.get(weather_state.state, 0.0)
                if condition_rate > 0.0:
                    condition_slot_mm = rate_to_slot_mm(condition_rate, UPDATE_INTERVAL_MINUTES)
                    raining_by_condition = True

        slot_mm = max(sensor_slot_mm, condition_slot_mm)
        self._rain_buffer.append(slot_mm)
        rain_weighted_12h = self._compute_weighted_rain()

        raining_now = slot_mm > RAINING_NOW_THRESHOLD_MM or raining_by_condition
        detector_id = cfg.get(CONF_RAIN_DETECTOR, "")
        if detector_id:
            det_state = self.hass.states.get(detector_id)
            if det_state and det_state.state not in _UNAVAILABLE:
                if det_state.state == "on":
                    raining_now = True
                else:
                    det_val = _safe_float(det_state.state)
                    if det_val is not None and det_val > 0.05:
                        raining_now = True

        # 2. Strahlung & Solar Peak
        sun_elev       = self._get_sun_elevation()
        radiation_now  = self._get_radiation(cfg, sun_elev)
        self._radiation_peak = max(
            SOLAR_PEAK_MIN,
            max(self._radiation_peak * DECAY_PER_UPDATE, radiation_now),
        )
        # _radiation_peak ist per Konstruktion >= radiation_now → solar_factor <= 1.0
        solar_factor = radiation_now / self._radiation_peak if self._radiation_peak > 0 else 0.0

        # Sonnenschein-Tracking für Tau-Prognose (in-memory, kein Storage nötig)
        # Schwellwert 200 W/m² = Sonne "zählt" physikalisch für Trocknungseffekt
        if radiation_now >= RADIATION_SUN_THRESHOLD:
            if self._sunshine_start_utc is None:
                self._sunshine_start_utc = now_utc
        else:
            self._sunshine_start_utc = None

        # 3. Prognosen (DWD-Sensor oder OWM/generisch über weather.get_forecasts)
        rain_today_remaining, rain_tomorrow, rain_fc_3h, _radiation_fc_3h = (
            await self._parse_forecasts(cfg, now_utc)
        )

        # Niederschlag-Nowcast: DWD-Sensorwert oder OWM-Attribut der weather-Entity
        if cfg.get(CONF_DWD_PRECIP):
            precip_nowcast = _state_float(self.hass, cfg[CONF_DWD_PRECIP]) or 0.0
        else:
            precip_nowcast = _attr_float(self.hass, cfg.get(CONF_DWD_WEATHER, ""), "precipitation") or 0.0

        # 4. Wind
        wind_drying = self._get_wind_drying(cfg)

        # 5. Taupunkt / Morgentau
        temp, humidity = self._get_temp_humidity(cfg)
        dew_point = temp - ((100 - humidity) / 5)
        dew_offset = float(cfg.get(CONF_THRESH_DEW_OFFSET, DEFAULT_THRESH_DEW_OFFSET))
        min_sun_h  = float(cfg.get(CONF_MIN_SUN_H_FOR_DEW, DEFAULT_MIN_SUN_H_FOR_DEW))

        # Wie lange scheint die Sonne schon kontinuierlich ≥ 200 W/m²?
        sunshine_h = 0.0
        if self._sunshine_start_utc is not None:
            sunshine_h = (now_utc - self._sunshine_start_utc).total_seconds() / 3600

        # Tau-Erkennung:
        # Initiale Trocknung: Temperatur UND Sonnenschein nötig (Grashalme physisch trocknen).
        # Nach Trocknung (_dew_cleared_today): nur Temperatur entscheidend — Tau kann nur
        # zurückkommen wenn die Temperatur wieder auf Taupunktnähe fällt. Sinkende Abend-
        # Strahlung ist kein Grund für erneutes dew_present.
        temp_ok = temp > dew_point + dew_offset
        sun_ok  = (sunshine_h >= min_sun_h) or (radiation_now >= RADIATION_INSTANT_CLEAR)

        if self._dew_cleared_today:
            # Einmal getrocknet: nur Temperatur entscheidet über Rückkehr von Tau
            dew_present = not temp_ok
        else:
            # Noch nicht getrocknet: braucht temp_ok UND sun_ok
            dew_evaporated = temp_ok and sun_ok
            if dew_evaporated:
                self._dew_cleared_today = True
            dew_present = not dew_evaporated

        # 5b. Wuchsmodell (GDD)
        gdd_step = max(0.0, temp - GDD_BASE_TEMP_C) / 288  # pro 5-Minuten-Schritt
        fertilizer_factor = 1.0
        # Dünge-Datum: date-Entität hat Vorrang, Options als Fallback
        last_fert = None
        if self.fertilization_date_entity is not None:
            last_fert = self.fertilization_date_entity.native_value
        if last_fert is None:
            last_fert_str = cfg.get(CONF_LAST_FERTILIZATION)
            if last_fert_str:
                try:
                    last_fert = dt_util.parse_date(last_fert_str)
                except (ValueError, TypeError, AttributeError):
                    pass
        if last_fert is not None:
            try:
                days_since = (dt_util.now().date() - last_fert).days
                if 0 <= days_since < FERTILIZER_ACTIVE_DAYS:
                    fertilizer_factor = FERTILIZER_BOOST_FACTOR
            except (ValueError, TypeError, AttributeError):
                pass
        self._growth_gdd_accum += gdd_step * fertilizer_factor
        max_growth_mm = float(cfg.get(CONF_MAX_GROWTH_MM, DEFAULT_MAX_GROWTH_MM))
        growth_mm = self._growth_gdd_accum * GROWTH_MM_PER_GDD
        # Linearer Anstieg ab 30 % des Max-Schwellwerts, volle Dringlichkeit bei 100 %
        growth_lower = max_growth_mm * 0.3
        if growth_mm <= growth_lower:
            growth_ratio = 0.0
        else:
            growth_ratio = min(1.0, (growth_mm - growth_lower) / (max_growth_mm - growth_lower))

        # 6. Helligkeit
        brightness_ok = self._check_brightness(cfg, sun_elev)

        # 7. Wetness Score
        wetness_score = self._compute_wetness(
            rain_weighted_12h, rain_today, solar_factor,
            dew_present, wind_drying, rain_fc_3h, precip_nowcast,
        )

        # 7b. Bewässerungs-Boost
        irrigation_on = (
            self.irrigation_switch_entity is not None
            and self.irrigation_switch_entity.is_on
        )
        if irrigation_on:
            # Während aktiver Bewässerung Boost auf Maximum halten
            self._irrigation_wetness_boost = float(IRRIGATION_WETNESS_BOOST)
        else:
            # Natürlicher Abbau (Boost wird beim Abschalten vom Switch-Entity gesetzt)
            self._irrigation_wetness_boost = max(
                0.0, self._irrigation_wetness_boost - IRRIGATION_DECAY_PER_UPDATE
            )
        # Boost auf Wetness-Score anwenden; Score auf 0–100 begrenzen
        wetness_score = min(100, max(wetness_score, int(self._irrigation_wetness_boost)))

        # 8. Akku-Plausibilisierung — Mähzustand aus Akkudelta ableiten
        # NUR bei dediziertem Akku-Sensor (CONF_BATTERY_SENSOR) und veraltetem Wert.
        # Das Mäher-Attribut (Fallback) ist immer is_fresh=False und löst bei jedem
        # normalen Standby-Verbrauch fälschlicherweise einen Mähvorgang aus → ausgeschlossen.
        battery_pct, battery_fresh = self._current_battery_pct(cfg)
        now_ts = dt_util.utcnow().timestamp()
        if cfg.get(CONF_BATTERY_SENSOR) and not battery_fresh and self._prev_battery_pct is not None:
            delta = battery_pct - self._prev_battery_pct
            if delta < -0.5 and self._mow_start_ts is None:
                # Akku sinkt, State-Update offenbar verpasst → Mähvorgang nacherfassen
                _LOGGER.debug("weather_mow: Akkudelta %.1f%% (veraltet) → Mähen nacherfasst", delta)
                self._mow_start_ts = now_ts
            elif delta > 0.5 and self._mow_start_ts is not None:
                # Akku steigt, Mähvorgang war offen → Andocken nacherfassen
                _LOGGER.debug("weather_mow: Akkudelta +%.1f%% (veraltet) → Andocken nacherfasst", delta)
                self._duration_today_s += now_ts - self._mow_start_ts
                self._mow_start_ts = None
        self._prev_battery_pct = battery_pct

        # 9. Mähdauer
        duration_today_h    = self._current_duration_today_h()
        duration_yesterday_h   = self._duration_yesterday_s / 3600
        duration_day_before_h  = self._duration_day_before_s / 3600
        duration_avg_3d_h   = (duration_today_h + duration_yesterday_h + duration_day_before_h) / 3

        # 10. Entscheidung
        mow_allowed, start_now, block_reason = self._compute_decision(
            cfg, now_local, wetness_score, brightness_ok, dew_present,
            rain_today_remaining, rain_tomorrow, duration_today_h,
        )

        # 11. Priorität
        priority = self._compute_priority(
            cfg, now_local, wetness_score,
            duration_today_h, duration_avg_3d_h, mow_allowed,
            growth_ratio=growth_ratio,
        )

        # start_now: Priority-Gate gilt solange genug Zeit im Fenster ist.
        # Bei Zeitdruck (Restzeit ≤ 3× noch benötigte Mähzeit) immer starten —
        # dann ist Warten auf bessere Bedingungen keine sinnvolle Option mehr.
        # Ausnahme: Emergency-Mähen setzt start_now bereits direkt in _compute_decision.
        if mow_allowed and block_reason == "mowing_allowed":
            target_h = float(cfg.get(CONF_TARGET_DAILY_H, 3.0))
            try:
                mow_end_t = dt_util.parse_time(cfg.get(CONF_MOW_END, "20:00:00"))
                end_dt_w = now_local.replace(
                    hour=mow_end_t.hour, minute=mow_end_t.minute, second=0, microsecond=0
                )
            except (ValueError, AttributeError):
                end_dt_w = now_local.replace(hour=20, minute=0, second=0, microsecond=0)
            remaining_window_h = max(0.0, (end_dt_w - now_local).total_seconds() / 3600)
            remaining_needed_h = max(0.0, target_h - duration_today_h)
            time_pressure = remaining_needed_h > 0 and remaining_window_h <= remaining_needed_h * 3
            start_now = (priority >= 40) or time_pressure
        # Bei emergency ist start_now bereits True

        # 11b. Morgen-Startverzögerung (nur für den allerersten Start des Tages)
        # Robuster Float-Vergleich: kürzer als 1 Sekunde gilt als "noch nicht gemäht"
        start_delay_s = float(cfg.get(CONF_START_DELAY_MIN, DEFAULT_START_DELAY_MIN)) * 60
        not_mowed_today = duration_today_h < (1.0 / 3600.0)
        if start_delay_s > 0 and not_mowed_today:
            # start_now_pre_delay: Was start_now ohne Delay wäre (für Tracking)
            start_now_pre_delay = start_now
            # Tracking: Ersten start_now=True Moment heute merken
            if start_now_pre_delay:
                if self._mow_first_allowed_ts is None:
                    self._mow_first_allowed_ts = now_utc.timestamp()
            else:
                # Bedingungen nicht mehr erfüllt → Countdown zurücksetzen
                self._mow_first_allowed_ts = None
            # Delay anwenden — außer bei hoher Dringlichkeit oder Notmähen
            delay_bypass = (
                priority >= DELAY_BYPASS_PRIORITY
                or self.emergency_mow_active
            )
            if (start_now_pre_delay
                    and not delay_bypass
                    and self._mow_first_allowed_ts is not None):
                elapsed = now_utc.timestamp() - self._mow_first_allowed_ts
                if elapsed < start_delay_s:
                    start_now = False
                    # mow_allowed bleibt True → Automationen sehen: erlaubt aber wartend
        elif not not_mowed_today:
            # Bereits gemäht heute → Tracking-Timestamp nicht mehr nötig
            self._mow_first_allowed_ts = None

        # 11c. Akku: verhindert nur NEUE Starts, niemals stop_now
        # mow_allowed bleibt True → prevent_auto_resume feuert nicht fälschlicherweise
        # Der Mäher regelt laufende Sessions selbst (Firmware geht nach Hause)
        min_batt = int(cfg.get(CONF_MIN_BATTERY_PCT, DEFAULT_MIN_BATTERY))
        if start_now and battery_pct < min_batt:
            start_now = False
            if block_reason == "mowing_allowed":
                block_reason = "battery_low"

        # 12. Prognose: wann ist Mähen das nächste Mal möglich?
        # Nur wenn start_now (Prio >= 40 UND erlaubt) → sofort; sonst Prognose
        if start_now:
            next_mow_expected: datetime | None = now_local
        else:
            next_mow_expected = self._forecast_next_mow(
                cfg, now_local, now_utc, wetness_score, dew_present,
                radiation_now=radiation_now,
                duration_today_h=duration_today_h,
            )

        # 11. Auto-Dock-Status übernehmen, dann zurücksetzen
        self._last_mow_allowed = mow_allowed
        self._last_block_reason = block_reason or ""
        auto_resume_blocked = self._auto_resume_blocked
        self._auto_resume_blocked = False

        # stop_now: Signal für Automationen — Mäher soll gestoppt werden
        # Gründe: Regen, Nässe, zu dunkel, Bewässerung aktiv, unerlaubter Start
        # Wenn der Haupt-Switch deaktiviert ist: kein stop_now (Nutzer steuert manuell)
        _switch_on = self.switch_entity is None or self.switch_entity.is_on
        stop_now = _switch_on and (
            raining_now
            or irrigation_on
            or auto_resume_blocked
            or (block_reason == "too_wet")
            or (block_reason == "too_dark_hedgehog")
        )

        # 12. Storage (non-blocking)
        self.hass.async_create_task(self._flush_storage())

        # Debug-CSV-Log wenn aktiviert
        if self.debug_switch_entity is not None and self.debug_switch_entity.is_on:
            result = {
                "wetness_score": wetness_score, "priority": priority,
                "start_now": start_now, "mow_allowed": mow_allowed,
                "stop_now": stop_now, "block_reason": block_reason or "",
                "emergency_mow_active": self.emergency_mow_active,
                "raining": raining_now, "dew_present": dew_present,
                "brightness_ok": brightness_ok,
                "rain_last_1h_mm": round(rain_1h, 3),
                "rain_weighted_12h": round(rain_weighted_12h, 3),
                "rain_today_mm": round(rain_today, 2),
                "rain_today_remaining": round(rain_today_remaining, 2),
                "rain_tomorrow": round(rain_tomorrow, 2),
                "radiation_peak": round(self._radiation_peak, 1),
                "solar_factor": round(solar_factor, 3),
                "sun_elevation": round(sun_elev, 1),
                "dew_point": round(dew_point, 1),
                "battery_pct": round(battery_pct, 1),
                "duration_today_h": round(duration_today_h, 3),
                "duration_avg_3d_h": round(duration_avg_3d_h, 3),
                "growth_mm": round(growth_mm, 1),
                "growth_ratio": round(growth_ratio, 3),
                "fertilizer_active": fertilizer_factor > 1.0,
                "irrigation_active": irrigation_on,
                "irrigation_boost": round(self._irrigation_wetness_boost, 1),
                "next_mow_expected": next_mow_expected,
            }
            # Non-blocking: File-I/O in den Executor-Pool auslagern
            self.hass.async_add_executor_job(self._write_debug_csv, result)

        return {
            "wetness_score":        wetness_score,
            "priority":             priority,
            "duration_today_h":     round(duration_today_h, 3),
            "duration_avg_3d_h":    round(duration_avg_3d_h, 3),
            "rain_last_1h_mm":      round(rain_1h, 3),
            "rain_weighted_12h":    round(rain_weighted_12h, 3),
            "rain_today_mm":        round(rain_today, 2),
            "rain_today_remaining": round(rain_today_remaining, 2),
            "rain_tomorrow":        round(rain_tomorrow, 2),
            "radiation_peak":       round(self._radiation_peak, 1),
            "solar_factor":         round(solar_factor, 3),
            "dew_point":            round(dew_point, 1),
            "dew_present":          dew_present,
            "brightness_ok":        brightness_ok,
            "sun_elevation":        round(sun_elev, 1),
            "mow_allowed":          mow_allowed,
            "start_now":            start_now,
            "stop_now":             stop_now,
            "emergency_mow_active": self.emergency_mow_active,
            "raining":              raining_now,
            "block_reason":         block_reason or "",
            "auto_resume_blocked":  auto_resume_blocked,
            "battery_pct":          round(battery_pct, 1),
            "growth_mm":            round(growth_mm, 1),
            "growth_ratio":         round(growth_ratio, 3),
            "fertilizer_active":    fertilizer_factor > 1.0,
            "irrigation_active":    irrigation_on,
            "irrigation_boost":     round(self._irrigation_wetness_boost, 1),
            "next_mow_expected":    next_mow_expected,
        }
