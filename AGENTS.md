# AGENTS.md

Guidance for AI coding agents working on this repository.

## Commands

```bash
# Setup
uv sync

# Format
uv run --group format ruff format .

# Check formatting (no changes)
uv run --group format ruff format --check .

# Lint
uv run --group lint ruff check .

# Type check
uv run --group typecheck ty check

# Run all tests
uv run --group test pytest

# Run a single test file
uv run --group test pytest tests/test_rain_input.py

# Run a single test
uv run --group test pytest tests/test_rain_input.py::test_name -v
```

After changing `pyproject.toml`, run `uv sync` to keep the lockfile in sync.

After making changes, always run:
```bash
uv run --group lint ruff check . && uv run --group format ruff format --check . && uv run --group test pytest
```

**CI** (runs on push/PR to `develop`): HACS validation, hassfest, pytest.

---

## Architecture

A **Home Assistant custom integration** (`domain: weather_mow`) that provides
weather-aware mowing decision sensors. It does not control the mower directly —
it outputs sensor/binary-sensor states that HA automations act on.

### File structure

```
custom_components/weather_mow/
├── coordinator.py      # All decision logic (~2900 lines) — the heart
├── rain_input.py       # Rain normalisation — HA-independent, unit-testable
├── wetness.py          # Penman-Monteith drying + condensation — HA-independent
├── drying.py           # Shadow-corrected solar factor — HA-independent
├── growth.py           # Cardinal-temperature growth response — HA-independent
├── scheduling.py       # Usable forecast hours / early-start hold — HA-independent
├── charging.py         # Charge-rate learning + battery ceiling — HA-independent
├── freshness.py        # Weather-data staleness decision — HA-independent
├── const.py            # All constants and configuration defaults
├── config_flow.py      # 6-step setup wizard + options flow + reconfigure flow
├── __init__.py         # async_setup_entry / async_unload_entry / migrations v1→v4
├── sensor.py           # Read-only sensor entities (from coordinator.data)
├── binary_sensor.py    # Read-only binary sensor entities
├── switch.py           # enabled + debug_log + emergency_mow + irrigation switches
├── number.py           # mow_threshold_mm, mow_threshold_urgent_mm, lawn_sun_efficiency, max_mow_temp_c
├── time.py             # lawn_sun_from time entity
├── date.py             # last_fertilization date entity
├── button.py           # irrigation_apply + wetness_reset buttons
└── diagnostics.py      # JSON snapshot for troubleshooting
```

### Coordinator pattern

`WeatherMowCoordinator` extends `DataUpdateCoordinator[dict[str, Any]]` with a
5-minute update interval. All platform files are thin `CoordinatorEntity`
wrappers — they read from `coordinator.data` and have no logic of their own.

**Persistent state** survives HA restarts via six `Store` instances:
- `STORAGE_KEY_MOWING` — mowing sessions, daily durations, mow start timestamp
- `STORAGE_KEY_RAIN_BUF` — 12-hour rain buffer (144 slots × 5 min)
- `STORAGE_KEY_SOLAR` — solar peak calibration value
- `STORAGE_KEY_GROWTH` — accumulated GDD growth value
- `STORAGE_KEY_WETNESS` — `wetness_mm` + `below_threshold_ts` (grace period persistence)
- `STORAGE_KEY_CHARGE` — learned charge rate + learned battery ceiling

**Entity references** on the coordinator (set during `async_setup_entry`):
`mow_threshold_entity`, `mow_threshold_urgent_entity`, `lawn_sun_efficiency_entity`,
`lawn_sun_from_entity`, `last_fertilization_entity`, `enabled_switch`,
`debug_log_switch`, `emergency_mow_switch`.

**Real-time listeners** supplement the 5-minute poll: state-change listeners on
weather/rain/mower entities for rapid rain detection and session tracking; a
midnight callback resets daily stats and grace period.

### Config flow (6 steps)

Station-centric setup, VERSION = 4:

1. **device** — mower entity, optional battery sensor, min battery %
2. **weather** — weather forecast entity (OWM, DWD, Met.no, …)
3. **station** — rain provider type: `ecowitt | netatmo | other | none`
4. **station_ecowitt / station_netatmo / station_other / station_none** — provider-specific sensors
5. **radiation_fallback** — radiation source (PV power or sun elevation); skipped if local radiation sensor was provided in step 4
6. **mow_times** — mowing window, daily targets, wetness/rain thresholds → stored as `options`

Options flow and reconfigure flow reuse the same step handlers.

### Wetness model (Penman-Monteith, `wetness.py` + `drying.py`)

`wetness_mm` is a physical value (0–2 mm) representing lawn surface moisture.
It is **not** a 0–100 score. All thresholds are in mm.

