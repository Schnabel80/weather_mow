# smart_mow — Funktionsweise & Sensor-Empfehlungen

## Wie die Integration funktioniert

smart_mow trifft alle fünf Minuten eine Mähentscheidung auf Basis von Wetter, Sensordaten und Verlaufswerten. Es gibt keine direkte Mähersteuerung — die Integration gibt nur Signale aus, die eine HA-Automation auswertet.

### Die fünf Kernberechnungen

**1. Nässescore (0–100)**
Der wichtigste Einzelwert. Er kombiniert:
- Regengewichtung der letzten 12h (jüngerer Regen wiegt mehr als älterer)
- Morgenschwäche (Regen von heute früh trocknet langsamer als Regen am Vortag)
- Taupunkt: Temperatur ≤ Taupunkt + 3°C → +35 Punkte (überschreitet alleine die Mähschwelle von 30)
- Sonnentrocknung (aktueller Solar-Anteil am Tages-Peak)
- Windtrocknung (DWD-Windgeschwindigkeit)
- DWD-Regenprognose für die nächsten 3h
- Bewässerungs-Boost (separat, 70 Punkte, klingt über ~3h ab)

Ein Score ≥ 30 blockiert das Mähen mit Grund `too_wet`. Der Score ist auf 0–100 begrenzt.

**2. Mähentscheidung (7 Prüfungen in Reihe)**
1. Hauptschalter aus → blockiert
2. Außerhalb Zeitfenster (Standard 08–20 Uhr) → blockiert
3. Zu dunkel (Sonne < 10° Höhe UND Helligkeit unter Schwelle) → blockiert (`too_dark_hedgehog`)
4. Akku < Mindestwert → blockiert
5. Nässescore ≥ 30 → blockiert (`too_wet`)
6. DWD-Regenprognose heute verbleibend ≥ 5 mm → blockiert
7. Tagesziel bereits erreicht: bei aktivem Notmäh-Schalter und DWD-Regen morgen ≥ 8 mm → Notmähen erlaubt, sonst blockiert

**3. Priorität (0–100)**
Steuert, wann innerhalb eines erlaubten Fensters tatsächlich gestartet wird:
- Tagesdefizit (wie weit unter dem 2,5h-Ziel, bis +40)
- 3-Tage-Durchschnittsdefizit (bis +20)
- Notmähen-Bonus (+40)
- Wuchsbonus (0–15, linear ab 6 mm bis 20 mm Wuchshöhe)
- Mittagsbonus 11–16 Uhr (+10)
- Dringlichkeitsbonus in den letzten 3h des Fensters (bis +15)
- Nässeabzug (bis −30)

`start_now = True` wenn Priorität ≥ 40 und Mähen erlaubt.

**4. Wuchsmodell (GDD)**
Akkumuliert Growing Degree Days seit dem letzten Mähende: `max(0, Temperatur − 5°C) / 288` pro 5-Minuten-Schritt. Nach Düngung (Datum konfigurierbar) wird der Wuchs für 21 Tage mit Faktor 1,5 multipliziert. Wuchs ab 6 mm beginnt die Priorität zu erhöhen, Maximum (+15 Punkte) bei 20 mm. Reset erfolgt automatisch nach jedem Mähvorgang.

**5. Stop-Signale**
`stop_now = True` bei: Regen jetzt, Bewässerung aktiv, Nässeschwelle überschritten, zu dunkel für Igel, unerlaubter Autostart blockiert.

---

## Sensoren und Wetterdaten

### Zwingend erforderlich

| Entität | Domäne | Funktion |
|---------|--------|----------|
| Mäher-Entity | `lawn_mower` | Zustandsüberwachung (mäht/lädt), Mähzeiterfassung |
| DWD Wetter-Entity | `weather.dwd_*` | Temperatur- und Feuchte-Fallback, Grundlage |
| DWD Niederschlag-Sensor | `sensor.dwd_*_niederschlag` | Regenprognose heute/morgen/3h — zentral für Entscheidungslogik |

### Dringend empfohlen (funktioniert ohne, aber deutlich schlechter)

| Entität | Typ | Warum lokal besser |
|---------|-----|--------------------|
| Batterie-Sensor | `sensor.*_akku` | Das `battery_level`-Attribut am Mäher kann minuten- bis stundenverspätet sein. Lokaler Sensor ermöglicht exakte Mähzeiterfassung. |
| Lokaler Regensensor (aktuell) | `sensor.*_niederschlag` | **Kritisch.** DWD liefert Regionalprognose, keinen Echtzeit-Messwert vor Ort. Im 10-Tage-Backtest hat DWD alle lokalen Schauer nicht erkannt. Der Regen-Buffer und damit der gesamte Nässescore basieren auf diesem Sensor. |
| Lokaler Regensensor (1h) | `sensor.*_letzte_stunde` | Bereichert den Nässescore |
| Lokaler Regensensor (heute) | `sensor.*_heute` | Wird für die Morgenstraf-Berechnung genutzt |

### Optional (mit sinnvollem Fallback)

| Entität | Typ | Fallback | Empfehlung |
|---------|-----|----------|------------|
| Temperatursensor | `sensor.*` | DWD-Attribut | **Lokal bevorzugt** — Taupunktberechnung ist entscheidend für Morgentau; DWD-Station kann km entfernt sein |
| Luftfeuchte-Sensor | `sensor.*` | DWD-Attribut | **Lokal bevorzugt** — gleiche Begründung wie Temperatur |
| Helligkeitssensor | `sensor.*` | Sonnen-Elevation | Nützlich an bedeckten Tagen wenn die Sonne zwar > 10° steht, das Licht für Igel aber noch zu schwach ist |
| DWD Strahlungs-Sensor | `sensor.*_sonneneinstrahlung` | PV-Leistung oder Sonnenstand | Verbessert Trocknungsberechnung; ohne ihn ist Solar-Peak-Tracking ungenauer |
| DWD Wind-Sensor | `sensor.*_windgeschwindigkeit` | Kein Wind angenommen | Wind ist regional homogen — DWD reicht hier |
| PV-Leistung | `sensor.*` | Sonnenstand-Formel | Strahlungs-Fallback wenn kein DWD-Strahlungssensor vorhanden |

---

## Empfehlung: Lokal vs. DWD

**Lokal unbedingt:**
- **Regensensor** — DWD erkennt lokale Schauer nicht zuverlässig. Ohne lokalen Sensor verpasst die Integration echten Regen und der Mäher fährt auf nassem Rasen aus.
- **Temperatur und Feuchte** — für die Taupunktberechnung. Ein DWD-Wert von 15 km Entfernung kann Morgentau am eigenen Standort komplett verschätzen.

**DWD reicht:**
- **Regenprognose** (heute/morgen) — dafür ist DWD MOSMIX gemacht. Lokale Stationen liefern keine Vorhersagen.
- **Wind** — regional homogen, DWD-Wert ausreichend.
- **Strahlung** — wenn kein lokaler Sensor vorhanden, sind DWD-Strahlungsdaten gut genug.

**Merksatz:** Für das *Was gerade passiert* (Regen, Tau, Temperatur) sind lokale Sensoren klar überlegen. Für das *Was kommt* (Regenprognose, Strahlungsvorhersage) ist DWD die einzige sinnvolle Quelle.
