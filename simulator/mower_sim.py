"""
Mower state machine for simulation.

States: IDLE → MOWING → CHARGING → IDLE
- MOWING: 1.5 h = 90 min = 18 ticks
- CHARGING: 1 h = 60 min = 12 ticks
- IDLE: waits for start_now=True
"""

from __future__ import annotations

_MOWING_TICKS = 18  # 90 min / 5 min per tick
_CHARGING_TICKS = 12  # 60 min / 5 min per tick


class MowerSim:
    """
    Call tick(start_now, stop_now) once per 5-minute simulation step.
    Returns the current HA mower state string ("mowing" or "docked").
    """

    def __init__(self):
        self._phase = "idle"  # "idle", "mowing", "charging"
        self._ticks_remaining = 0
        self.ha_state = "docked"  # what coordinator sees

    def tick(self, start_now: bool, stop_now: bool) -> str:
        """Advance by one 5-minute step. Returns new ha_state."""
        if self._phase == "mowing":
            self._ticks_remaining -= 1
            if stop_now or self._ticks_remaining <= 0:
                self._phase = "charging"
                self._ticks_remaining = _CHARGING_TICKS
                self.ha_state = "docked"
        elif self._phase == "charging":
            self._ticks_remaining -= 1
            if self._ticks_remaining <= 0:
                self._phase = "idle"
                self.ha_state = "docked"

        # Handle idle phase (may have just transitioned into it)
        if self._phase == "idle" and start_now:
            self._phase = "mowing"
            self._ticks_remaining = _MOWING_TICKS
            self.ha_state = "mowing"

        return self.ha_state

    @property
    def is_mowing(self) -> bool:
        return self._phase == "mowing"
