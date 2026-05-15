# Smart Mow — Wetterabhängige Mähroboter-Steuerung

Eine Home Assistant Custom Integration, die **Sensoren und Binärsensoren** für wetterabhängige Mähentscheidungen bereitstellt. Die Integration steuert den Mäher **nicht direkt** — sie liefert Signale, die in eigenen Automationen verwendet werden.

**Kompatibel mit:** Navimow, Husqvarna Automower, Luba, Worx Landroid und jedem anderen `lawn_mower`-Entity.

---

## Inhalt

1. [Voraussetzungen](#voraussetzungen)
2. [Installation](#installation)
3. [Konfiguration (6 Schritte)](#konfiguration)
4. [Alle Entities](#alle-entities)
5. [Wetness Score erklärt](#wetness-score-erklärt)
6. [Entscheidungslogik](#entscheidungslogik)
7. [Automatisierungs-Beispiele](#automatisierungs-beispiele)
8. [Backtest-Tool](#backtest-tool)
9. [SQLite-Export-Befehl](#sqlite-export-befehl)
10. [Troubleshooting](#troubleshooting)

---

## Voraussetzungen

- Home Assistant 2023.1 oder neuer
- [DWD-Integration](https://www.home-assistant.io/integrations/dwd_weather_warnings/) oder [DWD MOSMIX](https://github.com/FL550/dwd_weather) (liefert stündliche Niederschlags- und Strahlungsprognosen als `sensor.*` mit `data`-Attribut)
- Lokale Regenstation, z. B. Netatmo (liefert aktuellen Regen, letzte Stunde, Tageswert)
- Außentemperatur- und Luftfeuchtigkeitssensor
- Optionale: Helligkeitssensor (Igelschutz), PV-Leistungssensor (Strahlungs-Fallback)

---

## Installation

### HACS (empfohlen)

1. HACS öffnen → **Integrationen** → ⋮ → *Benutzerdefinierte Repositories*
2. URL: `https://github.com/placeholder/smart_mow`, Typ: **Integration**
3. *Smart Mow* suchen und installieren
4. Home Assistant neu starten
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Smart Mow**

### Manuell

```bash
cp -r custom_components/smart_mow /config/custom_components/
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

### Schritt 2 — DWD Wetterdaten

| Feld | Beschreibung |
|------|-------------|
| DWD Wetter-Entität | `weather.*` — Fallback für Temp/Feuchte |
| DWD Sonneneinstrahlung | `sensor.*` in W/m², mit `data`-Attribut (optional, aber empfohlen) |
| DWD Niederschlag | `sensor.*` in mm/h, mit `data`-Attribut (Stunden-Prognose) |
| DWD Wind | `sensor.*` in km/h (optional, verbessert Trocknung) |

> **Wichtig:** Die DWD-Sensoren müssen ein `data`-Attribut mit Listeneinträgen `{"datetime": "...", "value": ...}` haben. Dies liefert z. B. die [custom_component dwd_weather](https://github.com/FL550/dwd_weather).

### Schritt 3 — Regensensoren

| Feld | Beschreibung |
|------|-------------|
| Regenmesser aktuell | Momentanwert in mm |
| Regen letzte Stunde | Nativer 1h-Wert des Sensors (kein eigener Buffer nötig) |
| Regen heute gesamt | `total_increasing` seit Mitternacht — für Nachtregen-Erkennung |

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

## Backtest-Tool

Das Skript `backtest_smart_mow.py` simuliert die Algorithmus-Logik mit historischen HA-Sensordaten.

### Verwendung

```bash
# Simulation mit exportierter CSV und DWD MOSMIX Download
python3 backtest_smart_mow.py --input smart_mow_backtest.csv

# Mit angepassten Parametern
python3 backtest_smart_mow.py \
  --input smart_mow_backtest.csv \
  --thresh-wetness 25 \
  --target-daily-h 2.5 \
  --mow-start 09:00 \
  --mow-end 19:00 \
  --output-html mein_backtest.html

# Ohne MOSMIX (nur CSV-Daten)
python3 backtest_smart_mow.py --input data.csv --no-mosmix

# Zeitraum einschränken
python3 backtest_smart_mow.py --input data.csv --start 2026-05-01 --end 2026-05-10
```

### Ausgaben

- **`backtest_result.csv`** — Alle berechneten Werte in 5-Minuten-Auflösung
- **Konsole** — Tagesübersicht: Mähstunden, häufigste Sperrgründe, max. Nässe-Score
- **`backtest_result.html`** — Farbige Stundentabelle (im Browser öffnen)
  - 🟢 Grün: Mähen empfohlen (`start_now`)
  - 🟩 Hellgrün: Bedingungen ok (`allowed`)
  - 🟡 Gelb: Zu nass
  - 🔴 Rot: Regen
  - ⬜ Grau: Außerhalb Mähfenster

---

## SQLite-Export-Befehl

Historische Sensordaten aus HA exportieren (via SSH-Addon):

```bash
sqlite3 /config/home-assistant_v2.db -separator "," \
"SELECT m.entity_id,
        s.state,
        datetime(s.last_updated_ts, 'unixepoch', 'localtime') AS ts
 FROM states s
 JOIN states_meta m ON s.metadata_id = m.metadata_id
 WHERE m.entity_id IN (
   'sensor.weather_station_regenmesser_niederschlag',
   'sensor.weather_station_regenmesser_niederschlag_letzte_stunde',
   'sensor.weather_station_regenmesser_niederschlag_heute',
   'sensor.dwd_meine_sonneneinstrahlung',
   'sensor.dwd_meine_niederschlag',
   'sensor.boiler_outside_temperature',
   'sensor.garage_temperatur_luftfeuchtigkeit',
   'sensor.helligkeit_beleuchtungsstarke',
   'sensor.solaredge_ac_power'
 )
 AND s.last_updated_ts >= unixepoch('now', '-10 days')
 AND s.state NOT IN ('unknown','unavailable','none')
 ORDER BY m.entity_id, s.last_updated_ts ASC;" \
> /config/www/smart_mow_backtest.csv
```

Danach abrufbar unter:
`http://<HA-IP>:8123/local/smart_mow_backtest.csv`

---

## Troubleshooting

### Integration lädt nicht

- Prüfe `homeassistant.log` auf Fehler mit `smart_mow`
- Stelle sicher, dass der Ordner `custom_components/smart_mow/` im HA-Config-Verzeichnis liegt (nicht in einem Unterordner)

### Entities bleiben `unavailable`

- Die Integration benötigt einen erfolgreichen ersten Coordinator-Update. Prüfe ob alle konfigurierten Entity-IDs in HA existieren.
- Bei DWD: Das `data`-Attribut muss eine Liste sein. Prüfe mit Entwicklertools → Zustände.

### Wetness Score immer 0

- Der 12h-Buffer füllt sich erst nach 12h Laufzeit komplett. Anfangs sind die Werte normal niedrig.
- Prüfe ob `sensor.dwd_meine_niederschlag` einen validen State liefert.

### DWD Prognose fehlt

- Stelle sicher, dass der DWD-Sensor ein `data`-Attribut hat (nicht alle DWD-Integrationen liefern dies).
- Die [dwd_weather](https://github.com/FL550/dwd_weather) custom component ist kompatibel.

### Mähdauer zählt nicht

- Die Integration trackt den `lawn_mower` Entity-State `mowing`. Prüfe ob dein Mäher diesen State korrekt setzt.
- Bei Neustart von HA: Die Zählung wird aus dem HA-Storage wiederhergestellt.

### Options Flow zeigt keine Änderungen

- Nach Speichern der Optionen wird die Integration automatisch neu geladen. Warte ca. 10 Sekunden.
