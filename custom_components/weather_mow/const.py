"""Konstanten für die weather_mow Integration."""

from __future__ import annotations

DOMAIN = "weather_mow"
PLATFORMS = [
    "sensor",
    "binary_sensor",
    "switch",
    "date",
    "number",
    "time",
    "button",
]

# Storage
STORAGE_VERSION = 1
STORAGE_KEY_MOWING = "weather_mow_{entry_id}_mowing_data"
STORAGE_KEY_RAIN_BUF = "weather_mow_{entry_id}_rain_buffer"
STORAGE_KEY_SOLAR = "weather_mow_{entry_id}_solar_peak"

# ── Config-Keys Schritt 1: Gerät ────────────────────────────────────────────
CONF_MOWER_ENTITY = "mower_entity_id"
CONF_BATTERY_SENSOR = "battery_sensor_entity_id"
CONF_MIN_BATTERY_PCT = "min_battery_pct"

# ── Config-Keys Schritt 2: Wetterquelle + DWD-Sensoren ──────────────────────
CONF_WEATHER_SOURCE = "weather_source"
WEATHER_SOURCE_DWD = "dwd"
WEATHER_SOURCE_OWM = "owm"
DEFAULT_WEATHER_SOURCE = WEATHER_SOURCE_DWD  # Rückwärtskompatibilität

CONF_WEATHER_ENTITY = "weather_entity_id"
CONF_RADIATION_FORECAST = "radiation_forecast_entity_id"
CONF_PRECIP_FORECAST = "precip_forecast_entity_id"
CONF_WIND_SENSOR = "wind_sensor_entity_id"
# Backward-compat aliases (removed in Task 3 when all usages are updated)
CONF_DWD_WEATHER = CONF_WEATHER_ENTITY
CONF_DWD_RADIATION = CONF_RADIATION_FORECAST
CONF_DWD_PRECIP = CONF_PRECIP_FORECAST
CONF_DWD_WIND = CONF_WIND_SENSOR
CONF_LOCAL_RADIATION = "local_radiation_entity_id"

# ── Config-Keys Schritt 3: Regensensoren ────────────────────────────────────
CONF_RAIN_SENSOR = "rain_sensor_entity_id"
CONF_RAIN_1H = "rain_1h_sensor_entity_id"
CONF_RAIN_TODAY = "rain_today_sensor_entity_id"
CONF_RAIN_DETECTOR = "rain_detector_entity_id"
CONF_RAIN_PROVIDER = "rain_provider"
CONF_RAIN_SENSOR_TYPE = "rain_sensor_type"

# ── Config-Keys Schritt 4: Temp / Feuchte / Helligkeit ──────────────────────
CONF_TEMP = "outdoor_temp_entity_id"
CONF_HUMIDITY = "outdoor_humidity_entity_id"
CONF_BRIGHTNESS = "brightness_entity_id"
CONF_MIN_BRIGHTNESS = "min_brightness_lux"

# ── Config-Keys Schritt 5: Strahlungs-Fallback ──────────────────────────────
CONF_RADIATION_SOURCE = "radiation_source"
CONF_PV_POWER = "pv_power_entity_id"
CONF_PV_PEAK_KW = "pv_peak_kw"

RADIATION_SOURCE_DWD = "dwd"
RADIATION_SOURCE_PV = "pv"
RADIATION_SOURCE_SUN = "sun"

# ── Options-Keys Schritt 6 (im Options Flow änderbar) ───────────────────────
CONF_PREVENT_AUTO_RESUME = "prevent_auto_resume"
CONF_MOW_START = "mow_window_start"
CONF_MOW_END = "mow_window_end"
CONF_TARGET_DAILY_H = "target_daily_duration_h"
CONF_FULL_CYCLE_H = "full_cycle_duration_h"
CONF_THRESH_WETNESS = "threshold_wetness_score"
CONF_THRESH_RAIN_TODAY = "threshold_rain_today_remaining_mm"
CONF_THRESH_RAIN_TMRW = "threshold_rain_tomorrow_mm"
CONF_THRESH_EMERG_H = "threshold_min_time_for_emergency_h"
CONF_THRESH_DEW_OFFSET = "threshold_dew_temp_offset"
CONF_MIN_SUN_H_FOR_DEW = "min_sun_h_for_dew"
CONF_START_DELAY_MIN = "start_delay_minutes"
CONF_TARGET_BUFFER_H = "target_buffer_h"