Per 5-minute update:
```
Δwetness = rain_delta + condensation(vpd) − penman_drying(...)
wetness_mm = clamp(wetness_mm + Δwetness, 0, WETNESS_MAX_MM=2.0)
```

`penman_drying(eff_solar, vpd_c, wind_kmh, sun_elevation_deg, efficiency, temp_c)`
sums two independent terms:
- **Solar term** — `K_SOLAR × eff_solar`, driven by radiation reaching the lawn
- **Aerodynamic term** — wind × vapour-pressure deficit, scaled by
  `es(T)/es(20 °C)` (Magnus/Tetens), by `shade_compensation(efficiency)`, and by
  a day/night factor

**Day/night for the aerodynamic term comes from `sun_elevation_deg` only**
(`day_factor`, linear ramp −6°…+6°), never from `eff_solar`. `eff_solar` also
carries clouds and permanent shade, so using it there suppressed wind-driven
drying on cloudy or shaded *days* — fixed in 1.2.0. `eff_solar` now drives the
solar term exclusively.

`shade_compensation(efficiency)` boosts the aerodynamic term on permanently
shaded lawns (neutral at `efficiency = 1.0`): less direct sun is real, but
wind/VPD evaporation does not need direct sunlight.

`drying.py` applies shadow correction before passing `eff_solar` to
`penman_drying`:
- `lawn_sun_from` (time entity): solar factor = 0 before this time
- `lawn_sun_efficiency` (number entity, 0.1–1.0): permanent shade factor

`dew_present` is a **diagnostic sensor only** — it no longer influences mowing
decisions (removed in v0.4.0b5).

### Decision logic (`_compute_decision` in coordinator.py)

Ordered gates evaluated each update — **first match wins**. The literal
`block_reason` strings are listed in `BLOCK_REASONS` (const.py); the ENUM sensor
breaks if a value is missing there or in both translation files.

1. Integration disabled (main switch off) → `disabled`
2. Outside mow window (default 08:00–20:00) → `outside_time_window`
3. Too dark (brightness < threshold, default 2000 lux) → `too_dark_hedgehog`
4. **Heat gate** (`max_mow_temp_c`, default 35 °C): temperature ≥ threshold → `too_hot`
   (emergency mow overrides)
5. Raining right now → `raining`
6. Daily target met + rain tomorrow ≥ threshold + time left → `emergency_mow_tomorrow_rain`
7. Daily target met → `daily_target_reached`
8. **Wetness gate** (adaptive threshold + grace period):
   - `wetness_mm > mow_threshold_mm` (default 0.5 mm) → `too_wet`
   - `wetness_mm > effective_threshold` (= threshold − `FORECAST_DISCOUNT_MM` 0.3 mm when no rain forecast) → `waiting_for_favorable`
   - Grace period: if wetness just dropped below effective threshold, wait `GRACE_PERIOD_MINUTES` (30 min) → `waiting_for_favorable`
   - Grace period timestamp persisted across restarts in `STORAGE_KEY_WETNESS`; reset at midnight
9. → `mowing_allowed`; `start_now` fires when priority ≥ 40 or under time pressure

**After the chain**, four suppressors may clear `start_now` — each keeps
`mow_allowed = True` and never raises `stop_now`, so a manually started mower
keeps running:

- **Early-start hold** (`_early_start_hold`, `scheduling.py`) → `waiting_optimal_time`.
  Before a preferred start time (mow-window start + `EARLY_HOLD_OFFSET_H`, capped
  at `EARLY_HOLD_LATEST_HOUR`), starting is only allowed if too little *usable*
  forecast time would remain afterwards. A usable hour has rain
  < `RAIN_HOUR_BLOCK_MM` and temperature < `max_mow_temp_c`. Bypassed by emergency
  mow, time pressure, `no_dry_window`, or priority ≥ `DELAY_BYPASS_PRIORITY`.
  With no hourly forecast, it holds.
- **Start delay** (`start_delay_minutes`) — settling time after first eligibility
- **Battery gate** → `battery_low`; target is the *learned* ceiling, see below
- **Stale weather data** — integration goes fully passive (no start, no stop)

### Priority calculation (`_compute_priority`)

Weighted sum, clamped to 0–100, then multiplied by the heat factor:

| Contribution | Formula | Max |
|---|---|---|
| `deficit_score` | `(1 − today_h / target_h) × 40` | 40 |
| `avg_score` | `(1 − avg_3d_h / target_h) × 20` | 20 |
| `emergency_bonus` | flat, when emergency mow is active | 40 |
| `growth_bonus` | `growth_ratio × 15` (ratio is 0 below 30 % of `max_growth_mm`) | 15 |
| `urgency_bonus` | window closing in | 15 |
| `midday_bonus` | full between 11:00 and 16:00 | 10 |
| `wetness_penalty` | `− min(5, wetness_mm × 1.5)` | −5 |

