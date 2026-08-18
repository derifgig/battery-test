#!/usr/bin/env python3
import os
import subprocess
import sys

TARGETS = ["sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"]


def run(cmd):
    print("+", " ".join(cmd), flush=True)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"WARNING: command failed with exit code {result.returncode}", flush=True)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("off", "on"):
        print("Usage: python3 manage-sleep.py off|on")
        print("  off  — mask system sleep targets (test runs uninterrupted)")
        print("  on   — unmask them back to default")
        sys.exit(2)

    action = sys.argv[1]

    if os.geteuid() != 0:
        print("Re-running with sudo...")
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

    for target in TARGETS:
        verb = "mask" if action == "off" else "unmask"
        run(["systemctl", verb, target])

    if action == "off":
        print("Sleep/hibernate targets are masked. Run 'python3 manage-sleep.py on' to restore.")
    else:
        print("Sleep/hibernate targets are unmasked (back to default).")


if __name__ == "__main__":
    main()