# ── Default-Werte ────────────────────────────────────────────────────────────
DEFAULT_NAME = "Rasenmaeher"
DEFAULT_PREVENT_AUTO_RESUME = True
DEFAULT_MIN_BATTERY = 100
DEFAULT_MIN_BRIGHTNESS = 2000
DEFAULT_MOW_START = "08:00:00"
DEFAULT_MOW_END = "20:00:00"
DEFAULT_TARGET_DAILY_H = 2.5
DEFAULT_FULL_CYCLE_H = 2.0
DEFAULT_THRESH_WETNESS = 30
DEFAULT_THRESH_RAIN_TODAY = 5.0
DEFAULT_THRESH_RAIN_TMRW = 8.0
DEFAULT_THRESH_EMERG_H = 2.0
DEFAULT_THRESH_DEW_OFFSET = 3.0
DEFAULT_MIN_SUN_H_FOR_DEW = 1.0  # Stunden kontinuierlicher Sonne ≥ 200 W/m² für Tau-Freigabe
DEFAULT_PV_PEAK_KW = 6.4
DEFAULT_START_DELAY_MIN = 0  # 0 = deaktiviert (Rückwärtskompatibilität)
DEFAULT_TARGET_BUFFER_H = 2.0  # Stunden Puffer vor Mähfenster-Ende als Fertig-Deadline
DELAY_BYPASS_PRIORITY = 65  # Ab dieser Prio wird Startverzögerung ignoriert

DEFAULT_BATTERY_SENSOR = ""

# ── Options-Keys Wuchs ──────────────────────────────────────────────────────
CONF_LAST_FERTILIZATION = "last_fertilization_date"
CONF_MAX_GROWTH_MM = "max_growth_mm"
DEFAULT_MAX_GROWTH_MM = 20

# ── Physik / Algorithmus ─────────────────────────────────────────────────────
UPDATE_INTERVAL_MINUTES = 5
BATTERY_STALE_MINUTES = 10  # Sensor gilt als veraltet wenn älter als dieser Wert
RAIN_BUFFER_MAXLEN = 144  # 12 h bei 5-Minuten-Auflösung
DECAY_PER_UPDATE = 1.0 - (0.005 / 288)  # 0,5 % Decay pro Tag
SOLAR_PEAK_MIN = 50.0  # W/m²
RADIATION_SUN_THRESHOLD = 200.0  # W/m² — Sonne "zählt" für Tau-Trocknung und Tracking
RADIATION_INSTANT_CLEAR = 500.0  # W/m² — sofortige Tau-Freigabe ohne Stunden-Bedingung

# Score-Umrechnung: 1 mm gewichteter 12h-Regen ergibt so viele Nässescore-Punkte.
# Begründete Schätzung — im Beta-Feldtest gegen echtes Regenverhalten validieren.
RAIN_SCORE_PER_MM = 20.0

# Noise-Floor: Slot-mm darüber gelten als "regnet gerade" — filtert
# Spurenrauschen von Raten-Sensoren. 0,01 mm/Slot ≈ 0,12 mm/h.
RAINING_NOW_THRESHOLD_MM = 0.01

# Regen-Erkennung aus weather-Entity condition.
# Werte sind Regen-RATEN in mm/h — werden je Update via rate_to_slot_mm in
# Slot-mm umgerechnet, damit die Condition den 12h-Puffer nicht aufbläht.
CONDITION_RAIN_RATE: dict[str, float] = {
    "rainy": 1.0,  # Niesel / leichter Regen
    "pouring": 5.0,  # Starkregen
    "lightning-rainy": 3.0,  # Gewitter mit Regen
    "snowy-rainy": 0.5,  # Schneeregen
}

# Wuchsmodell (Growing Degree Days)
GDD_BASE_TEMP_C = 5.0  # Basistemperatur Gras (°C)
GROWTH_MM_PER_GDD = 0.8  # mm Wachstum pro GDD
FERTILIZER_BOOST_FACTOR = 1.5  # Multiplikator nach Düngung
FERTILIZER_ACTIVE_DAYS = 21  # Tage bis Dünger-Effekt nachlässt
STORAGE_KEY_GROWTH = "weather_mow_{entry_id}_growth"

