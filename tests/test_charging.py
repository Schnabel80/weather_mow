"""Tests für charging.py — Laderaten-Lernen (HA-frei)."""

from __future__ import annotations

import pytest

from custom_components.weather_mow.charging import (
    CHARGE_RATE_MAX,
    CHARGE_RATE_MIN,
    DEFAULT_CHARGE_RATE_PCT_PER_MIN,
    learn_charge_rate,
    minutes_to_target,
)


class TestLearnChargeRate:
    def test_first_measurement_below_60_no_change(self):
        rate, learned = learn_charge_rate(
            DEFAULT_CHARGE_RATE_PCT_PER_MIN, False, measured_rate=0.9, rise_pct=50.0
        )
        assert rate == pytest.approx(DEFAULT_CHARGE_RATE_PCT_PER_MIN)
        assert learned is False

    def test_first_measurement_at_60_replaces_default(self):
        rate, learned = learn_charge_rate(
            DEFAULT_CHARGE_RATE_PCT_PER_MIN, False, measured_rate=1.5, rise_pct=60.0
        )
        assert rate == pytest.approx(1.5)
        assert learned is True

    def test_subsequent_below_20_no_change(self):
        rate, learned = learn_charge_rate(1.5, True, measured_rate=0.5, rise_pct=15.0)
        assert rate == pytest.approx(1.5)
        assert learned is True

    def test_subsequent_at_20_uses_ema(self):
        rate, learned = learn_charge_rate(1.5, True, measured_rate=1.0, rise_pct=20.0)
        assert rate == pytest.approx(1.4)
        assert learned is True

    def test_clamped_to_max(self):
        rate, learned = learn_charge_rate(1.0, False, measured_rate=99.0, rise_pct=80.0)
        assert rate == pytest.approx(CHARGE_RATE_MAX)
        assert learned is True

    def test_clamped_to_min(self):
        rate, learned = learn_charge_rate(1.0, False, measured_rate=0.01, rise_pct=80.0)
        assert rate == pytest.approx(CHARGE_RATE_MIN)
        assert learned is True


class TestMinutesToTarget:
    def test_normal(self):
        assert minutes_to_target(66.0, 80.0, 1.0) == pytest.approx(14.0)

    def test_already_above_target(self):
        assert minutes_to_target(85.0, 80.0, 1.0) == 0.0

    def test_zero_rate_returns_zero(self):
        assert minutes_to_target(50.0, 80.0, 0.0) == 0.0
