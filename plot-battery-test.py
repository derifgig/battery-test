#!/usr/bin/env python3
import argparse
import csv
import glob
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def find_latest_csv():
    dirs = sorted(glob.glob(os.path.join("tests", "*")))
    if not dirs:
        sys.exit("No output dirs found in tests/")
    d = dirs[-1]
    csvs = glob.glob(os.path.join(d, "log.csv"))
    if not csvs:
        sys.exit(f"No log.csv in {d}")
    return csvs[0]


def parse_csv(csv_path):
    x_battery = []
    x_cpu = []
    battery = []
    cpu = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        t0 = None
        for row in reader:
            status = (row.get("status") or "").strip()
            if status and status != "Discharging":
                continue
            try:
                t = float(row["unix"])
            except (KeyError, ValueError):
                continue
            if t0 is None:
                t0 = t
            x_min = (t - t0) / 60.0
            cap = (row.get("capacity") or "").strip()
            cp = (row.get("cpu_percent") or "").strip()
            if cap:
                try:
                    x_battery.append(x_min)
                    battery.append(float(cap))
                except ValueError:
                    pass
            if cp:
                try:
                    x_cpu.append(x_min)
                    cpu.append(float(cp))
                except ValueError:
                    pass
    return x_battery, battery, x_cpu, cpu, t0


def main():
    parser = argparse.ArgumentParser(
        description="Generate a battery test chart from log.csv")
    parser.add_argument("csv", nargs="?",
                        help="path to log.csv (default: latest in tests/)")
    parser.add_argument("-o", "--output", default=None,
                        help="output image path (default: chart.png next to the CSV)")
    args = parser.parse_args()

    csv_path = args.csv or find_latest_csv()
    out_path = args.output or os.path.join(os.path.dirname(csv_path), "chart.png")

    x_battery, battery, x_cpu, cpu, t0 = parse_csv(csv_path)

    if len(x_battery) < 2 and len(x_cpu) < 2:
        sys.exit("Not enough rows in the CSV.")

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=130)
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    if battery:
        ax.plot(x_battery, battery, color="#00d4ff", linewidth=2,
                label="Battery charge (%)")
    if cpu:
        ax.plot(x_cpu, cpu, color="#ff6b6b", linewidth=1.5, alpha=0.85,
                label="CPU utilization (%)")
    else:
        print("WARNING: no cpu_percent column found — CPU line omitted.")

    ax.set_xlabel("Time from start (minutes)", color="#c0c0d0")
    ax.set_ylabel("Percent (%)", color="#c0c0d0")
    ax.tick_params(colors="#c0c0d0")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444466")
    ax.set_ylim(0, 100)
    ax.grid(True, which="both", axis="both", linestyle=":", alpha=0.3, color="#5555aa")
    ax.legend(loc="upper right", facecolor="#1a1a2e", edgecolor="#444466", labelcolor="#c0c0d0")

    runtime_h = None
    end_unix = (x_battery[-1] if x_battery else x_cpu[-1])
    if t0 is not None:
        runtime_h = end_unix / 60.0

    title = f"Battery discharge test — {os.path.basename(os.path.dirname(csv_path))}"
    if runtime_h:
        title += f"   |   runtime ~{runtime_h:.2f} h"
    ax.set_title(title)

    fig.tight_layout()
    fig.savefig(out_path)
    print(f"Chart saved: {os.path.abspath(out_path)}")
    if battery:
        print(f"Battery samples: {len(battery)}")
    if cpu:
        print(f"CPU samples: {len(cpu)}")
    if runtime_h:
        print(f"Runtime: {runtime_h:.2f} h")


if __name__ == "__main__":
    main()
