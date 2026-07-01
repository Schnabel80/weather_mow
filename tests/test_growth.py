"""Unit-Tests für das physikalische Wachstumsmodell (growth.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "weather_mow"),
)

from const import (
    GDD_BASE_TEMP_C,
    GDD_MAX_TEMP_C,
    GDD_OPT_TEMP_C,
    GROWTH_MOISTURE_FLOOR,
    GROWTH_MOISTURE_REF_MM,
)
from growth import moisture_factor, temperature_response

# ── temperature_response (Kardinaltemperatur-Dreieck) ──────────────────────


def test_temp_below_base_is_zero():
    assert temperature_response(GDD_BASE_TEMP_C - 1) == 0.0
    assert temperature_response(GDD_BASE_TEMP_C) == 0.0


def test_temp_at_or_above_max_is_zero():
    assert temperature_response(GDD_MAX_TEMP_C) == 0.0
    assert temperature_response(GDD_MAX_TEMP_C + 2) == 0.0


def test_below_optimum_matches_old_linear_model():
    # Unterhalb des Optimums identisch zum alten Modell (T − Basis).
    for t in (8.0, 12.0, 18.0, GDD_OPT_TEMP_C):
        assert temperature_response(t) == pytest.approx(t - GDD_BASE_TEMP_C)


def test_peak_at_optimum():
    peak = GDD_OPT_TEMP_C - GDD_BASE_TEMP_C
    assert temperature_response(GDD_OPT_TEMP_C) == pytest.approx(peak)
    # Knapp über dem Optimum bereits niedriger als das Maximum.
    assert temperature_response(GDD_OPT_TEMP_C + 1) < peak


def test_declines_above_optimum_to_zero_at_max():
    # 25 °C: linearer Abfall vom Peak (bei 20) auf 0 (bei 31).
    peak = GDD_OPT_TEMP_C - GDD_BASE_TEMP_C
    expected = peak * (GDD_MAX_TEMP_C - 25.0) / (GDD_MAX_TEMP_C - GDD_OPT_TEMP_C)
    assert temperature_response(25.0) == pytest.approx(expected)
    # Monoton fallend zwischen Optimum und Max.
    assert temperature_response(22.0) > temperature_response(28.0) > 0.0


# ── moisture_factor (Trockendormanz) ───────────────────────────────────────


def test_moisture_dry_is_floor():
    assert moisture_factor(0.0, 0.0) == pytest.approx(GROWTH_MOISTURE_FLOOR)


def test_moisture_wet_is_full():
    # Reichlich Wasser (Regen + Feuchte) → voller Faktor 1.0.
    assert moisture_factor(rain_12h_mm=5.0, wetness_mm=1.5) == pytest.approx(1.0)


def test_moisture_monotonic_between_floor_and_one():
    dry = moisture_factor(0.0, 0.1)
    mid = moisture_factor(1.0, 0.3)
    wet = moisture_factor(3.0, 1.0)
    assert GROWTH_MOISTURE_FLOOR <= dry < mid < wet <= 1.0


def test_moisture_negative_inputs_clamped():
    assert moisture_factor(-5.0, -1.0) == pytest.approx(GROWTH_MOISTURE_FLOOR)


def test_normal_day_with_dew_reaches_full_growth():
    """Befund 3 (mildere Kalibrierung): Ein normaler Tag mit etwas Tau/Restfeuchte
    (Wassersumme ≥ REF) erreicht vollen Wuchs — die Dämpfung greift nur bei echter
    Dürre. Egal ob das Wasser aus Regen oder Oberflächenfeuchte stammt."""
    assert moisture_factor(0.0, GROWTH_MOISTURE_REF_MM) == pytest.approx(1.0)
    assert moisture_factor(GROWTH_MOISTURE_REF_MM, 0.0) == pytest.approx(1.0)
    # Knapp darüber bleibt voll (kein Überschwingen).
    assert moisture_factor(0.0, GROWTH_MOISTURE_REF_MM + 1.0) == pytest.approx(1.0)
