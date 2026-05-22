"""Unit-Tests für die Regen-Normalisierung (rain_input.py)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "weather_mow"))

import rain_input  # noqa: E402
from rain_input import (  # noqa: E402
    RainNormalizer,
    cumulative_delta,
    rate_to_slot_mm,
    resolve_rain_mode,
)


def test_cumulative_delta_normal():
    assert cumulative_delta(5.0, 3.0) == 2.0


def test_cumulative_delta_first_reading():
    assert cumulative_delta(5.0, None) == 0.0


def test_cumulative_delta_reset():
    # Zähler fällt (Mitternachts-Reset) -> aktueller Wert gilt als Regen seit Reset
    assert cumulative_delta(0.4, 12.0) == 0.4


def test_rate_to_slot_mm():
    # 6 mm/h über 5 min = 0,5 mm
    assert rate_to_slot_mm(6.0, 5.0) == pytest.approx(0.5)


def test_rate_to_slot_mm_negative_clamped():
    assert rate_to_slot_mm(-2.0, 5.0) == 0.0


def test_resolve_rain_mode_ecowitt():
    assert resolve_rain_mode(rain_input.RAIN_PROVIDER_ECOWITT, None) == rain_input.RAIN_MODE_CUMULATIVE


def test_resolve_rain_mode_netatmo():
    assert resolve_rain_mode(rain_input.RAIN_PROVIDER_NETATMO, None) == rain_input.RAIN_MODE_INTERVAL


def test_resolve_rain_mode_other_uses_sensor_type():
    assert resolve_rain_mode(rain_input.RAIN_PROVIDER_OTHER, rain_input.RAIN_MODE_RATE) == rain_input.RAIN_MODE_RATE


def test_resolve_rain_mode_other_invalid():
    assert resolve_rain_mode(rain_input.RAIN_PROVIDER_OTHER, None) is None


def test_resolve_rain_mode_none():
    assert resolve_rain_mode(rain_input.RAIN_PROVIDER_NONE, None) is None


def test_normalizer_cumulative():
    n = RainNormalizer(rain_input.RAIN_MODE_CUMULATIVE)
    assert n.slot_mm(10.0, 100.0, 5.0) == 0.0          # erste Ablesung
    assert n.slot_mm(10.6, 200.0, 5.0) == pytest.approx(0.6)
    assert n.slot_mm(10.6, 300.0, 5.0) == 0.0          # kein neuer Regen


def test_normalizer_rate():
    n = RainNormalizer(rain_input.RAIN_MODE_RATE)
    assert n.slot_mm(12.0, 100.0, 5.0) == pytest.approx(1.0)
    assert n.slot_mm(12.0, 200.0, 5.0) == pytest.approx(1.0)


def test_normalizer_interval_dedup():
    n = RainNormalizer(rain_input.RAIN_MODE_INTERVAL)
    assert n.slot_mm(0.3, 100.0, 5.0) == pytest.approx(0.3)
    assert n.slot_mm(0.3, 100.0, 5.0) == 0.0           # gleiche Ablesung -> nicht doppelt
    assert n.slot_mm(0.2, 160.0, 5.0) == pytest.approx(0.2)


def test_normalizer_prime_cumulative():
    n = RainNormalizer(rain_input.RAIN_MODE_CUMULATIVE)
    n.prime(8.0, 50.0)
    assert n.slot_mm(8.5, 100.0, 5.0) == pytest.approx(0.5)