# ── Schatten-Korrektur (vom Nutzer über UI-Entitäten verstellbar) ──────────
# Anteil der am Standort gemessenen Sonnenstrahlung, der den Rasen effektiv
# erreicht. 1.0 = freier Rasen ohne Schatten, 0.7 = leichter bis mittlerer
# Schatten (Default — viele Hausgärten), 0.3 = stark verschattet.
DEFAULT_LAWN_SUN_EFFICIENCY = 0.7
LAWN_SUN_EFFICIENCY_MIN = 0.1
LAWN_SUN_EFFICIENCY_MAX = 1.0
LAWN_SUN_EFFICIENCY_STEP = 0.05

# Lokale Uhrzeit, ab der die Sonne den Rasen erreicht. Vor dieser Zeit zählt
# die Strahlung NICHT für Trocknung und Tau-Freigabe — typisch für Gärten
# mit langem Morgenschatten durch Bäume/Häuser im Osten.
# Default "00:00" = keine Morgenschatten-Annahme, Verhalten unverändert.
DEFAULT_LAWN_SUN_FROM = "00:00:00"

# Gewichts-Map: (index_range, weight)
RAIN_WEIGHT_MAP = [
    (range(0, 48), 0.1),  # 8–12 h alt
    (range(48, 72), 0.2),  # 6–8 h alt
    (range(72, 96), 0.4),  # 4–6 h alt
    (range(96, 120), 0.7),  # 2–4 h alt
    (range(120, 144), 1.0),  # 0–2 h alt
]

# ── v0.4 Physikalisches Nässe-Modell (Penman-Monteith vereinfacht) ───────────
# Alle Konstanten wirken pro 5-Min-Update-Schritt.
K_SOLAR_MM_PER_UPDATE = 0.030  # Peak-Sonne (eff=1.0) → ~0.36 mm/h
K_TEMP_MM_PER_UPDATE_C = 0.001  # VPD=10°C → ~0.12 mm/h
K_WIND_MM_PER_UPDATE_KMH = 0.0005  # 20 km/h → ~0.06 mm/h
K_COND_MM_PER_UPDATE_C = 0.003  # 3°C unter Taupunkt → ~0.22 mm/h
DEW_OFFSET_C = 3.0  # Grasoberfläche ~3°C kühler als Luft bei Nacht
WETNESS_MAX_MM = 2.0  # Physikalischer Deckel: Grashalm hält max. ~2 mm

# ── v0.4 Mäh-Schwellwert (Restfeuchte) ──────────────────────────────────────
DEFAULT_MOW_THRESHOLD_MM = 0.5
MOW_THRESHOLD_MIN_MM = 0.1
MOW_THRESHOLD_MAX_MM = 3.0
MOW_THRESHOLD_STEP_MM = 0.1

DEFAULT_MOW_THRESHOLD_URGENT_MM = 1.5  # Dringlichkeits-Schwelle (bei Zeitdruck)
MOW_THRESHOLD_URGENT_MIN_MM = 0.5
MOW_THRESHOLD_URGENT_MAX_MM = 5.0
MOW_THRESHOLD_URGENT_STEP_MM = 0.1

# ── v0.4 Bewässerungs-Einheit ────────────────────────────────────────────────
IRRIGATION_FIXED_MM = 2.0  # Fixer Buchungswert pro Button-Druck (Halm-Sättigung ~1-2 mm)
WETNESS_DELTA_CAP_MM = 2.0  # Max. wetness-Zuwachs pro Update (Halm hält max. ~2 mm)

# ── v0.4 Adaptiver Startschwellwert + Grace Period ───────────────────────────
FORECAST_DISCOUNT_MM = 0.3  # Threshold-Discount wenn kein Regen in 3h
GRACE_PERIOD_MINUTES = 30  # Wartezeit unter eff. Schwellwert vor Start

# ── Gras-Dringlichkeit ────────────────────────────────────────────────────────
# urgency_high schaltet auf die Dringlichkeits-Nässe-Schwelle, wenn die
# durchschnittliche Mähdauer der letzten 3 Tage unter diesen Anteil des
# Tagesziels fällt (Gras zu lang → tolerantere Nässe-Schwelle).
URGENCY_GRASS_DEFICIT_RATIO = 0.5  # avg_3d_h < target * 0.5 → urgency_high

# ── v0.4 Storage ─────────────────────────────────────────────────────────────
STORAGE_KEY_WETNESS = "weather_mow_{entry_id}_wetness"
