"""Physikalisches Wachstumsmodell für weather_mow.

Pure-Python — keine Home-Assistant-Abhängigkeiten, voll unit-testbar.

Kühlgräser (typischer mitteleuropäischer Rasen: Weidelgras, Schwingel, Rispe)
wachsen nicht linear mit der Temperatur, und sie brauchen Wasser. Das Modell
bildet beides ab:

- ``temperature_response``: Kardinaltemperatur-Kurve (Basis/Optimum/Maximum).
- ``moisture_factor``: Trockendormanz über einen Wasser-Proxy.

Beide werden im Coordinator pro 5-Min-Schritt multipliziert in den GDD-Akkumulator
gespeist.
"""

from __future__ import annotations

try:
    from .const import (
        GDD_BASE_TEMP_C,
        GDD_MAX_TEMP_C,
        GDD_OPT_TEMP_C,
        GROWTH_MOISTURE_FLOOR,
        GROWTH_MOISTURE_REF_MM,
    )
except ImportError:
    from const import (  # type: ignore[no-redef]
        GDD_BASE_TEMP_C,
        GDD_MAX_TEMP_C,
        GDD_OPT_TEMP_C,
        GROWTH_MOISTURE_FLOOR,
        GROWTH_MOISTURE_REF_MM,
    )


def temperature_response(temp_c: float) -> float:
    """Effektiver Temperaturbeitrag pro Grad (Kardinaltemperatur-Dreieck).

    - ``temp ≤ BASE`` oder ``temp ≥ MAX`` → 0 (zu kalt bzw. Hitzedormanz).
    - ``BASE < temp ≤ OPT`` → linear ``temp − BASE`` (identisch zum alten Modell,
      daher bleibt die Kalibrierung für Normaltage unverändert).
    - ``OPT < temp < MAX`` → linearer Abfall vom Peak (bei OPT) auf 0 (bei MAX).

    Returns:
        Temperaturbeitrag in °C-Äquivalent (≥ 0), Peak = ``OPT − BASE``.
    """
    if temp_c <= GDD_BASE_TEMP_C or temp_c >= GDD_MAX_TEMP_C:
        return 0.0
    if temp_c <= GDD_OPT_TEMP_C:
        return temp_c - GDD_BASE_TEMP_C
    peak = GDD_OPT_TEMP_C - GDD_BASE_TEMP_C
    return peak * (GDD_MAX_TEMP_C - temp_c) / (GDD_MAX_TEMP_C - GDD_OPT_TEMP_C)


def moisture_factor(rain_12h_mm: float, wetness_mm: float) -> float:
    """Wasser-Verfügbarkeit als Wuchsfaktor 0..1 (Trockendormanz).

    Proxy aus kurzfristigem Regen (12h-Puffer) plus aktueller Oberflächenfeuchte
    (``wetness_mm`` deckt auch Bewässerung ab). Bei reichlich Wasser → 1.0, bei
    anhaltender Trockenheit → ``GROWTH_MOISTURE_FLOOR``.

    Returns:
        Faktor in [GROWTH_MOISTURE_FLOOR, 1.0].
    """
    water = max(0.0, rain_12h_mm) + max(0.0, wetness_mm)
    ramp = min(1.0, water / GROWTH_MOISTURE_REF_MM)
    return GROWTH_MOISTURE_FLOOR + (1.0 - GROWTH_MOISTURE_FLOOR) * ramp
