<p align="center">
  <img src="custom_components/weather_mow/logo.png" alt="WeatherMow Logo" width="160">
</p>

# WeatherMow — Wetterabhängige Mähroboter-Steuerung

Eine Home Assistant Custom Integration, die **Sensoren und Binärsensoren** für wetterabhängige Mähentscheidungen bereitstellt. Die Integration steuert den Mäher **nicht direkt** — sie liefert Signale, die in eigenen Automationen verwendet werden.

**Kompatibel mit:** Navimow, Husqvarna Automower, Luba, Worx Landroid und jedem anderen `lawn_mower`-Entity.

---

## Inhalt

1. [Voraussetzungen](#voraussetzungen)
2. [Installation](#installation)
3. [Konfiguration (6 Schritte)](#konfiguration)
4. [Datenquellen — Signalübersicht](#datenquellen)
5. [Konfiguration mit OpenWeatherMap](#konfiguration-mit-openweathermap)
6. [Alle Entities](#alle-entities)
7. [Wetness Score erklärt](#wetness-score-erklärt)
8. [Entscheidungslogik](#entscheidungslogik)
9. [Automatisierungs-Beispiele](#automatisierungs-beispiele)
10. [Troubleshooting](#troubleshooting)
11. [Changelog](#changelog)

---

## Voraussetzungen

- Home Assistant 2023.1 oder neuer
- Eine `weather.*`-Integration mit Stundenprognose — **OpenWeatherMap** (weltweit empfohlen) oder [dwd_weather](https://github.com/FL550/dwd_weather) HACS-Integration von FL550 (Deutschland, bietet zusätzlich Strahlungsprognose)
- Lokale Regenstation (optional, aber empfohlen): Ecowitt, Netatmo o. Ä.
- Außentemperatur- und Luftfeuchtigkeitssensor (optional — Fallback auf weather-Attribut)
- Optional: Helligkeitssensor (Igelschutz), PV-Leistungssensor (Strahlungs-Fallback)

---

## Installation

### HACS (empfohlen)

1. HACS öffnen → **Integrationen** → ⋮ → *Benutzerdefinierte Repositories*
2. URL: `https://github.com/Schnabel80/weather_mow`, Typ: **Integration**
3. *WeatherMow* suchen und installieren
4. Home Assistant neu starten
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen → WeatherMow**

### Manuell

```bash
cp -r custom_components/weather_mow /config/custom_components/
```
Home Assistant neu starten, dann wie oben fortfahren.

---

## Konfiguration

Die Integration wird vollständig über die UI eingerichtet (6 Schritte).

### Schritt 1 — Gerät

| Feld | Beschreibung | Default |
|------|-------------|---------|
| Name | Prefix für alle Entities (z. B. `rasenmaeher`) | Rasenmaeher |
| Mäher-Entität | `lawn_mower.*` Entity | `lawn_mower.navimow_i105` |
| Mindest-Akkustand | Mähen nur wenn Akku ≥ diesem Wert | 100 % |

### Schritt 2 — Wetterdaten

| Feld | Beschreibung |
|------|-------------|
| Wetter-Entität | `weather.*` — Pflicht. Wird für Temp-/Feuchte-Fallback, Konditions-Erkennung (Niesel) und Stunden-Prognosen verwendet. |
| Sonneneinstrahlung-Sensor | `sensor.*` in W/m², mit `data`-Attribut — **Optional, nur DWD**. Einzige Quelle für echte Strahlungsprognose. |
| Niederschlagsprognose-Sensor | `sensor.*` in mm/h, mit `data`-Attribut — **Optional, nur DWD**. Bei OWM leer lassen. |
| Wind-Sensor | `sensor.*` in km/h — Optional. Bei OWM leer lassen (Wind aus weather-Attribut). |

> **OWM-Nutzer:** Nur die Wetter-Entität eintragen, alle anderen Felder leer lassen. Prognosen werden automatisch per `weather.get_forecasts` Service abgerufen.
> **DWD-Nutzer:** DWD-Sensoren müssen ein `data`-Attribut mit `{"datetime": "...", "value": ...}` Einträgen liefern — dies erfordert die [HACS dwd_weather Integration](https://github.com/FL550/dwd_weather) von FL550, **nicht** die offizielle HA-Kern-Integration.

### Schritt 3 — Regensensoren

Alle Felder optional. Niesel wird automatisch aus der weather-Entität erkannt wenn kein lokaler Sensor konfiguriert ist.

| Feld | Beschreibung |
|------|-------------|
| Regenmesser aktuell | Momentanwert in mm/h (z. B. Ecowitt rain_rate, Netatmo) — Basis für den 12h-Puffer |
| Regen letzte Stunde | Nativer 1h-Wert des Sensors (kein eigener Buffer nötig) |
| Regen heute gesamt | `total_increasing` seit Mitternacht — für Nachtregen-Erkennung |
| Regenerkennung | `binary_sensor` (on/off) oder `sensor` (>0) — sofortige Regen-Meldung |

### Schritt 4 — Temperatur, Feuchte, Helligkeit

| Feld | Beschreibung |
|------|-------------|
| Außentemperatur | °C (Fallback: DWD-Attribut `temperature`) |
| Luftfeuchtigkeit | % (Fallback: DWD-Attribut `humidity`) |
| Helligkeitssensor | Lux, optional — für Igelschutz (z. B. Homematic HmIP-SLO) |
| Mindesthelligkeit | Mähen gesperrt unterhalb dieses Werts (Default: 2000 Lux) |

### Schritt 5 — Strahlungs-Fallback

Wird **übersprungen**, wenn in Schritt 2 ein DWD-Strahlungssensor angegeben wurde.

Andernfalls: Entweder PV-Leistung als Proxy oder Sonnenstand (sun.sun elevation).

### Schritt 6 — Mähfenster & Schwellwerte

Alle Werte sind später im **Options Flow** änderbar (ohne Re-Setup).

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| Mähfenster Start | 08:00 | Frühester Mähzeitpunkt |
| Mähfenster Ende | 20:00 | Spätester Mähzeitpunkt |
| Tagesziel Mähstunden | 3,0 h | Angestrebte tägliche Mähzeit |
| Dauer eines vollen Zyklus | 2,0 h | Für Notmäh-Berechnung |
| Nässe-Schwellwert | 30 | Mähen gesperrt ab diesem Score |
| Regenerwartung heute | 5,0 mm | Mähen gesperrt wenn DWD mehr erwartet |
| Regenerwartung morgen | 8,0 mm | Löst Notmähen aus wenn Tagesziel erreicht |
| Mindestzeit für Notmähen | 2,0 h | Notmähen nur wenn noch genug Zeit im Fenster |
| Tau-Temperaturoffset | 3,0 °C | Tau gilt als getrocknet bei Temp > Taupunkt + Offset |
| Mindeststunden Sonne für Tau-Freigabe | 1,0 h | Kontinuierliche Strahlung ≥ 200 W/m² nötig für Tau-Clearance (bei ≥ 500 W/m²: sofort) |

---

## Datenquellen

Die folgende Tabelle zeigt, welche Signale von welchen Quellen verfügbar sind und was für deine Situation empfohlen wird.

| Signal | OpenWeatherMap | DWD (FL550 HACS) | Ecowitt (lokal) | Netatmo (lokal) | ⭐ Empfehlung |
|--------|:---:|:---:|:---:|:---:|---|
| **Niederschlagsprognose** | ✅ 48h Stundenprognose | ✅ sehr präzise (nur D) | ❌ | ❌ | ⭐ **OWM** — weltweit, kein Extra-Sensor |
| **Regen jetzt** | ✅ via `condition` | ✅ via `condition` | ✅ Piezo-Sensor | ⚠️ Kippschale | ⭐ **Ecowitt + OWM** kombiniert |
| **Niesel-Erkennung** | ✅ `condition: rainy` | ✅ `condition: rainy` | ✅ `binary_sensor.rain_state` | ❌ zu grob | ⭐ **Ecowitt** oder **OWM** condition |
| **Globalstrahlung aktuell** | ❌ | ✅ eigener Sensor | ✅ Solar-Sensor | ❌ | ⭐ **Ecowitt** oder DWD-Sensor |
| **Globalstrahlung Prognose** | ⚠️ Cloud-Schätzung | ✅ stündl. W/m² Forecast | ❌ | ❌ | ⭐ **DWD** — einzige echte Quelle |
| **Temperatur** | ✅ weather-Attribut | ✅ weather-Attribut | ✅ lokaler Sensor | ✅ lokaler Sensor | ⭐ **Ecowitt / Netatmo** — direkt im Garten |
| **Luftfeuchtigkeit** | ✅ weather-Attribut | ✅ weather-Attribut | ✅ lokaler Sensor | ✅ lokaler Sensor | ⭐ **Ecowitt / Netatmo** — für Taupunkt wichtig |
| **Wind** | ✅ weather-Attribut | ✅ eigener Sensor | ✅ Anemometer inklusive | ⚠️ Extra-Modul nötig | ⭐ **Ecowitt** lokal — OWM als einfacher Fallback |
| **Helligkeit (Lux)** | ❌ | ❌ | ⚠️ Solar W/m² (kein Lux) | ⚠️ nur Innenmodul | Eigener Lux-Sensor (optional, Igelschutz) |
| **Regen-Detektor (binär)** | — | — | ✅ `binary_sensor.rain_state` | ❌ | ⭐ **Ecowitt** — schnellste Hardware-Erkennung |

**Hinweise:**
- **(D)** DWD ist nur für Deutschland verfügbar
- **OWM vs. DWD:** Für Niederschlagsprognosen liefern beide vergleichbare Ergebnisse. **DWD ist unverzichtbar wenn du die Strahlungsprognose nutzen möchtest** — keine andere Integration liefert stündliche W/m²-Forecasts. In Deutschland: OWM als Hauptquelle + DWD-Strahlungssensor ist die optimale Kombination.
- **Ecowitt:** Direkte lokale Abfrage vom Gerät — kein Cloud-Umweg, keine API-Limits. Für Deutschland verfügbar über die [Ecowitt HACS Integration](https://github.com/briis/hass-ecowitt).
- **Weather Underground:** Ecowitt kann dorthin hochladen, aber die offizielle HA-Integration wurde eingestellt. Direkt die Ecowitt-Integration nutzen.

**Optimale Kombination (Deutschland):** OWM (weather entity) + DWD-Strahlungssensor + Ecowitt (Temp, Feuchte, Regen-Hardware) + PV als Fallback

**Optimale Kombination (international):** OWM (weather entity) + Ecowitt mit Solar-Sensor (aktuelle Strahlung) + PV oder Sonnenstand als Prognose-Fallback

---

## Konfiguration mit OpenWeatherMap

OpenWeatherMap ist die empfohlene Wetterdatenquelle für alle Nutzer außerhalb Deutschlands — und eine gute Alternative auch in Deutschland, da OWM globale Abdeckung mit stündlichen Prognosen bietet.

### Einrichtung in Home Assistant

1. **OpenWeatherMap Integration** installieren (offiziell im HA-Kern enthalten)
2. API-Key bei [openweathermap.org](https://openweathermap.org/api) erstellen (kostenloser Plan reicht)
3. Integration in HA hinzufügen → `weather.openweathermap` Entity wird erstellt

### WeatherMow konfigurieren für OWM

**Schritt 2 — Wetterdaten:**
| Feld | Wert |
|------|------|
| Wetter-Entität | `weather.openweathermap` |
| Sonneneinstrahlung-Sensor | *leer lassen* |
| Niederschlagsprognose-Sensor | *leer lassen* |
| Wind-Sensor | *leer lassen* |

**Schritt 3 — Regensensoren:**
Alle Felder können leer bleiben. Niesel und Sprühregen werden automatisch aus dem OWM-Zustand erkannt (`rainy`, `pouring`, etc.). Lokale Sensoren (Ecowitt, Netatmo) können zusätzlich konfiguriert werden.

**Schritt 4 — Temp/Feuchte:**
Leer lassen → Fallback auf OWM weather-Entity Attribute.

**Schritt 5 — Strahlungsquelle:**
OWM liefert keine Globalstrahlung (W/m²). Hier muss etwas konfiguriert werden:
- **PV-Sensor:** Wenn PV-Anlage vorhanden, als Proxy nutzen
- **Sonnenstand:** Immer verfügbar, weniger präzise bei Bewölkung

### Was OWM automatisch liefert

| Signal | Wie |
|--------|-----|
| Niederschlagsprognose (48h) | `weather.get_forecasts` Service — automatisch wenn kein DWD-Sensor konfiguriert |
| Regen jetzt (inkl. Niesel) | `weather.state` condition (`rainy`, `pouring`) |
| Temperatur | `weather.*` Attribut als Fallback |
| Luftfeuchtigkeit | `weather.*` Attribut als Fallback |
| Wind | `weather.*` Attribut `wind_speed` |
| Globalstrahlung | Cloud-Coverage-basierte Schätzung für Prognose-Algorithmus |

---

## Alle Entities

Alle Entity-Namen werden mit dem in Schritt 1 konfigurierten **Namen** als Prefix gebildet (Kleinbuchstaben, Leerzeichen durch `_` ersetzt).

### Sensoren

| Entity-Suffix | Einheit | Beschreibung |
|--------------|---------|-------------|
| `_wetness_score` | — | Nässe-Score 0–100+ (Algorithmus-Kernwert) |
| `_priority` | — | Mäh-Priorität 0–100 |
| `_duration_today` | h | Mähstunden heute |
| `_duration_avg_3d` | h | Durchschnitt letzte 3 Tage |
| `_rain_last_1h` | mm | Regen letzte Stunde (Netatmo nativ) |
| `_rain_weighted_12h` | mm | Gewichteter 12h-Regenwert (Algorithmus-intern) |
| `_rain_today_total` | mm | Regen heute gesamt (Netatmo, seit Mitternacht) |
| `_rain_today_remaining` | mm | Regenprognose bis Mitternacht (DWD) |
| `_rain_tomorrow` | mm | Regenprognose morgen gesamt (DWD) |
| `_solar_peak` | W/m² | Kalibrierter Spitzenwert des Solar-Trackers |
| `_dew_point` | °C | Berechneter Taupunkt |
| `_block_reason` | — | Aktueller Sperrgrund (Text) |

### Binärsensoren

| Entity-Suffix | Klasse | Beschreibung |
|--------------|--------|-------------|
| `_allowed` | running | `on` = alle Bedingungen erfüllt, Mähen möglich |
| `_start_now` | — | `on` = Mähen **empfohlen** (Priorität ≥ 40) |
| `_emergency_mow` | — | `on` = Notmähen aktiv (Regen morgen + Tagesziel erreicht) |
| `_raining` | moisture | `on` = aktuell Regen > 0,1 mm |
| `_dew_present` | — | `on` = Morgentau noch nicht verdunstet |
| `_brightness_ok` | light | `on` = genug Licht für Igelschutz |

### Schalter

| Entity-Suffix | Default | Beschreibung |
|--------------|---------|-------------|
| `_enabled` | an | Hauptschalter — bei `off` kein Mähen empfohlen |

---

## Wetness Score erklärt

Der Wetness Score (0–100+) beschreibt, wie nass der Rasen wahrscheinlich ist:

```
Score = rain_score
      + morning_penalty   (Nachtregen-Malus, klingt mit Sonne ab)
      + dew_score          (Morgentau: +25 wenn aktiv)
      - drying             (Sonne trocknet: bis -15)
      - wind_dry           (Wind trocknet: bis -5)
      + future_score       (Regenprognose nächste 3h)
```

- **rain_score**: Gewichteter 12h-Regenhistorie × 8. Regen vor 1h zählt mehr als Regen vor 10h.
- **morning_penalty**: `rain_heute_mm × 1,5` — erkennt Nachtregen über den `total_increasing`-Sensor. Wird durch `(1 - solar_factor)` multipliziert, verschwindet also bei starker Sonne automatisch.
- **Nowcast-Override**: Wenn DWD gerade > 0,1 mm/h meldet, wird der Score auf mindestens 70 gesetzt.

**Beispiel:** 5 mm Nachtregen, 08:00 Uhr, noch keine Sonne → Score ≈ 47. Mit Score-Schwellwert 30: Mähen gesperrt. Um 11:00 Uhr mit voller Sonne → Score ≈ 15: Mähen erlaubt.

---

## Entscheidungslogik

`binary_sensor.[name]_allowed` und `binary_sensor.[name]_start_now` folgen dieser Reihenfolge:

1. **Switch aus** → gesperrt (`disabled`)
2. **Außerhalb Mähfenster** → gesperrt (`outside_time_window`)
3. **Zu dunkel** (Igelschutz) → gesperrt (`too_dark_hedgehog`)
4. **Akku zu niedrig** → gesperrt (`battery_low`)
5. **Nässe-Score ≥ Schwellwert** → gesperrt (`too_wet`)
6. **Regenprognose heute ≥ Schwellwert** → gesperrt (`rain_expected_today`)
7. **Tagesziel erreicht + Regen morgen** → **Notmähen** wenn Zeit verbleibt (`emergency_mow_tomorrow_rain`)
8. **Tagesziel erreicht** → gesperrt (`daily_target_reached`)
9. **Alles ok** → `allowed = true`, `start_now = (Priorität ≥ 40)`

Der aktuelle Sperrgrund ist in `sensor.[name]_block_reason` abrufbar.

---

## Automatisierungs-Beispiele

### Navimow (lawn_mower.start_mowing / pause)

```yaml
alias: Smart Mow — Navimow starten
trigger:
  - platform: state
    entity_id: binary_sensor.rasenmaeher_start_now
    to: "on"
condition:
  - condition: state
    entity_id: lawn_mower.navimow_i105
    state: docked
action:
  - service: lawn_mower.start_mowing
    target:
      entity_id: lawn_mower.navimow_i105

---

alias: Smart Mow — Navimow stoppen
trigger:
  - platform: state
    entity_id: binary_sensor.rasenmaeher_start_now
    to: "off"
condition:
  - condition: state
    entity_id: lawn_mower.navimow_i105
    state: mowing
action:
  - service: lawn_mower.pause
    target:
      entity_id: lawn_mower.navimow_i105
```

### Generischer lawn_mower

```yaml
alias: Smart Mow — Generisch starten
trigger:
  - platform: state
    entity_id: binary_sensor.rasenmaeher_start_now
    to: "on"
  - platform: time_pattern
    minutes: "/5"
condition:
  - condition: state
    entity_id: binary_sensor.rasenmaeher_start_now
    state: "on"
  - condition: not:
    - condition: state
      entity_id: lawn_mower.mein_maeher
      state: mowing
action:
  - service: lawn_mower.start_mowing
    target:
      entity_id: lawn_mower.mein_maeher

---

alias: Smart Mow — Generisch zurückrufen
trigger:
  - platform: state
    entity_id: binary_sensor.rasenmaeher_allowed
    to: "off"
condition:
  - condition: state
    entity_id: lawn_mower.mein_maeher
    state: mowing
action:
  - service: lawn_mower.dock
    target:
      entity_id: lawn_mower.mein_maeher
```

### Benachrichtigung bei Notmähen

```yaml
alias: Smart Mow — Notmähen Benachrichtigung
trigger:
  - platform: state
    entity_id: binary_sensor.rasenmaeher_emergency_mow
    to: "on"
action:
  - service: notify.mobile_app_mein_handy
    data:
      title: "🌧 Notmähen aktiv"
      message: >
        Morgen wird Regen erwartet ({{ states('sensor.rasenmaeher_rain_tomorrow') }} mm).
        Mäher läuft jetzt für einen zusätzlichen Zyklus.
```

---

---

## Troubleshooting

### Integration lädt nicht

- Prüfe `homeassistant.log` auf Fehler mit `weather_mow`
- Stelle sicher, dass der Ordner `custom_components/weather_mow/` im HA-Config-Verzeichnis liegt (nicht in einem Unterordner)

### Entities bleiben `unavailable`

- Die Integration benötigt einen erfolgreichen ersten Coordinator-Update. Prüfe ob alle konfigurierten Entity-IDs in HA existieren.
- Bei DWD: Das `data`-Attribut muss eine Liste sein. Prüfe mit Entwicklertools → Zustände.

### Wetness Score immer 0

- Der 12h-Buffer füllt sich erst nach 12h Laufzeit komplett. Anfangs sind die Werte normal niedrig.
- Prüfe ob der konfigurierte Niederschlagssensor einen validen State liefert.

### DWD Prognose fehlt

WeatherMow liest stündliche Forecast-Werte aus dem `data`-Attribut der Prognose-Sensoren:

```json
[{"start": "2024-06-01T08:00:00", "value": 0.2}, ...]
```

Die **HACS-Custom-Integration [dwd_weather](https://github.com/FL550/dwd_weather)** (von FL550) liefert dieses Format — ihre Sensoren `sensor.<name>_niederschlag` und `sensor.<name>_sonneneinstrahlung` sind kompatibel.

Die **offizielle HA-Kern-Integration** `dwd_weather_warnings` ist **nicht kompatibel** — sie stellt Forecasts in einem anderen Format bereit, das WeatherMow nicht liest.

Kurz: Wenn die Prognose fehlt, prüfe ob du die HACS-Version (FL550) verwendest, nicht die Kern-Integration.

### Mähdauer zählt nicht

- Die Integration trackt den `lawn_mower` Entity-State `mowing`. Prüfe ob dein Mäher diesen State korrekt setzt.
- Bei Neustart von HA: Die Zählung wird aus dem HA-Storage wiederhergestellt.

### Options Flow zeigt keine Änderungen

- Nach Speichern der Optionen wird die Integration automatisch neu geladen. Warte ca. 10 Sekunden.

---

## Changelog

### 0.2.2
- **Neu: Debug Mode** — zwei neue Diagnose-Werkzeuge:
  - **Download Diagnostics** (Einstellungen → Geräte → WeatherMow → Download Diagnostics): JSON-Snapshot mit allen aktuellen Sensorwerten, berechneten Scores und internem Zustand (Regen-Buffer, Solar-Peak, Mähdauern). Kein Addon nötig.
  - **`switch.<name>_debug_log`**: Wenn eingeschaltet, schreibt die Integration alle 5 Minuten eine Zeile in `/config/weather_mow_debug.csv` — 28 Spalten mit allen Entscheidungswerten. Download via File Editor Addon.
- **Neu: Logo** — Icon erscheint in der HA-Integrationsübersicht und in HACS (via `brand/`-Ordner, HA 2026.3+).

### 0.2.1
- **Fix: `sensor.next_mow_expected` zeigt jetzt den tatsächlich erwarteten Start** — der Sensor setzte bisher bei `mow_allowed = True` die aktuelle Zeit, auch wenn die Priorität noch unter 40 lag und `start_now = False` war. Jetzt gilt: nur wenn `start_now = True` (Priorität ≥ 40 UND erlaubt) zeigt der Sensor "jetzt". Sonst liefert `_forecast_next_mow()` den nächsten prognostizierten Startzeitpunkt.
- **Fix: TIMESTAMP-Sensor veraltet nicht mehr** — `native_value` gibt bei `start_now = True` dynamisch `dt_util.now()` zurück, sodass der Sensor nicht alle 5 Minuten kurz in die Vergangenheit fällt.

### 0.2.0
- **Neu: OpenWeatherMap-Unterstützung** — jede `weather.*`-Integration mit `get_forecasts`-Service funktioniert jetzt als vollwertige Datenquelle. Niederschlagsprognosen, Windgeschwindigkeit und Konditions-Erkennung (Niesel via `rainy`/`pouring`/etc.) werden automatisch aus der weather-Entität gelesen wenn kein DWD-Prognose-Sensor konfiguriert ist.
- **Neu: Strahlungsbasierte Tau-Freigabe** — Morgentau gilt erst als verdunstet wenn zusätzlich zur Temperatur-Bedingung mindestens 1 Stunde kontinuierliche Sonnenstrahlung ≥ 200 W/m² gemessen wurde. Bei ≥ 500 W/m² sofortige Freigabe. Konfigurierbar im Options Flow unter "Mindeststunden Sonne für Tau-Freigabe".
- **Neu: Niesel-Erkennung via weather condition** — `weather.state` = `rainy`, `pouring`, `lightning-rainy` oder `snowy-rainy` erhöht den Regen-Buffer auch wenn der Kippschalen-Sensor noch nichts meldet. Netatmo-Nutzer erkennen Sprühregen damit zuverlässig.
- **Neu: Alle Regensensor-Felder optional** — Konfiguration ohne lokale Wetterstation möglich, OWM übernimmt dann alle Wetterdaten.
- **Geändert:** Sonnenschein-Tracking-Schwellwert von 100 auf 200 W/m² angehoben — physikalisch sinnvollere Grenze für tatsächlich relevante Trocknungsenergie.
- **Doku:** Neue Signalquellen-Tabelle (OWM / DWD / Ecowitt / Netatmo) + vollständiger OWM-Konfigurationsabschnitt.

### 0.1.5
- **Neu:** Regen-Buffer (12h), heutige Mähdauer und Solar-Peak werden beim ersten Update direkt aus dem HA-Recorder rekonstruiert. Nach Neustart, Integration-Update oder Neuinstallation sind die Werte sofort korrekt — kein 12-stündiger Aufwärmpuffer mehr nötig. Erkennt außerdem eine laufende Mähsession nach einem HA-Absturz und trackt sie weiter.
- **Fix:** `sensor.<name>_next_mow_expected` springt nicht mehr unerwartet — die bereits verstrichene Sonnenscheindauer wird aus dem HA-Recorder gelesen und beim Tau-Clearance-Countdown korrekt berücksichtigt.

### 0.1.4
- **Neu:** `date.<name>_last_fertilization` — beschreibbares Datumsfeld direkt im Dashboard. Kein Umweg über ⚙️ Konfigurieren mehr nötig. Der 21-Tage-Wachstums-Boost (GDD ×1,5) wird automatisch aktiviert.
- **Neu:** `sensor.<name>_next_mow_expected` — Timestamp-Sensor mit stündlicher Vorausschau (bis 48h). Zeigt wann Mähen voraussichtlich wieder möglich ist, basierend auf DWD-Niederschlags- und Strahlungsprognose, Wetness-Decay-Simulation und Tau-Clearance.

### 0.1.3
- **Neu:** Entitäten nach Setup korrigierbar — **Einstellungen → Geräte & Dienste → WeatherMow → ⋮ → Neu konfigurieren**. Alle 5 Schritte werden vorausgefüllt, nur die falsche Entität muss geändert werden.

### 0.1.2
- **Fix:** `binary_sensor.<name>_allowed` zeigt jetzt "Ein"/"Aus" statt irreführendem "Außer Betrieb".

### 0.1.1
- **Fix:** `dew_present` ist jetzt eine harte Sperre — Mähen wird zuverlässig blockiert wenn Morgentau vorhanden ist.
- **Fix:** Notmähen überbrückt die Tau-Sperre (Mäher läuft auch bei Tau wenn morgen Regen erwartet wird).
- **Fix:** `async_shutdown` ValueError beim HA-Neustart behoben.
- **Neu:** Optionaler Regen-Erkenner (`rain_detector_entity_id`) für Ecowitt-Sensoren oder andere Schnellerkenner.

### 0.1.0
- Erstveröffentlichung
