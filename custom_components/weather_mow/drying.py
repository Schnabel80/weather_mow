"""Schattenkorrigierte Trocknungs-Berechnung für weather_mow.

Pure-Python — keine Home-Assistant-Abhängigkeiten, damit eigenständig testbar.

Hintergrund:
    Die Rohwerte `solar_factor` (0..1) aus der DWD-/PV-Strahlung repräsentieren
    die Strahlung am Standort der Wetterstation bzw. der PV-Anlage. Sie sagen
    nichts darüber aus, wie viel davon TATSÄCHLICH AM RASEN ankommt.

    Zwei Effekte werden hier korrigiert:
      1. Schatten durch Bäume/Häuser/Mauern (Tagsüber-Schatten):
         per Effizienz-Faktor `efficiency` ∈ [0.1, 1.0].
      2. Lange Morgenschatten (Sonne erreicht den Rasen erst spät):
         per Schwellzeit `lawn_sun_from` (vorher = 0).
"""
from __future__ import annotations

from datetime import time as dt_time

EFFICIENCY_MIN = 0.1
EFFICIENCY_MAX = 1.0


def effective_solar_factor(
    solar_factor: float,
    efficiency: float,
    lawn_sun_from: dt_time,
    now_local: dt_time,
) -> float:
    """Auf den Rasen tatsächlich ankommender Anteil des Standort-Solar-Faktors.

    Args:
        solar_factor: Roher Faktor (0..1) aus Strahlung / max-Tagespeak.
        efficiency: Anteil der Standort-Strahlung, der den Rasen erreicht.
            Wird auf [0.1, 1.0] geclampt — 0 würde Trocknung dauerhaft ausschalten.
        lawn_sun_from: Lokale Uhrzeit, ab der die Sonne den Rasen erreicht.
            Davor zählt die Strahlung nicht (langer Morgenschatten).
        now_local: Aktuelle lokale Uhrzeit (nur HH:MM relevant).

    Returns:
        Effektiver Solar-Faktor ∈ [0, 1].
    """
    if now_local < lawn_sun_from:
        return 0.0
    eff = max(EFFICIENCY_MIN, min(EFFICIENCY_MAX, efficiency))
    return solar_factor * eff
