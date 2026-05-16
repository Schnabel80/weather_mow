"""Konstanten für die weather_mow Integration."""
from __future__ import annotations

DOMAIN   = "weather_mow"
PLATFORMS = ["sensor", "binary_sensor", "switch", "date"]

# Storage
STORAGE_VERSION      = 1
STORAGE_KEY_MOWING   = "weather_mow_{entry_id}_mowing_data"
STORAGE_KEY_RAIN_BUF = "weather_mow_{entry_id}_rain_buffer"
STORAGE_KEY_SOLAR    = "weather_mow_{entry_id}_solar_peak"

# ── Config-Keys Schritt 1: Gerät ────────────────────────────────────────────
CONF_MOWER_ENTITY    = "mower_entity_id"
CONF_BATTERY_SENSOR  = "battery_sensor_entity_id"
CONF_MIN_BATTERY_PCT = "min_battery_pct"

# ── Config-Keys Schritt 2: Wetterquelle + DWD-Sensoren ──────────────────────
CONF_WEATHER_SOURCE  = "weather_source"
WEATHER_SOURCE_DWD   = "dwd"
WEATHER_SOURCE_OWM   = "owm"
DEFAULT_WEATHER_SOURCE = WEATHER_SOURCE_DWD  # Rückwärtskompatibilität

CONF_DWD_WEATHER     = "dwd_weather_entity_id"
CONF_DWD_RADIATION   = "dwd_radiation_entity_id"
CONF_DWD_PRECIP      = "dwd_precip_entity_id"
CONF_DWD_WIND        = "dwd_wind_entity_id"

# ── Config-Keys Schritt 3: Regensensoren ────────────────────────────────────
CONF_RAIN_SENSOR     = "rain_sensor_entity_id"
CONF_RAIN_1H         = "rain_1h_sensor_entity_id"
CONF_RAIN_TODAY      = "rain_today_sensor_entity_id"
CONF_RAIN_DETECTOR   = "rain_detector_entity_id"

# ── Config-Keys Schritt 4: Temp / Feuchte / Helligkeit ──────────────────────
CONF_TEMP            = "outdoor_temp_entity_id"
CONF_HUMIDITY        = "outdoor_humidity_entity_id"
CONF_BRIGHTNESS      = "brightness_entity_id"
CONF_MIN_BRIGHTNESS  = "min_brightness_lux"

# ── Config-Keys Schritt 5: Strahlungs-Fallback ──────────────────────────────
CONF_RADIATION_SOURCE = "radiation_source"
CONF_PV_POWER         = "pv_power_entity_id"
CONF_PV_PEAK_KW       = "pv_peak_kw"

RADIATION_SOURCE_DWD  = "dwd"
RADIATION_SOURCE_PV   = "pv"
RADIATION_SOURCE_SUN  = "sun"

# ── Options-Keys Schritt 6 (im Options Flow änderbar) ───────────────────────
CONF_PREVENT_AUTO_RESUME   = "prevent_auto_resume"
CONF_MOW_START         = "mow_window_start"
CONF_MOW_END           = "mow_window_end"
CONF_TARGET_DAILY_H    = "target_daily_duration_h"
CONF_FULL_CYCLE_H      = "full_cycle_duration_h"
CONF_THRESH_WETNESS    = "threshold_wetness_score"
CONF_THRESH_RAIN_TODAY = "threshold_rain_today_remaining_mm"
CONF_THRESH_RAIN_TMRW  = "threshold_rain_tomorrow_mm"
CONF_THRESH_EMERG_H    = "threshold_min_time_for_emergency_h"
CONF_THRESH_DEW_OFFSET = "threshold_dew_temp_offset"
CONF_MIN_SUN_H_FOR_DEW = "min_sun_h_for_dew"

# ── Default-Werte ────────────────────────────────────────────────────────────
DEFAULT_NAME              = "Rasenmaeher"
DEFAULT_PREVENT_AUTO_RESUME   = True
DEFAULT_MIN_BATTERY       = 100
DEFAULT_MIN_BRIGHTNESS    = 2000
DEFAULT_MOW_START         = "08:00:00"
DEFAULT_MOW_END           = "20:00:00"
DEFAULT_TARGET_DAILY_H    = 2.5
DEFAULT_FULL_CYCLE_H      = 2.0
DEFAULT_THRESH_WETNESS    = 30
DEFAULT_THRESH_RAIN_TODAY = 5.0
DEFAULT_THRESH_RAIN_TMRW  = 8.0
DEFAULT_THRESH_EMERG_H    = 2.0
DEFAULT_THRESH_DEW_OFFSET = 3.0
DEFAULT_MIN_SUN_H_FOR_DEW = 1.0   # Stunden kontinuierlicher Sonne ≥ 200 W/m² für Tau-Freigabe
DEFAULT_PV_PEAK_KW        = 6.4

DEFAULT_BATTERY_SENSOR = ""

# ── Options-Keys Wuchs ──────────────────────────────────────────────────────
CONF_LAST_FERTILIZATION = "last_fertilization_date"
CONF_MAX_GROWTH_MM      = "max_growth_mm"
DEFAULT_MAX_GROWTH_MM   = 20

# ── Physik / Algorithmus ─────────────────────────────────────────────────────
UPDATE_INTERVAL_MINUTES  = 5
BATTERY_STALE_MINUTES    = 10   # Sensor gilt als veraltet wenn älter als dieser Wert
RAIN_BUFFER_MAXLEN      = 144     # 12 h bei 5-Minuten-Auflösung
DECAY_PER_UPDATE        = 1.0 - (0.005 / 288)   # 0,5 % Decay pro Tag
SOLAR_PEAK_MIN          = 50.0   # W/m²
RADIATION_SUN_THRESHOLD = 200.0  # W/m² — Sonne "zählt" für Tau-Trocknung und Tracking
RADIATION_INSTANT_CLEAR = 500.0  # W/m² — sofortige Tau-Freigabe ohne Stunden-Bedingung

# Regen-Erkennung aus weather-Entity condition
CONDITION_RAIN_MM: dict[str, float] = {
    "rainy":           1.0,   # Niesel / leichter Regen
    "pouring":         5.0,   # Starkregen
    "lightning-rainy": 3.0,   # Gewitter mit Regen
    "snowy-rainy":     0.5,   # Schneeregen
}

# Wuchsmodell (Growing Degree Days)
GDD_BASE_TEMP_C         = 5.0    # Basistemperatur Gras (°C)
GROWTH_MM_PER_GDD       = 0.8    # mm Wachstum pro GDD
FERTILIZER_BOOST_FACTOR = 1.5    # Multiplikator nach Düngung
FERTILIZER_ACTIVE_DAYS  = 21     # Tage bis Dünger-Effekt nachlässt
STORAGE_KEY_GROWTH      = "weather_mow_{entry_id}_growth"

# Bewässerungs-Boost
IRRIGATION_WETNESS_BOOST    = 70   # Score direkt nach Bewässerung (≈ 10mm Regen)
IRRIGATION_DECAY_PER_UPDATE =  2   # Abbau pro 5-Min-Schritt → 0 nach ~3h, <30 nach ~100min

# Gewichts-Map: (index_range, weight)
RAIN_WEIGHT_MAP = [
    (range(0,    48), 0.1),   # 8–12 h alt
    (range(48,   72), 0.2),   # 6–8 h alt
    (range(72,   96), 0.4),   # 4–6 h alt
    (range(96,  120), 0.7),   # 2–4 h alt
    (range(120, 144), 1.0),   # 0–2 h alt
]
