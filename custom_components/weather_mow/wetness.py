"""Physikalisches Nässe-Modell für weather_mow (Penman-Monteith vereinfacht).

Pure-Python — keine Home-Assistant-Abhängigkeiten.

Alle Rückgabewerte in mm pro 5-Min-Update-Schritt.
"""

from __future__ import annotations

import math

try:
    from .const import (
        DAY_RAMP_END_DEG,
        DAY_RAMP_START_DEG,
        DEW_OFFSET_C,
        K_COND_MM_PER_UPDATE_C,
        K_SOLAR_MM_PER_UPDATE,
        K_TEMP_MM_PER_UPDATE_C,
        K_WIND_VPD_COUPLING,
        LAWN_SUN_EFFICIENCY_MAX,
        LAWN_SUN_EFFICIENCY_MIN,
        NIGHT_DRYING_FLOOR,
        SHADE_BOOST_MAX,
        VPD_TEMP_REF_C,
    )
except ImportError:
    from const import (  # type: ignore[no-redef]
        DAY_RAMP_END_DEG,
        DAY_RAMP_START_DEG,
        DEW_OFFSET_C,
        K_COND_MM_PER_UPDATE_C,
        K_SOLAR_MM_PER_UPDATE,
        K_TEMP_MM_PER_UPDATE_C,
        K_WIND_VPD_COUPLING,
        LAWN_SUN_EFFICIENCY_MAX,
        LAWN_SUN_EFFICIENCY_MIN,
        NIGHT_DRYING_FLOOR,
        SHADE_BOOST_MAX,
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


def day_factor(sun_elevation_deg: float) -> float:
    """Tag/Nacht-Übergang 0..1 für den aerodynamischen Trocknungsterm.

    Rein aus dem Sonnenstand — NICHT aus eff_solar. eff_solar enthält neben
    Tageszeit auch Wolken UND lokale Beschattung (lawn_sun_efficiency); Wind-
    und VPD-getriebene Verdunstung braucht aber kein direktes Sonnenlicht, nur
    Tageslicht. Unterhalb DAY_RAMP_START_DEG (bürgerliche Dämmerung) → 0,
    oberhalb DAY_RAMP_END_DEG → 1, dazwischen linear (kein Tag/Nacht-Sprung).
    """
    if sun_elevation_deg <= DAY_RAMP_START_DEG:
        return 0.0
    if sun_elevation_deg >= DAY_RAMP_END_DEG:
        return 1.0
    return (sun_elevation_deg - DAY_RAMP_START_DEG) / (DAY_RAMP_END_DEG - DAY_RAMP_START_DEG)


def shade_compensation(efficiency: float) -> float:
    """Verstärkungsfaktor ≥1.0 für den aerodynamischen Term bei Dauerschatten.

    Der direkte Solar-Term (K_SOLAR·eff_solar) fällt bei beschatteten Rasen-
    flächen korrekt klein aus — weniger direkte Sonne ist real. Der Wind-/VPD-
    Term braucht aber kein direktes Sonnenlicht; er wird proportional dazu
    verstärkt, wie wenig Sonne den Rasen laut lawn_sun_efficiency erreicht.
    Bei efficiency=1.0 (kein Dauerschatten) bleibt die Kompensation 1.0.
    """
    eff = max(LAWN_SUN_EFFICIENCY_MIN, min(LAWN_SUN_EFFICIENCY_MAX, efficiency))
    return 1.0 + SHADE_BOOST_MAX * (1.0 - eff)


def penman_drying(
    eff_solar: float,
    vpd_c: float,
    wind_kmh: float,
    sun_elevation_deg: float,
    efficiency: float = 1.0,
    temp_c: float = VPD_TEMP_REF_C,
) -> float:
    """Trocknungs-Rate in mm pro 5-Min-Update (vereinfachtes Penman-Monteith).

    Args:
        eff_solar: Effektiver Solar-Faktor 0..1 (schattenkorrigiert) — treibt NUR
            den direkten Solar-Term.
        vpd_c: Vapor Pressure Deficit in °C (Temp − Taupunkt; negativ = Nebel/Sättigung).
        wind_kmh: Windgeschwindigkeit in km/h.
        sun_elevation_deg: Sonnenstand in Grad — treibt den Tag/Nacht-Übergang des
            aerodynamischen (Wind/VPD-)Terms, siehe day_factor().
        efficiency: lawn_sun_efficiency (0.1..1.0) — treibt die Schatten-Kompensation
            des Aero-Terms, siehe shade_compensation(). Default 1.0 (kein Effekt).
        temp_c: Lufttemperatur in °C (Default = Referenz 20 °C → temperaturneutral).

    Wind koppelt seit v0.4.1 an den VPD-Term (aerodynamisches Penman-Monteith):
    er verstärkt die VPD-getriebene Verdunstung, statt unabhängig zu addieren.
    Bei VPD ≤ 0 (Sättigung/Nebel) bleibt der Wind-Beitrag damit 0.

    Seit v0.4.3b3 wird der aerodynamische Term (VPD+Wind) gedämpft: nächtliche
    Verdunstung ist energielimitiert, daher bleibt nachts nur NIGHT_DRYING_FLOOR
    übrig. Bis v1.1.x lief diese Dämpfung fälschlich über eff_solar — dadurch
    wurde Wind/VPD-Verdunstung an bewölkten oder beschatteten TAGEN fast auf den
    Nacht-Wert gedrückt, obwohl sie kein direktes Sonnenlicht braucht. Seit v1.2.0
    entscheidet ausschließlich sun_elevation_deg über Tag/Nacht (glatte Rampe →
    kein Sprung in der Dämmerung); eff_solar steuert nur noch den Solar-Term.

    Seit v0.5.0 wird der aerodynamische Term zusätzlich mit dem Temperaturfaktor
    es(T)/es(20 °C) skaliert. Die °C-VPD-Näherung ist temperaturunabhängig; der echte
    Sättigungsdampfdruck steigt aber stark mit T. Verankert bei 20 °C → Durchschnitts-
    tage unverändert, warme Tage trocknen schneller, kühle langsamer. Der Solar-Term
    bleibt davon unberührt (Strahlungsenergie ist bereits in eff_solar enthalten).

    Seit v1.2.0 wird der aerodynamische Term zusätzlich mit shade_compensation(
    efficiency) skaliert: dauerhaft beschattete Rasenflächen verlieren real Solar-
    Trocknung, gleichen das aber teilweise über Wind-/VPD-Verdunstung aus. Bei
    efficiency=1.0 (Default) ist die Kompensation neutral (×1.0).

    Returns:
        Trocknungs-Delta in mm (≥ 0).
    """
    vpd = max(0.0, vpd_c)
    aero_factor = NIGHT_DRYING_FLOOR + (1.0 - NIGHT_DRYING_FLOOR) * day_factor(sun_elevation_deg)
    temp_factor = saturation_vapor_pressure(temp_c) / _ES_REF
    return (
        K_SOLAR_MM_PER_UPDATE * eff_solar
        + shade_compensation(efficiency)
        * temp_factor
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
