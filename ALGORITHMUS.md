# Smart Mow — Algorithmus-Dokumentation

Alle Berechnungen die in `backtest_smart_mow.py` (Simulation) und  
`custom_components/smart_mow/coordinator.py` (HA-Integration) ablaufen.  
Beide Dateien verwenden identische Formeln.

---

## 1. Eingangsdaten (Sensoren)

| Sensor | Entity-ID | Einheit | Verwendung |
|--------|-----------|---------|------------|
| Regen aktuell | `sensor.weather_station_regenmesser_niederschlag` | mm/5min | Rain-Buffer, `raining`-Flag |
| Regen letzte Stunde | `sensor.weather_station_regenmesser_niederschlag_letzte_stunde` | mm | Morning-Penalty im Wetness Score |
| Regen heute | `sensor.weather_station_regenmesser_niederschlag_heute` | mm | Morning-Penalty |
| DWD Sonneneinstrahlung | `sensor.dwd_meine_sonneneinstrahlung` | W/m² | Solar Peak Tracker |
| DWD Niederschlag | `sensor.dwd_meine_niederschlag` | mm/h | Nowcast-Override |
| Außentemperatur | `sensor.boiler_outside_temperature` | °C | Taupunkt |
| Luftfeuchtigkeit | `sensor.garage_temperatur_luftfeuchtigkeit` | % | Taupunkt |
| Helligkeit | `sensor.helligkeit_beleuchtungsstarke` | Lux | Helligkeits-Check |
| PV-Leistung | `sensor.solaredge_ac_power` | W | Strahlungs-Fallback |

**DWD MOSMIX** (stündliche Prognose, Station X120):
- `RR1c` — Niederschlag mm/h: für Regenprognose heute, morgen, in 3h und Nowcast
- `RAD1h` — Globalstrahlung kJ/m²: wird zu W/m² umgerechnet (`/ 3.6`)

---

## 2. Update-Zyklus

Alle Berechnungen laufen **alle 5 Minuten** (288 Schritte/Tag).  
Der Ablauf pro Schritt:

```
Sensordaten lesen
→ Rain-Buffer aktualisieren → rain_weighted_12h
→ Strahlung bestimmen → solar_factor
→ DWD-Prognosen lesen
→ Wind berechnen
→ Taupunkt berechnen → dew_present
→ brightness_ok prüfen
→ Wetness Score berechnen
→ Mähfenster prüfen
→ _compute_decision() → mow_allowed, block_reason
→ _compute_priority() → priority (0–100)
→ start_now = mow_allowed AND priority >= 40
→ Akku-Zustandsmaschine
```

---

## 3. Regen-Buffer (gewichteter 12h-Regen)

Der Regen-Buffer speichert die letzten **144 Messwerte** (= 12 Stunden bei 5-Minuten-Auflösung) als gleitende Warteschlange (FIFO). Jeder neue `rain_now`-Wert wird am Ende angehängt, älteste Werte fallen heraus.

### Gewichtung nach Alter

| Buffer-Index | Alter des Messwerts | Gewicht |
|-------------|---------------------|---------|
| 0 – 47 | 8 – 12 Stunden alt | 0.1 |
| 48 – 71 | 6 – 8 Stunden alt | 0.2 |
| 72 – 95 | 4 – 6 Stunden alt | 0.4 |
| 96 – 119 | 2 – 4 Stunden alt | 0.7 |
| 120 – 143 | 0 – 2 Stunden alt | 1.0 |

Index 0 = ältester Wert, Index 143 = jüngster Wert.

### Berechnung

```
rain_weighted_12h = Σ (rain_now[i] × Gewicht[i])  für i = 0..143
```

**Interpretation:** Ein Wert von z. B. 5.0 bedeutet 5 mm effektiv gewichteter Regen in den letzten 12h. Frischer Regen zählt 10× stärker als Regen von vor 10 Stunden.

---

## 4. Strahlung und Solar Peak Tracker

### Strahlungsquelle (Priorität)

1. **DWD-Sensor** `sensor.dwd_meine_sonneneinstrahlung` (W/m²) — bevorzugt
2. **PV-Fallback**: `radiation = pv_leistung_W / (pv_peak_kW × 1000) × 1000`
3. **Sonnenhöhen-Fallback** (nur Backtest, nur bei Datenlücken):  
   `radiation = max(0, sin(sun_elevation°)) × 800 W/m²`

### Solar Peak Tracker

Verfolgt den höchsten bisher gemessenen Strahlungswert mit täglichem Decay:

```
radiation_peak = max(SOLAR_PEAK_MIN,  max(radiation_peak × DECAY_PER_UPDATE,  radiation_now))
```

