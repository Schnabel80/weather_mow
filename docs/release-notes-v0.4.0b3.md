## 🇩🇪 v0.4.0b3

### Nässe-Reset-Button

Neuer Button `button.<name>_nasse_auf_0_zurucksetzen` — setzt `wetness_mm` sofort auf 0,0 mm
zurück. Gedacht für Fehlbedienungen (z.B. versehentlicher Bewässerungs-Druck) und
Sensorfehler (Regensensor hat Regen gemeldet der nicht gefallen ist).

### Erwartetes Mähen bei „waiting_for_favorable" präzisiert

Wenn der Block-Grund `waiting_for_favorable` ist (Nässe liegt zwischen Normal- und
Dringlichkeits-Schwelle), wurde `next_mow_expected` bisher zu weit in die Zukunft
geschätzt (Stundenraster der Simulation beginnt erst bei `now+1h`). Ab b3 wird die
verbleibende Trocknungszeit direkt aus der aktuellen Trocknungsrate berechnet:
`ETA = jetzt + ceil(Δmm / Trocknungsrate_5min) × 5min + 30min Grace`.

---

## 🇬🇧 v0.4.0b3

### Wetness reset button

New button `button.<name>_reset_wetness_to_0` — immediately sets `wetness_mm` to 0.0 mm.
Use after accidental irrigation button presses or sensor errors that caused a false
wetness spike.

### More accurate next-mow ETA in waiting_for_favorable state

When `block_reason` is `waiting_for_favorable` (wetness between normal and urgency
threshold), `next_mow_expected` previously showed the result of the hourly simulation
starting at `now+1h`, which could show 1–2 hours when the actual wait was only minutes.
The fix calculates the ETA directly: `ETA = now + ceil(Δmm / drying_rate_5min) × 5min + 30min grace`.
