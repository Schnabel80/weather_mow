#!/usr/bin/env python3
"""
Smart Mow Backtester
Simuliert die smart_mow Entscheidungslogik mit historischen HA-Sensordaten.

Usage:
  python3 backtest_smart_mow.py --input smart_mow_backtest.csv [Optionen]
"""

import argparse
import csv
import io
import json
import math
import os
import random
import ssl
import sys
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.request import urlopen
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

RAIN_BUFFER_MAXLEN = 144
DECAY_PER_UPDATE   = 1.0 - (0.005 / 288)
SOLAR_PEAK_MIN     = 50.0
UPDATE_INTERVAL_S  = 300          # 5 Minuten
BATTERY_RATE_PCT   = 100.0 / 12  # % pro 5-min-Schritt (1h = 100%)

RAIN_WEIGHT_MAP = [
    (range(0,    48), 0.1),
    (range(48,   72), 0.2),
    (range(72,   96), 0.4),
    (range(96,  120), 0.7),
    (range(120, 144), 1.0),
]

ENTITY_RAIN_NOW   = "sensor.weather_station_regenmesser_niederschlag"
ENTITY_RAIN_1H    = "sensor.weather_station_regenmesser_niederschlag_letzte_stunde"
ENTITY_RAIN_TODAY = "sensor.weather_station_regenmesser_niederschlag_heute"
ENTITY_RADIATION  = "sensor.dwd_meine_sonneneinstrahlung"
ENTITY_PRECIP     = "sensor.dwd_meine_niederschlag"
ENTITY_TEMP       = "sensor.boiler_outside_temperature"
ENTITY_HUMIDITY   = "sensor.garage_temperatur_luftfeuchtigkeit"
ENTITY_BRIGHTNESS = "sensor.helligkeit_beleuchtungsstarke"
ENTITY_PV         = "sensor.solaredge_ac_power"


# ---------------------------------------------------------------------------
# DWD MOSMIX
# ---------------------------------------------------------------------------

DWD_BASE = (
    "https://opendata.dwd.de/weather/local_forecasts/mos/"
    "MOSMIX_L/single_stations/{station}/kml/"
    "MOSMIX_L_LATEST_{station}.kmz"
)


def _parse_dwd_kmz(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        kml_name = next(n for n in zf.namelist() if n.endswith(".kml"))
        kml_data = zf.read(kml_name)
    root   = ET.fromstring(kml_data)
    NS_DWD = "http://www.dwd.de/forecasts/mos/mosmix"

    timestamps = [
        datetime.fromisoformat(
            ts.text.strip().rstrip("Z").split(".")[0]
        ).replace(tzinfo=timezone.utc)
        for ts in root.iter(f"{{{NS_DWD}}}TimeStep")
    ]

    def _vals(name):
        for fc in root.iter(f"{{{NS_DWD}}}Forecast"):
            if fc.attrib.get(f"{{{NS_DWD}}}elementName") == name:
                el = fc.find(f"{{{NS_DWD}}}value")
                if el is not None and el.text:
                    out = []
                    for p in el.text.split():
                        try:
                            v = float(p)
                            out.append(None if math.isnan(v) else max(0.0, v))
                        except ValueError:
                            out.append(None)
                    return out
        return []

    rr1c  = _vals("RR1c")
    rad1h = _vals("RAD1h")
    result = {}
    for i, dt in enumerate(timestamps):
        r = rr1c[i]  if i < len(rr1c)  else None
        d = rad1h[i] if i < len(rad1h) else None
        result[dt] = {
            "RR1c":  r if r is not None else 0.0,
            "RAD1h": (d / 3.6) if d is not None else 0.0,
        }
    return result


def download_mosmix(station: str, cache_dir: str = ".mosmix_cache") -> dict:
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"mosmix_{station}_{datetime.now():%Y%m%d}.kmz")
    if os.path.exists(cache_path):
        print(f"[DWD] Cache: {cache_path}")
        with open(cache_path, "rb") as f:
            data = f.read()
    else:
        url = DWD_BASE.format(station=station)
        print(f"[DWD] Lade MOSMIX: {url}")
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE
            with urlopen(url, timeout=60, context=ctx) as resp:
                data = resp.read()
            with open(cache_path, "wb") as f:
                f.write(data)
            print(f"[DWD] OK ({len(data)//1024} KB)")
        except Exception as e:
            print(f"[DWD] WARNUNG: {e} — fahre ohne MOSMIX fort.")
            return {}
    return _parse_dwd_kmz(data)


# ---------------------------------------------------------------------------
# CSV-Loader
# ---------------------------------------------------------------------------

