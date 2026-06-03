"""Laderaten-Lernen für den Mäher-Akku (Zeit-zu-SoC).

Bewusst frei von Home-Assistant-Importen, damit das Lernen eigenständig per
pytest testbar bleibt — analog zu wetness.py und drying.py.
"""

from __future__ import annotations

DEFAULT_CHARGE_RATE_PCT_PER_MIN = 1.0  # Startwert bis erste valide Messung
CHARGE_RATE_MIN = 0.2  # Plausibilitäts-Klammer unten
CHARGE_RATE_MAX = 3.0  # Plausibilitäts-Klammer oben
FIRST_LEARN_MIN_RISE_PCT = 60.0  # Erstmessung erst ab diesem SoC-Anstieg
EMA_LEARN_MIN_RISE_PCT = 20.0  # Folgemessungen ab diesem SoC-Anstieg
EMA_ALPHA = 0.2  # Glättung für Folgemessungen


def learn_charge_rate(
    current_rate: float,
    learned: bool,
    measured_rate: float,
    rise_pct: float,
) -> tuple[float, bool]:
    """Aktualisiert die gelernte Laderate aus einer Lade-Messung.

    current_rate  — bisher gespeicherte Rate (%/min)
    learned       — ob schon eine echte Messung übernommen wurde
    measured_rate — gemessene Rate dieses Ladevorgangs (%/min)
    rise_pct      — kumulierter SoC-Anstieg des Ladevorgangs (%)

    Rückgabe: (neue_rate, learned). Bei zu kleinem Anstieg unverändert.
    """
    if not learned:
        if rise_pct < FIRST_LEARN_MIN_RISE_PCT:
            return current_rate, False
        new_rate = measured_rate  # α = 1.0: Default komplett ersetzen
    else:
        if rise_pct < EMA_LEARN_MIN_RISE_PCT:
            return current_rate, True
        new_rate = (1.0 - EMA_ALPHA) * current_rate + EMA_ALPHA * measured_rate
    new_rate = max(CHARGE_RATE_MIN, min(CHARGE_RATE_MAX, new_rate))
    return new_rate, True


def minutes_to_target(battery_now: float, target_pct: float, rate: float) -> float:
    """Minuten bis der Akku target_pct erreicht. rate ≤ 0 → 0 (kein Schätzwert)."""
    if rate <= 0.0:
        return 0.0
    return max(0.0, (target_pct - battery_now) / rate)
