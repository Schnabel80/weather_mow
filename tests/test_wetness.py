"""Unit-Tests für das physikalische Nässe-Modell (wetness.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "weather_mow"),
)

from const import (
    DAY_RAMP_END_DEG,
    DAY_RAMP_START_DEG,
    LAWN_SUN_EFFICIENCY_MIN,
    NIGHT_DRYING_FLOOR,
    SHADE_BOOST_MAX,
)
from wetness import condensation, day_factor, penman_drying, shade_compensation

DAY = 45.0  # Sonnenstand weit oberhalb der Rampe → day_factor=1.0
NIGHT = -90.0  # Sonnenstand weit unterhalb der Rampe → day_factor=0.0

# ── day_factor ───────────────────────────────────────────────────────────────


def test_day_factor_below_ramp_is_zero():
    assert day_factor(DAY_RAMP_START_DEG - 1) == 0.0
    assert day_factor(NIGHT) == 0.0


def test_day_factor_above_ramp_is_one():
    assert day_factor(DAY_RAMP_END_DEG + 1) == 1.0
    assert day_factor(DAY) == 1.0


def test_day_factor_at_horizon_is_midpoint():
    # Ramp ist symmetrisch um 0° (Sonnenaufgang/-untergang) → exakt 0.5.
    assert day_factor(0.0) == pytest.approx(0.5)


def test_day_factor_linear_between_bounds():
    quarter = DAY_RAMP_START_DEG + (DAY_RAMP_END_DEG - DAY_RAMP_START_DEG) * 0.25
    assert day_factor(quarter) == pytest.approx(0.25)


# ── shade_compensation ────────────────────────────────────────────────────


def test_shade_compensation_no_shade_is_neutral():
    # Volle Sonne (kein Dauerschatten) → Kompensation 1.0, unverändertes Verhalten.
    assert shade_compensation(1.0) == pytest.approx(1.0)


def test_shade_compensation_scales_with_shade():
    # Bei efficiency=0.3 (70 % Dauerschatten): Kompensation = 1 + BOOST_MAX*(1-0.3).
    expected = 1.0 + SHADE_BOOST_MAX * 0.7
    assert shade_compensation(0.3) == pytest.approx(expected)


def test_shade_compensation_max_shade():
    expected = 1.0 + SHADE_BOOST_MAX * (1.0 - LAWN_SUN_EFFICIENCY_MIN)
    assert shade_compensation(LAWN_SUN_EFFICIENCY_MIN) == pytest.approx(expected)


def test_shade_compensation_clamped_to_valid_range():
    # Werte außerhalb [0.1, 1.0] (Sensorfehler) dürfen nicht extrapolieren.
    assert shade_compensation(1.5) == pytest.approx(1.0)
    assert shade_compensation(0.0) == pytest.approx(shade_compensation(LAWN_SUN_EFFICIENCY_MIN))


# ── penman_drying ──────────────────────────────────────────────────────────


def test_penman_drying_peak_sun_no_wind():
    result = penman_drying(eff_solar=1.0, vpd_c=0.0, wind_kmh=0.0, sun_elevation_deg=DAY)
    assert result == pytest.approx(0.030)


def test_penman_drying_all_zero():
    result = penman_drying(eff_solar=0.0, vpd_c=0.0, wind_kmh=0.0, sun_elevation_deg=NIGHT)
    assert result == 0.0


def test_penman_drying_temp_term():
    # Echte Nacht (sun_elevation weit unter Horizont) → Basis-VPD-Term auf
    # NIGHT_DRYING_FLOOR gedämpft.
    result = penman_drying(eff_solar=0.0, vpd_c=10.0, wind_kmh=0.0, sun_elevation_deg=NIGHT)
    assert result == pytest.approx(NIGHT_DRYING_FLOOR * 0.010)


def test_penman_drying_wind_needs_vpd():
    # Wind×VPD-Kopplung: Wind ohne VPD (gesättigte/feuchte Luft) → kein Beitrag.
    # Schützt vor Über-Trocknung bei Nebel/Nacht.
    result = penman_drying(eff_solar=0.0, vpd_c=0.0, wind_kmh=20.0, sun_elevation_deg=DAY)
    assert result == 0.0


def test_penman_drying_wind_couples_to_vpd():
    # Wind verstärkt den VPD-Term multiplikativ: (K_TEMP + K_WIND_VPD·wind)·VPD
    # Echte Nacht → zusätzlich auf NIGHT_DRYING_FLOOR gedämpft.
    result = penman_drying(eff_solar=0.0, vpd_c=10.0, wind_kmh=20.0, sun_elevation_deg=NIGHT)
    assert result == pytest.approx(NIGHT_DRYING_FLOOR * (0.001 + 0.0003 * 20) * 10)


def test_penman_drying_windy_dries_more_than_calm():
    # Bei trockener Luft (hohe VPD) trocknet es mit Wind deutlich mehr als ohne.
    calm = penman_drying(eff_solar=0.3, vpd_c=9.0, wind_kmh=0.0, sun_elevation_deg=DAY)
    windy = penman_drying(eff_solar=0.3, vpd_c=9.0, wind_kmh=15.0, sun_elevation_deg=DAY)
    assert windy > calm * 1.3


def test_penman_drying_negative_vpd_clamped():
    # VPD negativ → Wind-Term ebenfalls 0 (kein Trocknen bei Sättigung)
    result = penman_drying(eff_solar=0.0, vpd_c=-5.0, wind_kmh=20.0, sun_elevation_deg=DAY)
    assert result == 0.0


def test_penman_drying_full_combination():
    # K_SOLAR·eff + aero_factor(sun_elevation)·(K_TEMP + K_WIND_VPD·wind)·VPD
    # Voller Tag → aero_factor = 1.0, UNABHÄNGIG vom (ggf. beschatteten) eff_solar=0.7.
    expected = 0.030 * 0.7 + 1.0 * (0.001 + 0.0003 * 15.0) * 8.0
    result = penman_drying(eff_solar=0.7, vpd_c=8.0, wind_kmh=15.0, sun_elevation_deg=DAY)
    assert result == pytest.approx(expected)


def test_penman_drying_cloudy_shaded_day_dries_much_more_than_true_night():
    """Regressionstest für den gemeldeten Bug: an einem echten (aber bewölkten/
    beschatteten) Tag mit eff_solar=0.0 darf der Wind/VPD-Term NICHT auf den
    Nacht-Wert fallen — nur der SONNENSTAND entscheidet über Tag/Nacht, nicht
    eff_solar (das Wolken UND lokale Beschattung enthält)."""
    cloudy_shaded_day = penman_drying(
        eff_solar=0.0, vpd_c=6.6, wind_kmh=5.8, sun_elevation_deg=DAY
    )
    true_night = penman_drying(eff_solar=0.0, vpd_c=6.6, wind_kmh=5.8, sun_elevation_deg=NIGHT)
    assert cloudy_shaded_day == pytest.approx(true_night / NIGHT_DRYING_FLOOR)
    assert cloudy_shaded_day > true_night * 5


def test_penman_drying_default_efficiency_is_neutral():
    """Ohne explizites efficiency-Argument keine Schatten-Kompensation (Default 1.0)
    → identisch zum expliziten efficiency=1.0."""
    explicit = penman_drying(
        eff_solar=0.5, vpd_c=8.0, wind_kmh=10.0, sun_elevation_deg=DAY, efficiency=1.0
    )
    default = penman_drying(eff_solar=0.5, vpd_c=8.0, wind_kmh=10.0, sun_elevation_deg=DAY)
    assert explicit == default


def test_penman_drying_shade_compensation_scales_pure_aero_term():
    """Kernfall der K-Konstanten-Anpassung: die Kompensation wirkt NUR auf den
    Aero-Term (Solar-Term=0 via eff_solar=0.0, isoliert die Wirkung)."""
    compensated = penman_drying(
        eff_solar=0.0, vpd_c=6.6, wind_kmh=5.8, sun_elevation_deg=DAY, efficiency=0.3
    )
    uncompensated = penman_drying(
        eff_solar=0.0, vpd_c=6.6, wind_kmh=5.8, sun_elevation_deg=DAY, efficiency=1.0
    )
    assert compensated == pytest.approx(uncompensated * shade_compensation(0.3))
    assert compensated > uncompensated * 2


# ── Temperaturabhängiger VPD (v0.5.0) ──────────────────────────────────────


def test_temp_20c_is_reference_unchanged():
    """Bei 20 °C (Referenz) ist die Trocknung identisch zum Aufruf ohne temp_c.
    Garantiert: Durchschnittstage bleiben gegenüber dem alten Modell unverändert."""
    explicit = penman_drying(
        eff_solar=0.3, vpd_c=8.0, wind_kmh=15.0, sun_elevation_deg=DAY, temp_c=20.0
    )
    default = penman_drying(eff_solar=0.3, vpd_c=8.0, wind_kmh=15.0, sun_elevation_deg=DAY)
    assert explicit == default


def test_warm_air_dries_aero_faster():
    """25 °C → aerodynamischer Term ~×1.355 vs. 20 °C (es(25)/es(20))."""
    # eff_solar=0 (Solar-Term=0), voller Tag → Temperaturfaktor am reinen Aero-Term sichtbar
    ref = penman_drying(
        eff_solar=0.0, vpd_c=8.0, wind_kmh=10.0, sun_elevation_deg=DAY, temp_c=20.0
    )
    warm = penman_drying(
        eff_solar=0.0, vpd_c=8.0, wind_kmh=10.0, sun_elevation_deg=DAY, temp_c=25.0
    )
    assert warm == pytest.approx(ref * 1.355, rel=0.02)


def test_cold_air_dries_aero_slower():
    """12 °C → aerodynamischer Term ~×0.60 vs. 20 °C — kühl = vorsichtiger."""
    ref = penman_drying(
        eff_solar=0.0, vpd_c=8.0, wind_kmh=10.0, sun_elevation_deg=DAY, temp_c=20.0
    )
    cold = penman_drying(
        eff_solar=0.0, vpd_c=8.0, wind_kmh=10.0, sun_elevation_deg=DAY, temp_c=12.0
    )
    assert cold == pytest.approx(ref * 0.600, rel=0.02)


def test_solar_term_independent_of_temp():
    """Nur der Aero-Term ist temperaturabhängig — der Solar-Term nicht."""
    # vpd_c=0 → kein Aero-Term, reiner Solar-Term; Temperatur darf nichts ändern
    cool = penman_drying(
        eff_solar=1.0, vpd_c=0.0, wind_kmh=0.0, sun_elevation_deg=DAY, temp_c=15.0
    )
    hot = penman_drying(eff_solar=1.0, vpd_c=0.0, wind_kmh=0.0, sun_elevation_deg=DAY, temp_c=30.0)
    assert cool == hot == pytest.approx(0.030)


# ── Nächtliche Trocknungs-Dämpfung (v0.4.3b3, korrigiert v1.2.0) ───────────


def test_night_damps_aerodynamic_term():
    # Echte Nacht (sun_elevation weit unter Horizont): aerodynamischer Term auf
    # NIGHT_DRYING_FLOOR gedämpft, weil keine Strahlungsenergie die Verdunstung antreibt.
    full_aero = (0.001 + 0.0003 * 20.0) * 10.0
    result = penman_drying(eff_solar=0.0, vpd_c=10.0, wind_kmh=20.0, sun_elevation_deg=NIGHT)
    assert result == pytest.approx(NIGHT_DRYING_FLOOR * full_aero)


def test_full_sun_aerodynamic_unchanged():
    # Voller Tag: aero_factor=1.0 → unverändert (Solar + voller Aero).
    expected = 0.030 + (0.001 + 0.0003 * 20.0) * 10.0
    result = penman_drying(eff_solar=1.0, vpd_c=10.0, wind_kmh=20.0, sun_elevation_deg=DAY)
    assert result == pytest.approx(expected)


def test_dusk_ramps_aerodynamic():
    # Sonnenuntergang (sun_elevation=0°, day_factor=0.5): glatte Rampe, kein
    # Tag/Nacht-Sprung. eff_solar=0.5 rein zufällig gleich (z. B. Restlicht) —
    # steuert nur noch den Solar-Term, NICHT mehr den Aero-Übergang.
    aero_factor = NIGHT_DRYING_FLOOR + (1.0 - NIGHT_DRYING_FLOOR) * 0.5
    expected = 0.030 * 0.5 + aero_factor * (0.001 + 0.0003 * 20.0) * 10.0
    result = penman_drying(eff_solar=0.5, vpd_c=10.0, wind_kmh=20.0, sun_elevation_deg=0.0)
    assert result == pytest.approx(expected)


def test_night_wind_strongly_reduced_vs_day():
    # Realszenario 2026-06-14/15: VPD 5.5, Wind 13 km/h.
    # Nachts darf der Wind den Rasen nicht annähernd so stark trocknen wie tags.
    night = penman_drying(eff_solar=0.0, vpd_c=5.5, wind_kmh=13.0, sun_elevation_deg=NIGHT)
    day = penman_drying(eff_solar=1.0, vpd_c=5.5, wind_kmh=13.0, sun_elevation_deg=DAY)
    assert night < day * 0.25


# ── condensation ───────────────────────────────────────────────────────────


def test_condensation_at_dew_offset():
    result = condensation(vpd_c=2.9)
    assert result == pytest.approx(0.003 * 0.1)


def test_condensation_zero_at_dew_point():
    result = condensation(vpd_c=3.0)
    assert result == 0.0


def test_condensation_above_dew_offset_zero():
    result = condensation(vpd_c=5.0)
    assert result == 0.0


def test_condensation_negative_vpd():
    # VPD = -2°C: K_COND * (3.0 - (-2.0)) = 0.003 * 5.0
    result = condensation(vpd_c=-2.0)
    assert result == pytest.approx(0.003 * 5.0)


def test_condensation_max_reasonable():
    # VPD = 0: K_COND * DEW_OFFSET = 0.003 * 3.0
    result = condensation(vpd_c=0.0)
    assert result == pytest.approx(0.003 * 3.0)
