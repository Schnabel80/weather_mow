## 🇩🇪 v0.4.0b1

### DWD-Entkopplung

Alle internen Bezeichnungen wurden von DWD-spezifischen Namen auf generische Namen umgestellt.
Die Integration funktioniert gleichwertig mit OpenWeatherMap, DWD Weather, Met.no oder
jeder anderen HA-weather-Integration.

**Storage-Key Migration (automatisch beim Start):**
- `dwd_weather_entity_id` → `weather_entity_id`
- `dwd_radiation_entity_id` → `radiation_forecast_entity_id`
- `dwd_precip_entity_id` → `precip_forecast_entity_id`
- `dwd_wind_entity_id` → `wind_sensor_entity_id`

Bestehende Konfigurationen werden beim ersten Start automatisch migriert. Kein manueller Eingriff nötig.

### Bugfix: Prognose "Nächstes Mähen erwartet" zu konservativ

Die Prognose-Funktion hat Wind-Trocknung nicht berücksichtigt (`wind_kmh=0` war hardcoded).
Jetzt wird der Wind aus dem Stunden-Forecast der Wetter-Integration gelesen.
Ergebnis: "Nächstes Mähen erwartet" wird deutlich früher und realistischer — insbesondere
nach Bewässerung oder starkem Regen.

### Config Flow: Stationszentrierter Aufbau

Schritt 2 fragt jetzt nur noch die Wetter-Entität ab — kein DWD-spezifisches Feld mehr.
Schritt 3 konfiguriert alle Stations-Sensoren (Regen, Temp, Wind, Strahlung, Helligkeit)
in einem einzigen Schritt je Stationstyp:

| Stationstyp | Felder |
|---|---|
| Ecowitt | Regen (daily/hourly/today), Regenmelder, Temp, Feuchte, Wind, Strahlung, Helligkeit |
| Netatmo | Regen (daily/hourly), Regenmelder, Temp, Feuchte, Helligkeit |
| Andere | Sensortyp-Auswahl + alle obigen Felder |
| Keine Station | Regenmelder, Temp, Feuchte, Helligkeit |

Der separate Temp/Feuchte-Schritt entfällt — alle Sensoren werden in einem Schritt konfiguriert.

---

## 🇬🇧 v0.4.0b1

### DWD Decoupling

All internal naming has been changed from DWD-specific to generic names.
The integration works equally well with OpenWeatherMap, DWD Weather, Met.no, or any
other HA weather integration.

**Storage key migration (automatic on start):**
- `dwd_weather_entity_id` → `weather_entity_id`
- `dwd_radiation_entity_id` → `radiation_forecast_entity_id`
- `dwd_precip_entity_id` → `precip_forecast_entity_id`
- `dwd_wind_entity_id` → `wind_sensor_entity_id`

Existing configurations are migrated automatically on first start. No manual action required.

### Bugfix: "Next mow expected" forecast too conservative

The forecast function ignored wind drying (`wind_kmh` was hardcoded to 0).
Wind speed is now read from the weather integration's hourly forecast.
Result: "Next mow expected" will be significantly earlier and more realistic — especially
after irrigation or heavy rain.

### Config Flow: Station-Centric Setup

Step 2 now only asks for the weather entity — no more DWD-specific fields.
Step 3 configures all station sensors (rain, temp, wind, radiation, brightness)
in a single step per station type:

| Station type | Fields |
|---|---|
| Ecowitt | Rain (daily/hourly/today), rain detector, temp, humidity, wind, radiation, brightness |
| Netatmo | Rain (daily/hourly), rain detector, temp, humidity, brightness |
| Other | Sensor type selector + all fields above |
| No station | Rain detector, temp, humidity, brightness |

The separate temp/humidity step is gone — all sensors are configured in one step.
