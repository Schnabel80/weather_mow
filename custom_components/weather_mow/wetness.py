"""Physikalisches Nässe-Modell für weather_mow (Penman-Monteith vereinfacht).

Pure-Python — keine Home-Assistant-Abhängigkeiten.

Alle Rückgabewerte in mm pro 5-Min-Update-Schritt.
"""

from __future__ import annotations

import math

try:
    from .const import (
        DEW_OFFSET_C,
        K_COND_MM_PER_UPDATE_C,
        K_SOLAR_MM_PER_UPDATE,
        K_TEMP_MM_PER_UPDATE_C,
        K_WIND_VPD_COUPLING,
        NIGHT_DRYING_FLOOR,
        VPD_TEMP_REF_C,
    )
except ImportError:
    from const import (  # type: ignore[no-redef]
        DEW_OFFSET_C,
        K_COND_MM_PER_UPDATE_C,
        K_SOLAR_MM_PER_UPDATE,
        K_TEMP_MM_PER_UPDATE_C,
        K_WIND_VPD_COUPLING,
        NIGHT_DRYING_FLOOR,
        VPD_TEMP_REF_C,
    )


def saturation_vapor_pressure(temp_c: float) -> float:
    """Sättigungsdampfdruck der Luft [kPa] nach Magnus/Tetens.

    es(T) = 0.6108 · exp(17.27·T / (T+237.3)). Steigt exponentiell mit der
    Temperatur — die physikalische Grundlage dafür, dass warme Luft schneller
    trocknet als kühle bei gleicher relativer Feuchte.
    """
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


# Sättigungsdampfdruck am Referenzpunkt (20 °C) — Anker für den Temperaturfaktor.
_ES_REF = saturation_vapor_pressure(VPD_TEMP_REF_C)


def penman_drying(
    eff_solar: float,
    vpd_c: float,
    wind_kmh: float,
    temp_c: float = VPD_TEMP_REF_C,
) -> float:
    """Trocknungs-Rate in mm pro 5-Min-Update (vereinfachtes Penman-Monteith).

    Args:
        eff_solar: Effektiver Solar-Faktor 0..1 (schattenkorrigiert).
        vpd_c: Vapor Pressure Deficit in °C (Temp − Taupunkt; negativ = Nebel/Sättigung).
        wind_kmh: Windgeschwindigkeit in km/h.
        temp_c: Lufttemperatur in °C (Default = Referenz 20 °C → temperaturneutral).

    Wind koppelt seit v0.4.1 an den VPD-Term (aerodynamisches Penman-Monteith):
    er verstärkt die VPD-getriebene Verdunstung, statt unabhängig zu addieren.
    Bei VPD ≤ 0 (Sättigung/Nebel) bleibt der Wind-Beitrag damit 0.

    Seit v0.4.3b3 wird der aerodynamische Term (VPD+Wind) mit eff_solar gedämpft:
    nächtliche Verdunstung ist energielimitiert, daher bleibt bei eff_solar=0 nur
    NIGHT_DRYING_FLOOR übrig (glatte Rampe → kein Tag/Nacht-Sprung in der Dämmerung).

    Seit v0.5.0 wird der aerodynamische Term zusätzlich mit dem Temperaturfaktor
    es(T)/es(20 °C) skaliert. Die °C-VPD-Näherung ist temperaturunabhängig; der echte
    Sättigungsdampfdruck steigt aber stark mit T. Verankert bei 20 °C → Durchschnitts-
    tage unverändert, warme Tage trocknen schneller, kühle langsamer. Der Solar-Term
    bleibt davon unberührt (Strahlungsenergie ist bereits in eff_solar enthalten).

    Returns:
        Trocknungs-Delta in mm (≥ 0).
    """
    vpd = max(0.0, vpd_c)
    aero_factor = NIGHT_DRYING_FLOOR + (1.0 - NIGHT_DRYING_FLOOR) * eff_solar
    temp_factor = saturation_vapor_pressure(temp_c) / _ES_REF
    return (
        K_SOLAR_MM_PER_UPDATE * eff_solar
        + temp_factor
        * aero_factor
        * (K_TEMP_MM_PER_UPDATE_C + K_WIND_VPD_COUPLING * max(0.0, wind_kmh))
        * vpd
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