- `SOLAR_PEAK_MIN = 50.0 W/m²` — Minimum damit Division durch Null ausgeschlossen ist
- `DECAY_PER_UPDATE = 1 − 0.005/288` — entspricht 0,5 % Decay pro Tag (sehr langsam)

Der Peak sinkt also minimal zwischen Sonnentagen, passt sich aber nach bewölkten Perioden nach unten an.

### Solar Factor

```
solar_factor = min(1.0,  radiation_now / radiation_peak)
```

Wertebereich 0.0 – 1.0. Entspricht dem aktuellen Anteil der Sonneneinstrahlung relativ zum historischen Tagesmaximum.

---

## 5. Taupunkt

Vereinfachte Magnus-Näherung:

```
dew_point = temp − (100 − humidity) / 5
```

Beispiel: 15 °C, 80 % Feuchte → `dew_point = 15 − 20/5 = 11.8 °C`

### Tau vorhanden?

```
dew_evaporated = temp > dew_point + threshold_dew_temp_offset
dew_present    = NOT dew_evaporated
```

`threshold_dew_temp_offset` (Default: 3 °C) — Sicherheitsabstand: Tau gilt erst als verdunstet wenn die Temperatur mindestens 3 °C über dem Taupunkt liegt.

---

## 6. Wind (Simulation im Backtest)

Im Backtest wird Wind simuliert (kein Sensor verfügbar). Die HA-Integration nutzt `sensor.dwd_meine_windgeschwindigkeit`.

### WindSimulator

Für jeden Kalendertag wird ein deterministisches Zufallsprofil erzeugt (Seed = Datum-Hash).  
Stützpunkte: 00:00 = 0 km/h, 08:00/12:00/16:00/18:00 = Zufallswert 0–20 km/h, 24:00 = 0 km/h.  
Zwischen den Stützpunkten wird **linear interpoliert**.

### Wind-Trocknung (Einfluss auf Wetness Score)

```
wind_drying = min(1.0,  wind_kmh / 30) × 5
```

Maximum 5 Punkte Abzug vom Wetness Score bei ≥ 30 km/h Wind.

---

## 7. Helligkeits-Check

```
brightness_ok = (sun_elevation >= 10°)  OR  (sensor_lux >= min_brightness_lux)
```

- Wenn die Sonne mehr als 10° über dem Horizont steht → immer hell genug
- Sensor dient als Ergänzung bei bewölktem Himmel oder Dämmerung  
- `min_brightness_lux` Default: 2000 Lux

In der HA-Integration liefert `sun.sun` die Sonnenhöhe direkt.  
Im Backtest wird sie aus Datum/Uhrzeit (Breitengrad 53°N, MESZ→UTC) berechnet.

---

## 8. Wetness Score

Der Wetness Score ist ein dimensionsloser Wert, der die aktuelle Bodennässe und Regenerwartung abbildet. **Höher = nasser**.

```
rain_score      = rain_weighted_12h × 8
morning_penalty = min(40,  rain_today_mm × 1.5) × (1 − solar_factor)
dew_score       = 25  falls dew_present, sonst 0
solar_drying    = solar_factor × 15
wind_drying     = min(1, wind_kmh/30) × 5
future_score    = rain_fc_3h_mm × 8

wetness_score = max(0,
    rain_score + morning_penalty + dew_score
    − solar_drying − wind_drying + future_score
)
```

### Nowcast-Override

Falls DWD MOSMIX für die aktuelle Stunde Niederschlag > 0.1 mm/h meldet:

```
wetness_score = max(wetness_score, 70)
```

Das garantiert dass laufender Regen immer über dem Schwellwert von 30 liegt.

### Komponenten-Übersicht

| Komponente | Wertebereich | Wirkung |
|-----------|-------------|---------|
| `rain_score` | 0 – ∞ | +Nässe durch bisherigen Regen |
| `morning_penalty` | 0 – 40 | +Nässe bei Regen heute (schwindet mit Sonne) |
| `dew_score` | 0 oder 25 | +Nässe bei vorhandenem Tau |
| `solar_drying` | 0 – 15 | −Nässe durch Sonne |
| `wind_drying` | 0 – 5 | −Nässe durch Wind |
| `future_score` | 0 – ∞ | +Nässe durch erwarteten Regen (3h) |

---

## 9. Entscheidungslogik (`_compute_decision`)

Gibt zurück: `(mow_allowed: bool, start_now: bool, block_reason: str)`

Die Checks werden **sequenziell** ausgeführt — der erste fehlgeschlagene Check stoppt.

