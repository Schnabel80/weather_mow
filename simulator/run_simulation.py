"""
WeatherMow Simulation — main orchestrator.

Usage:
    python3 simulator/run_simulation.py
    python3 simulator/run_simulation.py --past-days 7
    python3 simulator/run_simulation.py --refresh   # re-download weather data
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import zoneinfo
from pathlib import Path

# --- Inject HA stubs BEFORE any weather_mow import ---
_SIM_DIR = Path(__file__).parent
sys.path.insert(0, str(_SIM_DIR))
sys.path.insert(0, str(_SIM_DIR.parent))

from ha_stubs import (
    MockConfigEntry,
    MockEvent,
    MockHass,
    MockState,
    install_stubs,
    set_sim_time,
)
install_stubs()

# --- Now import the real coordinator ---
from custom_components.weather_mow.coordinator import WeatherMowCoordinator
from custom_components.weather_mow.const import (
    CONF_HUMIDITY,
    CONF_LOCAL_RADIATION,
    CONF_MOWER_ENTITY,
    CONF_MOW_END,
    CONF_MOW_START,
    CONF_PREVENT_AUTO_RESUME,
    CONF_RAIN_TODAY,
    CONF_TARGET_DAILY_H,
    CONF_TEMP,
    CONF_WIND_SENSOR,
    DEFAULT_FULL_CYCLE_H,
)

from weather_loader import load_ticks
from mower_sim import MowerSim


def build_entry() -> MockConfigEntry:
    """Build a minimal config entry for the simulation."""
    return MockConfigEntry(
        data={
            "name": "Simulator",
            CONF_TEMP:            "sensor.sim_temp",
            CONF_HUMIDITY:        "sensor.sim_humidity",
            CONF_LOCAL_RADIATION: "sensor.sim_solar",
            CONF_WIND_SENSOR:     "sensor.sim_wind",
            CONF_RAIN_TODAY:      "sensor.sim_rain_today",
            CONF_MOWER_ENTITY:    "sensor.sim_mower",
            CONF_MOW_START:       "08:00:00",
            CONF_MOW_END:         "20:00:00",
            CONF_TARGET_DAILY_H:  2.5,
            "full_cycle_duration_h": DEFAULT_FULL_CYCLE_H,
            CONF_PREVENT_AUTO_RESUME: True,
            "min_battery_pct":    0,  # disable battery blocking (0 = always allowed)
        }
    )


def update_states(hass: MockHass, tick: dict, mower_ha_state: str) -> None:
    """Push current weather + mower state into hass.states."""
    hass.states.set("sensor.sim_temp",       str(round(tick["temperature_2m"], 1)))
    hass.states.set("sensor.sim_humidity",   str(round(tick["relative_humidity_2m"], 1)))
    hass.states.set("sensor.sim_solar",      str(round(tick["shortwave_radiation"], 1)))
    hass.states.set("sensor.sim_wind",       str(round(tick["wind_speed_10m"], 1)))
    hass.states.set("sensor.sim_rain_today", str(round(tick["rain_today_cumulative_mm"], 3)))

    # Sun elevation: approximate from solar radiation (avoids astropy dependency)
    elev = 30.0 if tick["shortwave_radiation"] > 50 else -5.0
    hass.states.set("sun.sun",
                    "above_horizon" if elev > 0 else "below_horizon",
                    attributes={"elevation": elev})

    hass.states.set("sensor.sim_mower", mower_ha_state,
                    attributes={"battery_level": 80},
                    last_updated=tick["time_utc"])


def fire_mow_state_change(coordinator: WeatherMowCoordinator,
                           old_state: str, new_state: str,
                           time_utc) -> None:
    """Trigger _handle_mower_state_change so coordinator updates _duration_today_s."""
    event = MockEvent({
        "old_state": MockState(old_state, last_updated=time_utc),
        "new_state": MockState(new_state, last_updated=time_utc),
    })
    coordinator._handle_mower_state_change(event)


async def run(past_days: int = 14, force_refresh: bool = False) -> list[dict]:
    print(f"Loading {past_days} days of weather data from Open-Meteo...")
    ticks = load_ticks(past_days=past_days, force=force_refresh)
    print(f"  {len(ticks)} ticks loaded "
          f"({ticks[0]['time_utc'].date()} → {ticks[-1]['time_utc'].date()})")

    hass = MockHass()
    entry = build_entry()
    coordinator = WeatherMowCoordinator(hass, entry)
    mower = MowerSim()
    current_mower_ha = "docked"
    results: list[dict] = []

    print("Running simulation...")
    current_sim_date = None  # for midnight reset

    for i, tick in enumerate(ticks):
        set_sim_time(tick["time_utc"])
        update_states(hass, tick, current_mower_ha)

        try:
            result = await coordinator._async_update_data()
        except Exception as exc:
            print(f"  [tick {i}] coordinator error: {exc}")
            continue

        await hass.drain_tasks()

        # Midnight reset: fire _handle_midnight when simulated date changes
        tick_local_date = tick["time_utc"].astimezone(zoneinfo.ZoneInfo("Europe/Berlin")).date()
        if current_sim_date is not None and tick_local_date != current_sim_date:
            try:
                coordinator._handle_midnight(tick["time_utc"])
            except Exception:
                pass
        current_sim_date = tick_local_date

        # Advance mower, fire state-change event if it changed
        new_mower_ha = mower.tick(result["start_now"], result["stop_now"])
        if new_mower_ha != current_mower_ha:
            fire_mow_state_change(coordinator, current_mower_ha, new_mower_ha, tick["time_utc"])
            current_mower_ha = new_mower_ha
            # Update state in hass so next tick reads the new state
            hass.states.set("sensor.sim_mower", current_mower_ha,
                            attributes={"battery_level": 80},
                            last_updated=tick["time_utc"])

        results.append({
            "timestamp": tick["time_utc"],
            "mower_state":           current_mower_ha,
            "temperature_c":         tick["temperature_2m"],
            "rain_today_mm":         tick["rain_today_cumulative_mm"],
            "solar_wm2":             tick["shortwave_radiation"],
            **result,
        })

        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(ticks)} ticks done...")

    print(f"Simulation complete. {len(results)} results.")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="WeatherMow Simulator")
    parser.add_argument("--past-days", type=int, default=14)
    parser.add_argument("--refresh", action="store_true",
                        help="Force re-download of weather data")
    args = parser.parse_args()

    results = asyncio.run(run(past_days=args.past_days, force_refresh=args.refresh))

    # Print summary statistics
    mowing_ticks = [r for r in results if r["mower_state"] == "mowing"]
    total_mow_h = len(mowing_ticks) * 5 / 60

    sessions = 0
    in_session = False
    for r in results:
        if r["mower_state"] == "mowing" and not in_session:
            sessions += 1
            in_session = True
        elif r["mower_state"] != "mowing":
            in_session = False

    stop_events = sum(1 for r in results if r["stop_now"])
    max_wetness = max((r["wetness_mm"] for r in results), default=0.0)

    print("\n─── Statistics ──────────────────────────────")
    print(f"Period:          {results[0]['timestamp'].date()} → {results[-1]['timestamp'].date()}")
    print(f"Total mow time:  {total_mow_h:.1f} h")
    print(f"Mow sessions:    {sessions}")
    print(f"stop_now events: {stop_events}")
    print(f"Max wetness_mm:  {max_wetness:.2f}")
    print("─────────────────────────────────────────────")
    print("Run plot.py to generate charts.")

    # Save CSV for inspection
    import csv
    out_path = Path(__file__).parent / "sim_results.csv"
    if results:
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            for row in results:
                writer.writerow({k: (v.isoformat() if hasattr(v, "isoformat") else v)
                                 for k, v in row.items()})
        print(f"CSV saved: {out_path}")


if __name__ == "__main__":
    main()
