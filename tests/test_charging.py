"""Tests für charging.py — Laderaten-Lernen (HA-frei)."""

from __future__ import annotations

import pytest

from custom_components.weather_mow.charging import (
    BATTERY_CEILING_MIN_PCT,
    BATTERY_CEILING_WARN_PCT,
    CHARGE_RATE_MAX,
    CHARGE_RATE_MIN,
    DEFAULT_CHARGE_RATE_PCT_PER_MIN,
    battery_ceiling_warning,
    learn_battery_ceiling,
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


class TestLearnBatteryCeiling:
    def test_healthy_full_kept(self):
        # Gesunder Mäher plateaut bei 100 % → unverändert übernommen.
        assert learn_battery_ceiling(100.0) == pytest.approx(100.0)

    def test_indego_plateau_at_93_learned(self):
        # Bosch Indego erreicht real nur 93 % → genau dieser Wert wird gelernt.
        assert learn_battery_ceiling(93.0) == pytest.approx(93.0)

    def test_user_charge_limit_80_learned(self):
        # Am Gerät gesetztes 80-%-Ladelimit → 80 % wird die neue Decke.
        assert learn_battery_ceiling(80.0) == pytest.approx(80.0)

    def test_above_100_clamped(self):
        # Sensor-Ausreißer > 100 % wird gekappt.
        assert learn_battery_ceiling(103.0) == pytest.approx(100.0)

    def test_implausibly_low_clamped_to_floor(self):
        # Unplausibel niedriges Plateau (Sensor-Glitch) auf harten Boden geklammert.
        assert learn_battery_ceiling(30.0) == pytest.approx(BATTERY_CEILING_MIN_PCT)


class TestBatteryCeilingWarning:
    def test_healthy_no_warning(self):
        assert battery_ceiling_warning(93.0) is False

    def test_at_warn_threshold_no_warning(self):
        assert battery_ceiling_warning(BATTERY_CEILING_WARN_PCT) is False

    def test_below_warn_threshold_warns(self):
        assert battery_ceiling_warning(BATTERY_CEILING_WARN_PCT - 1) is True