**Heat factor**: at `max_mow_temp_c − TEMP_HOT_REDUCTION_START_OFFSET_C`
(default 30 °C) priority declines linearly to 0 at `max_mow_temp_c` — nudges the
mower toward cooler morning/evening hours.

At priority ≥ 40: `start_now = True`. At priority ≥ `DELAY_BYPASS_PRIORITY` (65): start delay ignored.

> `deficit_score` alone reaches its full 40 points whenever nothing has been mowed
> yet that day — i.e. exactly the start threshold. Mornings are therefore
> "start-ready" by construction; the early-start hold decides whether it acts.

### Rain normalisation (`rain_input.py`)

Three modes, selected per provider:
- `CUMULATIVE` — monotonic counter → delta (Ecowitt daily rain; handles midnight resets)
- `INTERVAL` — native per-update value with deduplication (Netatmo)
- `RATE` — mm/h → slot mm conversion

`RainNormalizer` is stateful and supports `prime()` for warm-start from stored
state. `rebuild_slots()` reconstructs the buffer from HA recorder history on
startup.

### Growth model (GDD)

Every 5-minute update:
```
gdd_step  = temperature_response(temp_c) × moisture_factor(rain_12h, wetness) / 288
growth_mm = accumulator × GROWTH_MM_PER_GDD          # 0.8
```
`temperature_response` (growth.py) is a cardinal-temperature triangle — base
5 °C, optimum 20 °C, standstill at 31 °C (heat dormancy) — not the old linear
`temp − 5`. `moisture_factor` damps growth under drought (floor
`GROWTH_MOISTURE_FLOOR`).

`growth_ratio` (the value feeding the priority) stays 0 below 30 % of
`max_growth_mm`, then rises linearly to 1.0.

The accumulator resets when the mower finishes a session. Fertilisation (via
`date.last_fertilization`) multiplies the step by 1.5 for 21 days.

### Battery ceiling (`charging.py`)

The "full" threshold is **learned**, not fixed: while docked, if the state of
charge plateaus for `BATTERY_PLATEAU_MINUTES` without rising, that value becomes
the ceiling (handles mowers that never reach 100 % and user-set charge limits).
It updates continuously in both directions and is persisted. A learned ceiling
below `BATTERY_CEILING_WARN_PCT` raises a persistent notification. Only readings
from the dedicated battery sensor may train it.

### Weather-data staleness (`freshness.py`)

If **all** configured station inputs (temp, humidity, wind, radiation, rain) are
older than `WEATHER_STALE_MINUTES` (or unavailable), the station counts as dead:
`weather_data_stale` turns on, a persistent notification is raised, and the
integration goes passive — neither `start_now` nor `stop_now` is set, so the user
keeps manual control. A single fresh input prevents the alarm.

### HA-independent modules

`rain_input.py`, `wetness.py`, `drying.py`, `growth.py`, `scheduling.py`,
`charging.py`, and `freshness.py` contain **no HA imports** and
are fully covered by pure pytest unit tests (no fixtures needed). Keep them
that way — any new pure logic belongs in one of these files or a new module of
the same kind.

### External data contracts — read this before touching a `.get()`

Nearly every value from outside comes in via a string key with a silent
fallback (`fc.get("x") or 0.0`, `state.attributes.get("y")`). A wrong or stale
key therefore does not raise — it yields a plausible number, and the feature
dies quietly.

This exact pattern caused issue #16: the hourly forecast was read from
`native_precipitation`, but `weather.get_forecasts` returns already-converted
keys **without** the `native_` prefix. Rain forecast was 0 for every user for
three months, which also silently disabled emergency mowing. The test suite
missed it because **the fixture encoded the same wrong assumption as the code**.

Rules when adding or changing such a read:

1. **Verify the key against a live instance**, not against memory or the docs —
   `weather.get_forecasts` returns `precipitation`, `temperature`, `wind_speed`,
   `cloud_coverage`; `sun.sun` exposes `elevation` and `next_setting`. A
   `lawn_mower` entity has **no** `battery_level` attribute.
2. **Never let a test invent the shape of foreign data.** Copy a real payload.
   A self-invented fixture can only confirm what the code already believes.
3. Prefer `_first_not_none(data, "key", "native_key")` when both spellings are
   plausible across integrations.
4. A config key the coordinator reads but `config_flow.py` never writes is dead
   for new installs — check both sides when adding one.

### Diagnostics

- **Download Diagnostics**: JSON snapshot of all sensor values, internal state,
  and buffer contents
- **Debug CSV** (`switch.[name]_debug_log`): 40-column CSV written to
  `/config/weather_mow_debug_<entry_id>.csv` at each update cycle
