"""Unit-Tests für die schattenkorrigierte Trocknungs-Berechnung (drying.py)."""

import sys
from datetime import time as dt_time
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "weather_mow"),
)

from drying import effective_solar_factor


def test_no_shade_returns_full_solar_factor():
    # Volle Sonne, 100 % Effizienz, ab Mitternacht aktiv
    assert effective_solar_factor(0.8, 1.0, dt_time(0, 0), dt_time(14, 0)) == 0.8


def test_efficiency_scales_linearly():
    # 50 % Effizienz halbiert den effektiven Solar-Faktor
    assert effective_solar_factor(0.8, 0.5, dt_time(0, 0), dt_time(14, 0)) == pytest.approx(0.4)


def test_before_lawn_sun_from_returns_zero():
    # Sonne erreicht den Rasen erst ab 11:00 — um 09:30 zählt sie nicht
    assert effective_solar_factor(0.8, 0.7, dt_time(11, 0), dt_time(9, 30)) == 0.0


def test_after_lawn_sun_from_applies_efficiency():
    # Ab 11:00 zählt die Sonne mit 70 % Effizienz
    assert effective_solar_factor(0.8, 0.7, dt_time(11, 0), dt_time(12, 0)) == pytest.approx(0.56)


def test_exactly_at_lawn_sun_from_counts():
    # Genau zur Schwellzeit zählt die Sonne bereits (inklusiv)
    assert effective_solar_factor(1.0, 1.0, dt_time(11, 0), dt_time(11, 0)) == 1.0


def test_zero_solar_factor_stays_zero():
    # Nachts (solar_factor=0) bleibt das Ergebnis 0, egal welche Konfig
    assert effective_solar_factor(0.0, 0.7, dt_time(0, 0), dt_time(3, 0)) == 0.0


def test_efficiency_clamped_to_min():
    # Effizienz unter 0.1 wird auf 0.1 hochgesetzt (Sicherheits-Floor)
    assert effective_solar_factor(1.0, 0.0, dt_time(0, 0), dt_time(14, 0)) == pytest.approx(0.1)


def test_efficiency_clamped_to_max():
    # Effizienz über 1.0 wird auf 1.0 begrenzt
    assert effective_solar_factor(1.0, 1.5, dt_time(0, 0), dt_time(14, 0)) == 1.0
