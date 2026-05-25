## 🇩🇪 v0.4.0a1 — Alpha

### Kernänderung: Physikalisches Nässe-Modell (mm)

Der bisherige Nässe-Score (0–100 Punkte) wird durch eine physikalische Zustandsgröße
`wetness_mm` (0–20 mm) ersetzt. Alle Nässe-Quellen und die Trocknung folgen jetzt
einem einheitlichen physikalischen Modell (vereinfachtes Penman-Monteith):

**Nässe-Quellen:**
- Regen: mm-Delta direkt aus dem Tagessensor
- Tau: Kondensation wenn Grasoberfläche (≈ 3°C kühler als Luft) den Taupunkt unterschreitet
- Bewässerung: Button bucht einmalig die eingestellte mm-Menge

**Trocknung:**
- Solar-Term: proportional zur tatsächlichen Sonnenstrahlung am Rasen
- Temperatur-Term: proportional zu Temp − Taupunkt (VPD)
- Wind-Term: proportional zur Windgeschwindigkeit

**Neue UI-Entitäten:**
- `number.<name>_mow_threshold_mm` — Erlaubte Restfeuchte (0.1–3.0 mm, Default 0.5 mm)
- `number.<name>_irrigation_amount_mm` — Bewässerungsmenge (0–50 mm, Default 5 mm)
- `button.<name>_irrigation_apply` — Bucht die Bewässerungsmenge einmalig

**Bewässerungs-Workflow:**
1. Bewässerungs-Switch ON → Mäher zurückrufen (wie v0.3)
2. Nach der Bewässerung: `irrigation_amount_mm` setzen → Button drücken → `wetness_mm += mm`
3. Fehlbedienung korrigieren: 0 mm eingeben → Button drücken

**Adaptiver Startschwellwert:**
Wenn kein Regen in den nächsten 3h erwartet wird, reduziert sich der Startschwellwert
um 0.3 mm — der Mäher darf also leicht früher starten. Danach gilt eine 30-minütige
Wartezeit (`waiting_for_favorable`) vor der eigentlichen Freigabe.

### Kalibrierungs-Konstanten (Alpha — Beta-Validierung steht aus)

| Konstante | Wert | Bedeutung |
|-----------|------|-----------|
| K_SOLAR | 0.030 mm/Update | Peak-Sonne → ~0.36 mm/h |
| K_TEMP | 0.001 mm/Update/°C | VPD=10°C → ~0.12 mm/h |
| K_WIND | 0.0005 mm/Update/(km/h) | 20 km/h → ~0.06 mm/h |
| K_COND | 0.003 mm/Update/°C | 3°C unter Taupunkt → ~0.22 mm/h |
| DEW_OFFSET | 3.0 °C | Grasoberfläche kühlt ~3°C unter Lufttemperatur |
| WETNESS_MAX | 20.0 mm | Physikalischer Deckel (Ablauf) |

### ⚠️ Alpha-Hinweis

Die K-Konstanten sind Schätzungen aus Simulationen mit echten Sensordaten. Die
Beta-Validierung gegen Live-Messungen steht aus. Feedback über tatsächliches
Trocknungsverhalten ist ausdrücklich erwünscht — bitte im Debug-CSV `wetness_mm`
und `temp_c` beobachten.

### Migration von v0.3

Beim ersten Start wird `wetness_mm` aus dem alten Regen-Buffer rekonstruiert.
Falls kein Buffer vorhanden: sauberer Neustart mit 0 mm.

---

## 🇬🇧 v0.4.0a1 — Alpha

### Core change: Physical wetness model (mm)

The previous wetness score (0–100 points) is replaced by a physical state variable
`wetness_mm` (0–20 mm). All wetness sources and drying now follow a unified physical
model (simplified Penman-Monteith):

**Wetness sources:**
- Rain: mm delta directly from the daily sensor
- Dew: condensation when grass surface (≈ 3°C cooler than air) falls below dew point
- Irrigation: button books the set mm amount once

**Drying:**
- Solar term: proportional to actual solar radiation reaching the lawn
- Temperature term: proportional to Temp − Dew Point (VPD)
- Wind term: proportional to wind speed

**New UI entities:**
- `number.<name>_mow_threshold_mm` — Allowed residual moisture (0.1–3.0 mm, default 0.5 mm)
- `number.<name>_irrigation_amount_mm` — Irrigation amount (0–50 mm, default 5 mm)
- `button.<name>_irrigation_apply` — Books the irrigation amount once

**Irrigation workflow:**
1. Irrigation switch ON → recall mower (same as v0.3)
2. After irrigation: set `irrigation_amount_mm` → press button → `wetness_mm += mm`
3. Correct a mistake: set 0 mm → press button

**Adaptive start threshold:**
When no rain is expected in the next 3h, the start threshold is reduced by 0.3 mm —
allowing the mower to start slightly earlier. A 30-minute grace period
(`waiting_for_favorable`) then applies before full release.

### Calibration constants (Alpha — beta validation pending)

| Constant | Value | Meaning |
|----------|-------|---------|
| K_SOLAR | 0.030 mm/update | Peak sun → ~0.36 mm/h |
| K_TEMP | 0.001 mm/update/°C | VPD=10°C → ~0.12 mm/h |
| K_WIND | 0.0005 mm/update/(km/h) | 20 km/h → ~0.06 mm/h |
| K_COND | 0.003 mm/update/°C | 3°C below dew point → ~0.22 mm/h |
| DEW_OFFSET | 3.0 °C | Grass surface cools ~3°C below air temp |
| WETNESS_MAX | 20.0 mm | Physical ceiling (drainage/saturation) |

### ⚠️ Alpha note

The K constants are estimates from simulations with real sensor data. Beta validation
against live measurements is pending. Feedback on actual drying behavior is explicitly
welcome — please monitor `wetness_mm` and `temp_c` in the debug CSV.

### Migration from v0.3

On first start, `wetness_mm` is reconstructed from the old rain buffer.
If no buffer exists: clean start at 0 mm.
