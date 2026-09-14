## 🇩🇪 v1.3.0b1

### Neu: Sonnenelevation statt fixer Uhrzeit für Rasen-Beschattung (#17)

Die neue Number-Entität **Sonnenelevation für Rasen** (`number.*_sonnenelevation_fur_rasen`,
0–90°, Default 0°) ist eine saisonal korrekte Alternative zur bisherigen fixen Uhrzeit
**Sonne erreicht Rasen ab**. Statt einer über das ganze Jahr gleichen Uhrzeit wird die
tatsächliche Schwellzeit — ab wann die Morgensonne den Rasen erreicht — jeden Tag neu aus
der konfigurierten Sonnenhöhe berechnet (per `astral`, das Home Assistant bereits mitbringt).
Das behebt die Ungenauigkeit einer fixen Uhrzeit über Sommer, Winter und Zeitumstellungen
hinweg.

**Verhalten:**
- **Default 0° = deaktiviert.** Ohne Änderung an dieser Entität verhält sich die Integration
  exakt wie bisher — die manuelle Uhrzeit `lawn_sun_from` entscheidet weiter.
- **Wert > 0° aktiviert den Modus.** Die Schwellzeit wird ab dann täglich neu berechnet;
  ein zusätzlich gesetzter Wert bei `lawn_sun_from` wird in diesem Modus ignoriert.
- **Polarnacht / hohe Breitengrade:** Erreicht die Sonne die konfigurierte Elevation an
  einem Tag nie, gilt dieser Tag konservativ als ganztägig beschattet (kein Trocknungs­effekt
  durch Sonne) statt eine unsichere Zeit zu schätzen.
- Wirkt auf die Live-Trocknungsberechnung **und** auf die 48h-Vorausschau (dort jetzt pro
  Prognosetag einzeln berechnet statt einer festen Zeit über den gesamten Horizont).

Kein Setup-Wizard-Schritt nötig — wie `lawn_sun_efficiency` ist die neue Entität jederzeit
im Dashboard verstellbar.

Danke an [@17Halbe](https://github.com/17Halbe) für den durchdachten Vorschlag inkl.
Implementierungsskizze in Issue #17.

### Fix: Totes Config-Feld "Tau-Temperaturoffset" entfernt (#18)

Das Setup-Feld `threshold_dew_temp_offset` dokumentierte seinen Effekt falsch herum — der
tiefere Grund war aber, dass der Wert seit v0.4.0b5 gar keine Mähentscheidung mehr
beeinflusst hat (die Tau-Sperre wurde durch das Penman-Monteith-Feuchtemodell ersetzt).
Er speiste nur noch den rein diagnostischen `dew_present`-Sensor. Statt die Doku zu
korrigieren, wurde das irreführende Feld entfernt; der Wert ist jetzt fest im Code
verankert (unverändert 3,0 °C).

---

## 🇬🇧 v1.3.0b1

### New: Sun elevation instead of fixed time for lawn shading (#17)

The new number entity **Lawn Sun Elevation From** (`number.*_lawn_sun_elevation_from`,
0–90°, default 0°) is a seasonally correct alternative to the previous fixed-time
**Lawn Sun From** setting. Instead of one time-of-day used all year round, the actual
threshold time — when morning sun starts reaching the lawn — is now recalculated every day
from the configured sun elevation (via `astral`, already bundled with Home Assistant). This
fixes the inaccuracy of a fixed time across summer, winter, and DST changes.

**Behavior:**
- **Default 0° = disabled.** Without touching this entity, the integration behaves exactly
  as before — the manual `lawn_sun_from` time keeps deciding.
- **A value > 0° enables the mode.** The threshold time is then recalculated daily; any
  value set on `lawn_sun_from` is ignored while this mode is active.
- **Polar night / high latitudes:** if the sun never reaches the configured elevation on a
  given day, that day is conservatively treated as shaded all day (no solar drying
  contribution) instead of guessing an uncertain time.
- Affects both the live drying calculation **and** the 48h forecast (now computed per
  forecast day instead of a single fixed time across the whole horizon).

No setup wizard step needed — like `lawn_sun_efficiency`, the new entity is adjustable in
the dashboard at any time.

Thanks to [@17Halbe](https://github.com/17Halbe) for the well thought-out proposal,
including an implementation sketch, in issue #17.

### Fix: Removed dead "dew temperature offset" config field (#18)

The setup field `threshold_dew_temp_offset` documented its effect backwards — but the
deeper issue was that the value hasn't influenced any mowing decision since v0.4.0b5 (the
dew gate was replaced by the Penman-Monteith wetness model). It only ever fed the purely
diagnostic `dew_present` sensor. Rather than fixing the docs, the misleading field was
removed; the value is now fixed in code (unchanged at 3.0 °C).
