"""Zeitplanung: Morgen-Zurückhaltung des Mähstarts.

Bewusst frei von Home-Assistant-Importen, damit die Entscheidung eigenständig
per pytest testbar bleibt — analog zu wetness.py, drying.py, growth.py,
freshness.py.

Hintergrund:
    Das Tagesdefizit ist morgens per Definition maximal (noch nichts gemäht) und
    treibt die Priorität damit sofort auf die Start-Schwelle. Ohne Bremse fährt
    der Mäher los, sobald Mähfenster, Helligkeit und Nässe es zulassen — auch an
    einem kühlen, trockenen Tag, an dem noch der ganze Tag Zeit wäre.

    Leitsatz: *so früh wie nötig, so spät wie möglich.* Vor der Wunsch-Startzeit
    wird nur gestartet, wenn danach nicht mehr genug NUTZBARE Zeit bliebe, um das
    Tagesziel zu schaffen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

# Ab dieser Regenmenge gilt eine Prognosestunde als nicht mähbar. Bewusst knapp
# über 0: OpenWeatherMap meldet Niesel oft als 0.0–0.1 mm bei hoher Wahrschein-
# lichkeit. Wie in charging.py wohnt die Tuning-Konstante im reinen Modul selbst.
RAIN_HOUR_BLOCK_MM = 0.2


def usable_mow_hours(
    hourly: list[tuple[datetime, float, float]],
    start: datetime,
    end: datetime,
    max_temp_c: float,
    rain_block_mm: float = RAIN_HOUR_BLOCK_MM,
) -> float:
    """Zählt die zum Mähen nutzbaren Prognosestunden im Fenster [start, end).

    hourly: (Stunde, Regenmenge mm, Temperatur °C) — je Prognosestunde.
    Eine Stunde ist nutzbar, wenn sie weder verregnet (< rain_block_mm) noch zu
    heiß (< max_temp_c, dieselbe Grenze wie das Hitze-Gate) ist.

    Stunden mit abweichender Zeitzonen-Info werden übersprungen statt zu crashen —
    der Sensor-Pfad kann naive Zeitstempel liefern.
    """
    usable = 0.0
    for dt, rain_mm, temp_c in hourly:
        try:
            if not (start <= dt < end):
                continue
        except TypeError:
            # naive vs. aware datetime → nicht vergleichbar, Stunde ignorieren
            continue
        if rain_mm >= rain_block_mm:
            continue
        if temp_c >= max_temp_c:
            continue
        usable += 1.0
    return usable


def enough_time_after_hold(
    usable_h: float,
    remaining_needed_h: float,
    safety_factor: float,
) -> bool:
    """True, wenn Zurückhalten vertretbar ist.

    Nach der Wartezeit muss noch das safety_factor-fache der benötigten Mähzeit
    an nutzbaren Stunden übrig sein (Puffer für Andocken/Zwischenladen).
    Bei erfülltem Tagesziel (remaining_needed_h ≤ 0) gibt es ohnehin keinen Grund
    für einen frühen Start.
    """
    if remaining_needed_h <= 0.0:
        return True
    return usable_h >= remaining_needed_h * safety_factor
