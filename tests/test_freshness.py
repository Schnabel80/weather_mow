"""Tests für freshness.py — Stale-Erkennung der Wetter-/Stationsdaten (HA-frei)."""

from __future__ import annotations

from custom_components.weather_mow.freshness import weather_data_stale

THRESHOLD_S = 3600.0  # 60 min


class TestWeatherDataStale:
    def test_no_inputs_configured_not_stale(self):
        # Keine Stations-Eingänge konfiguriert → keine Aussage, nicht veraltet.
        assert weather_data_stale([], THRESHOLD_S) is False

    def test_all_fresh_not_stale(self):
        assert weather_data_stale([10.0, 30.0, 120.0], THRESHOLD_S) is False

    def test_all_old_is_stale(self):
        # Alle Eingänge älter als 60 min → Station tot.
        assert weather_data_stale([4000.0, 5000.0, 90000.0], THRESHOLD_S) is True

    def test_one_fresh_input_prevents_stale(self):
        # Ein noch frischer Sensor (z. B. Wind) → Station lebt, kein Alarm,
        # auch wenn ein anderer (Strahlung nachts) uralt wirkt.
        assert weather_data_stale([30.0, 90000.0], THRESHOLD_S) is False

    def test_unavailable_input_counts_as_stale(self):
        # Konfiguriert, liefert aber nichts (None) → gilt als veraltet.
        assert weather_data_stale([None, None], THRESHOLD_S) is True

    def test_unavailable_but_one_fresh_not_stale(self):
        assert weather_data_stale([None, 30.0], THRESHOLD_S) is False

    def test_exactly_at_threshold_not_stale(self):
        # Genau auf der Schwelle zählt noch als frisch (strikt größer).
        assert weather_data_stale([THRESHOLD_S, THRESHOLD_S], THRESHOLD_S) is False
