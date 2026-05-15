"""DataUpdateCoordinator für weather_mow."""
from __future__ import annotations

import logging
import math
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
    CONF_RAIN_SENSOR,
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
    DECAY_PER_UPDATE,
    DEFAULT_MIN_BATTERY,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_PREVENT_AUTO_RESUME,
    DEFAULT_PV_PEAK_KW,
    DEFAULT_THRESH_DEW_OFFSET,
    DOMAIN,
    RAIN_BUFFER_MAXLEN,
    RAIN_WEIGHT_MAP,
    RADIATION_SOURCE_PV,
    SOLAR_PEAK_MIN,
    STORAGE_KEY_MOWING,
    STORAGE_KEY_RAIN_BUF,
    STORAGE_KEY_SOLAR,
    STORAGE_VERSION,
    UPDATE_INTERVAL_MINUTES,
)

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
        self._mow_state_unsub = None
        self._midnight_unsub  = None

        # Mähdauer-Tracking
        self._mow_start_ts: float | None = None
        self._duration_today_s:      float = 0.0
        self._duration_yesterday_s:  float = 0.0
        self._duration_day_before_s: float = 0.0

        # Regen-Buffer
        self._rain_buffer: deque[float] = deque(maxlen=RAIN_BUFFER_MAXLEN)

        # Solar Peak
        self._radiation_peak: float = SOLAR_PEAK_MIN

        # Entscheidungszustand
        self.emergency_mow_active: bool = False

        # Auto-Dock-Schutz
        self._last_mow_allowed: bool = False
        self._auto_resume_blocked: bool = False

        # Akku-Plausibilisierung
        self._prev_battery_pct: float | None = None

        # Wuchsmodell (GDD-Akkumulator, reset bei jedem Mähende)
        self._growth_gdd_accum: float = 0.0

        # Bewässerungs-Boost (unabhängig vom Regen-Buffer)
        self._irrigation_wetness_boost: float = 0.0

        # Referenzen auf Switches (werden von switch.py gesetzt)
        self.switch_entity:            Any = None
        self.emergency_switch_entity:  Any = None
        self.irrigation_switch_entity: Any = None

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
            await self._store_growth.async_save({"gdd_accum": self._growth_gdd_accum})

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

    @callback
    def _handle_mower_state_change(self, event: Any) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        now_ts = dt_util.utcnow().timestamp()

        if old_state and old_state.state == "mowing" and self._mow_start_ts is not None:
            self._duration_today_s += now_ts - self._mow_start_ts
            self._mow_start_ts = None
            self._growth_gdd_accum = 0.0  # Wuchs nach Mähvorgang zurücksetzen

        if new_state and new_state.state == "mowing":
            self._mow_start_ts = now_ts
            cfg = {**self.entry.data, **self.entry.options}
            if cfg.get(CONF_PREVENT_AUTO_RESUME, DEFAULT_PREVENT_AUTO_RESUME) and not self._last_mow_allowed:
                _LOGGER.warning(
                    "weather_mow: Unerlaubter Mähstart erkannt (mow_allowed=False) → stop_now=True"
                )
                self._auto_resume_blocked = True

    @callback
    def _handle_midnight(self, now: datetime) -> None:
        self._duration_day_before_s = self._duration_yesterday_s
        self._duration_yesterday_s  = self._duration_today_s
        self._duration_today_s      = 0.0
        self._mow_start_ts          = None
        self.emergency_mow_active   = False
        self.hass.async_create_task(self._flush_storage())

    # ── Shutdown ─────────────────────────────────────────────────────────────

    async def async_shutdown(self) -> None:
        for attr in ("_mow_state_unsub", "_midnight_unsub"):
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
        # Primär: DWD Strahlungssensor
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
        midnight_today    = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
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
        if not cfg.get(CONF_DWD_WIND):
            return 0.0
        kmh = _state_float(self.hass, cfg[CONF_DWD_WIND])
        if kmh is None:
            return 0.0
        return min(1.0, kmh / 30.0) * 5.0

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
        rain_score      = rain_weighted_12h * 8
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

        # 4. Akku (aus dediziertem Sensor, Fallback: lawn_mower-Attribut)
        battery, _ = self._current_battery_pct(cfg)
        min_batt = int(cfg.get(CONF_MIN_BATTERY_PCT, DEFAULT_MIN_BATTERY))
        if battery < min_batt:
            return False, False, "battery_low"

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
        try:
            mow_end = dt_util.parse_time(mow_end_str)
            end_dt  = now_local.replace(hour=mow_end.hour, minute=mow_end.minute, second=0, microsecond=0)
            time_remaining_h = max(0.0, (end_dt - now_local).total_seconds() / 3600)
        except (ValueError, AttributeError):
            time_remaining_h = 6.0
        urgency_bonus = max(0.0, 3.0 - time_remaining_h) * 5
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
    ) -> datetime | None:
        """Stündliche Vorausschau (max. 48h): wann wäre Mähen das nächste Mal möglich?

        Vereinfachtes Modell: kein Akkustand, kein Tagesziel, kein Switch-Status.
        Nur: Mähfenster + geschätzte Wetness + Regenprognose + Tau.
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
        radiation_peak    = max(self._radiation_peak, SOLAR_PEAK_MIN)

        # Stunden-Lookups aufbauen
        precip_by_hour: dict[datetime, float] = {}
        for dt_h, val in self._dwd_hourly_precip:
            h = dt_h.replace(minute=0, second=0, microsecond=0)
            precip_by_hour[h] = precip_by_hour.get(h, 0.0) + val

        rad_by_hour: dict[datetime, float] = {}
        for dt_h, val in self._dwd_hourly_radiation:
            h = dt_h.replace(minute=0, second=0, microsecond=0)
            rad_by_hour[h] = max(rad_by_hour.get(h, 0.0), val)

        # Basis-Wetness ohne Tau-Anteil (Tau wird stündlich separat berechnet)
        dew_score_now = 35.0 if dew_present else 0.0
        wetness_base = max(0.0, float(current_wetness) - dew_score_now)
        dew_still_present = dew_present
        consecutive_sun_h = 0

        start_h = (now_utc + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

        for step in range(48):
            h_utc   = start_h + timedelta(hours=step)
            h_local = dt_util.as_local(h_utc)

            rad    = rad_by_hour.get(h_utc, 0.0)
            rain_h = precip_by_hour.get(h_utc, 0.0)

            # Tau-Tracking (wirkt auch außerhalb Mähfenster)
            if rad > 100:
                consecutive_sun_h += 1
            else:
                consecutive_sun_h = 0
            if consecutive_sun_h >= 2:
                dew_still_present = False

            # Wetness-Base immer aktualisieren (Sonne trocknet, Regen nässt)
            solar_factor_h = min(1.0, rad / radiation_peak)
            wetness_base = max(0.0, wetness_base - solar_factor_h * 15.0 + rain_h * 8.0)

            # Mähfenster-Check
            if not (mow_start <= h_local.time() <= mow_end):
                continue

            # Geschätzte Gesamtwetness inkl. Tau
            estimated = wetness_base + (35.0 if dew_still_present else 0.0)

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

        # 1. Regendaten
        rain_now   = _state_float(self.hass, cfg.get(CONF_RAIN_SENSOR, "")) or 0.0
        rain_1h    = _state_float(self.hass, cfg.get(CONF_RAIN_1H,     "")) or 0.0
        rain_today = _state_float(self.hass, cfg.get(CONF_RAIN_TODAY,  "")) or 0.0
        self._rain_buffer.append(rain_now)
        rain_weighted_12h = self._compute_weighted_rain()

        raining_now = rain_now > 0.1
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
        solar_factor = radiation_now / self._radiation_peak if self._radiation_peak > 0 else 0.0
        solar_factor = min(1.0, solar_factor)

        # 3. DWD Prognosen
        rain_today_remaining, rain_tomorrow, rain_fc_3h, _radiation_fc_3h = (
            self._parse_dwd_forecasts(cfg, now_utc)
        )

        # DWD Nowcast (aktueller state des Niederschlagssensors)
        precip_nowcast = _state_float(self.hass, cfg.get(CONF_DWD_PRECIP, "")) or 0.0

        # 4. Wind
        wind_drying = self._get_wind_drying(cfg)

        # 5. Taupunkt / Morgentau
        temp, humidity = self._get_temp_humidity(cfg)
        dew_point = temp - ((100 - humidity) / 5)
        dew_evaporated = (
            temp > dew_point + float(cfg.get(CONF_THRESH_DEW_OFFSET, DEFAULT_THRESH_DEW_OFFSET))
        )
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

        # 8. Akku-Plausibilisierung — Mähzustand aus Akkudelta ableiten (nur bei veralteten Daten)
        battery_pct, battery_fresh = self._current_battery_pct(cfg)
        now_ts = dt_util.utcnow().timestamp()
        if not battery_fresh and self._prev_battery_pct is not None:
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

        # start_now ergibt sich aus mow_allowed + priority >= 40
        if mow_allowed and block_reason == "mowing_allowed":
            start_now = priority >= 40
        # Bei emergency ist start_now bereits True

        # 12. Prognose: wann ist Mähen das nächste Mal möglich?
        if mow_allowed:
            next_mow_expected: datetime | None = now_local
        else:
            next_mow_expected = self._forecast_next_mow(
                cfg, now_local, now_utc, wetness_score, dew_present,
            )

        # 11. Auto-Dock-Status übernehmen, dann zurücksetzen
        self._last_mow_allowed = mow_allowed
        auto_resume_blocked = self._auto_resume_blocked
        self._auto_resume_blocked = False

        # stop_now: Signal für Automationen — Mäher soll gestoppt werden
        # Gründe: Regen, Nässe, zu dunkel, Bewässerung aktiv, unerlaubter Start
        stop_now = (
            raining_now
            or irrigation_on
            or auto_resume_blocked
            or (block_reason == "too_wet")
            or (block_reason == "too_dark_hedgehog")
        )

        # 12. Storage (non-blocking)
        self.hass.async_create_task(self._flush_storage())

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
