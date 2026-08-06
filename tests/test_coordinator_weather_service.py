"""Tests für _parse_weather_entity_forecasts und weitere verstreute Blöcke.

Deckt ab: Weather-Service-Call, _get_temp_humidity Edge Cases,
_check_brightness, Zeit-Fenster-Grenzen, stop_now-Pfade, Batterie-Check.
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.weather_mow.const import RAIN_BUFFER_MAXLEN
from custom_components.weather_mow.coordinator import WeatherMowCoordinator

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def entry():
    e = MagicMock()
    e.entry_id = "ws_test"
    e.data = {
        "name": "Test",
        "mower_entity_id": "lawn_mower.test",
        "weather_entity_id": "weather.test",
        "rain_sensor_entity_id": "",
        "rain_1h_sensor_entity_id": "",
        "rain_today_sensor_entity_id": "",
        "rain_detector_entity_id": "",
        "outdoor_temp_entity_id": "",
        "outdoor_humidity_entity_id": "",
        "wind_sensor_entity_id": "",
        "local_radiation_entity_id": "",
        "brightness_entity_id": "",
        "radiation_source": "sun",
    }
    e.options = {
        "mow_window_start": "00:00:00",
        "mow_window_end": "23:59:00",
        "target_buffer_h": 0.0,
    }
    return e


@pytest.fixture
async def coord(hass, entry):
    c = WeatherMowCoordinator(hass, entry)
    with patch.object(c, "_load_storage"), patch.object(c, "_register_listeners"):
        await c._async_setup()
    c._sunshine_initialized = True
    c._duration_yesterday_s = 9000.0
    c._duration_day_before_s = 9000.0
    sw = MagicMock()
    sw.is_on = True
    c.switch_entity = sw
    yield c


def _weather_state(hass, temp=20.0, humidity=60, wind=5.0):
    hass.states.async_set(
        "weather.test",
        "sunny",
        attributes={"temperature": temp, "humidity": humidity, "wind_speed": wind, "forecast": []},
    )
    hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
    hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 100})


def _dry(coord):
    coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

    def _keep(*a, **kw):
        coord._wetness_mm = 0.0
        return 0.0, 0.0, 0.0

    return _keep


# ── _parse_weather_entity_forecasts (Service-Call) ────────────────────────────


class TestParseWeatherEntityForecasts:
    def _bare_coord(self, hass=None):
        if hass is None:
            hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "fc_svc"
        entry.data = {"name": "Test"}
        entry.options = {}
        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c.hass = hass
        c.entry = entry
        c._hourly_precip = []
        c._hourly_radiation = []
        c._hourly_wind = []
        return c

    @pytest.mark.freeze_time("2026-06-15 12:00:00+00:00")
    async def test_service_returns_forecast_data(self, hass):
        """Service liefert Forecast → Regen und Strahlung werden verarbeitet."""
        c = self._bare_coord(hass)
        now_utc = dt_util.utcnow()
        fc_time = (now_utc + timedelta(hours=1)).isoformat()

        hass.services = MagicMock()
        hass.services.async_call = AsyncMock(
            return_value={
                "weather.test": {
                    "forecast": [
                        {
                            "datetime": fc_time,
                            "native_precipitation": 2.5,
                            "cloud_coverage": 50.0,
                            "wind_speed": 8.0,
                        }
                    ]
                }
            }
        )

        cfg = {"weather_entity_id": "weather.test"}
        r_today, _r_tomorrow, r_3h, _rad_3h = await c._parse_weather_entity_forecasts(cfg, now_utc)

        assert r_today == pytest.approx(2.5)  # In verbleibenden Stunden heute
        assert r_3h == pytest.approx(2.5)  # In nächsten 3h
        assert len(c._hourly_precip) == 1
        assert len(c._hourly_radiation) == 1

    async def test_no_weather_entity_returns_zeros(self, hass):
        """Keine weather entity → sofort (0,0,0,0)."""
        c = self._bare_coord(hass)
        cfg = {"weather_entity_id": ""}
        result = await c._parse_weather_entity_forecasts(cfg, dt_util.utcnow())
        assert result == (0.0, 0.0, 0.0, 0.0)

    async def test_service_exception_returns_zeros(self, hass):
        """Service-Exception (z.B. not found) → (0,0,0,0), kein Crash."""
        c = self._bare_coord(hass)
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock(side_effect=Exception("not found"))
        cfg = {"weather_entity_id": "weather.test"}
        result = await c._parse_weather_entity_forecasts(cfg, dt_util.utcnow())
        assert result == (0.0, 0.0, 0.0, 0.0)

    @pytest.mark.freeze_time("2026-06-15 12:00:00+00:00")
    async def test_invalid_forecast_entry_skipped(self, hass):
        """Ungültiger Forecast-Eintrag → übersprungen, kein Crash."""
        c = self._bare_coord(hass)
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock(
            return_value={
                "weather.test": {
                    "forecast": [
                        {"datetime": "not-a-date", "native_precipitation": 1.0},
                        {
                            "datetime": (dt_util.utcnow() + timedelta(hours=1)).isoformat(),
                            "native_precipitation": 0.5,
                            "cloud_coverage": 30.0,
                            "wind_speed": 5.0,
                        },
                    ]
                }
            }
        )
        cfg = {"weather_entity_id": "weather.test"}
        _r_today, _r_tomorrow, r_3h, _rad_3h = await c._parse_weather_entity_forecasts(
            cfg, dt_util.utcnow()
        )
        # Nur der gültige Eintrag gezählt
        assert r_3h == pytest.approx(0.5)


# ── _get_temp_humidity Edge Cases ─────────────────────────────────────────────


class TestGetTempHumidityEdgeCases:
    def _bare(self, hass):
        entry = MagicMock()
        entry.entry_id = "th_edge"
        entry.data = {"name": "Test"}
        entry.options = {}
        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c.hass = hass
        c.entry = entry
        return c

    def test_falls_back_to_defaults_when_all_unavailable(self):
        hass = MagicMock()
        hass.states.get.return_value = None
        c = self._bare(hass)
        cfg = {
            "weather_entity_id": "",
            "outdoor_temp_entity_id": "",
            "outdoor_humidity_entity_id": "",
        }
        temp, hum = c._get_temp_humidity(cfg)
        assert isinstance(temp, float)
        assert isinstance(hum, float)

    def test_sensor_unavailable_state_falls_back(self):
        """Sensor mit state 'unavailable' → Fallback auf Weather."""
        hass = MagicMock()
        unavail = MagicMock()
        unavail.state = "unavailable"
        weather = MagicMock()
        weather.state = "sunny"
        weather.attributes = {"temperature": 18.0, "humidity": 70.0}
        hass.states.get = lambda eid: unavail if "sensor" in eid else weather
        c = self._bare(hass)
        cfg = {
            "outdoor_temp_entity_id": "sensor.temp",
            "outdoor_humidity_entity_id": "sensor.hum",
            "weather_entity_id": "weather.test",
        }
        temp, hum = c._get_temp_humidity(cfg)
        assert temp == pytest.approx(18.0)
        assert hum == pytest.approx(70.0)


# ── _check_brightness Edge Cases ──────────────────────────────────────────────


class TestCheckBrightnessEdgeCases:
    def _bare(self, hass):
        entry = MagicMock()
        entry.entry_id = "br_edge"
        c = WeatherMowCoordinator.__new__(WeatherMowCoordinator)
        c.hass = hass
        return c

    def test_high_sun_elevation_always_bright(self):
        """Sonnenstand ≥ 10° → immer brightness_ok=True unabhängig vom Sensor."""
        hass = MagicMock()
        hass.states.get.return_value = MagicMock(state="100")  # 100 lux (unter Schwelle)
        c = self._bare(hass)
        cfg = {"brightness_entity_id": "sensor.lux", "min_brightness_lux": 2000}
        assert c._check_brightness(cfg, sun_elev=15.0) is True

    def test_low_sun_no_sensor_returns_false(self):
        """Tiefer Sonnenstand + kein Sensor → False."""
        hass = MagicMock()
        hass.states.get.return_value = None
        c = self._bare(hass)
        cfg = {"brightness_entity_id": "", "min_brightness_lux": 2000}
        assert c._check_brightness(cfg, sun_elev=5.0) is False

    def test_low_sun_sensor_above_threshold(self):
        """Tiefer Sonnenstand + Sensor über Schwelle → True."""
        hass = MagicMock()
        hass.states.get.return_value = MagicMock(state="3000")
        c = self._bare(hass)
        cfg = {"brightness_entity_id": "sensor.lux", "min_brightness_lux": 2000}
        assert c._check_brightness(cfg, sun_elev=5.0) is True

    def test_low_sun_sensor_below_threshold(self):
        """Tiefer Sonnenstand + Sensor unter Schwelle → False."""
        hass = MagicMock()
        hass.states.get.return_value = MagicMock(state="500")
        c = self._bare(hass)
        cfg = {"brightness_entity_id": "sensor.lux", "min_brightness_lux": 2000}
        assert c._check_brightness(cfg, sun_elev=5.0) is False


# ── Batterie-Check in _async_update_data ──────────────────────────────────────


class TestBatteryCheck:
    async def test_low_battery_prevents_start_not_allowed(self, hass, coord):
        """Niedriger Akku + mow_allowed → start_now=False, block=battery_low."""
        _weather_state(hass)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
        # Mäher mit niedrigem Akku
        hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 5})
        coord.entry.data = {**coord.entry.data, "min_battery_pct": 20}

        with patch.object(coord, "_update_wetness", _dry(coord)):
            data = await coord._async_update_data()

        assert data["start_now"] is False

    async def test_full_battery_allows_start(self, hass, coord):
        """Voller Akku → start_now hängt nur von Priorität ab."""
        _weather_state(hass, temp=20.0)
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)
        hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 100})

        with patch.object(coord, "_update_wetness", _dry(coord)):
            data = await coord._async_update_data()

        # Kein Battery-Block
        assert data.get("block_reason") != "battery_low"


# ── stop_now Pfade ────────────────────────────────────────────────────────────


class TestStopNow:
    async def test_stop_now_when_raining(self, hass, coord):
        """Regen erkannt + Mäher fährt → stop_now=True."""
        hass.states.async_set(
            "weather.test",
            "rainy",
            attributes={"temperature": 15.0, "humidity": 90, "wind_speed": 3.0, "forecast": []},
        )
        hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
        # Mäher fährt gerade
        hass.states.async_set("lawn_mower.test", "mowing", attributes={"battery_level": 100})

        with patch.object(
            coord,
            "_update_wetness",
            lambda *a, **kw: setattr(coord, "_wetness_mm", 0.0) or (0.0, 0.0, 0.0),
        ):
            data = await coord._async_update_data()

        # Wenn es regnet und Mäher läuft → stop_now=True
        assert data["stop_now"] is True

    async def test_no_stop_when_sunny_and_docked(self, hass, coord):
        """Kein Regen + Mäher dockt → stop_now=False."""
        hass.states.async_set(
            "weather.test",
            "sunny",
            attributes={"temperature": 20.0, "humidity": 60, "wind_speed": 5.0, "forecast": []},
        )
        hass.states.async_set("sun.sun", "above_horizon", attributes={"elevation": 45.0})
        hass.states.async_set("lawn_mower.test", "docked", attributes={"battery_level": 100})
        coord._below_threshold_since = dt_util.now() - timedelta(minutes=35)

        with patch.object(coord, "_update_wetness", _dry(coord)):
            data = await coord._async_update_data()

        assert data["stop_now"] is False


# ── Rain Today from Buffer Fallback ──────────────────────────────────────────


class TestRainTodayFromBuffer:
    async def test_rain_today_from_buffer_when_no_sensor(self, hass, coord):
        """Ohne rain_today_sensor → Tagesregen aus dem 12h-Puffer berechnet."""
        _weather_state(hass)
        # Buffer mit Regen befüllen (deque ist nach _async_setup leer — auffüllen)
        coord._rain_buffer = deque([0.0] * RAIN_BUFFER_MAXLEN, maxlen=RAIN_BUFFER_MAXLEN)
        coord._rain_buffer[-1] = 1.0
        coord._rain_buffer[-2] = 0.5

        with patch.object(coord, "_update_wetness", _dry(coord)):
            data = await coord._async_update_data()

        # rain_today_mm kommt aus dem Puffer (wenn kein Sensor)
        assert data["rain_today_mm"] >= 0.0


# ── waiting_for_favorable mit last_drying_mm ─────────────────────────────────


class TestWaitingForFavorable:
    async def test_next_mow_estimated_when_drying(self, hass, coord):
        """waiting_for_favorable + _last_drying_mm > 0 → next_mow_expected geschätzt."""
        _weather_state(hass)
        coord._last_drying_mm = 0.05  # Trocknung aktiv

        # Wetness zwischen effective_threshold und hard_threshold
        thresh = MagicMock()
        thresh.native_value = 0.5
        coord.mow_threshold_entity = thresh
        coord._below_threshold_since = None  # Grace Period just startet

        def _mid(*a, **kw):
            coord._wetness_mm = 0.3  # zwischen effective(0.2) und hard(0.5)
            return 0.0, 0.02, 0.0

        with patch.object(coord, "_update_wetness", _mid):
            data = await coord._async_update_data()

        if data["block_reason"] == "waiting_for_favorable":
            assert data["next_mow_expected"] is not None


# ── too_wet: 48h-Forecast findet nichts → linearer Fallback ──────────────────


class TestForecastFallbackWhenNoDryHourFound:
    async def test_linear_fallback_used_when_forecast_returns_none(self, hass, coord):
        """too_wet + _forecast_next_mow liefert None (kein Stundenforecast) + Akku
        voll → next_mow_expected nutzt die lineare Fallback-Schätzung statt leer
        zu bleiben (Code-Review 2026-07-02: Sensor zeigte 'unbekannt', obwohl
        aktuell aktiv getrocknet wird)."""
        _weather_state(hass)  # forecast=[] → _forecast_next_mow liefert None
        coord._last_drying_mm = 0.02  # Trocknung aktiv

        def _wet(*a, **kw):
            coord._wetness_mm = 1.0  # über der harten Standard-Schwelle (0.5)
            return 0.0, 0.02, 0.0

        with patch.object(coord, "_update_wetness", _wet):
            data = await coord._async_update_data()

        assert data["block_reason"] == "too_wet"
        assert data["next_mow_expected"] is not None
