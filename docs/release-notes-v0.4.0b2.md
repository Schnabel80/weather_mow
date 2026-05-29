## 🇩🇪 v0.4.0b2

### Bewässerungs-Buchung: fester 2mm-Wert

Der Bewässerungs-Button bucht immer 2 mm auf `wetness_mm`. Der Slider zur
Mengeneingabe wurde entfernt — er war irreführend, weil die Integration ohnehin
nur die Halm-Sättigungsgrenze (~1–2 mm) modelliert, nicht die tatsächlich
verregnetete Wassermenge.

**Neue Entität:** `number.<name>_mow_threshold_urgent_mm`.
**Entfernt:** `number.<name>_irrigation_amount_mm`.

### Feuchte-Deckel: max. 2 mm pro Update

Regen und Bewässerung können `wetness_mm` pro 5-Minuten-Update um maximal 2 mm
erhöhen. Auch bei Starkregen (10 mm in 5 Minuten) steigt der Modellwert damit
nur moderat — was dem echten Verhalten von Grashalmen entspricht (Überschuss
fließt sofort ab).

### Zwei Feuchte-Schwellen: Normal + Dringlichkeit

Neue Entität `number.<name>_mow_threshold_urgent_mm` (Standard: 1,5 mm).

Wenn Zeitdruck besteht (past der Fertig-Deadline, z. B. nach 18:00 bei
Mähfenster bis 20:00 mit 2h Puffer) oder Notmähen aktiv ist, gilt die
Dringlichkeits-Schwelle statt der normalen Schwelle. Der Mäher darf dann
mit leichter Restfeuchte losfahren.

**Konfiguration:** Normale Schwelle bei 0,5 mm, Dringlichkeits-Schwelle
nach Belieben höher (z.B. 1,5 mm) → der Mäher fährt bei Zeitdruck auch
wenn der Rasen noch leicht feucht ist.

---

## 🇬🇧 v0.4.0b2

### Irrigation booking: fixed 2mm value

The irrigation button always books 2 mm to `wetness_mm`. The amount slider
has been removed — it was misleading because the integration only models the
grass blade saturation limit (~1–2 mm), not the actual water volume applied.

**New entity:** `number.<name>_mow_threshold_urgent_mm`.
**Removed:** `number.<name>_irrigation_amount_mm`.

### Wetness cap: max. 2 mm per update

Rain and irrigation can increase `wetness_mm` by at most 2 mm per 5-minute
update. Even during heavy rain (10 mm in 5 minutes), the model value rises
only moderately — matching real grass blade behavior (excess runs off immediately).

### Two wetness thresholds: normal + urgency

New entity `number.<name>_mow_threshold_urgent_mm` (default: 1.5 mm).

When time pressure exists (past the target deadline, e.g. after 18:00 with
mow window ending at 20:00 and 2h buffer) or emergency mowing is active,
the urgency threshold applies instead of the normal threshold. The mower may
then start with slight residual moisture.

**Configuration:** Set normal threshold at 0.5 mm, urgency threshold higher
(e.g. 1.5 mm) → the mower starts under time pressure even if the lawn is
slightly damp.