```
1. in_window?          → sonst: "outside_time_window"
2. brightness_ok?      → sonst: "too_dark_hedgehog"
3. battery >= min%?    → sonst: "battery_low"  (Ausnahme s. u.)
4. wetness < threshold?→ sonst: "too_wet"
5. rain_today_rem < threshold? → sonst: "rain_expected_today"
6. duration < target?  → sonst: Notmäh-Prüfung oder "daily_target_reached"
7. → True, False, "mowing_allowed"  (Bedingungen ok, Priorität entscheidet)
```

### Mähfenster (Check 1)

`mow_window_start` bis `mow_window_end` (Default: 08:00 – 20:00 Uhr).

### Helligkeit (Check 2)

Siehe Abschnitt 7.

### Akku (Check 3)

Normales Verhalten: Mähen blockiert wenn `battery_pct < min_battery_pct` (Default: 20 %).

**Ausnahme bei Notdringlichkeit** (Regen im Anmarsch):  
Wenn Regen prognostiziert ist, wird geprüft ob noch eine sinnvolle Mährunde möglich ist:

```
batt_mow_min  = battery_pct / 100 × 60         # Minuten Laufzeit mit aktuellem Akku
avail         = minutes_until_rain − 15         # Zeit bis Regen minus 15 min Puffer
can_mow       = min(batt_mow_min, avail)

→ Mähen erlaubt wenn can_mow >= 20 Minuten
→ sonst: "battery_low"
```

Wenn kein Regen prognostiziert: normal blockiert.

### Nässe (Check 4)

```
wetness_score >= threshold_wetness_score  → "too_wet"
```

Default: `threshold_wetness_score = 30`

### Regenerwartung heute (Check 5)

```
rain_today_remaining >= threshold_rain_today_remaining_mm  → "rain_expected_today"
```

`rain_today_remaining` = Summe MOSMIX RR1c von jetzt bis Mitternacht (mm).  
Default Schwellwert: 5 mm.

### Tagesziel & Notmähen (Check 6)

```
if duration_today_h >= target_daily_h:
    if rain_tomorrow >= threshold_rain_tomorrow_mm:
        if time_remaining_h >= threshold_min_time_for_emergency_h
           AND duration_today_h < (target + full_cycle_h):
            → emergency_mow = True, start_now = True  ("emergency_mow_tomorrow_rain")
    → "daily_target_reached"
```

Notmähen greift wenn: Tagesziel bereits erreicht, morgen wird es regnen, noch genug Zeit im Fenster und die Zusatzmähzeit würde `target + full_cycle_h` nicht überschreiten.

---

## 10. Priorität (`_compute_priority`)

Gibt einen Wert 0–100 zurück. `start_now = True` wenn `priority >= 40`.

```
deficit_ratio  = max(0,  1 − duration_today_h / target_daily_h)
avg_deficit    = max(0,  1 − duration_avg_3d_h / target_daily_h)

emergency_bonus = 40  falls emergency_mow aktiv, sonst 0
wetness_penalty = min(30,  wetness_score × 0.3)
urgency_bonus   = max(0,  3.0 − time_remaining_h) × 5   # max +15 in letzter Stunde
midday_bonus    = (siehe unten)                           # max +10 zwischen 11–16 Uhr

priority = clamp(0..100,
    deficit_ratio × 40
    + avg_deficit × 20
    + emergency_bonus
    + urgency_bonus
    + midday_bonus
    − wetness_penalty
)
```

### Mittagsbevorzugung

```
10:00–11:00 Uhr: midday_bonus = (hour − 10) × 10      # Rampe 0 → 10
11:00–16:00 Uhr: midday_bonus = 10                     # Plateau +10
16:00–17:00 Uhr: midday_bonus = (17 − hour) × 10      # Rampe 10 → 0
sonst:           midday_bonus = 0
```

### Prioritäts-Komponenten im Überblick

| Komponente | Max. Beitrag | Bedeutung |
|-----------|-------------|-----------|
| `deficit_ratio × 40` | +40 | Heute noch nichts gemäht → hohe Dringlichkeit |
| `avg_deficit × 20` | +20 | 3-Tage-Durchschnitt unter Ziel |
| `emergency_bonus` | +40 | Notmähbedingung aktiv |
| `urgency_bonus` | +15 | Fenster läuft ab (letzte 3h) |
| `midday_bonus` | +10 | 11–16 Uhr bevorzugt |
| `wetness_penalty` | −30 | Boden noch feucht |

**Maximal erreichbare Priorität ohne Notfall:** 40 + 20 + 15 + 10 = **85**  
**Start-Schwellwert:** 40

---

## 11. Akku-Zustandsmaschine (Simulation)

