# Battery TUI Project

## Overview

This project provides a terminal-based status readout for the system battery, using a Python curses interface. It's intended for quick inspection of battery health, status, charge level, temperature, and related power-supply details.

## Repository Structure

```
├── PROJECTS.md           # Project overview and usage flow (this file)
├── battery_tui.py        # Main TUI script
├── .git/                 # Git metadata
├── .agents/              # Agent-related configuration
└── .codex/               # Codex-related configuration
```

## Program Flow (battery_tui.py)

1. **Entry point**: `curses.wrapper(main)` initializes the terminal UI safely.
2. **Data collection**:
   - Reads battery metrics from `/sys/class/power_supply/BAT1`.
   - Calls `acpi -V` for thermal/temperature data and temperature parsing.
3. **Rendering**:
   - Shows a centered header and large charge percentage.
   - Draws a colorized progress bar for charge level.
   - Renders rows for status, health, cycle count, temperature, model, and voltage.
   - Includes a separator and footer controls.
4. **Interaction**:
   - Press `r` to refresh battery data.
   - Press `q` or `ESC` to quit.
   - Any other key is ignored.
5. **Error handling**:
   - Exceptions are logged to `/tmp/battery_tui_error.log`.
   - A fallback terminal message prints crash details if curses cannot initialize.

## Data Sources

- Linux power supply sysfs under `/sys/class/power_supply/BAT1`.
- ACPI via `acpi -V` when available.

## Usage Notes

- Run with Python 3: `python battery_tui.py`
- Requires a terminal that supports curses and is at least 45x15 for stable rendering.
