#!/usr/bin/env python3
"""Waybar module: VPN indicator, visible only while a VPN is active."""

import csv
import json
import subprocess
import sys


def _run(args: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _rows(raw: str):
    for line in raw.splitlines():
        if line.strip():
            yield next(csv.reader([line], delimiter=":", escapechar="\\"))


vpn = ""
for parts in _rows(_run(["nmcli", "-t", "-f", "TYPE,NAME", "con", "show",
                         "--active"])):
    if len(parts) >= 2 and parts[0] == "vpn":
        vpn = parts[1]
        break

if "--disconnect" in sys.argv[1:]:
    if vpn:
        _run(["nmcli", "con", "down", vpn], timeout=15)
        _run(["pkill", "-RTMIN+8", "-x", "waybar"])
    raise SystemExit(0)

if vpn:
    output = {"text": "\uf023", "class": "active", "tooltip": f"VPN: {vpn}"}
else:
    output = {"text": "", "class": "hidden", "tooltip": ""}

print(json.dumps(output))