```
BATTERY_RATE_PCT = 100 / 12  ≈ 8.33 % pro 5-Minuten-Schritt
                             (1 Stunde Mähen = 100 %, 1 Stunde Laden = 100 %)
```

### Zustandsübergänge

```
Zustand: "mowing"
  stop = (battery <= 0) OR raining OR rain_imminent OR NOT mow_allowed
  wenn stop    → Zustand: "docked"
  sonst        → battery -= BATTERY_RATE_PCT
               → duration_today_s += 300

Zustand: "docked"
  rain_imminent = minutes_until_rain < 15
  wenn start_now AND NOT raining AND NOT rain_imminent
               → Zustand: "mowing"
               → battery -= BATTERY_RATE_PCT
               → duration_today_s += 300
  sonst        → battery += BATTERY_RATE_PCT  (aufladen)
```

**In der HA-Integration** wird kein simulierter Akkustand geführt — dort liest der Coordinator den echten Akkustand aus der `lawn_mower`-Entity (wenn verfügbar).

---

## 12. Notmäh-Prüfung (Emergency Mow)

Greift wenn das Tagesziel bereits erreicht ist, aber morgen Regen erwartet wird.  
Aktiviert `emergency_active = True` für den aktuellen Tag (wird um Mitternacht zurückgesetzt).

Bedingungen:
```
duration_today_h >= target_daily_h
AND rain_tomorrow >= threshold_rain_tomorrow_mm     (Default: 8 mm)
AND time_remaining_h >= threshold_min_time_emergency_h  (Default: 2 h)
AND duration_today_h < target + full_cycle_h
```

Im aktiven Notmäh-Zustand: `start_now = True` (unabhängig von Priorität), `emergency_bonus = +40` in Prioritätsformel.

---

## 13. Regenprognose via DWD MOSMIX

MOSMIX-L-Daten werden einmal täglich von `opendata.dwd.de` geladen (Station X120, gecacht).  
Format: KMZ-Archiv mit KML-Datei, stündliche Zeitschritte in UTC.

Verwendete Felder:
- `RR1c` — Niederschlag in mm/h (stundenweise)
- `RAD1h` — Globalstrahlung in kJ/m² (wird zu W/m²: `/ 3.6`)

### Abfragen im Algorithmus

| Variable | Berechnung | Bedeutung |
|----------|-----------|-----------|
| `rain_today_remaining` | Summe RR1c von jetzt bis Mitternacht | Noch erwarteter Regen heute |
| `rain_tomorrow` | Summe RR1c der 24h ab Mitternacht | Gesamtregen morgen |
| `rain_fc_3h` | Summe RR1c der nächsten 3 Stunden | Kurzfristige Regenerwartung |
| `precip_nowcast` | RR1c aktuelle Stunde | Regen jetzt laut Prognose |
| `minutes_until_rain` | Stunden bis erster RR1c > 0.1 mm/h | Wann kommt der nächste Regen? |

---

## 14. Auto-Dock-Schutz (HA-Integration)

Die HA-Integration überwacht den Mäherzustand via `async_track_state_change_event`.

```
Wenn Mäher → "mowing" wechselt:
    falls _last_mow_allowed == False:
        → lawn_mower.dock aufrufen
        → binary_sensor "auto_resume_blocked" für einen Zyklus = True
        → WARNING ins HA-Log
```

`_last_mow_allowed` wird nach jedem 5-Minuten-Update auf den aktuellen `mow_allowed`-Wert gesetzt.

Deaktivierbar via Option `prevent_auto_resume = False`.

---

## 15. Konfigurierbare Parameter

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `mow_window_start` | 08:00 | Früheste Mähzeit |
| `mow_window_end` | 20:00 | Späteste Mähzeit |
| `target_daily_h` | 2.5 h | Tägliches Mähziel |
| `full_cycle_h` | 2.0 h | Dauer für einen vollständigen Durchgang |
| `min_battery_pct` | 20 % | Minimaler Akkustand für Mähstart |
| `threshold_wetness_score` | 30 | Nässe-Schwellwert (darunter = mähen ok) |
| `threshold_rain_today_remaining_mm` | 5 mm | Prognose-Regen heute blockiert Mähen |
| `threshold_rain_tomorrow_mm` | 8 mm | Regen morgen löst Notmähen aus |
| `threshold_min_time_for_emergency_h` | 2 h | Mindest-Restzeit für Notmähen |
| `threshold_dew_temp_offset` | 3 °C | Temp-Abstand über Taupunkt → Tau verdunstet |
| `min_brightness_lux` | 2000 | Helligkeitsschwelle (Fallback zu Sonnenhöhe) |
| `prevent_auto_resume` | True | Mäher wird bei unerlaubtem Start gedockt |
