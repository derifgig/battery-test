#!/usr/bin/env python3
import csv
import datetime
import os
import signal
import time

INTERVAL_SECONDS = int(os.environ.get("BAT_LOG_INTERVAL", "60"))
BAT_DIR = "/sys/class/power_supply/BAT0"


def read_battery():
    data = {}
    for name in ("status", "capacity", "capacity_level", "voltage_now", "power_now",
                 "energy_now", "energy_full", "energy_full_design", "cycle_count"):
        path = os.path.join(BAT_DIR, name)
        try:
            with open(path) as f:
                data[name] = f.read().strip()
        except OSError:
            data[name] = ""
    for key in ("voltage_now", "power_now", "energy_now", "energy_full", "energy_full_design"):
        if data.get(key):
            data[key] = float(data[key]) / 1_000_000
    return data


def read_cpu_stat():
    with open("/proc/stat") as f:
        line = f.readline()
    values = [int(x) for x in line.split()[1:]]
    total = sum(values)
    idle = values[3] + values[4]
    return total, idle


def cpu_percent(sample_seconds=1.0):
    try:
        t0, i0 = read_cpu_stat()
    except (OSError, ValueError, IndexError):
        return ""
    time.sleep(sample_seconds)
    try:
        t1, i1 = read_cpu_stat()
    except (OSError, ValueError, IndexError):
        return ""
    dt = t1 - t0
    di = i1 - i0
    if dt <= 0:
        return ""
    return round(100.0 * (dt - di) / dt, 1)


def human(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def log_console(dt, bat, cpu):
    status = bat.get("status", "?")
    cap = bat.get("capacity", "?")
    power = bat.get("power_now")
    cpu_s = f"{cpu}%" if cpu != "" else "?"
    eta = ""
    if status == "Discharging" and power:
        energy = bat.get("energy_now")
        if energy:
            eta = f", ETA ~{energy / power:.1f} h"
    print(f"[{human(dt)}] charge {cap}% ({status}) cpu {cpu_s}{eta}", flush=True)


def log_csv(writer, dt, bat, cpu):
    row = {
        "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "unix": int(dt.timestamp()),
        "capacity": bat.get("capacity", ""),
        "status": bat.get("status", ""),
        "cpu_percent": f"{cpu:.1f}" if cpu != "" else "",
        "power_w": f"{bat.get('power_now', 0):.2f}" if bat.get("power_now") else "",
        "voltage_v": f"{bat.get('voltage_now', 0):.2f}" if bat.get("voltage_now") else "",
        "energy_wh": f"{bat.get('energy_now', 0):.1f}" if bat.get("energy_now") else "",
        "energy_full_wh": f"{bat.get('energy_full', 0):.1f}" if bat.get("energy_full") else "",
        "cycle_count": bat.get("cycle_count", ""),
    }
    writer.writerow(row)


def main():
    start_dt = datetime.datetime.now()
    stamp = start_dt.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor", stamp)
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "log.csv")

    print(f"Battery monitor | start {human(start_dt)}")
    print(f"Log interval: {INTERVAL_SECONDS} s | no load emulation")
    print(f"Output: {os.path.abspath(out_dir)}")
    print(f"Stop: Ctrl+C or kill {os.getpid()}")
    print()

    log_file = open(log_path, "w", newline="")
    writer = csv.DictWriter(log_file, fieldnames=[
        "time", "unix", "capacity", "status", "cpu_percent", "power_w", "voltage_v",
        "energy_wh", "energy_full_wh", "cycle_count"])
    writer.writeheader()

    should_stop = False

    def on_signal(signum, frame):
        nonlocal should_stop
        should_stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    count = 0
    while not should_stop:
        dt = datetime.datetime.now()
        cpu = cpu_percent()
        bat = read_battery()
        log_console(dt, bat, cpu)
        log_csv(writer, dt, bat, cpu)
        log_file.flush()
        count += 1

        if INTERVAL_SECONDS > 0 and not should_stop:
            deadline = time.monotonic() + INTERVAL_SECONDS - 1.0
            while time.monotonic() < deadline and not should_stop:
                time.sleep(0.5)

    log_file.close()

    end_dt = datetime.datetime.now()
    print()
    print(f"Stopped {human(end_dt)} | duration {(end_dt - start_dt).total_seconds() / 60:.1f} min | records: {count}")
    print(f"Log: {os.path.abspath(log_path)}")


if __name__ == "__main__":
    main()
