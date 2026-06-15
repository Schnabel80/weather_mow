"""Physikalisches Nässe-Modell für weather_mow (Penman-Monteith vereinfacht).

Pure-Python — keine Home-Assistant-Abhängigkeiten.

Alle Rückgabewerte in mm pro 5-Min-Update-Schritt.
"""

from __future__ import annotations

try:
    from .const import (
        DEW_OFFSET_C,
        K_COND_MM_PER_UPDATE_C,
        K_SOLAR_MM_PER_UPDATE,
        K_TEMP_MM_PER_UPDATE_C,
        K_WIND_VPD_COUPLING,
        NIGHT_DRYING_FLOOR,
    )
except ImportError:
    from const import (  # type: ignore[no-redef]
        DEW_OFFSET_C,
        K_COND_MM_PER_UPDATE_C,
        K_SOLAR_MM_PER_UPDATE,
        K_TEMP_MM_PER_UPDATE_C,
        K_WIND_VPD_COUPLING,
        NIGHT_DRYING_FLOOR,
    )


def penman_drying(eff_solar: float, vpd_c: float, wind_kmh: float) -> float:
    """Trocknungs-Rate in mm pro 5-Min-Update (vereinfachtes Penman-Monteith).

    Args:
        eff_solar: Effektiver Solar-Faktor 0..1 (schattenkorrigiert).
        vpd_c: Vapor Pressure Deficit in °C (Temp − Taupunkt; negativ = Nebel/Sättigung).
        wind_kmh: Windgeschwindigkeit in km/h.

    Wind koppelt seit v0.4.1 an den VPD-Term (aerodynamisches Penman-Monteith):
    er verstärkt die VPD-getriebene Verdunstung, statt unabhängig zu addieren.
    Bei VPD ≤ 0 (Sättigung/Nebel) bleibt der Wind-Beitrag damit 0.

    Seit v0.4.3b3 wird der aerodynamische Term (VPD+Wind) mit eff_solar gedämpft:
    nächtliche Verdunstung ist energielimitiert, daher bleibt bei eff_solar=0 nur
    NIGHT_DRYING_FLOOR übrig (glatte Rampe → kein Tag/Nacht-Sprung in der Dämmerung).

    Returns:
        Trocknungs-Delta in mm (≥ 0).
    """
    vpd = max(0.0, vpd_c)
    aero_factor = NIGHT_DRYING_FLOOR + (1.0 - NIGHT_DRYING_FLOOR) * eff_solar
    return (
        K_SOLAR_MM_PER_UPDATE * eff_solar
        + aero_factor * (K_TEMP_MM_PER_UPDATE_C + K_WIND_VPD_COUPLING * max(0.0, wind_kmh)) * vpd
    )


def condensation(vpd_c: float) -> float:
    """Kondensations-Rate in mm pro 5-Min-Update (Taubildung auf Grashalmen).

    Die Grasoberfläche ist ~DEW_OFFSET_C kühler als die Luft.
    Wenn VPD < DEW_OFFSET → Grashalm-Oberfläche unterschreitet Taupunkt → Tau.

    Args:
        vpd_c: Vapor Pressure Deficit in °C (Temp − Taupunkt).

    Returns:
        Kondensations-Delta in mm (≥ 0).
    """
    return K_COND_MM_PER_UPDATE_C * max(0.0, DEW_OFFSET_C - vpd_c)
