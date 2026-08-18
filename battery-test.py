#!/usr/bin/env python3
import csv
import datetime
import os
import signal
import time
from multiprocessing import get_context

try:
    _MP = get_context("fork")
except ValueError:
    _MP = get_context()
Event = _MP.Event
Process = _MP.Process

INTERVAL_SECONDS = int(os.environ.get("BAT_TEST_INTERVAL", "60"))
STOP_CAPACITY = int(os.environ.get("BAT_TEST_STOP_CAPACITY", "5"))
LOAD_PROFILE = os.environ.get("BAT_TEST_LOAD_PROFILE", "")
BAT_DIR = "/sys/class/power_supply/BAT0"

PROFILES = {
    "light": "0-1:25,1-4:8,4-4.5:30,4.5-6:6,6-7:12,7-8:5,8-8.5:20,8.5-10:3",
    "video": "0-1:30,1-2:8,2-7:14,7-8:6,8-8.5:25,8.5-10:4",
    "compile": "0-1:30,1-3:7,3-3.3:45,3.3-5:10,5-6:15,6-7.5:6,7.5-7.8:40,7.8-10:5",
}


def parse_profile(spec):
    segments = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            interval, pct_s = part.rsplit(":", 1)
            start_s, end_s = interval.split("-", 1)
            start, end, pct = float(start_s), float(end_s), float(pct_s)
        except (ValueError, TypeError):
            raise ValueError(f"invalid profile segment: {part!r} (expected 'start-end:pct')")
        if start < 0 or end <= start:
            raise ValueError(f"invalid interval in segment: {part!r}")
        pct = max(0.0, min(100.0, pct))
        segments.append((start, end, pct))
    if not segments:
        raise ValueError("empty load profile")
    return sorted(segments)


def resolve_profile():
    raw = LOAD_PROFILE.strip()
    if raw.lower() in PROFILES:
        return parse_profile(PROFILES[raw.lower()]), raw.lower()
    if raw:
        return parse_profile(raw), "custom"
    return parse_profile(PROFILES["light"]), "light"


def profile_period(profile):
    return max(end for _, end, _ in profile) * 60.0


def percent_at(elapsed_seconds, profile):
    el_min = elapsed_seconds / 60.0
    for start, end, pct in profile:
        if start <= el_min < end:
            return pct
    return profile[-1][2]


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


def _load_worker(profile, period, ref, window, stop):
    while not stop.is_set():
        elapsed = (time.monotonic() - ref) % period
        busy = window * percent_at(elapsed, profile) / 100.0
        window_start = time.monotonic()
        while time.monotonic() < window_start + busy:
            pass
        remain = window - (time.monotonic() - window_start)
        if remain > 0:
            stop.wait(remain)


class LoadEmulator:
    def __init__(self, window=0.5):
        self.window = window
        self._stop = None
        self._processes = []

    @property
    def is_running(self):
        return self._stop is not None

    def start(self, profile, ref):
        if self.is_running:
            return
        self._stop = Event()
        n = os.cpu_count() or 1
        self._processes = [
            Process(target=_load_worker,
                    args=(profile, profile_period(profile), ref, self.window, self._stop),
                    daemon=True)
            for _ in range(n)
        ]
        for p in self._processes:
            p.start()

    def stop_now(self):
        if self._stop is None:
            return
        self._stop.set()
        for p in self._processes:
            p.join(timeout=2)
        self._stop = None
        self._processes = []


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
    out_dir = os.path.join("tests", stamp)
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "log.csv")

    profile, profile_name = resolve_profile()
    start_monotonic = time.monotonic()

    print(f"Battery test | start {human(start_dt)}")
    print(f"Log interval: {INTERVAL_SECONDS} s | stop at {STOP_CAPACITY}%")
    if profile_name == "custom":
        print(f"Load profile: custom — {LOAD_PROFILE}")
    else:
        print(f"Load profile: {profile_name} — {LOAD_PROFILE}")
    for start, end, pct in profile:
        print(f"  {start:>4.1f}–{end:<4.1f} min: {pct:>4.0f}%")
    print(f"Output: {os.path.abspath(out_dir)}")
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

    load_emu = LoadEmulator()
    load_emu.start(profile, start_monotonic)

    count = 0
    while not should_stop:
        dt = datetime.datetime.now()
        cpu = cpu_percent()
        bat = read_battery()
        log_console(dt, bat, cpu)
        log_csv(writer, dt, bat, cpu)
        log_file.flush()

        count += 1
        try:
            capacity = int(bat.get("capacity", 100))
        except ValueError:
            capacity = 100
        if capacity <= STOP_CAPACITY:
            print(f"Reached {capacity}% — stopping the test.")
            should_stop = True
            break

        if INTERVAL_SECONDS > 0:
            time.sleep(INTERVAL_SECONDS)

    load_emu.stop_now()
    log_file.close()

    end_dt = datetime.datetime.now()
    print()
    print(f"Finished {human(end_dt)} | duration {(end_dt - start_dt).total_seconds() / 60:.1f} min | records: {count}")
    print(f"Log: {os.path.abspath(log_path)}")


if __name__ == "__main__":
    main()
