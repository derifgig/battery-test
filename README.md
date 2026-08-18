# Laptop battery-life testing procedure

This document describes how to run a reproducible battery-life test from 100%
charge to 0%, and how to verify the authenticity of the collected data.

## Goal

Obtain an objective, reproducible, and verifiable estimate of battery runtime
under a standardized workload:

- a realistic light-user CPU profile (browsing, code, video) or a custom one,
- battery and CPU log **every minute**.

## Required environment

- OS: Linux (battery sysfs path `/sys/class/power_supply/BAT0`, `/proc/stat`).
- Laptop fully charged to 100% before starting.
- Ideally identical conditions across runs: room temperature, stable network
  connection, same screen brightness.

## Preparation

1. Charge the laptop to 100% and disconnect the AC adapter.
2. Disable system sleep and screen blanking so the test is not interrupted:
   ```
   python3 manage-sleep.py off
   ```
   (restore after the test with `python3 manage-sleep.py on`)
3. Disable power saving (if needed):
   - in GNOME/KDE: «Settings → Power → Never turn off the screen»;
   - `gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'`.
4. Set a fixed screen brightness (e.g., 50%) and state it in the report.
5. Close other applications so they do not affect the measurements.

## Run parameters

All parameters are set via environment variables (defaults in parentheses):

| Variable | Description | Default |
|---|---|---|
| `BAT_TEST_INTERVAL` | log record interval, seconds | `60` |
| `BAT_TEST_STOP_CAPACITY` | charge at which the test stops, % | `5` |
| `BAT_TEST_LOAD_PROFILE` | load profile: `light`, `video`, `compile`, or a custom spec | `light` |

## Load profiles

The load schedule repeats in a cycle and is defined by segments
`start-end:pct` (minutes from cycle start → % of total CPU capacity).

**`light`** — browsing + code, a little video (average ~10%):

| Cycle minute | CPU | Activity |
|---|---|---|
| 0 – 1 | 25% | browser start, opening tabs |
| 1 – 4 | 8% | browsing, scrolling |
| 4 – 4.5 | 30% | loading a new tab |
| 4.5 – 6 | 6% | reading |
| 6 – 7 | 12% | 1080p video |
| 7 – 8 | 5% | typing code |
| 8 – 8.5 | 20% | save + linter/formatter |
| 8.5 – 10 | 3% | near idle |

**`video`** — more video streaming (average ~13%):

| Cycle minute | CPU | Activity |
|---|---|---|
| 0 – 1 | 30% | browser start |
| 1 – 2 | 8% | browsing |
| 2 – 7 | 14% | video streaming |
| 7 – 8 | 6% | code |
| 8 – 8.5 | 25% | save + linter/formatter |
| 8.5 – 10 | 4% | near idle |

**`compile`** — code with small project builds + video (average ~12%):

| Cycle minute | CPU | Activity |
|---|---|---|
| 0 – 1 | 30% | browser start |
| 1 – 3 | 7% | browsing / code |
| 3 – 3.3 | 45% | building a small project |
| 3.3 – 5 | 10% | code |
| 5 – 6 | 15% | video |
| 6 – 7.5 | 6% | reading |
| 7.5 – 7.8 | 40% | building a small project |
| 7.8 – 10 | 5% | near idle |

**Custom** — any spec, e.g. `0-1:20,1-5:5` (20% for the first minute,
then 5% until minute 5). The cycle length is the end of the last segment.

If `BAT_TEST_LOAD_PROFILE` is unset, the `light` profile is used.

## Running the test

```
cd battery-test
python3 battery-test.py
```

Example with a custom profile:

```
BAT_TEST_LOAD_PROFILE=light python3 battery-test.py
```

Example with an inline profile spec:

```
BAT_TEST_INTERVAL=60 BAT_TEST_LOAD_PROFILE=0-1:20,1-5:5 python3 battery-test.py
```

The test stops automatically when the charge reaches `BAT_TEST_STOP_CAPACITY`
(5% by default). You can also stop it manually with `Ctrl+C`; the log will be
preserved.

## What happens during the test

The load follows the selected profile. The schedule repeats from the test start
(a `light` profile example):

| Test minute | CPU |
|---|---|
| 0 – 1 | ~25% |
| 1 – 4 | ~8% |
| 4 – 4.5 | ~30% |
| 4.5 – 6 | ~6% |
| 6 – 7 | ~12% |
| 7 – 8 | ~5% |
| 8 – 8.5 | ~20% |
| 8.5 – 10 | ~3% |
| 10 – 20 | the cycle repeats |

Every minute the script:

1. measures CPU utilization (averaged over ~1 s via `/proc/stat`);
2. reads the battery state from `/sys/class/power_supply/BAT0`;
3. writes a row to `log.csv`;
4. stops the CPU load once the load period is over.

## Results

All files are written to `tests/<date-time>/`:

- `log.csv` — the test log. Columns:
  - `time` — local time, `unix` — Unix timestamp (for plotting);
  - `capacity` — battery charge, %;
  - `status` — battery status (`Discharging`);
  - `cpu_percent` — CPU utilization, % (should follow the selected profile);
  - `power_w` — current power draw, W;
  - `voltage_v` — voltage, V;
  - `energy_wh` — remaining energy, Wh;
  - `energy_full_wh` — full energy, Wh;
  - `cycle_count` — number of charge/discharge cycles.

## Analysis and publication

1. Plot `capacity` against `time` — the discharge curve.
2. Runtime = `max(time) - min(time)` for `status == Discharging`.
3. The CPU chart should follow the selected load profile — confirming the load
   scenario was executed.
4. For the website, publish: the methodology, `log.csv`, and the chart.

## Recommendations for objectivity

- Run the test **3–5 times** and report the mean and spread
  (e.g., `7.1 ± 0.3 h`).
- Publish the full `log.csv`, not just the final number.
- State the conditions: brightness, OS/kernel version, browser, run parameters,
  CPU core count, and battery `cycle_count`.
- Do not change parameters between runs of one report.

## Running battery-monitor in the background

`battery-monitor.py` logs battery and CPU stats without any load emulation.
It is useful for passive monitoring during normal use.

```bash
nohup python3 battery-monitor.py &
echo $!
```

Output goes to `nohup.out` in the current directory.
To stop: `kill <PID>` (the PID is printed by `echo $!`, or find it with `pgrep -f battery-monitor.py`).

## Known limitations

- Runtime depends on the battery state and age (`cycle_count` accounts for this).
- Random spikes from background OS processes may slightly affect measurements;
  multiple runs help minimize the impact.
- CPU load is set as a percentage of the total CPU capacity (one process per
  core), so results are comparable across different laptops.
