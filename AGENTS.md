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
├── coordinator.py      # All decision logic (~2000 lines) — the heart
├── rain_input.py       # Rain normalisation — HA-independent, unit-testable
├── wetness.py          # Penman-Monteith drying model — HA-independent, unit-testable
├── drying.py           # Shadow-corrected solar factor — HA-independent, unit-testable
├── const.py            # All constants and configuration defaults
├── config_flow.py      # 6-step setup wizard + options flow + reconfigure flow
├── __init__.py         # async_setup_entry / async_unload_entry / migration v1→v2
├── sensor.py           # Read-only sensor entities (from coordinator.data)
├── binary_sensor.py    # Read-only binary sensor entities
├── switch.py           # enabled + debug_log switches
├── number.py           # mow_threshold_mm, mow_threshold_urgent_mm, lawn_sun_efficiency
├── time.py             # lawn_sun_from time entity
├── date.py             # last_fertilization date entity
├── button.py           # irrigation_apply + wetness_reset buttons
└── diagnostics.py      # JSON snapshot for troubleshooting
```

### Coordinator pattern

`WeatherMowCoordinator` extends `DataUpdateCoordinator[dict[str, Any]]` with a
5-minute update interval. All platform files are thin `CoordinatorEntity`
wrappers — they read from `coordinator.data` and have no logic of their own.

**Persistent state** survives HA restarts via five `Store` instances:
- `STORAGE_KEY_MOWING` — mowing sessions, daily durations, mow start timestamp
- `STORAGE_KEY_RAIN_BUF` — 12-hour rain buffer (144 slots × 5 min)
- `STORAGE_KEY_SOLAR` — solar peak calibration value
- `STORAGE_KEY_GROWTH` — accumulated GDD growth value
- `STORAGE_KEY_WETNESS` — `wetness_mm` + `below_threshold_ts` (grace period persistence)

**Entity references** on the coordinator (set during `async_setup_entry`):
`mow_threshold_entity`, `mow_threshold_urgent_entity`, `lawn_sun_efficiency_entity`,
`lawn_sun_from_entity`, `last_fertilization_entity`, `enabled_switch`,
`debug_log_switch`, `emergency_mow_switch`.

**Real-time listeners** supplement the 5-minute poll: state-change listeners on
weather/rain/mower entities for rapid rain detection and session tracking; a
midnight callback resets daily stats and grace period.

### Config flow (6 steps)

Station-centric setup, VERSION = 2:

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
Δwetness = condensation(temp, humidity) − penman_drying(eff_solar, vpd, wind)
wetness_mm = clamp(wetness_mm + Δwetness, 0, WETNESS_MAX_MM=2.0)
```

`drying.py` applies shadow correction before passing `eff_solar` to
`penman_drying`:
- `lawn_sun_from` (time entity): solar factor = 0 before this time
- `lawn_sun_efficiency` (number entity, 0.1–1.0): permanent shade factor

`dew_present` is a **diagnostic sensor only** — it no longer influences mowing
decisions (removed in v0.4.0b5).

### Decision logic (`_compute_decision` in coordinator.py)

Ordered gates evaluated each update:

1. Integration disabled → `blocked`
2. Outside mow window (default 08:00–20:00) → `outside_window`
3. Too dark (brightness < threshold, default 2000 lux) → `too_dark`
4. Battery below minimum % → `low_battery`
5. Rain today ≥ threshold (default 5 mm) → `rain_today`
6. Daily target already met + rain tomorrow ≥ threshold → emergency-mow path
7. Daily target met → `target_reached`
8. **Wetness gate** (adaptive threshold + grace period):
   - `wetness_mm > mow_threshold_mm` (default 0.5 mm) → `too_wet`
   - `wetness_mm > effective_threshold` (= threshold − `FORECAST_DISCOUNT_MM` 0.3 mm when no rain forecast) → `waiting_for_favorable`
   - Grace period: if wetness just dropped below effective threshold, wait `GRACE_PERIOD_MINUTES` (30 min) → `waiting_for_favorable`
   - Grace period timestamp persisted across restarts in `STORAGE_KEY_WETNESS`; reset at midnight
9. → `mowing_allowed`; `start_now` fires when priority ≥ 40

### Priority calculation (`_compute_priority`)

0–100 score combining:
- Deficit vs. daily target (main driver)
- Days since last mow
- 3-day average mow duration vs. target (urgency indicator)
- Growth model contribution

At priority ≥ 40: `start_now = True`. At priority ≥ `DELAY_BYPASS_PRIORITY` (65): start delay ignored.

### Rain normalisation (`rain_input.py`)

Three modes, selected per provider:
- `CUMULATIVE` — monotonic counter → delta (Ecowitt daily rain; handles midnight resets)
- `INTERVAL` — native per-update value with deduplication (Netatmo)
- `RATE` — mm/h → slot mm conversion

`RainNormalizer` is stateful and supports `prime()` for warm-start from stored
state. `rebuild_slots()` reconstructs the buffer from HA recorder history on
startup.

### Growth model (GDD)

Every 5-minute update: `GDD_step = max(0, temp_°C − 5.0) / 288`.
`growth_mm = GDD_accumulator × 0.8`. Resets when mower finishes a session.
Fertilisation (via `date.last_fertilization`) multiplies GDD by 1.5 for 21 days.

### HA-independent modules

`rain_input.py`, `wetness.py`, and `drying.py` contain **no HA imports** and
are fully covered by pure pytest unit tests (no fixtures needed). Keep them
that way — any new pure logic belongs in one of these files or a new module of
the same kind.

### Diagnostics

- **Download Diagnostics**: JSON snapshot of all sensor values, internal state,
  and buffer contents
- **Debug CSV** (`switch.[name]_debug_log`): 28-column CSV written to
  `/config/weather_mow_debug_<entry_id>.csv` at each update cycle