def _parse_ts(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unbekanntes Format: {s!r}")


def load_csv(path: str) -> dict:
    data = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        sample = f.read(1024); f.seek(0)
        has_hdr = sample.lower().startswith(("entity", "ts", "time", "state"))
        reader  = csv.reader(f)
        header  = [h.strip().lower() for h in next(reader)] if has_hdr else None
        for row in reader:
            if not row or len(row) < 3:
                continue
            try:
                if header:
                    d = dict(zip(header, row))
                    eid = d.get("entity_id","").strip()
                    st  = d.get("state","").strip()
                    ts  = (d.get("ts") or d.get("timestamp") or "").strip()
                else:
                    if row[0].startswith("sensor."):
                        eid, st, ts = row[0].strip(), row[1].strip(), row[2].strip()
                    else:
                        ts, eid, st = row[0].strip(), row[1].strip(), row[2].strip()
                if not eid or not st or not ts:
                    continue
                if st in ("unknown","unavailable","none","None",""):
                    continue
                data[eid].append((_parse_ts(ts), float(st)))
            except Exception:
                continue
    for eid in data:
        data[eid].sort(key=lambda x: x[0])
    print(f"[CSV] {path}")
    for eid, v in sorted(data.items()):
        print(f"  {eid}: {len(v)} Einträge")
    return dict(data)


# ---------------------------------------------------------------------------
# Wind-Simulation
# ---------------------------------------------------------------------------

class WindSimulator:
    """
    Tägliches Windprofil: Nachts 0 km/h, tagsüber Zufallswerte an
    4 Stützpunkten (08, 12, 16, 18 Uhr), dazwischen linear interpoliert.
    Deterministisch per Tag (reproduzierbar).
    """

    def __init__(self):
        self._profiles: dict = {}

    def _profile(self, day) -> dict:
        if day not in self._profiles:
            rng = random.Random(hash(str(day)))
            self._profiles[day] = {
                8:  rng.uniform(0, 20),
                12: rng.uniform(0, 20),
                16: rng.uniform(0, 20),
                18: rng.uniform(0, 20),
            }
        return self._profiles[day]

    def get(self, ts: datetime) -> float:
        p = self._profile(ts.date())
        h = ts.hour + ts.minute / 60.0
        # Stützpunkte: (Stunde, km/h)
        points = [(0, 0.0), (8, p[8]), (12, p[12]),
                  (16, p[16]), (18, p[18]), (24, 0.0)]
        for i in range(len(points) - 1):
            h0, v0 = points[i]
            h1, v1 = points[i + 1]
            if h0 <= h < h1:
                t = (h - h0) / (h1 - h0)
                return round(v0 + t * (v1 - v0), 1)
        return 0.0


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class SmartMowSimulator:

    def __init__(self, sensor_data: dict, mosmix_data: dict, params: dict):
        self.sensor_data  = sensor_data
        self.mosmix_data  = mosmix_data
        self.p            = params
        self.wind_sim     = WindSimulator()

        # Regen-Buffer
        self.rain_buffer = deque(maxlen=RAIN_BUFFER_MAXLEN)

        # Solar Peak
        self.radiation_peak = SOLAR_PEAK_MIN

        # Mähdauer
        self.duration_today_s      = 0.0
        self.duration_yesterday_s  = 0.0
        self.duration_day_before_s = 0.0
        self.emergency_active      = False
        self._last_midnight        = None

        # Akku & Mäherzustand
        self.battery_pct   = 100.0       # startet voll geladen
        self.mower_state   = "docked"    # "docked" | "mowing"

    # ── Hilfsmethoden ──────────────────────────────────────────────────────

    def get_value(self, entity_id: str, ts: datetime) -> float | None:
        series = self.sensor_data.get(entity_id)
        if not series:
            return None
        lo, hi, result = 0, len(series) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if series[mid][0] <= ts:
                result = series[mid][1]; lo = mid + 1
            else:
                hi = mid - 1
        return result

    def get_mosmix(self, ts_local: datetime, key: str, hours: float = 0) -> float:
        if not self.mosmix_data:
            return 0.0
        utc_h = (ts_local - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        if hours <= 0:
            e = self.mosmix_data.get(utc_h)
            return e[key] if e else 0.0
        return sum(
            (self.mosmix_data.get(utc_h + timedelta(hours=h)) or {}).get(key, 0.0)
            for h in range(int(hours))
        )

    def minutes_until_rain(self, ts_local: datetime, threshold: float = 0.1) -> float | None:
        """Minuten bis zum ersten MOSMIX-Stundenwert > threshold. None = kein Regen in 24h."""
        if not self.mosmix_data:
            return None
        utc_h = (ts_local - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        for h in range(25):
            slot  = utc_h + timedelta(hours=h)
            entry = self.mosmix_data.get(slot)
            if entry and entry.get("RR1c", 0) > threshold:
                slot_local = slot + timedelta(hours=2)
                return max(0.0, (slot_local - ts_local).total_seconds() / 60)
        return None

    def _midnight_reset(self, ts: datetime):
        m = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        if self._last_midnight is None:
            self._last_midnight = m; return
        if m > self._last_midnight:
            self.duration_day_before_s = self.duration_yesterday_s
            self.duration_yesterday_s  = self.duration_today_s
            self.duration_today_s      = 0.0
            self.emergency_active      = False
            self._last_midnight        = m

    def _weighted_rain(self) -> float:
        buf = list(self.rain_buffer)
        total = 0.0
        for i, v in enumerate(buf):
            w = 0.1
            for r, wt in RAIN_WEIGHT_MAP:
                if i in r: w = wt; break
            total += v * w
        return total

    def _sun_elevation(self, ts: datetime) -> float:
        lat  = math.radians(53.0)
        doy  = ts.timetuple().tm_yday
        decl = math.radians(23.45 * math.sin(math.radians(360 / 365 * (doy - 81))))
        utc_h = ts.hour + ts.minute / 60 - 2  # MESZ → UTC
        ha   = math.radians(15 * (utc_h - 12))
        s    = math.sin(lat)*math.sin(decl) + math.cos(lat)*math.cos(decl)*math.cos(ha)
        return math.degrees(math.asin(max(-1.0, min(1.0, s))))

    # ── Entscheidung ───────────────────────────────────────────────────────

    def _compute_decision(self, wetness_score, brightness_ok, in_window,
                          rain_today_remaining, rain_tomorrow,
                          duration_today_h, time_remaining_h, ts):
        p = self.p
        if not in_window:
            return False, False, "outside_time_window"
        if not brightness_ok:
            return False, False, "too_dark_hedgehog"

        # ── Akku-Prüfung ──────────────────────────────────────────────────
        min_batt = p["min_battery_pct"]
        batt_mow_min = self.battery_pct / 100.0 * 60.0  # Minuten die der Akku noch reicht

        if self.battery_pct < min_batt:
            # Bei hoher Dringlichkeit: prüfen ob noch 20 min vor Regen möglich
            mins_until_rain = self.minutes_until_rain(ts)
            if mins_until_rain is not None:
                avail = mins_until_rain - 15          # 15 min Puffer vor Regen
                can_mow = min(batt_mow_min, avail)
                if can_mow >= 20:
                    pass  # trotzdem starten — weiter mit Wetness-Check
                else:
                    return False, False, "battery_low"
            else:
                return False, False, "battery_low"

        # ── Wetness ───────────────────────────────────────────────────────
        if wetness_score >= p["threshold_wetness_score"]:
            return False, False, "too_wet"
        if rain_today_remaining >= p["threshold_rain_today_remaining_mm"]:
            return False, False, "rain_expected_today"

        # ── Tagesziel ─────────────────────────────────────────────────────
        target     = p["target_daily_duration_h"]
        full_cycle = p["full_cycle_duration_h"]

        if duration_today_h >= target:
            if rain_tomorrow >= p["threshold_rain_tomorrow_mm"]:
                if (time_remaining_h >= p["threshold_min_time_for_emergency_h"]
                        and duration_today_h < (target + full_cycle)):
                    self.emergency_active = True
                    return True, True, "emergency_mow_tomorrow_rain"
            return False, False, "daily_target_reached"

        return True, False, "mowing_allowed"

    def _compute_priority(self, wetness_score, duration_today_h,
                          duration_avg_3d_h, mow_allowed, time_remaining_h, ts) -> int:
        if not mow_allowed:
            return 0
        target = self.p["target_daily_duration_h"]
        deficit_ratio = max(0.0, 1 - duration_today_h / target) if target > 0 else 0.0
        avg_deficit   = max(0.0, 1 - duration_avg_3d_h / target) if target > 0 else 0.0
        emergency_bonus  = 40 if self.emergency_active else 0
        wetness_penalty  = min(30.0, wetness_score * 0.3)
        urgency_bonus    = max(0.0, 3.0 - time_remaining_h) * 5
        # Mittagsbevorzugung 11-16 Uhr (sanfte Rampe ±1h, max +10)
        hour = ts.hour + ts.minute / 60.0
        if 11.0 <= hour < 16.0:
            midday_bonus = 10.0
        elif 10.0 <= hour < 11.0:
            midday_bonus = (hour - 10.0) * 10.0
        elif 16.0 <= hour < 17.0:
            midday_bonus = (17.0 - hour) * 10.0
        else:
            midday_bonus = 0.0
        return min(100, max(0, round(
            deficit_ratio * 40 + avg_deficit * 20
            + emergency_bonus + urgency_bonus + midday_bonus - wetness_penalty
        )))

    # ── Haupt-Schritt ──────────────────────────────────────────────────────

    def step(self, ts: datetime) -> dict:
        self._midnight_reset(ts)
        p = self.p

        # Rohdaten
        rain_now   = self.get_value(ENTITY_RAIN_NOW,   ts) or 0.0
        rain_1h    = self.get_value(ENTITY_RAIN_1H,    ts) or 0.0
        rain_today = self.get_value(ENTITY_RAIN_TODAY, ts) or 0.0
        self.rain_buffer.append(rain_now)
        rain_weighted_12h = self._weighted_rain()

        sun_elev = self._sun_elevation(ts)

        # Strahlung
        radiation_now = self.get_value(ENTITY_RADIATION, ts)
        if radiation_now is None:
            pv_w = self.get_value(ENTITY_PV, ts)
            if pv_w is not None and p["pv_peak_kw"] > 0:
                radiation_now = pv_w / (p["pv_peak_kw"] * 1000) * 1000
            else:
                radiation_now = max(0.0, math.sin(math.radians(sun_elev))) * 800
        radiation_now = max(0.0, radiation_now)

        self.radiation_peak = max(SOLAR_PEAK_MIN,
                                  max(self.radiation_peak * DECAY_PER_UPDATE, radiation_now))
        solar_factor = min(1.0, radiation_now / self.radiation_peak) if self.radiation_peak > 0 else 0.0

        # DWD Prognosen
        rain_today_remaining = self.get_mosmix(ts, "RR1c", hours=_hours_until_midnight(ts))
        rain_fc_3h           = self.get_mosmix(ts, "RR1c", hours=3)
        precip_nowcast       = self.get_mosmix(ts, "RR1c", hours=0)

        # Regen morgen
        midnight_ts = ts.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        rain_tomorrow = 0.0
        if self.mosmix_data:
            utc_mn = midnight_ts - timedelta(hours=2)
            for h in range(24):
                e = self.mosmix_data.get(utc_mn + timedelta(hours=h))
                if e: rain_tomorrow += e.get("RR1c", 0.0)

        # Wind (simuliert)
        wind_kmh    = self.wind_sim.get(ts)
        wind_drying = min(1.0, wind_kmh / 30.0) * 5.0

        # Temp / Feuchte / Tau
        temp     = self.get_value(ENTITY_TEMP,     ts) or 15.0
        humidity = self.get_value(ENTITY_HUMIDITY, ts) or 70.0
        dew_point = temp - ((100 - humidity) / 5)
        dew_evaporated = temp > dew_point + p["threshold_dew_temp_offset"]
        dew_present = not dew_evaporated

        # Helligkeit
        brightness = self.get_value(ENTITY_BRIGHTNESS, ts)
        brightness_ok = (sun_elev >= 10) or (brightness is not None and brightness >= p["min_brightness_lux"])

        # Wetness Score
        rain_score      = rain_weighted_12h * 8
        morning_penalty = min(40.0, rain_today * 1.5) * (1 - solar_factor)
        dew_score       = 35 if dew_present else 0
        future_score    = rain_fc_3h * 8
        wetness_score   = max(0.0,
            rain_score + morning_penalty + dew_score
            - solar_factor * 15 - wind_drying + future_score
        )
        if precip_nowcast > 0.1:
            wetness_score = max(wetness_score, 70.0)
        wetness_score = round(wetness_score)

        # Mähfenster
        mow_sh, mow_sm = map(int, p["mow_window_start"].split(":")[:2])
        mow_eh, mow_em = map(int, p["mow_window_end"].split(":")[:2])
        in_window = (ts.hour, ts.minute) >= (mow_sh, mow_sm) and \
                    (ts.hour, ts.minute) <= (mow_eh, mow_em)
        end_dt = ts.replace(hour=mow_eh, minute=mow_em, second=0, microsecond=0)
        time_remaining_h = max(0.0, (end_dt - ts).total_seconds() / 3600)

        # Mähdauer (vor Akkuschritt)
        duration_today_h    = self.duration_today_s / 3600
        duration_yesterday_h = self.duration_yesterday_s / 3600
        duration_day_before_h = self.duration_day_before_s / 3600
        duration_avg_3d_h   = (duration_today_h + duration_yesterday_h + duration_day_before_h) / 3

        # Entscheidung (auf Basis aktueller Werte)
        mow_allowed, start_now_flag, block_reason = self._compute_decision(
            wetness_score, brightness_ok, in_window,
            rain_today_remaining, rain_tomorrow,
            duration_today_h, time_remaining_h, ts,
        )

        priority = self._compute_priority(
            wetness_score, duration_today_h, duration_avg_3d_h,
            mow_allowed, time_remaining_h, ts,
        )
        if mow_allowed and block_reason == "mowing_allowed":
            start_now_flag = priority >= 40

        # ── Akku-Zustandsmaschine ─────────────────────────────────────────
        # Regen in < 15 min? → sofort andocken
        mins_rain = self.minutes_until_rain(ts)
        rain_imminent = mins_rain is not None and mins_rain < 15

        raining = rain_now > 0.1

        if self.mower_state == "mowing":
            stop = (
                self.battery_pct <= 0
                or raining
                or rain_imminent
                or not mow_allowed
            )
            if stop:
                self.mower_state = "docked"
            else:
                self.battery_pct       = max(0.0, self.battery_pct - BATTERY_RATE_PCT)
                self.duration_today_s += UPDATE_INTERVAL_S
        else:  # docked
            if start_now_flag and not raining and not rain_imminent:
                self.mower_state  = "mowing"
                self.battery_pct  = max(0.0, self.battery_pct - BATTERY_RATE_PCT)
                self.duration_today_s += UPDATE_INTERVAL_S
            else:
                self.battery_pct = min(100.0, self.battery_pct + BATTERY_RATE_PCT)

        actually_mowing = (self.mower_state == "mowing")

        return {
            "ts":                   ts,
            # Simulation
            "mower_state":          self.mower_state,
            "battery_pct":          round(self.battery_pct, 1),
            "actually_mowing":      actually_mowing,
            "duration_today_h":     round(self.duration_today_s / 3600, 3),
            "duration_avg_3d_h":    round(duration_avg_3d_h, 3),
            # Entscheidung
            "wetness_score":        wetness_score,
            "priority":             priority,
            "mow_allowed":          mow_allowed,
            "start_now":            start_now_flag,
            "emergency_mow":        self.emergency_active,
            "block_reason":         block_reason or "",
            "in_window":            in_window,
            "raining":              rain_now > 0.1,
            # Rohdaten (für Charts)
            "rain_now_mm":          round(rain_now, 3),
            "rain_last_1h_mm":      round(rain_1h, 3),
            "rain_today_mm":        round(rain_today, 2),
            "rain_weighted_12h":    round(rain_weighted_12h, 3),
            "rain_today_remaining": round(rain_today_remaining, 2),
            "rain_tomorrow":        round(rain_tomorrow, 2),
            "radiation_now":        round(radiation_now, 1),
            "radiation_peak":       round(self.radiation_peak, 1),
            "solar_factor":         round(solar_factor, 3),
            "temperature":          round(temp, 1),
            "humidity":             round(humidity, 1),
            "dew_point":            round(dew_point, 1),
            "wind_kmh":             round(wind_kmh, 1),
            "brightness":           round(brightness, 0) if brightness is not None else None,
            "sun_elevation":        round(sun_elev, 1),
            "dew_present":          dew_present,
            "brightness_ok":        brightness_ok,
            "mins_until_rain":      round(mins_rain, 0) if mins_rain is not None else None,
        }


def _hours_until_midnight(ts: datetime) -> float:
    return ((ts.replace(hour=0, minute=0, second=0, microsecond=0)
             + timedelta(days=1)) - ts).total_seconds() / 3600


# ---------------------------------------------------------------------------
# Zeitreihen-Generator
# ---------------------------------------------------------------------------

def generate_timestamps(sensor_data, start, end):
    all_ts = [s[0] for series in sensor_data.values() for s in series[:1] + series[-1:]]
    if not all_ts:
        return []
    ts_min = max(min(all_ts), start) if start else min(all_ts)
    ts_max = min(max(all_ts), end)   if end   else max(all_ts)
    offset = ts_min.minute % 5
    if offset:
        ts_min = ts_min + timedelta(minutes=5 - offset)
    ts_min = ts_min.replace(second=0, microsecond=0)
    result, cur = [], ts_min
    while cur <= ts_max:
        result.append(cur); cur += timedelta(minutes=5)
    return result


# ---------------------------------------------------------------------------
# Ausgabe: CSV
# ---------------------------------------------------------------------------

def write_csv(results, path):
    if not results:
        return
    skip = {"ts"}
    fields = [k for k in results[0] if k not in skip]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts"] + fields)
        for r in results:
            w.writerow([r["ts"].strftime("%Y-%m-%d %H:%M:%S")] + [r.get(k,"") for k in fields])
    print(f"[OUT] CSV: {path} ({len(results)} Zeilen)")


# ---------------------------------------------------------------------------
# Ausgabe: Konsole
# ---------------------------------------------------------------------------

def print_daily_summary(results, params):
    by_day = defaultdict(list)
    for r in results:
        by_day[r["ts"].date()].append(r)
    print("\n" + "=" * 76)
    print("TAGESÜBERSICHT")
    print("=" * 76)
    for day in sorted(by_day.keys()):
        rows = by_day[day]
        mow_h     = rows[-1]["duration_today_h"]
        start_h   = sum(1 for r in rows if r["start_now"]) * 5 / 60
        actual_h  = sum(1 for r in rows if r["actually_mowing"]) * 5 / 60
        max_wet   = max(r["wetness_score"] for r in rows)
        em        = sum(1 for r in rows if r["emergency_mow"])
        reasons   = defaultdict(int)
        for r in rows:
            if r["block_reason"]: reasons[r["block_reason"]] += 1
        top = sorted(reasons.items(), key=lambda x: -x[1])[:3]
        em_s = f"  ⚡{em}×Notmähen" if em else ""
        print(
            f"{day}  gemäht={mow_h:.1f}h  tatsächlich={actual_h:.1f}h  "
            f"max_wet={max_wet:3d}  "
            f"[{', '.join(f'{k}({v})' for k,v in top) or '-'}]{em_s}"
        )
    print("=" * 76 + "\n")


# ---------------------------------------------------------------------------
# Ausgabe: HTML mit Chart.js
# ---------------------------------------------------------------------------

_COL = {
    "start_now":            "#4CAF50",
    "emergency":            "#FF9800",
    "allowed":              "#C8E6C9",
    "too_wet":              "#FFF9C4",
    "raining":              "#FFCDD2",
    "outside_time_window":  "#EEEEEE",
    "too_dark_hedgehog":    "#E0E0E0",
    "battery_low":          "#F3E5F5",
    "daily_target_reached": "#E3F2FD",
    "disabled":             "#F5F5F5",
    "default":              "#F5F5F5",
}


def write_html(results, path, params):
    if not results:
        return
    thresh_wet = params["threshold_wetness_score"]
    target_h   = params.get("target_daily_h", 2.5)

    # Gruppen
    by_dh = defaultdict(lambda: defaultdict(list))
    for r in results:
        by_dh[r["ts"].date()][r["ts"].hour].append(r)

    all_days = sorted(by_dh.keys())

    # Tagesübersicht: letzter duration_today_h-Wert pro Tag + 3-Tage-Avg
    daily_mow = {}
    for day in all_days:
        day_rows = sorted(
            [r for r in results if r["ts"].date() == day],
            key=lambda r: r["ts"]
        )
        daily_mow[day] = round(day_rows[-1]["duration_today_h"], 2) if day_rows else 0.0

    daily_summary = []
    for i, day in enumerate(all_days):
        mow_h = daily_mow[day]
        if i >= 2:
            avg3 = round(sum(daily_mow[all_days[j]] for j in range(i - 2, i + 1)) / 3, 2)
        elif i == 1:
            avg3 = round(sum(daily_mow[all_days[j]] for j in range(0, 2)) / 2, 2)
        else:
            avg3 = mow_h
        daily_summary.append({"date": str(day), "mow_h": mow_h, "avg3_h": avg3})

    daily_json = json.dumps(daily_summary)

    # JSON-Daten für Charts
    chart_data = {}
    for day in all_days:
        day_rows = sorted(
            [r for r in results if r["ts"].date() == day],
            key=lambda r: r["ts"]
        )
        chart_data[str(day)] = [
            {
                "t":         r["ts"].strftime("%H:%M"),
                # Sensor-Chart
                "rain_now":  r["rain_now_mm"],
                "rain_1h":   r["rain_last_1h_mm"],
                "rain_today":r["rain_today_mm"],
                "radiation": r["radiation_now"],
                "solar_pct": round(r["solar_factor"] * 100, 1),
                "temperature":r["temperature"],
                "humidity":  r["humidity"],
                "dew_point": r["dew_point"],
                "wind_kmh":  r["wind_kmh"],
                "brightness":r["brightness"],
                "sun_elev":  r["sun_elevation"],
                # Signal-Chart
                "wetness":   r["wetness_score"],
                "priority":  r["priority"],
                "battery":   r["battery_pct"],
                "duration_h":round(r["duration_today_h"], 2),
                "avg3_h":    round(r["duration_avg_3d_h"], 2),
                "rain_w12h": round(r["rain_weighted_12h"], 2),
                "mow_allowed":1 if r["mow_allowed"] else 0,
                "start_now": 1 if r["start_now"] else 0,
                "mowing":    1 if r["actually_mowing"] else 0,
                "block":     r["block_reason"],
                "mins_rain": r["mins_until_rain"],
            }
            for r in day_rows
        ]

    chart_json = json.dumps(chart_data)

    # Stundentabelle
    hour_hdr = "<tr><th>Datum</th>" + "".join(
        f"<th>{h:02d}</th>" for h in range(24)) + "</tr>"

    table_rows = []
    for day in all_days:
        cells = []
        for hour in range(24):
            hr = by_dh[day].get(hour, [])
            if not hr:
                cells.append('<td style="background:#F5F5F5"> </td>'); continue
            mowing    = any(r["actually_mowing"] for r in hr)
            emergency = any(r["emergency_mow"]   for r in hr)
            allowed   = any(r["mow_allowed"]     for r in hr)
            raining   = any(r["raining"]         for r in hr)
            in_win    = any(r["in_window"]       for r in hr)
            max_wet   = max(r["wetness_score"]   for r in hr)
            avg_prio  = sum(r["priority"]        for r in hr) / len(hr)
            batt      = hr[-1]["battery_pct"]
            block     = hr[-1]["block_reason"] or "-"
            mow_h     = hr[-1]["duration_today_h"]
            rain_1h   = hr[-1]["rain_last_1h_mm"]

            if not in_win:
                color, label = _COL["outside_time_window"], "—"
            elif raining:
                color, label = _COL["raining"], "🌧"
            elif mowing and emergency:
                color, label = _COL["emergency"], "✂⚡"
            elif mowing:
                color, label = _COL["start_now"], f"✂{batt:.0f}%"
            elif allowed:
                color, label = _COL["allowed"], "ok"
            elif max_wet >= thresh_wet:
                color, label = _COL["too_wet"], f"w{max_wet}"
            else:
                color = _COL.get(block, _COL["default"])
                label = block[:5] if block != "-" else "—"

            tt = (f"wetness={max_wet} prio={avg_prio:.0f} batt={batt:.0f}% "
                  f"rain_1h={rain_1h:.2f}mm gemäht={mow_h:.1f}h block={block}")
            cells.append(
                f'<td style="background:{color};padding:2px 4px;font-size:10px;'
                f'border:1px solid #ddd;cursor:pointer" title="{escape(tt)}">{label}</td>'
            )

        ds = str(day)
        table_rows.append(
            f'<tr class="dr" data-date="{ds}" onclick="showDay(\'{ds}\')" style="cursor:pointer">'
            f'<td style="white-space:nowrap;padding:2px 8px;font-weight:bold;'
            f'border-right:2px solid #ccc">{ds}</td>'
            + "".join(cells) + "</tr>"
        )

    params_html = " | ".join(f"<b>{k}</b>={v}" for k, v in sorted(params.items()))

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Smart Mow Backtest</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: monospace; font-size: 12px; margin: 16px; background: #fafafa; }}
  h2   {{ margin-bottom: 6px; }}
  table {{ border-collapse: collapse; }}
  th   {{ background: #263238; color: white; padding: 3px 5px; font-size: 10px; }}
  .dr:hover td {{ filter: brightness(0.9); }}
  .dr.sel td   {{ outline: 2px solid #1565C0; }}
  .leg {{ display:inline-block; padding:2px 10px; margin:2px 4px 2px 0;
          border:1px solid #aaa; font-size:11px; }}
  #detail {{ display:none; margin-top:20px; background:white;
             border:1px solid #ddd; border-radius:4px; padding:16px; }}
  #detail h3 {{ margin:0 0 10px; font-size:14px; }}
  .cw {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .cblock {{ background:#f9f9f9; border:1px solid #e0e0e0; border-radius:4px; padding:10px; }}
  .cblock b {{ display:block; margin-bottom:4px; font-size:11px; color:#333; }}
  canvas {{ max-height:260px; }}
  #params {{ font-size:10px; color:#777; margin-top:10px; }}
  #overviewWrap {{ background:white; border:1px solid #ddd; border-radius:4px;
                   padding:14px; margin-bottom:16px; max-width:900px; }}
  #overviewWrap b {{ display:block; margin-bottom:6px; font-size:12px; color:#333; }}
  #cOverview {{ max-height:200px; }}
</style>
</head>
<body>
<h2>Smart Mow Backtest</h2>
<div style="margin:6px 0">
  <span class="leg" style="background:#4CAF50;color:white">✂ Mäht (Akku%)</span>
  <span class="leg" style="background:#FF9800;color:white">✂⚡ Notmähen</span>
  <span class="leg" style="background:#C8E6C9">Bedingungen ok</span>
  <span class="leg" style="background:#FFF9C4">Zu nass</span>
  <span class="leg" style="background:#FFCDD2">🌧 Regen</span>
  <span class="leg" style="background:#F3E5F5">Akku leer</span>
  <span class="leg" style="background:#E3F2FD">Tagesziel erreicht</span>
  <span class="leg" style="background:#E0E0E0">Dunkel/Nacht</span>
  <span class="leg" style="background:#EEEEEE">Außerhalb Fenster</span>
</div>

<div id="overviewWrap">
  <b>📅 Tagesübersicht — Mähdauer, Ø 3 Tage &amp; Ziel</b>
  <canvas id="cOverview"></canvas>
</div>

<p style="font-size:11px;color:#666;margin:4px 0 8px">↓ Auf Datum klicken für Detaildiagramme</p>

<table>
{hour_hdr}
{"".join(table_rows)}
</table>

<div id="detail">
  <h3 id="dtitle">Detail</h3>
  <div class="cw">
    <div class="cblock"><b>🌧 Regen</b><canvas id="cRain"></canvas></div>
    <div class="cblock"><b>☀ Sonne &amp; Temperatur</b><canvas id="cSun"></canvas></div>
    <div class="cblock"><b>📊 Berechnete Signale</b><canvas id="cSig"></canvas></div>
    <div class="cblock"><b>🤖 Mäher</b><canvas id="cMow"></canvas></div>
  </div>
</div>

<div id="params">{params_html}</div>

<script>
const D = {chart_json};
const DAILY = {daily_json};
const TARGET_H = {target_h};
let cRain = null, cSun = null, cSig = null, cMow = null;

// ── Tagesübersicht ────────────────────────────────────────────────────────
(function() {{
  const labels  = DAILY.map(d => d.date.slice(5));   // MM-DD
  const mowVals = DAILY.map(d => d.mow_h);
  const avg3    = DAILY.map(d => d.avg3_h);
  const targetLine = DAILY.map(() => TARGET_H);
  const barColors = mowVals.map(v =>
    v >= TARGET_H   ? 'rgba(46,125,50,0.75)'   // grün: Ziel erreicht
    : v >= TARGET_H * 0.6 ? 'rgba(230,126,34,0.75)'  // orange: teilweise
    : 'rgba(192,57,43,0.75)'                          // rot: wenig/nichts
  );
  new Chart(document.getElementById('cOverview'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{ label: 'Mähdauer (h)', data: mowVals,
           backgroundColor: barColors, yAxisID: 'yh', order: 2 }},
        {{ label: 'Ø 3 Tage (h)', data: avg3,
           type: 'line', borderColor: '#1565C0', backgroundColor: 'transparent',
           pointRadius: 4, tension: 0.3, yAxisID: 'yh', order: 1 }},
        {{ label: `Ziel (${{TARGET_H}}h)`, data: targetLine,
           type: 'line', borderColor: '#C62828', borderDash: [8,4],
           pointRadius: 0, yAxisID: 'yh', order: 0 }},
      ]
    }},
    options: {{
      animation: false,
      interaction: {{ mode:'index', intersect:false }},
      plugins: {{ legend: {{ labels: {{ font: {{ size:10 }} }} }} }},
      scales: {{
        x:  {{ ticks: {{ font:{{ size:10 }} }} }},
        yh: {{ type:'linear', position:'left', min:0,
               title:{{ display:true, text:'Stunden', font:{{ size:9 }} }},
               ticks:{{ stepSize:0.5, font:{{ size:9 }} }} }}
      }}
    }}
  }});
}})();

const OPT = (scales) => ({{
  animation: false,
  interaction: {{ mode:'index', intersect:false }},
  plugins: {{ legend: {{ labels: {{ font: {{ size:9 }} }} }} }},
  scales,
}});
const XAXIS = {{ ticks: {{ maxTicksLimit:12, font:{{ size:9 }} }} }};
const YAXIS = (pos, label, extra={{}}) => ({{
  type:'linear', position:pos,
  title:{{ display:true, text:label, font:{{ size:9 }} }},
  grid:{{ drawOnChartArea: pos==='left' }},
  ...extra
}});

function showDay(date, userClick=true) {{
  document.querySelectorAll('.dr').forEach(r => r.classList.remove('sel'));
  const row = document.querySelector(`.dr[data-date="${{date}}"]`);
  if (row) row.classList.add('sel');
  const rows = D[date];
  if (!rows || !rows.length) return;
  const L = rows.map(r => r.t);
  document.getElementById('dtitle').textContent = 'Detail: ' + date;
  document.getElementById('detail').style.display = 'block';

  // ── 1. Regen — blau · teal · orange · lila ───────────────────────────
  if (cRain) cRain.destroy();
  cRain = new Chart(document.getElementById('cRain'), {{
    type: 'line',
    data: {{ labels: L, datasets: [
      {{ label:'Regen aktuell (mm)', data: rows.map(r=>r.rain_now),
         borderColor:'#1565C0', backgroundColor:'rgba(21,101,192,0.12)',
         yAxisID:'ymm', tension:0.2, pointRadius:0, fill:true }},
      {{ label:'Regen 1h (mm)', data: rows.map(r=>r.rain_1h),
         borderColor:'#00897B', yAxisID:'ymm', tension:0.2, pointRadius:0 }},
      {{ label:'Regen heute (mm)', data: rows.map(r=>r.rain_today),
         borderColor:'#E65100', yAxisID:'ytd', tension:0.2, pointRadius:0, borderDash:[5,3] }},
      {{ label:'Regen gew. 12h (mm)', data: rows.map(r=>r.rain_w12h),
         borderColor:'#6A1B9A', yAxisID:'ytd', tension:0.2, pointRadius:0, borderDash:[3,2] }},
    ]}},
    options: OPT({{
      x:   XAXIS,
      ymm: YAXIS('left',  'mm/5min · mm/1h', {{min:0}}),
      ytd: YAXIS('right', 'mm heute / gew.12h', {{min:0}}),
    }})
  }});

  // ── 2. Sonne & Temp — orange · lila · teal · grau · rot · blau · grün ─
  if (cSun) cSun.destroy();
  cSun = new Chart(document.getElementById('cSun'), {{
    type: 'line',
    data: {{ labels: L, datasets: [
      {{ label:'Strahlung (W/m²)', data: rows.map(r=>r.radiation),
         borderColor:'#E65100', backgroundColor:'rgba(230,81,0,0.1)',
         yAxisID:'yrad', tension:0.2, pointRadius:0, fill:true }},
      {{ label:'Solar-Peak (%)', data: rows.map(r=>r.solar_pct),
         borderColor:'#6A1B9A', yAxisID:'ypct', tension:0.2, pointRadius:0, borderDash:[3,2] }},
      {{ label:'Feuchte (%)', data: rows.map(r=>r.humidity),
         borderColor:'#00897B', yAxisID:'ypct', tension:0.3, pointRadius:0 }},
      {{ label:'Wind (km/h)', data: rows.map(r=>r.wind_kmh),
         borderColor:'#546E7A', yAxisID:'yrad', tension:0.3, pointRadius:0, borderDash:[4,2] }},
      {{ label:'Temp (°C)', data: rows.map(r=>r.temperature),
         borderColor:'#C62828', yAxisID:'ytmp', tension:0.3, pointRadius:0 }},
      {{ label:'Taupunkt (°C)', data: rows.map(r=>r.dew_point),
         borderColor:'#1565C0', yAxisID:'ytmp', tension:0.3, pointRadius:0, borderDash:[4,2] }},
      ...( rows.some(r=>r.brightness!==null) ? [{{
        label:'Helligkeit/100 (Lux)', data: rows.map(r=>r.brightness!==null?r.brightness/100:null),
        borderColor:'#558B2F', yAxisID:'yrad', tension:0.2, pointRadius:0, borderDash:[2,3]
      }}] : [] ),
    ]}},
    options: OPT({{
      x:    XAXIS,
      yrad: YAXIS('left',  'W/m² · km/h · Lux/100', {{min:0}}),
      ypct: YAXIS('right', '%', {{min:0, max:100}}),
      ytmp: YAXIS('right', '°C'),
    }})
  }});

  // ── 3. Signale — blau · rot · orange ─────────────────────────────────
  if (cSig) cSig.destroy();
  cSig = new Chart(document.getElementById('cSig'), {{
    type: 'line',
    data: {{ labels: L, datasets: [
      {{ label:'Nässe-Score', data: rows.map(r=>r.wetness),
         borderColor:'#1565C0', backgroundColor:'rgba(21,101,192,0.1)',
         yAxisID:'ysc', tension:0.2, pointRadius:0, fill:true }},
      {{ label:`Wetness-Schwelle ({thresh_wet})`,
         data: rows.map(()=>{thresh_wet}),
         borderColor:'#C62828', borderDash:[6,3], yAxisID:'ysc', pointRadius:0 }},
      ...( rows.some(r=>r.mins_rain!==null) ? [{{
        label:'Min bis Regen', data: rows.map(r=>r.mins_rain),
        borderColor:'#E65100', backgroundColor:'rgba(230,81,0,0.08)',
        yAxisID:'ymin', tension:0.2, pointRadius:0, fill:true
      }}] : [] ),
    ]}},
    options: OPT({{
      x:    XAXIS,
      ysc:  YAXIS('left',  'Nässe-Score', {{min:0}}),
      ymin: YAXIS('right', 'Min bis Regen', {{min:0}}),
    }})
  }});

  // ── 4. Mäher — orange · blau · teal · dunkelgrün · rot ───────────────
  if (cMow) cMow.destroy();
  cMow = new Chart(document.getElementById('cMow'), {{
    type: 'line',
    data: {{ labels: L, datasets: [
      {{ label:'Akku (%)', data: rows.map(r=>r.battery),
         borderColor:'#E65100', backgroundColor:'rgba(230,81,0,0.15)',
         yAxisID:'ypct', tension:0.1, pointRadius:0, fill:true }},
      {{ label:'Priorität (%)', data: rows.map(r=>r.priority),
         borderColor:'#1565C0', yAxisID:'ypct', tension:0.2, pointRadius:0 }},
      {{ label:'Mähdauer heute (h)', data: rows.map(r=>r.duration_h),
         borderColor:'#00897B', yAxisID:'ydur', tension:0.1, pointRadius:0 }},
      {{ label:'Ø 3 Tage (h)', data: rows.map(r=>r.avg3_h),
         borderColor:'#6A1B9A', yAxisID:'ydur', tension:0.3, pointRadius:0, borderDash:[5,3] }},
      {{ label:`Ziel ({target_h}h)`, data: rows.map(()=>{target_h}),
         borderColor:'#C62828', yAxisID:'ydur', pointRadius:0, borderDash:[8,4] }},
      {{ label:'Mäht tatsächlich', data: rows.map(r=>r.mowing),
         borderColor:'#2E7D32', backgroundColor:'rgba(46,125,50,0.25)',
         yAxisID:'ybin', tension:0, pointRadius:0, stepped:true, fill:true }},
      {{ label:'Start-Now Signal', data: rows.map(r=>r.start_now),
         borderColor:'#C62828', yAxisID:'ybin', tension:0, pointRadius:0, stepped:true }},
    ]}},
    options: OPT({{
      x:    XAXIS,
      ypct: YAXIS('left',  'Akku % · Priorität %', {{min:0, max:100}}),
      ydur: YAXIS('right', 'Mähdauer (h)', {{min:0}}),
      ybin: {{ type:'linear', position:'right', min:0, max:1.2,
               display:false, grid:{{ drawOnChartArea:false }} }},
    }})
  }});

  // kein Auto-Scroll beim Initialisieren, nur bei Benutzer-Klick
  if (userClick) document.getElementById('detail').scrollIntoView({{behavior:'smooth',block:'start'}});
}}

// Beim Laden automatisch den letzten Tag anzeigen
showDay(DAILY[DAILY.length - 1].date, false);
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OUT] HTML: {path}")


# ---------------------------------------------------------------------------
# CLI & Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Smart Mow Backtester",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--input",     metavar="FILE")
    g.add_argument("--input-dir", metavar="DIR")
    p.add_argument("--station",      default="X120")
    p.add_argument("--no-mosmix",    action="store_true")
    p.add_argument("--mosmix-cache", default=".mosmix_cache")
    p.add_argument("--start",        metavar="YYYY-MM-DD")
    p.add_argument("--end",          metavar="YYYY-MM-DD")
    p.add_argument("--target-daily-h",      type=float, default=2.5)
    p.add_argument("--full-cycle-h",        type=float, default=2.0)
    p.add_argument("--thresh-wetness",      type=int,   default=30)
    p.add_argument("--thresh-rain-today",   type=float, default=5.0)
    p.add_argument("--thresh-rain-tmrw",    type=float, default=8.0)
    p.add_argument("--thresh-emerg-h",      type=float, default=2.0)
    p.add_argument("--thresh-dew-offset",   type=float, default=3.0)
    p.add_argument("--mow-start",           default="08:00")
    p.add_argument("--mow-end",             default="20:00")
    p.add_argument("--min-brightness",      type=int,   default=2000)
    p.add_argument("--min-battery",         type=int,   default=20)
    p.add_argument("--pv-peak-kw",          type=float, default=6.4)
    p.add_argument("--output-csv",  default="backtest_result.csv")
    p.add_argument("--output-html", default="backtest_result.html")
    return p.parse_args()


def main():
    args = parse_args()
    params = {
        "target_daily_duration_h":           args.target_daily_h,
        "full_cycle_duration_h":             args.full_cycle_h,
        "threshold_wetness_score":           args.thresh_wetness,
        "threshold_rain_today_remaining_mm": args.thresh_rain_today,
        "threshold_rain_tomorrow_mm":        args.thresh_rain_tmrw,
        "threshold_min_time_for_emergency_h":args.thresh_emerg_h,
        "threshold_dew_temp_offset":         args.thresh_dew_offset,
        "mow_window_start":                  args.mow_start,
        "mow_window_end":                    args.mow_end,
        "min_brightness_lux":                args.min_brightness,
        "min_battery_pct":                   args.min_battery,
        "pv_peak_kw":                        args.pv_peak_kw,
    }

    sensor_data = load_csv(args.input) if args.input else _load_dir(args.input_dir)
    if not sensor_data:
        print("FEHLER: Keine Daten.", file=sys.stderr); sys.exit(1)

    mosmix_data = {} if args.no_mosmix else download_mosmix(args.station, args.mosmix_cache)

    start_dt = datetime.strptime(args.start, "%Y-%m-%d") if args.start else None
    end_dt   = datetime.strptime(args.end,   "%Y-%m-%d") + timedelta(days=1) if args.end else None
    timestamps = generate_timestamps(sensor_data, start_dt, end_dt)
    if not timestamps:
        print("FEHLER: Keine Zeitschritte.", file=sys.stderr); sys.exit(1)

    print(f"\n[SIM] {len(timestamps)} Schritte: {timestamps[0]} → {timestamps[-1]}")
    sim     = SmartMowSimulator(sensor_data, mosmix_data, params)
    results = []
    for i, ts in enumerate(timestamps):
        if i % 1000 == 0:
            print(f"[SIM] {i}/{len(timestamps)}  {ts}", end="\r")
        results.append(sim.step(ts))
    print(f"\n[SIM] Fertig.")

    write_csv(results, args.output_csv)
    print_daily_summary(results, params)
    write_html(results, args.output_html, params)


def _load_dir(d):
    merged = defaultdict(list)
    for f in sorted(os.listdir(d)):
        if f.endswith(".csv"):
            for eid, v in load_csv(os.path.join(d, f)).items():
                merged[eid].extend(v)
    for eid in merged:
        merged[eid].sort(key=lambda x: x[0])
    return dict(merged)


if __name__ == "__main__":
    main()
