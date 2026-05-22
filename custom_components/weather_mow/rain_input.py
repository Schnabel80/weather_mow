"""Anbieterbasierte Normalisierung von Regen-Sensorwerten in 'mm pro Slot'.

Dieses Modul ist bewusst frei von Home-Assistant-Importen, damit die
Normalisierungs-Mathematik eigenständig per pytest testbar bleibt.
"""
from __future__ import annotations

# ── Anbieter (Config-Flow-Auswahl) ──────────────────────────────────────────
RAIN_PROVIDER_ECOWITT = "ecowitt"
RAIN_PROVIDER_NETATMO = "netatmo"
RAIN_PROVIDER_OTHER   = "other"
RAIN_PROVIDER_NONE    = "none"
DEFAULT_RAIN_PROVIDER = RAIN_PROVIDER_NONE

# ── Verarbeitungsmodi ───────────────────────────────────────────────────────
RAIN_MODE_CUMULATIVE = "cumulative"   # monoton steigender Zähler -> Delta
RAIN_MODE_INTERVAL   = "interval"     # Menge je Messintervall -> direkt
RAIN_MODE_RATE       = "rate"         # Regenrate mm/h -> integrieren

_VALID_MODES = {RAIN_MODE_CUMULATIVE, RAIN_MODE_INTERVAL, RAIN_MODE_RATE}

# Welcher Modus gilt je Anbieter (Ecowitt: Daily Rain, Netatmo: Regen)
RAIN_PROVIDER_MODE: dict[str, str] = {
    RAIN_PROVIDER_ECOWITT: RAIN_MODE_CUMULATIVE,
    RAIN_PROVIDER_NETATMO: RAIN_MODE_INTERVAL,
}


def resolve_rain_mode(provider: str, sensor_type: str | None) -> str | None:
    """Verarbeitungsmodus für eine Anbieter-Auswahl.

    Gibt None zurück, wenn kein Sensor verarbeitet werden soll
    (Anbieter 'none' oder ungültige Auswahl bei 'other').
    """
    if provider == RAIN_PROVIDER_OTHER:
        return sensor_type if sensor_type in _VALID_MODES else None
    return RAIN_PROVIDER_MODE.get(provider)


def cumulative_delta(current: float, previous: float | None) -> float:
    """mm seit der vorherigen Ablesung eines monoton steigenden Zählers.

    Reset-fest: fällt der Wert (Mitternachts-Reset, Sensor-Neustart), gilt der
    aktuelle Wert selbst als der seit dem Reset gefallene Regen.
    """
    if previous is None:
        return 0.0
    if current < previous:
        return max(0.0, current)
    return current - previous


def rate_to_slot_mm(rate_mm_h: float, slot_minutes: float) -> float:
    """Wandelt eine Regenrate (mm/h) in die Regenmenge (mm) eines Slots um."""
    return max(0.0, rate_mm_h) * (slot_minutes / 60.0)


class RainNormalizer:
    """Hält den Verarbeitungszustand eines Regensensors und liefert je Update
    die im Slot gefallene Regenmenge in mm."""

    def __init__(self, mode: str) -> None:
        self._mode: str = mode
        self._prev_value: float | None = None
        self._last_ts: float | None = None

    @property
    def mode(self) -> str:
        return self._mode

    def prime(self, value: float | None, updated_ts: float | None) -> None:
        """Setzt den Zustand nach einer Recorder-Rekonstruktion, damit das
        nächste Live-Update ein korrektes Delta bzw. keine Doppelzählung liefert."""
        if value is not None:
            self._prev_value = value
        if updated_ts is not None:
            self._last_ts = updated_ts

    def slot_mm(self, value: float, updated_ts: float, slot_minutes: float) -> float:
        """Regenmenge in mm seit dem letzten Aufruf.

        value        — aktueller Sensorwert
        updated_ts   — last_updated des Sensor-States als Epoch-Sekunden
        slot_minutes — Länge des Update-Intervalls in Minuten
        """
        if self._mode == RAIN_MODE_CUMULATIVE:
            delta = cumulative_delta(value, self._prev_value)
            self._prev_value = value
            return delta
        if self._mode == RAIN_MODE_RATE:
            return rate_to_slot_mm(value, slot_minutes)
        if self._mode == RAIN_MODE_INTERVAL:
            if self._last_ts is not None and updated_ts <= self._last_ts:
                return 0.0
            self._last_ts = updated_ts
            return max(0.0, value)
        return 0.0
