"""
Generate simulation charts from sim_results.csv.

Usage:
    python3 simulator/plot.py
    python3 simulator/plot.py --csv simulator/sim_results.csv
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            row["timestamp"] = datetime.fromisoformat(row["timestamp"])
            for key in ("wetness_mm", "temperature_c", "rain_today_mm",
                        "solar_wm2", "start_now", "stop_now", "mow_allowed",
                        "drying_mm", "priority"):
                if key in row:
                    if key in ("start_now", "stop_now", "mow_allowed"):
                        row[key] = row[key] in ("True", "true", "1")
                    else:
                        try:
                            row[key] = float(row[key])
                        except (ValueError, TypeError):
                            row[key] = 0.0
            rows.append(row)
    return rows


def plot(rows: list[dict], out_path: Path) -> None:
    times = [r["timestamp"] for r in rows]
    wetness = [r.get("wetness_mm", 0.0) for r in rows]
    temps = [r.get("temperature_c", 0.0) for r in rows]
    rain = [r.get("rain_today_mm", 0.0) for r in rows]
    solar = [r.get("solar_wm2", 0.0) for r in rows]
    mowing = [r.get("mower_state") == "mowing" for r in rows]
    stop_now = [r.get("stop_now", False) for r in rows]

    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
    fig.suptitle("WeatherMow Simulation — 2-Week Replay", fontsize=14)

    # ── Panel 1: Wetness + mowing sessions ───────────────────────────────────
    ax1 = axes[0]
    ax1.plot(times, wetness, color="#2196F3", linewidth=0.8, label="wetness_mm")
    ax1.axhline(0.5, color="green", linestyle="--", linewidth=0.8, alpha=0.7, label="mow threshold (0.5)")
    ax1.axhline(1.5, color="orange", linestyle="--", linewidth=0.8, alpha=0.7, label="urgent threshold (1.5)")

    # Shade mowing sessions green
    in_session = False
    session_start = None
    for t, m in zip(times, mowing):
        if m and not in_session:
            in_session = True
            session_start = t
        elif not m and in_session:
            ax1.axvspan(session_start, t, alpha=0.15, color="green")
            in_session = False
    if in_session:
        ax1.axvspan(session_start, times[-1], alpha=0.15, color="green")

    # Mark stop_now events
    stop_times = [t for t, s in zip(times, stop_now) if s]
    if stop_times:
        ax1.scatter(stop_times, [0.1] * len(stop_times),
                    marker="v", color="red", s=20, zorder=5, label="stop_now")

    ax1.set_ylabel("wetness_mm")
    ax1.set_ylim(bottom=-0.1)
    ax1.legend(loc="upper right", fontsize=7,
               handles=ax1.get_legend_handles_labels()[0] + [
                   Patch(facecolor="green", alpha=0.3, label="mowing session")
               ])
    ax1.grid(axis="y", alpha=0.3)

    # ── Panel 2: Temperature + Solar radiation ────────────────────────────────
    ax2 = axes[1]
    ax2.plot(times, temps, color="#FF5722", linewidth=0.7, label="temp (°C)")
    ax2_r = ax2.twinx()
    ax2_r.fill_between(times, solar, alpha=0.25, color="#FFC107", label="solar (W/m²)")
    ax2_r.set_ylabel("W/m²", color="#FFC107")
    ax2.set_ylabel("°C", color="#FF5722")
    ax2.legend(loc="upper left", fontsize=7)
    ax2_r.legend(loc="upper right", fontsize=7)
    ax2.grid(axis="y", alpha=0.3)

    # ── Panel 3: Daily rain ───────────────────────────────────────────────────
    ax3 = axes[2]
    ax3.fill_between(times, rain, alpha=0.5, color="#42A5F5", label="rain today (mm)")
    ax3.set_ylabel("mm")
    ax3.legend(loc="upper right", fontsize=7)
    ax3.grid(axis="y", alpha=0.3)

    # X-axis formatting
    ax3.xaxis.set_major_locator(mdates.DayLocator())
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha="right")

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f"Chart saved: {out_path}")
    plt.show()


def print_statistics(rows: list[dict]) -> None:
    mowing_ticks = [r for r in rows if r.get("mower_state") == "mowing"]
    total_mow_h = len(mowing_ticks) * 5 / 60

    sessions = 0
    in_session = False
    for r in rows:
        if r.get("mower_state") == "mowing" and not in_session:
            sessions += 1
            in_session = True
        elif r.get("mower_state") != "mowing":
            in_session = False

    stop_events = sum(1 for r in rows if r.get("stop_now"))
    max_wetness = max((r.get("wetness_mm", 0.0) for r in rows), default=0.0)
    avg_wetness = sum(r.get("wetness_mm", 0.0) for r in rows) / len(rows) if rows else 0.0
    rain_days = len({r["timestamp"].date() for r in rows
                     if r.get("rain_today_mm", 0.0) > 1.0})

    if rows:
        first_day = rows[0]["timestamp"].date()
        last_day = rows[-1]["timestamp"].date()
        num_days = max(1, (last_day - first_day).days + 1)
    else:
        num_days = 14

    print("\n─── Simulation Statistics ────────────────────")
    if rows:
        print(f"Period:           {rows[0]['timestamp'].date()} → {rows[-1]['timestamp'].date()}")
    print(f"Total mow time:   {total_mow_h:.1f} h ({total_mow_h/num_days:.2f} h/day avg)")
    print(f"Mow sessions:     {sessions}")
    print(f"stop_now events:  {stop_events}")
    print(f"Max wetness_mm:   {max_wetness:.2f}")
    print(f"Avg wetness_mm:   {avg_wetness:.2f}")
    print(f"Rainy days (>1mm):{rain_days}")
    print("──────────────────────────────────────────────")


def main() -> None:
    parser = argparse.ArgumentParser(description="WeatherMow Simulation Plotter")
    parser.add_argument("--csv", type=Path,
                        default=Path(__file__).parent / "sim_results.csv")
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).parent / "sim_plot.png")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}")
        print("Run run_simulation.py first.")
        return

    rows = load_csv(args.csv)
    print(f"Loaded {len(rows)} rows from {args.csv}")
    print_statistics(rows)
    plot(rows, args.out)


if __name__ == "__main__":
    main()
