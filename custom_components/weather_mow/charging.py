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

# Gelernte Ladedecke ("voll"): manche Mäher erreichen nie 100 % (Alterung) oder
# der Nutzer setzt ein Ladelimit am Gerät. Statt einer fixen Schwelle wird das
# Plateau gelernt — siehe coordinator._maybe_track_charge.
BATTERY_CEILING_MIN_PCT = 50.0  # Harte Plausibilitäts-Klammer unten (Sensor-Glitch)
BATTERY_CEILING_WARN_PCT = 60.0  # Gelernte Decke darunter → Akku-Warnung an Nutzer


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


def learn_battery_ceiling(plateau_pct: float) -> float:
    """Klammert ein erkanntes Lade-Plateau auf eine plausible Decke (50–100 %).

    Der Mäher hat geladen und verharrt seit Minuten ohne weiteren SoC-Anstieg —
    dieser Plateau-Wert ist die reale "voll"-Schwelle. Nur grobe Ausreißer
    (Sensor-Glitch < 50 % oder > 100 %) werden gekappt; Werte 50–60 % bleiben
    erhalten und lösen separat eine Warnung aus (battery_ceiling_warning).
    """
    return max(BATTERY_CEILING_MIN_PCT, min(100.0, plateau_pct))


def battery_ceiling_warning(learned_pct: float) -> bool:
    """True, wenn die gelernte Ladedecke so niedrig ist, dass der Nutzer es
    wissen sollte (degradierter Akku oder sehr niedriges Ladelimit)."""
    return learned_pct < BATTERY_CEILING_WARN_PCT


def minutes_to_target(battery_now: float, target_pct: float, rate: float) -> float:
    """Minuten bis der Akku target_pct erreicht. rate ≤ 0 → 0 (kein Schätzwert)."""
    if rate <= 0.0:
        return 0.0
    return max(0.0, (target_pct - battery_now) / rate)
