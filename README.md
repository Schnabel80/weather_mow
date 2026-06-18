<p align="center">
  <img src="custom_components/weather_mow/logo.png" alt="WeatherMow Logo" width="160">
</p>

# WeatherMow — Wetterabhängige Mähroboter-Steuerung

[![CI](https://github.com/Schnabel80/weather_mow/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/Schnabel80/weather_mow/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/Schnabel80/weather_mow/branch/develop/graph/badge.svg)](https://codecov.io/gh/Schnabel80/weather_mow)

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
7. [Rasenfeuchtigkeit erklärt](#rasenfeuchtigkeit-erklärt)
8. [Wachstumsmodell erklärt](#wachstumsmodell-erklärt)
9. [Entscheidungslogik](#entscheidungslogik)
10. [Automatisierungs-Beispiele](#automatisierungs-beispiele)
11. [Troubleshooting](#troubleshooting)
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
| Tagesziel Mähstunden | 2,5 h | Angestrebte tägliche Mähzeit |
| Dauer eines vollen Zyklus | 2,0 h | Für Notmäh-Berechnung und GDD-Reset |
| Puffer vor Fenster-Ende | 2,0 h | Mäher soll bis `Fenster-Ende − Puffer` fertig sein |
| Max. Regenprognose heute | 5,0 mm | Mähen gesperrt wenn noch mehr Regen erwartet wird |
| Regenprognose morgen für Notmähen | 8,0 mm | Löst Notmähen aus wenn Tagesziel bereits erreicht |
| Mindestzeit für Notmähen | 2,0 h | Notmähen nur wenn noch genug Zeit im Fenster bleibt |
| Tau-Temperaturoffset | 3,0 °C | Tau gilt als verdunstet bei Temp > Taupunkt + Offset |
| Mindeststunden Sonne für Tau-Freigabe | 1,0 h | Stunden ≥ 200 W/m² vor Tau-Clearance (≥ 500 W/m²: sofort) |
| Max. Rasenwuchs | 20 mm | Ab diesem GDD-Wuchs gilt maximale Wuchs-Dringlichkeit |
| Letztes Düngungsdatum | — | Optional — erhöht Wuchsfaktor für 21 Tage um 50 % |
| Morgen-Startverzögerung | 0 min | Verzögerung nach Tau-Freigabe (0 = deaktiviert) |
| Autostart verhindern | an | Unerlaubte Mäherstarts außerhalb des Fensters stoppen |

### Dashboard-Einstellungen (jederzeit anpassbar)

Diese Parameter sind als **Number- / Time-Entitäten** direkt im HA-Dashboard verstellbar — kein Umweg über den Einrichtungsassistenten nötig.

| Entität | Default | Beschreibung |
|---------|---------|-------------|
| **Erlaubte Restfeuchte** (`number.*_erlaubte_restfeuchte`) | 0,5 mm | Mähen gesperrt wenn `wetness_mm` diesen Wert überschreitet |
| **Feuchte-Schwelle bei Dringlichkeit** (`number.*_feuchte_schwelle_bei_dringlichkeit`) | 1,5 mm | Tolerantere Schwelle bei Zeitdruck / Notmähen |
| **Max. Mähtemperatur** (`number.*_max_mahtemperatur`) | 35 °C | Ab diesem Wert: absolutes Mähverbot (`too_hot`). Ab max − 5 °C sinkt Priorität linear → verschiebt Mähstarts in kühle Stunden. 0 = deaktiviert |
| **Rasen-Sonneneffizienz** (`number.*_rasen_sonneneffizienz`) | 0,7 | Anteil der Strahlung der am Rasen ankommt (1,0 = kein Schatten, 0,3 = stark verschattet) |
| **Sonne erreicht Rasen ab** (`time.*_sonne_erreicht_rasen_ab`) | 00:00 | Vor dieser Uhrzeit zählt Strahlung nicht für Trocknung (Morgenschatten) |

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
| `_wetness` | mm | Oberflächenfeuchte des Rasens (Penman-Monteith, 0–2 mm) |
| `_priority` | — | Mäh-Priorität 0–100 |
| `_block_reason` | — | Aktueller Sperrgrund (`too_wet`, `rain_today`, `too_hot`, …) |
| `_duration_today` | h | Mähstunden heute |
| `_duration_avg_3d` | h | Ø Mähstunden letzte 3 Tage |
| `_grass_growth` | mm | Akkumulierter GDD-Wuchs seit letzter Session |
| `_next_mow_expected` | — | Voraussichtlicher nächster Mähstart |
| `_rain_last_1h` | mm | Regen letzte Stunde |
| `_rain_weighted_12h` | mm | Gewichteter 12h-Regenpuffer |
| `_rain_today_total` | mm | Regen heute gesamt (seit Mitternacht) |
| `_rain_today_remaining` | mm | Regenprognose für verbleibenden Tag |
| `_rain_tomorrow` | mm | Regenprognose morgen gesamt |
| `_solar_peak` | W/m² | Kalibrierter Spitzenwert (Solar-Tracker) |
| `_dew_point` | °C | Berechneter Taupunkt |

### Binärsensoren

| Entity-Suffix | Klasse | Beschreibung |
|--------------|--------|-------------|
| `_allowed` | — | `on` = alle Bedingungen erfüllt, Mähen möglich |
| `_start_now` | — | `on` = Mähen **empfohlen** (Priorität ≥ 40) |
| `_stop_now` | — | `on` = Mäher soll sofort stoppen |
| `_emergency_mow` | — | `on` = Notmähen aktiv |
| `_raining` | moisture | `on` = Regen erkannt (Sensor oder Wetter-Condition) |
| `_dew_present` | — | `on` = Morgentau noch nicht verdunstet |
| `_brightness_ok` | light | `on` = ausreichend hell für Igelschutz |
| `_auto_resume_blocked` | problem | `on` = unerlaubter Autostart erkannt und blockiert |

### Schalter

| Entity-Suffix | Default | Beschreibung |
|--------------|---------|-------------|
| `_enabled` | an | Hauptschalter — bei `off` kein Mähen empfohlen |
| `_emergency_mow` | aus | Notmähen manuell erzwingen |
| `_debug_log` | aus | Debug-CSV schreiben (`/config/weather_mow_debug_*.csv`) |

### Schaltflächen

| Entity-Suffix | Beschreibung |
|--------------|-------------|
| `_bewasserung_buchen_2_mm` | Bucht 2 mm Bewässerung (erhöht `wetness_mm` sofort) |
| `_nasse_auf_0_zurucksetzen` | Setzt `wetness_mm` auf 0 zurück |

### Datum

| Entity-Suffix | Beschreibung |
|--------------|-------------|
| `_last_fertilization` | Letztes Düngungsdatum — aktiviert 21-Tage-Wuchsboost (+50 %) |

---

## Rasenfeuchtigkeit erklärt

`sensor.[name]_wetness` ist ein **physikalischer Feuchtewert in mm** (0–2 mm), kein Punktescore. Er repräsentiert die Oberflächenfeuchtigkeit des Rasens nach dem Penman-Monteith-Verdunstungsmodell.

### Berechnung

Alle 5 Minuten wird aktualisiert:

```
Δwetness = Kondensation(Temperatur, Luftfeuchtigkeit)
         − Penman-Trocknung(Einstrahlung, VPD, Windgeschwindigkeit)

wetness_mm = clamp(wetness_mm + Δwetness, 0, 2,0 mm)
```

- **Kondensation**: Wenn die Luftfeuchtigkeit hoch ist (Taupunktnähe), steigt `wetness_mm` — Tau oder Niesel wird berücksichtigt.
- **Penman-Trocknung**: Sonne, Wind und Sättigungsdefizit (VPD) trocknen den Rasen. Bei starker Sonne und Wind sinkt `wetness_mm` schnell.
- **Schattenkorrektur**: Vor der in `time.[name]_sonne_erreicht_rasen_ab` konfigurierten Uhrzeit zählt Strahlung nicht für die Trocknung. `number.[name]_rasen_sonneneffizienz` (0,1–1,0) skaliert die effektive Strahlung dauerhaft — für verschattete Lagen.
- **Regen**: Jeder gemessene Niederschlag erhöht `wetness_mm` direkt.

### Schwellwerte

| Schwellwert | Entity | Default | Bedeutung |
|---|---|---|---|
| Normale Feuchte-Grenze | `number.[name]_erlaubte_restfeuchte` | 0,5 mm | Mähen gesperrt wenn `wetness_mm` diesen Wert überschreitet |
| Dringlichkeitsschwelle | `number.[name]_feuchte_schwelle_bei_dringlichkeit` | 1,5 mm | Tolerantere Grenze bei Zeitdruck (letztes Stundenfenster) oder Notmähen |

### Adaptiver Schwellwert

Wenn **kein Regen** in den nächsten Stunden prognostiziert wird, sinkt die effektive Sperrschwelle um 0,3 mm (FORECAST_DISCOUNT) — der Mäher fährt etwas früher los wenn der Rasen ohnehin weitertrocknen wird. Nach Unterschreiten der Schwelle gilt eine 30-minütige Gnadenfrist (`waiting_for_favorable`).

### Beispiel

5 mm Nachtregen, 08:00 Uhr, noch keine Sonne → `wetness_mm` ≈ 1,5 mm (über Schwellwert → `too_wet`). Um 11:00 Uhr mit voller Sonne → `wetness_mm` ≈ 0,3 mm (unter 0,5 mm → Mähen erlaubt).

---

## Wachstumsmodell erklärt

Der Sensor `sensor.[name]_grass_growth_mm` zeigt **wie viel der Rasen seit dem letzten Mähvorgang gewachsen ist** — kein Tageswert, sondern ein laufender Akkumulator.

### Berechnung

Das Modell nutzt **GDD (Growing Degree Days)** — ein in der Agronomie etabliertes Maß für pflanzliches Wachstum. Alle 5 Minuten wird addiert:

```
GDD-Schritt = max(0, Temperatur − 5 °C) / 288
Wachstum mm = GDD-Akkumulator × 0,8
```

Die Basistemperatur von **5 °C** entspricht der Mindesttemperatur ab der Gras wächst. Unterhalb von 5 °C: kein Wachstum. Der Divisor 288 normiert auf einen 24h-Tag (288 × 5 min = 24 h).

**Beispiel:** 18 °C Tagesdurchschnitt → 13 GDD/Tag × 0,8 = **~10 mm Wachstum pro Tag** bei warmem Wetter.

### Reset

Der Akkumulator wird auf **0 mm zurückgesetzt** sobald der Mäher einen Mähvorgang beendet. Nach dem Mähen startet das Wachstum von vorne.

### Einfluss auf die Priorität

Wachstum erhöht die Mäh-Dringlichkeit — aber erst ab einem gewissen Schwellwert:

| Angesammeltes Wachstum | Dringlichkeits-Bonus |
|---|---|
| 0–6 mm (unter 30 % des konfigurierten Max) | **+0 Punkte** — wird ignoriert |
| 6–20 mm (Standard-Konfiguration) | Linear **+0 bis +15 Punkte** |
| ≥ 20 mm | **+15 Punkte** (Maximum) |

Der Max-Schwellwert (Standard: 20 mm) ist in den Integrationseinstellungen anpassbar — bei schnell wachsenden Rasensorten empfiehlt sich ein niedrigerer Wert (z. B. 15 mm).

### Dünger-Effekt

Wenn du das Dünge-Datum im Dashboard einträgst (`date.[name]_last_fertilization`), wird das Wachstumsmodell **21 Tage lang um 50 % beschleunigt**:

```
GDD-Schritt × 1,5  (während der Dünger-Wirkungszeit)
```

Das entspricht der realen Wirkung von Rasendünger — der Mäher fährt nach dem Düngen spürbar häufiger, weil die Wachstumsrate steigt und die Dringlichkeit schneller ansteigt.

---

## Entscheidungslogik

`binary_sensor.[name]_allowed` und `binary_sensor.[name]_start_now` folgen dieser Reihenfolge. Der aktuelle Sperrgrund steht in `sensor.[name]_block_reason`.

| Priorität | Bedingung | block_reason |
|---|---|---|
| 1 | Integration deaktiviert (Switch aus) | `disabled` |
| 2 | Außerhalb des Mähfensters (z. B. vor 08:00 oder nach 20:00) | `outside_time_window` |
| 3 | Zu dunkel — Helligkeit unter Mindestschwelle (Igelschutz) | `too_dark_hedgehog` |
| 4 | Akku unter Mindestand | `battery_low` |
| 5 | Temperatur ≥ Max-Mähtemperatur (`number.[name]_max_mahtemperatur`) | `too_hot` |
| 6 | Regenprognose heute ≥ Schwellwert | `rain_today` |
| 7 | Tagesziel erreicht **und** Regen morgen ≥ Schwellwert → **Notmähen** wenn noch Zeit im Fenster | `emergency_mow_tomorrow_rain` |
| 8 | Tagesziel bereits erreicht | `daily_target_reached` |
| 9 | `wetness_mm` > Sperrschwelle | `too_wet` |
| 9b | `wetness_mm` > adaptiver Schwellwert **oder** Gnadenfrist läuft | `waiting_for_favorable` |
| — | **Mäher ist gerade aktiv** (Display-Override) | `mowing_active` |
| ✅ | Alle Bedingungen erfüllt | `mowing_allowed` |

**`start_now = True`** wenn `mowing_allowed` und Priorität ≥ 40. Ab Priorität ≥ 65 wird auch die konfigurierte Startverzögerung überbrückt.

### Priorität (0–100)

Die Mäh-Dringlichkeit kombiniert mehrere Faktoren:

- **Tagesdefizit**: Abstand zwischen bisheriger und angestrebter Tagesdauer (Haupttreiber)
- **Tage seit letztem Mähen**: steigt nach Regentagen an
- **3-Tage-Schnitt vs. Tagesziel**: erkennt ob der Mäher strukturell zu wenig mäht
- **Wachstumsmodell**: GDD-akkumuliertes Rasenwachstum erhöht Dringlichkeit ab 6 mm
- **Hitzefaktor** (ab v0.4.1): Ab `max_mow_temp − 5 °C` sinkt die Priorität linear auf 0 bei `max_mow_temp` — der Mäher bevorzugt automatisch kühlere Morgen- und Abendstunden

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

## Schatten am Rasen und Bewässerung verstehen

WeatherMow rechnet die Trocknung deines Rasens aus der gemessenen
Sonnenstrahlung der Wetterstation. Wenn dein Rasen größtenteils im Schatten
liegt, kommt am Gras viel weniger Sonne an als am Wetterstandort.
Zwei Entitäten korrigieren das:

### `number.<name>_lawn_sun_efficiency` — Rasen-Sonneneffizienz

Slider 0.1 – 1.0 (Default **0.7**). Anteil der gemessenen Standort-
Sonnenstrahlung, der tatsächlich auf den Rasen fällt.

| Wert | Bedeutung |
|------|-----------|
| 1.0  | Freier Rasen, voller Himmel über dem Rasen |
| 0.7  | Leichter bis mittlerer Schatten (Default — typischer Hausgarten) |
| 0.5  | Rasen ist die Hälfte des Tages im Schatten |
| 0.3  | Stark verschatteter Garten, Bäume / Häuser an mehreren Seiten |

Niedrigere Werte → längere geschätzte Trocknung nach Regen oder Bewässerung
→ Mäher wartet morgens länger, bis das Gras wirklich abgetrocknet ist.

### `time.<name>_lawn_sun_from` — Sonne erreicht Rasen ab

Lokale Uhrzeit (Default **00:00**). Vor dieser Uhrzeit zählt die
Sonnenstrahlung NICHT für die Trocknung — typisch wenn östlich vom Rasen
Bäume, Häuser oder eine Mauer stehen und der Rasen erst spät am Vormittag
direktes Sonnenlicht bekommt.

| Beispiel | Wirkung |
|----------|---------|
| 00:00 | Standard: Sonne zählt ab Tagesanbruch (keine Schatten-Korrektur) |
| 09:00 | Erste Stunden Morgenschatten — Trocknung beginnt erst um 09:00 |
| 11:00 | Starker Morgenschatten — Sonne erreicht den Rasen erst zur Mittagszeit |

### Bewässerung

Wenn du den `switch.<name>_irrigation_active` einschaltest (oder per
Automation für die Dauer deiner Bewässerung an lässt), erhöht WeatherMow den
Nässe-Score um bis zu 70 Punkte. Dieser Boost wird **nicht mehr** linear
über die Zeit abgebaut, sondern folgt demselben Trocknungs-Modell wie nach
echtem Regen:

- Im Schatten / nachts: Boost bleibt erhalten — der Rasen trocknet nicht.
- Bei voller Sonne und Effizienz 1.0: Boost zerfällt in ca. 3 h auf 0.
- Bei Effizienz 0.5: Boost zerfällt entsprechend langsamer.

→ Wenn du abends bewässerst, ist der Mäher am nächsten Morgen nicht mehr
   bereit, bevor die Sonne wirklich auf den Rasen scheint.

> **Hinweis:** Bei dauerhaft sehr starkem Schatten (Effizienz < 0.3) kann
> der Bewässerungs-Boost mehrere Tage halten, weil die Verdunstung
> ausschließlich an die direkte Sonneneinstrahlung gekoppelt ist. Wind-
> und Temperatur-getriebene Verdunstung sind in dieser Version (v0.3.1)
> noch nicht im Bewässerungs-Modell enthalten.

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

## Deinstallation

1. **Integration entfernen:** Einstellungen → Geräte & Dienste → WeatherMow → drei Punkte → Löschen
2. **Dateien entfernen:** Den Ordner `custom_components/weather_mow/` aus dem HA-Konfigurationsverzeichnis löschen
3. **HACS:** Falls über HACS installiert, unter HACS → Integrationen → WeatherMow → Deinstallieren

Alle gespeicherten Zustände (Nässewert, Mähdauer, etc.) werden beim Entfernen der Integration automatisch bereinigt.

---

## Changelog

### 0.4.3 *(Stable)*

Stabile Veröffentlichung der 0.4.3-Reihe — fasst alle Beta-Änderungen zusammen:

- **Sensoren ohne Neuanlage änderbar (Issue #7):** Regen-/Wetterquellen lassen sich über „Konfigurieren" nachträglich anpassen — kein Löschen & Neuanlegen mehr.
- **Integrations-Filter entfernt (Issues #7/#11):** In den Stationsschritten (Ecowitt/Netatmo) sind jetzt **alle** passenden `sensor`/`binary_sensor` wählbar — auch selbst erstellte Template-/Helper-Sensoren (z. B. ein eigener „Es-regnet"-Detektor).
- **Nässe-Persistenz bei Neustart** + **Mähfenster als harte Stop-Grenze:** abendliches Eigen-Fortsetzen der Mäher-Firmware löst jetzt `stop_now` aus.
- **Nächtliche Wind-Trocknung gedämpft:** der aerodynamische Trocknungsanteil wird mit dem effektiven Solarfaktor skaliert — kein fälschliches Leertrocknen bei Wind ohne Sonne.
- **Regen-Config vereinfacht (Issues #9/#10):** nur noch **eine** Regenquelle nötig; Stunden-/Tageswerte berechnet die Integration aus dem 12h-Puffer. Automatische Migration bestehender Einträge (Config v3→v4).

### 0.4.3b4 *(Developer Beta)*

- **Regen-Config vereinfacht (Issues #9/#10)** — die Felder „Regen letzte Stunde" und „Tagesregen gesamt" entfallen. Es genügt **eine** Regenquelle: „Regensensor (Hauptquelle)" + Typ. Tagesregen und Stundenwert berechnet die Integration aus dem internen 12h-Puffer — niemand muss mehr denselben Sensor doppelt eintragen. Das Hauptfeld beschreibt jetzt klar, *was der Sensor liefern muss* (Regenrate mm/h, Menge pro Intervall, oder stetig steigender Zähler). Bestehende Einträge werden automatisch migriert (Config v3→v4).

### 0.4.3b3 *(Developer Beta)*

- **Fix: Nachts/dämmerig trocknet der Rasen nicht mehr durch Wind leer** — der aerodynamische (wind-getriebene) Anteil des Trocknungsmodells wird jetzt mit dem effektiven Solarfaktor gedämpft. Physikalischer Hintergrund: nächtliche Verdunstung ist energielimitiert — ohne Sonnenstrahlung treibt nichts die Verdunstung an. Bei voller Sonne bleibt die Trocknung unverändert, bei tiefer/keiner Sonne (Spätnachmittag → Nacht → früher Morgen) bleibt ein Floor von 15 % übrig (FAO-56-nahe Nacht-ET). Die Übergänge sind glatt (kein Tag/Nacht-Sprung in der Dämmerung). Beobachtet 2026-06-14/15: ~2,2 mm Regen am Vortag, Rasen morgens real noch feucht — das Modell hatte ihn durch nächtlichen Wind fälschlich auf 0,0 mm getrocknet und Mähen freigegeben.

### 0.4.3b2 *(Developer Beta)*

- **Fix: HA-Neustart löscht die Rasennässe nicht mehr** — die Plausibilitäts-Kappung beim Laden begrenzte den gespeicherten Wert fälschlich auf „Regen seit letztem Speichern" (≈ Restart-Dauer) und nullte damit bei nassem Rasen gültigen Zustand. Gespeicherte Nässe bleibt jetzt erhalten (physikalischer Bereich 0–2 mm).
- **Fix: Mähfenster ist jetzt eine harte Grenze** — setzt die Mäher-Firmware nach Fensterende selbst fort (z. B. abends im Dunkeln), greift jetzt `stop_now` und der Auto-Resume-Schutz. Manuelles Mähen außerhalb des Fensters: Hauptschalter (`enabled`) ausschalten, dann greift die Integration nicht ein.
- **Fix: Auto-Resume-Schutz kennt den `raining`-Sperrgrund** — Regression aus 0.4.2rc2: Mähstarts während Regen wurden vom Schutz nicht mehr erkannt, weil `raining` vor `too_wet` greift.

### 0.4.3b1 *(Developer Beta)*

- **Neu (Issue #7): Alle Sensoren über den Konfigurieren-Button änderbar** — der Zahnrad-Button zeigt jetzt ein Menü: „Mähzeiten & Schwellwerte" und „Geräte & Sensoren ändern". Letzteres durchläuft alle Einrichtungsschritte mit vorausgefüllten Werten — kein Löschen/Neuanlegen der Instanz mehr nötig.
- **Fix (Issue #7): Ecowitt-/Netatmo-Sensorauswahl nicht mehr auf die Integration gefiltert** — Stationen, die z. B. via ecowitt2mqtt (MQTT) eingebunden sind, sind jetzt auswählbar.
- Intern: gemeinsame Sensor-Schritte als Mixin (Ersteinrichtung, „Neu konfigurieren", Options-Flow); Test erzwingt Synchronität der config-/options-Übersetzungen.

### 0.4.2 *(Stable)*

Stabile Veröffentlichung der 0.4.2-Reihe — fasst alle Beta-/RC-Änderungen zusammen:

- **Mäh-Status:** neuer Sperrgrund `mowing_active`; `next_mow_expected = max(Rasen trocken, Akku geladen)`
- **Adaptive Laderaten-Erkennung:** lernt die Laderate (%/min) aus Ladevorgängen, robust gegen Sensorrauschen (Peak-Tracking) und Sensorausfälle; Akku-Vollschwelle 98 % statt exakt 100 %
- **Kritischer Fix:** `start_now` nie mehr bei aktivem `stop_now` — Regen ist jetzt eigenes Entscheidungs-Gate (`block_reason: raining`)
- **Vollständige Übersetzungen:** alle Entitäten und `block_reason`-States (ENUM-Sensor) in Deutsch und Englisch

### 0.4.2rc2 *(Release Candidate)*

- **Fix (kritisch): `start_now` nie mehr bei aktivem `stop_now`** — meldete die Wetterstation Regenbeginn, war `stop_now = on`, aber `start_now` konnte gleichzeitig `on` sein (Rasen noch unter der Nässe-Schwelle) → Mäher startete in den Regen. Regen ist jetzt ein eigenes Entscheidungs-Gate (`block_reason: raining`, blockiert auch Notmähen), zusätzlich erzwingt eine Invariante `stop_now ⟹ kein start_now` für alle Stop-Quellen (auch Bewässerung).
- **Neu: `block_reason`-State `raining`** („Es regnet" / „Raining") in beiden Sprachen.

### 0.4.2rc1 *(Release Candidate)*

- **Fix: Akku-Vollschwelle jetzt 98 % statt exakt 100 %** (`CHARGE_FULL_PCT`) — Mäher-Firmwares, die nie exakt 100 % melden, blockierten Starts sonst dauerhaft. Gilt für Start-Gate, Ladezeit-Prognose und (gecappt) auch für `min_battery_pct = 100` im Zeitdruck-Pfad.
- **Fix: Laderaten-Lernen ignoriert veraltete Akku-Werte** — fällt der Akkusensor aus (Fallback 100 %), wird die laufende Lade-Messung verworfen statt eine Phantom-Rate zu lernen.
- **Verbessert: Ladephasen-Erkennung mit Peak-Tracking** — Sensorrauschen (Dips ≤ 2 %) beendet die Phase nicht mehr; gemessen wird Start → Peak, sodass Idle-Entladung am Phasenende die gelernte Rate nicht verwässert.
- **Fix: `mowing_active` maskiert `disabled` nicht mehr** — bei deaktivierter Integration zeigt `block_reason` weiterhin `disabled`, auch wenn der Mäher manuell mäht.
- **Verbessert: `block_reason` ist jetzt ENUM-Sensor** — mit fester Options-Liste (`BLOCK_REASONS`); kategorische Historie und garantiert übersetzte States.

### 0.4.2b1 *(Developer Beta)*

- **Neu: `mowing_active` Sperrgrund** — wenn der Mäher gerade mäht und kein Stop-Signal aktiv ist, zeigt `block_reason` nun `mowing_active` statt eines irreführenden Sperrgrundes (z. B. `battery_low`). Die Start-/Stop-Logik bleibt unverändert.
- **Neu: Adaptive Ladraten-Erkennung** — die Integration lernt die Laderate des Mähers (in %/min) automatisch aus beobachteten Ladevorgängen (EMA, α = 0,2). Startrate 1,0 %/min; erste Messung überschreibt den Startwert vollständig (α = 1). Die Laderate fließt in `next_mow_expected` ein: der nächste Mähstart ist `max(Rasen trocken, Akku geladen)`.
- **Neu: `next_mow = max(trocken, geladen)`** — der prognostizierte nächste Mähstart berücksichtigt jetzt beide Bedingungen: Rasenfeuchtigkeit und Akkustand. Der spätest-eintretende Zeitpunkt bestimmt den Sensor-Wert.
- **Neu: Adaptive Schwelle in `_forecast_next_mow`** — die Feuchte-Simulation spiegelt die echte Entscheidungslogik: Zeitdruck-Fenster → Dringlichkeitsschwelle; Regenprognose → normale Schwelle; sonst → Discount + Gnadenfrist.
- **Vollständige Übersetzungen** — alle Entities nutzen `translation_key`; alle 11 `block_reason`-States und sämtliche Entity-Namen sind in Deutsch und Englisch übersetzt.
- **Neu: Debug-CSV-Spalte `charge_rate_pct_per_min`** — aktuelle gelernte Laderate in der Debug-CSV sichtbar.

### 0.4.1

- **Fix: `next_mow_expected = unbekannt`** — Ursache war ein verwaistes `precip_forecast_entity_id`-Feld in der gespeicherten Konfiguration (hinterlassen von der v1→v2-Migration). Dieses Feld zwang die Integration auf den DWD-Sensor-Pfad ohne Wind- und Strahlungsdaten, was die Prognose komplett blockierte. Migration v2→v3 entfernt das Feld für alle bestehenden Installationen.
- **Neu: Hitze-Sperre (`max_mow_temp_c`)** — neue Number-Entity `number.[name]_max_mahtemperatur` (Default 35 °C). Bei Temperatur ≥ Schwellwert: absolutes Mähverbot (`too_hot`). Bei Temperatur ≥ Schwellwert − 5 °C: Priorität sinkt linear auf 0 — der Mäher bevorzugt automatisch kühlere Tagesstunden.
- **Config-Version: 3** — `config_flow.py` und `__init__.py` auf VERSION = 3 angehoben.

### 0.4.0

- **Neu: Penman-Monteith Feuchtemodell** — `wetness_mm` (0–2 mm) ersetzt den alten Score-basierten Ansatz (0–100+). Physikalisch fundierte Berechnung: Kondensation (Taupunktnähe) minus Verdunstung (Sonne × VPD × Wind). Alle Schwellwerte jetzt in mm statt Punkten.
- **Neu: Stationszentrierte Konfiguration** — 6-Schritt Setup-Wizard mit Auswahl des Regensenor-Typs (Ecowitt / Netatmo / Sonstige / Keine). Der bisherige DWD-zentrierte Aufbau ist in einen generischen `other`-Pfad übergegangen.
- **Neu: Regen-Normalisierung (`rain_input.py`)** — drei Modi: `CUMULATIVE` (Ecowitt, mit Mitternachts-Reset-Erkennung), `INTERVAL` (Netatmo, mit Deduplizierung), `RATE` (mm/h → Slot-mm). Warmer Neustart aus gespeichertem Puffer.
- **Neu: Adaptiver Feuchte-Schwellwert + Gnadenfrist** — wenn kein Regen prognostiziert, sinkt die effektive Sperrschwelle um 0,3 mm (`FORECAST_DISCOUNT`). Nach Unterschreiten: 30-minütige Gnadenfrist (`waiting_for_favorable`). Beide Werte überstehen HA-Neustarts.
- **Neu: Bewässerungs-Buchung** — Button `_bewasserung_buchen_2_mm` erhöht `wetness_mm` sofort um 2 mm; `_nasse_auf_0_zurucksetzen` setzt auf 0.
- **Neu: Schattenkorrektur für Feuchtemodell** — `time.[name]_sonne_erreicht_rasen_ab` und `number.[name]_rasen_sonneneffizienz` steuern, wie viel Strahlung am Rasen ankommt.
- **Fix: `_prev_rain_today` Persistenz** — nach Coordinator-Neustart wurde `_prev_rain_today` auf 0 zurückgesetzt, was zu einem falschen Regen-Delta im ersten Update führte (`too_wet`-Spike). Jetzt persistiert und mit Upgrade-Pfad (Schätzung aus Puffer wenn Schlüssel fehlt).
- **Config-Version: 2** — Migration v1→v2 benennt DWD-spezifische Konfig-Schlüssel in generische Namen um.

### 0.3.0b9 *(Developer Beta)*

- **Fix: `next_mow_expected` zeigt nach erreichtem Tagesziel immer „in einer Stunde"** — `_forecast_next_mow` kannte das Tagesziel nicht und startete die 48h-Suche immer bei `now + 1h`. Da nach einem erfolgreichen Mähtag die Bedingungen gut sind, wurde sofort der erste Slot (die nächste volle Stunde) zurückgegeben. Fix: `duration_today_h` wird jetzt an die Funktion übergeben. Im Loop werden alle verbleibenden Stunden von **heute** übersprungen, sobald `duration_today_h ≥ target_h`. Der Forecast sucht dann ab dem nächsten Morgen — und gibt z. B. `morgen 08:00` zurück.

### 0.3.0b8 *(Developer Beta — Hotfix)*

- **Fix: `TypeError: a coroutine was expected, got <Future>`** — `async_create_task()` erwartet eine Coroutine, nicht ein `asyncio.Future`. `hass.async_add_executor_job()` gibt aber ein Future zurück. Der fehlerhafte Wrapper `async_create_task(async_add_executor_job(...))` ließ die gesamte Integration nach dem ersten erfolgreichen Poll permanent auf `unavailable` fallen. Fix: `async_create_task`-Wrapper entfernt; `async_add_executor_job` direkt aufrufen (gibt ein Future zurück, das im Hintergrund läuft).

### 0.3.0b7 *(Developer Beta — Code-Review-Fixes)*

- **Fix: Debug-CSV non-blocking** — `_write_debug_csv` wird über `hass.async_add_executor_job` aufgerufen. Bisher wurde File-I/O direkt im Event Loop ausgeführt; auf langsamen Speichermedien (z. B. SD-Karte am Pi) konnte das den Loop blockieren.
- **Fix: Debug-CSV pro Instanz** — Dateiname enthält jetzt die `entry_id` (`weather_mow_debug_<entry_id>.csv`) über den neuen Helper `coordinator.debug_csv_path()`. Bei Mehrfach-Installationen (z. B. zwei Mäher) gehen Zeilen nicht mehr ins selbe File. `diagnostics.py` liest pro Entry den eigenen Pfad ein.
- **Fix: Solar-Peak-Init priorisiert wie zur Laufzeit** — `_init_solar_peak_from_recorder` nutzt jetzt die gleiche Priorisierung wie `_get_radiation()`: lokaler Sensor → DWD → PV. Bisher konnte der Peak gegen DWD kalibriert sein, während die Live-Werte vom lokalen Sensor kamen — Resultat: systematisch zu kleiner `solar_factor`.
- **Cleanup:** ungenutzte Imports entfernt (`CONF_WEATHER_SOURCE`, `WEATHER_SOURCE_OWM`, `DEFAULT_WEATHER_SOURCE`); redundantes `min(1.0, solar_factor)` entfernt (per Konstruktion ≤ 1); robusterer Float-Vergleich für „heute noch nicht gemäht" (`< 1/3600` statt `== 0`); `import csv`/`import os` auf Modulebene.
- **Test:** Docker-HA-Run verifiziert: Diagnostics-Download enthält `entry` / `config` / `data` / `internal` / `debug_csv`; CSV wird unter `weather_mow_debug_<entry_id>.csv` mit 29 Spalten geschrieben; Solar-Peak korrekt aus Recorder restauriert.

### 0.3.0b6 *(Developer Beta)*

- **Fix: Tau-Logik physikalisch korrekt** — bisher wurde `sun_ok` (Sonnenschein ≥ `min_sun_h`) dauerhaft als Bedingung geprüft, auch nach bereits erfolgter Trocknung. Physikalisch falsch: Tau kann nur zurückkommen wenn die Temperatur wieder auf Taupunktnähe fällt — sinkende Abendstrahlung allein genügt nicht. Neue Logik: Vor der ersten Trocknung braucht es `temp_ok AND sun_ok`. Danach (Latch gesetzt) entscheidet nur noch `temp_ok`. Das behebt auch den Abend-Neustart-Fall ohne Recorder-Daten, sofern die Temperatur noch deutlich über dem Taupunkt liegt.

### 0.3.0b5 *(Developer Beta)*

- **Fix: `dew_present` nach Abend-Neustart** — b4 setzte den Tau-Latch nur wenn zum Neustart-Zeitpunkt noch eine aktive Sonnenkette lief. Bei einem Neustart nach Sonnenuntergang (Strahlung bereits &lt; 200 W/m²) fand der Recorder keine aktuelle Kette, obwohl die Sonne tagsüber stundenlang geschienen hatte. Fix: Zweistufige Recorder-Suche — Phase 1 wie bisher (aktuelle Kette), Phase 2 als Fallback: Suche nach vergangener Sonnenperiode ≥ `min_sun_h` und setze Latch wenn gefunden.

### 0.3.0b4 *(Developer Beta)*

- **Fix: `dew_present` nach HA-Neustart fälschlicherweise aktiv** — nach einem Neustart wurde der interne `_dew_cleared_today`-Latch zurückgesetzt. Der Recorder-Restore stellte zwar den Sonnenschein-Startzeitpunkt wieder her, setzte den Latch aber nicht. Folge: Wenn die Sonne in den letzten Stunden schon ≥ `min_sun_h` (Standard: 1 h) ununterbrochen ≥ 200 W/m² gemessen hatte, meldete das System trotzdem `dew_present=True` und blockierte den Mäher. Fix: `_init_sunshine_from_recorder` setzt `_dew_cleared_today=True`, wenn die wiederhergestellte Sonnenschein-Dauer ≥ `min_sun_h`.

### 0.3.0b3 *(Developer Beta)*

- **Fix: `start_now`-Logik überarbeitet (Priorität als Zeitdruck-Gate)** — die Priorität dient jetzt als Warte-Signal bei nicht-idealen Bedingungen, nicht mehr als harte Sperre. Neue Regel: Priority-Gate (≥ 40) gilt solange genug Zeit im Mähfenster ist. Sobald die verbleibende Fensterzeit ≤ 3× der noch benötigten Mähzeit, startet der Mäher unabhängig von der Priorität. Beispiel: noch 0,9 h zu mähen bei 2,5 h Restfenster (2,5 ≤ 0,9×3) → Zeitdruck → sofortiger Start. Morgens bei 12 h Restfenster und 2,5 h Ziel (12 > 7,5) → Priority-Gate bleibt aktiv → wartet auf bessere Bedingungen.

### 0.3.0b2 *(Developer Beta)*

- **Fix: `start_now` feuerte nicht wenn Tagesziel nicht erreicht** *(ersetzt durch 0.3.0b3)*
- **Fix: Abend-Rückfall auf `dew_present=True`** — wenn die Sonne am Nachmittag unter 200 W/m² fiel, wurde der interne Sonnenschein-Zähler zurückgesetzt und das System meldete erneut "Tau vorhanden", obwohl der Rasen seit dem Vormittag trocken war. Neuer Tages-Latch `_dew_cleared_today`: sobald Tau einmal als verdunstet erkannt, bleibt er bis Mitternacht auf False. Reset täglich um 00:00.

### 0.3.0b1 *(Developer Beta)*

- **Fix: Regen-"heute"/"morgen" Grenze war UTC statt Lokalzeit** — `rain_today_remaining` und `rain_tomorrow` verwendeten UTC-Mitternacht als Grenze. Für Deutschland (UTC+2) lag die Grenze 2 Stunden zu spät, was dazu führte, dass Regen um 23:00 Uhr lokal als "morgen" eingestuft wurde. Jetzt wird lokale Mitternacht als Grenze verwendet (gilt für DWD- und OWM-Pfad).
- **Fix: `emergency_mow_active` wurde nicht zurückgesetzt wenn Regenprognose fiel** — das Flag blieb den gesamten Tag auf `True` wenn die Prognose für morgen nachträglich unter den Schwellwert fiel. Jetzt wird es bei jedem Entscheidungszyklus neu bewertet und ggf. auf `False` gesetzt.
- **Fix: OWM Strahlungsschätzung für `next_mow_expected` war ungenau** — die Strahlungsschätzung aus Bewölkungsdaten verwendete bisher die *aktuelle* Sonnenhöhe für alle Prognosestunden. Ein Forecast für 15:00 Uhr, abgerufen um 08:00 Uhr, bekam dadurch eine viel zu geringe Strahlung. Jetzt wird ein Kosinus-Modell verwendet (Maximum 12:00 Uhr lokal, ±6h = 0), das die Tageszeit jeder Prognosestunde korrekt berücksichtigt.
- **Fix: Solar-Peak-Log zeigte neuen statt alten Wert** — der Debug-Log beim Wiederherstellen des Solarpeaks aus dem Recorder zeigte "(was X)" mit dem neuen statt dem alten Wert. Kosmetisch, jetzt korrekt.
- **Fix: Race Condition `_init_duration_from_recorder`** — wenn HA während einer Mähsession neu startete und der Recorder die Session noch als offen zeigte, der Mäher aber bereits gedockt war, wurde `_mow_start_ts` auf die Vergangenheit gesetzt und lief dann unkontrolliert hoch. Jetzt wird der aktuelle Mäherstatus geprüft bevor `_mow_start_ts` gesetzt wird.
- **Fix: `_handle_mower_state_change` ohne `_mow_start_ts`** — wenn der "Mähende"-Event direkt nach einem Neustart eintraf bevor `_mow_start_ts` gesetzt wurde, ging die Sitzungsdauer verloren. Jetzt Fallback auf `old_state.last_updated` als Startzeit.
- **Fix: Auto-Resume-Schutz feuerte bei `outside_time_window` und `daily_target_reached`** — ein Mähstart nach dem Tagesziel (Emergency oder App-Start) oder außerhalb des Fensters wurde als "unerlaubt" gewertet und der Mäher sofort gestoppt. Jetzt greift `stop_now` nur noch bei Wetter-basierten Sperren (`too_wet`, `too_dark_hedgehog`, `dew_present`).
- **Fix: Auto-Resume-Schutz feuerte wenn Haupt-Switch AUS** — bei deaktivierter Integration wurde ein Mähstart trotzdem als unerlaubt erkannt. Jetzt kein Auto-Resume-Schutz wenn der Switch aus ist.
- **Fix: `stop_now` wurde bei deaktiviertem Switch gesendet** — auch wenn die Integration deaktiviert war, sendete sie `stop_now = True` bei Regen. Jetzt kein `stop_now` wenn Switch aus ist.
- **Fix: Akku-Plausibilisierung feuerte auf Mäher-Attribut (falsches Tracking)** — das Mäher-Attribut `battery_level` ist immer als "veraltet" markiert, was bei jedem normalen Standby-Verbrauch einen falschen Mähvorgang eingetragen hat. Plausibilisierung jetzt nur noch bei konfiguriertem dediziertem Akku-Sensor.

### 0.2.6
- **Fix: `sensor.next_mow_expected` zeigte dauerhaft "in 1 Stunde"** — die interne Prognose-Simulation hatte zwei Modellfehler: (1) der Trocknungsterm wurde doppelt abgezogen (einmal im aktuellen Score, nochmal pro Prognosestunde), was den Rasen rechnerisch doppelt so schnell abtrocknen ließ; (2) die `future_score`-Komponente (bevorstehender Regen nächste 3h) fehlte komplett in der Simulation, was die Prognose systematisch zu optimistisch machte.
- **Fix: `binary_sensor.stop_now` hatte kein Symbol** — `mdi:robot-mower-off` existiert nicht im MDI-Iconset, ersetzt durch `mdi:stop-circle`.
- **Doku: Wachstumsmodell erklärt** — neuer README-Abschnitt mit GDD-Formel, Dünger-Effekt (+50 % für 21 Tage) und Einfluss auf die Mäh-Dringlichkeit.

### 0.2.5
- **Neu: Debug-CSV im Diagnostics-Download enthalten** — der JSON-Snapshot (Download Diagnostics) enthält jetzt zusätzlich den vollständigen Inhalt der `weather_mow_debug.csv` als `debug_csv`-Feld. Kein separater Download über den File Editor mehr nötig.

### 0.2.4
- **Neu: Lokaler Strahlungssensor (`local_radiation_entity_id`)** — optionaler Sensor für aktuelle Solarstrahlung in W/m² von einer lokalen Wetterstation (z. B. Ecowitt WS90). Präziser als DWD da direkt am Standort gemessen. Priorität: lokal → DWD → PV → Sonnenstand. Kein Ersatz für den DWD-Strahlungssensor: dieser liefert zusätzlich stündliche Prognose-Daten.

### 0.2.3
- **Fix: Sofortreaktion auf Regen** — bisher reagierte die Integration nur alle 5 Minuten auf Regen (Polling-Intervall). Jetzt werden State-Change-Listener registriert für alle konfigurierten Regenquellen: Weather-Condition (OWM/DWD), Regensensor (mm/h), Regendetektor (binär). Der Mäher stoppt jetzt innerhalb von Sekunden wenn es anfängt zu regnen.

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
