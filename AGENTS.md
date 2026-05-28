# AGENTS.md

This file provides guidance for Coding Agents when working with code in this
repository.

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

# Run all tests (covers rain_input.py, wetness.py, drying.py)
uv run --group test pytest

# Run a single test file
uv run --group test pytest tests/test_rain_input.py

# Run a single test
uv run --group test pytest tests/test_rain_input.py::test_name -v
```

After changing `pyproject.toml`, run `uv sync` to keep the lockfile in sync.

After making changes, ALWAYS run:
```bash
uv run --group lint ruff check . && uv run --group format ruff format --check . && uv run --group typecheck ty check && uv run --group test pytest
```

**CI validation** (runs via GitHub Actions on push/PR to `develop`):
- HACS validation: `hacs/action@main category=integration`
- hassfest: `home-assistant/actions/hassfest@master`
- pytest: `astral-sh/setup-uv` + `uv run pytest`

## Architecture

This is a **Home Assistant custom integration** (`domain: weather_mow`) that
provides weather-aware mowing decision sensors — it does not control the mower
directly, it only outputs sensor/binary-sensor states that automations can act
on.

### Core structure

```
custom_components/weather_mow/
├── coordinator.py      # All decision logic (~2000 lines) — the heart of the integration
├── rain_input.py       # Rain normalization, HA-independent, unit-testable
├── wetness.py          # Penman-Monteith drying model, HA-independent, unit-testable
├── drying.py           # Shadow-corrected drying calculation, HA-independent, unit-testable
├── const.py            # All constants and configuration defaults
├── config_flow.py      # 6-step setup wizard
├── __init__.py         # async_setup_entry / async_unload_entry / config migration
├── sensor.py           # Sensor entities (read-only from coordinator data)
├── binary_sensor.py    # Binary sensor entities (read-only from coordinator data)
├── switch.py           # 2 switches: enabled + debug_log
├── date.py             # last_fertilization date picker
├── number.py           # Configurable number entities (mow thresholds, sun efficiency)
├── time.py             # Lawn sun-from time entity
├── button.py           # Irrigation apply + wetness reset buttons
└── diagnostics.py      # JSON snapshot for troubleshooting
```

### Coordinator pattern

`WeatherMowCoordinator` in `coordinator.py` extends
`DataUpdateCoordinator[dict[str, Any]]` with a 5-minute update interval. All
platform files (`sensor.py`, `binary_sensor.py`, `switch.py`, `date.py`,
`number.py`, `time.py`, `button.py`) are thin wrappers over `CoordinatorEntity`
— they read from `coordinator.data` and have no logic of their own.

**Persistent state** survives HA restarts via four `Store` instances:
- `STORAGE_KEY_MOWING` — mowing sessions and daily durations
- `STORAGE_KEY_RAIN_BUF` — 12-hour rain buffer (144 slots × 5 min)
- `STORAGE_KEY_SOLAR` — solar peak calibration

**Real-time event listeners** supplement the polling loop: state-change
listeners on weather entities (rapid rain detection), configured rain sensors,
and mower state (start/end session tracking). A midnight listener resets daily
stats.

### Weather data sources

The integration supports three mutually exclusive weather backends, selected in
config flow step 2:

| Source | Scope | How data is fetched |
|--------|-------|---------------------|
| **OpenWeatherMap** | Global | `weather.get_forecasts` service (48h hourly) |
| **DWD** (`dwd_weather` HACS integration) | Germany | Reads `data` attribute arrays from DWD sensor entities |
| **Local sensors** (Ecowitt / Netatmo / custom) | Any | Direct sensor state polling |

Radiation can come from a DWD radiation sensor, a PV power entity, or `sun.sun`
elevation as fallback.

### Decision logic (the `allowed` binary sensor)

`binary_sensor.[name]_allowed` evaluates these ordered gates each update cycle:

1. Main switch off → blocked
2. Outside configured time window (default 08:00–20:00) → blocked
3. Too dark (brightness < threshold, default 2000 lux) → blocked
4. Battery below minimum % → blocked
5. Wetness score ≥ threshold (default 30) → blocked
6. Rain forecast today ≥ threshold (default 5 mm) → blocked
7. Daily target met + rain tomorrow ≥ threshold (default 8 mm) → emergency mow
   (if time allows)
8. Daily target met → blocked
9. Otherwise → **allowed**; `start_now` fires when priority ≥ 40

### Wetness score

```
score = rain_score + morning_penalty + dew_score − drying − wind_dry + future_score
```

- **rain_score**: 12h weighted buffer × 20 per mm
- **morning_penalty**: Overnight rain detected via `total_increasing` sensor ×
  1.5, decays with solar exposure
- **dew_score**: +25 when dew is present
- **drying**: Radiation ≥ 200 W/m² removes up to 15 pts/update
- **wind_dry**: Wind ≥ 15 km/h removes up to 5 pts/update
- **future_score**: Next 3h rain forecast contribution

Dew is considered present when `temp < dew_point + offset` (configurable).
Release requires continuous radiation ≥ 200 W/m² for ≥ 1h or ≥ 500 W/m²
instantaneously, with a daily latch preventing re-triggering.

### Growth model (GDD)

Every 5-minute update: `GDD_step = max(0, temp_°C − 5) / 288`; `growth_mm =
GDD_accumulator × 0.8`. Resets to 0 when the mower finishes a session.
Fertilization (via `date.last_fertilization`) multiplies GDD by 1.5 for 21
days.

### Rain normalization (`rain_input.py`)

Three normalization modes selected per-provider:
- `CUMULATIVE` — monotonic counter → delta (Ecowitt daily rain; handles midnight resets)
- `INTERVAL` — native per-update value with deduplication (Netatmo)
- `RATE` — mm/h → slot conversion

`RainNormalizer` is stateful (tracks last value and timestamp) and supports
`prime()` for warm-start from stored state. `rebuild_slots()` reconstructs the
buffer from HA recorder history on startup.

### Drying model (`drying.py` + `wetness.py`)

`drying.py` applies shadow correction: a `lawn_sun_from` time (before which
solar factor = 0) and an `efficiency` factor (0.1–1.0) for permanent shade from
trees/buildings.

`wetness.py` implements a simplified Penman-Monteith evaporation model
returning mm per 5-min update step, combining solar radiation, vapor pressure
deficit, and wind contributions.

### Diagnostics

- **Download Diagnostics**: JSON snapshot of all sensors, internal scores, and
  buffer state
- **Debug CSV** (`switch.[name]_debug_log`): 28-column CSV written to
  `/config/weather_mow_debug_<entry_id>.csv` at each 5-minute update
