"""Tests für scheduling.py — Morgen-Zurückhaltung (HA-frei)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.weather_mow.scheduling import (
    RAIN_HOUR_BLOCK_MM,
    enough_time_after_hold,
    usable_mow_hours,
)


def _h(hour: int) -> datetime:
    """Stunde als UTC-datetime am 22.08.2026."""
    return datetime(2026, 8, 22, hour, 0, tzinfo=UTC)


def _series(entries: list[tuple[int, float, float]]):
    """(stunde, regen_mm, temp_c) → Forecast-Liste."""
    return [(_h(hour), rain, temp) for hour, rain, temp in entries]


class TestUsableMowHours:
    def test_all_hours_usable(self):
        fc = _series([(8, 0.0, 18.0), (9, 0.0, 19.0), (10, 0.0, 20.0)])
        assert usable_mow_hours(fc, _h(8), _h(11), max_temp_c=35.0) == pytest.approx(3.0)

    def test_empty_forecast_is_zero(self):
        assert usable_mow_hours([], _h(8), _h(20), max_temp_c=35.0) == 0.0

    def test_rainy_hours_excluded(self):
        # Genau auf der Sperrschwelle → unbrauchbar, knapp darunter → nutzbar.
        fc = _series(
            [
                (8, 0.0, 18.0),
                (9, RAIN_HOUR_BLOCK_MM, 18.0),
                (10, 1.5, 18.0),
                (11, RAIN_HOUR_BLOCK_MM / 2, 18.0),
            ]
        )
        assert usable_mow_hours(fc, _h(8), _h(12), max_temp_c=35.0) == pytest.approx(2.0)

    def test_hot_hours_excluded(self):
        # Temperatur >= max_temp_c → unbrauchbar (identisch zum Hitze-Gate).
        fc = _series([(8, 0.0, 29.9), (9, 0.0, 35.0), (10, 0.0, 38.0)])
        assert usable_mow_hours(fc, _h(8), _h(11), max_temp_c=35.0) == pytest.approx(1.0)

    def test_window_clips_outside_hours(self):
        fc = _series([(6, 0.0, 18.0), (10, 0.0, 18.0), (14, 0.0, 18.0), (22, 0.0, 18.0)])
        # Fenster [10, 15) → nur 10 und 14 zählen.
        assert usable_mow_hours(fc, _h(10), _h(15), max_temp_c=35.0) == pytest.approx(2.0)

    def test_window_end_is_exclusive(self):
        fc = _series([(10, 0.0, 18.0), (11, 0.0, 18.0)])
        assert usable_mow_hours(fc, _h(10), _h(11), max_temp_c=35.0) == pytest.approx(1.0)

    def test_persistent_rain_leaves_nothing(self):
        """Nutzerbeispiel: ab 10 Uhr dauerhaft Regen → keine nutzbare Stunde."""
        fc = _series([(h, 1.0, 18.0) for h in range(10, 20)])
        assert usable_mow_hours(fc, _h(10), _h(20), max_temp_c=35.0) == 0.0

    def test_afternoon_heat_leaves_little(self):
        """Nutzerbeispiel: ab 12 Uhr sehr heiß → nur die kühlen Stunden zählen."""
        fc = _series([(10, 0.0, 28.0), (11, 0.0, 31.0)] + [(h, 0.0, 36.0) for h in range(12, 20)])
        assert usable_mow_hours(fc, _h(10), _h(20), max_temp_c=35.0) == pytest.approx(2.0)

    def test_real_case_2026_08_22_plenty_of_time(self):
        """Echtdaten 22.08.: nur eine Nieselstunde (0,24 mm), max. 20,9 °C → viel Zeit."""
        fc = _series(
            [
                (10, 0.24, 16.8),
                (11, 0.0, 17.0),
                (12, 0.0, 17.2),
                (13, 0.0, 17.8),
                (14, 0.0, 18.5),
                (15, 0.0, 19.6),
                (16, 0.0, 20.0),
                (17, 0.0, 19.8),
                (18, 0.0, 20.9),
                (19, 0.0, 19.9),
            ]
        )
        assert usable_mow_hours(fc, _h(10), _h(20), max_temp_c=35.0) == pytest.approx(9.0)

    def test_naive_and_aware_datetimes_do_not_crash(self):
        """Gemischte tz-Info (Sensor-Pfad kann naive Zeiten liefern) → kein Crash."""
        fc = [(datetime(2026, 8, 22, 10, 0), 0.0, 18.0)]
        result = usable_mow_hours(fc, _h(8), _h(20), max_temp_c=35.0)
        assert isinstance(result, float)


class TestEnoughTimeAfterHold:
    def test_plenty_of_time_allows_hold(self):
        # 9 nutzbare Stunden bei 2.5 h Bedarf (×1.5 = 3.75) → warten ist vertretbar.
        assert enough_time_after_hold(9.0, 2.5, safety_factor=1.5) is True

    def test_too_little_time_forces_start(self):
        assert enough_time_after_hold(3.0, 2.5, safety_factor=1.5) is False

    def test_exactly_at_safety_margin_allows_hold(self):
        assert enough_time_after_hold(3.75, 2.5, safety_factor=1.5) is True

    def test_no_remaining_need_allows_hold(self):
        # Tagesziel bereits erfüllt → kein Grund für einen frühen Start.
        assert enough_time_after_hold(0.0, 0.0, safety_factor=1.5) is True

    def test_zero_usable_hours_forces_start(self):
        """Dauerregen/Dauerhitze ab Wunschzeit → jetzt losfahren."""
        assert enough_time_after_hold(0.0, 2.5, safety_factor=1.5) is False
