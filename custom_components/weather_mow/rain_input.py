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


def rebuild_slots(
    mode: str,
    states: list[tuple[float, float]],
    start_ts: float,
    slot_count: int,
    slot_minutes: float,
) -> list[float]:
    """Rekonstruiert die Slot-Werte (mm je Slot) aus Recorder-States.

    mode         — Verarbeitungsmodus (RAIN_MODE_*)
    states       — chronologisch sortierte (epoch_ts, value)-Paare der letzten 12 h
    start_ts     — Epoch-Sekunden des ersten Slots
    slot_count   — Anzahl Slots (z. B. 144)
    slot_minutes — Slot-Länge in Minuten (z. B. 5)
    """
    slot_seconds = slot_minutes * 60.0
    slots = [0.0] * slot_count

    if mode == RAIN_MODE_INTERVAL:
        # Jede distinkte Ablesung in den Slot ihres Zeitstempels einsortieren.
        for ts, value in states:
            idx = int((ts - start_ts) // slot_seconds)
            if 0 <= idx < slot_count and value > 0.0:
                slots[idx] += value
        return slots

    # cumulative & rate: Sensorwert am Ende jedes Slots per Vorwärtsscan ermitteln.
    slot_values: list[float] = []
    state_idx = 0
    current_val = 0.0
    for i in range(slot_count):
        slot_end = start_ts + slot_seconds * (i + 1)
        while state_idx < len(states) and states[state_idx][0] <= slot_end:
            current_val = max(0.0, states[state_idx][1])
            state_idx += 1
        slot_values.append(current_val)

    if mode == RAIN_MODE_RATE:
        return [rate_to_slot_mm(v, slot_minutes) for v in slot_values]

    # RAIN_MODE_CUMULATIVE: Delta zwischen aufeinanderfolgenden Slot-Werten.
    prev = slot_values[0] if slot_values else 0.0
    for i in range(1, slot_count):
        slots[i] = cumulative_delta(slot_values[i], prev)
        prev = slot_values[i]
    return slots


def rain_since_midnight(
    slots: list[float],
    minutes_since_midnight: float,
    slot_minutes: float,
) -> float:
    """Summiert die Slot-mm seit lokal Mitternacht.

    Fallback-Tagesregen für Anbieter ohne dedizierten Tagessensor. In der Früh —
    wenn die Morgenstrafe im Nässescore zählt — liegt Mitternacht innerhalb des
    12h-Puffers. Abends untercountet der Wert (Mitternacht außerhalb des Puffers),
    dann ist die Morgenstrafe aber ohnehin nahe 0.

    slots                  — Slot-mm, ältester Slot zuerst, neuester zuletzt
    minutes_since_midnight — Minuten seit lokal Mitternacht
    slot_minutes           — Slot-Länge in Minuten
    """
    if not slots or minutes_since_midnight <= 0 or slot_minutes <= 0:
        return 0.0
    count = int(minutes_since_midnight // slot_minutes) + 1
    return sum(slots[-count:])
