"""Unit-Tests für das physikalische Nässe-Modell (wetness.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "weather_mow"),
)

from wetness import condensation, penman_drying

# ── penman_drying ──────────────────────────────────────────────────────────


def test_penman_drying_peak_sun_no_wind():
    result = penman_drying(eff_solar=1.0, vpd_c=0.0, wind_kmh=0.0)
    assert result == pytest.approx(0.030)


def test_penman_drying_all_zero():
    result = penman_drying(eff_solar=0.0, vpd_c=0.0, wind_kmh=0.0)
    assert result == 0.0


def test_penman_drying_temp_term():
    result = penman_drying(eff_solar=0.0, vpd_c=10.0, wind_kmh=0.0)
    assert result == pytest.approx(0.010)


def test_penman_drying_wind_needs_vpd():
    # Wind×VPD-Kopplung: Wind ohne VPD (gesättigte/feuchte Luft) → kein Beitrag.
    # Schützt vor Über-Trocknung bei Nebel/Nacht.
    result = penman_drying(eff_solar=0.0, vpd_c=0.0, wind_kmh=20.0)
    assert result == 0.0


def test_penman_drying_wind_couples_to_vpd():
    # Wind verstärkt den VPD-Term multiplikativ: (K_TEMP + K_WIND_VPD·wind)·VPD
    # eff=0, vpd=10, wind=20 → (0.001 + 0.0003·20)·10 = 0.07
    result = penman_drying(eff_solar=0.0, vpd_c=10.0, wind_kmh=20.0)
    assert result == pytest.approx((0.001 + 0.0003 * 20) * 10)


def test_penman_drying_windy_dries_more_than_calm():
    # Bei trockener Luft (hohe VPD) trocknet es mit Wind deutlich mehr als ohne.
    calm = penman_drying(eff_solar=0.3, vpd_c=9.0, wind_kmh=0.0)
    windy = penman_drying(eff_solar=0.3, vpd_c=9.0, wind_kmh=15.0)
    assert windy > calm * 1.3


def test_penman_drying_negative_vpd_clamped():
    # VPD negativ → Wind-Term ebenfalls 0 (kein Trocknen bei Sättigung)
    result = penman_drying(eff_solar=0.0, vpd_c=-5.0, wind_kmh=20.0)
    assert result == 0.0


def test_penman_drying_full_combination():
    # K_SOLAR·eff + (K_TEMP + K_WIND_VPD·wind)·VPD
    expected = 0.030 * 0.7 + (0.001 + 0.0003 * 15.0) * 8.0
    result = penman_drying(eff_solar=0.7, vpd_c=8.0, wind_kmh=15.0)
    assert result == pytest.approx(expected)


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
