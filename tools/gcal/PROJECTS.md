# gcal — Project Overview

## Purpose
A lightweight desktop Google Calendar integration for a Waybar + foot + gcalcli setup.
It provides:
- a Waybar status module that shows today’s event count,
- a click handler that opens different calendar views,
- an interactive curses TUI for browsing and managing events.

All calendar reads/writes go through `gcalcli`.

## Repository layout
```
/home/neon/Projects/tools/gcal/
├── gcal.sh           # Waybar calendar module (status + tooltip)
├── gcal_click.sh     # Waybar click handler (left/right/middle)
├── gcal_tui.py       # Interactive month-view calendar TUI
├── .git/             # Git repository (no history detected in this tree)
├── .agents/          # Empty
└── .codex/           # Empty
```

There is no README, Makefile, requirements file, or Waybar config in this repo.

## File-by-file tour

### `gcal.sh`
- **Role**: Waybar custom module.
- **Flow**:
  1. Checks whether gcalcli is OAuth-configured (`~/.config/gcalcli/oauth.json`).
  2. If missing, emits JSON with a “not configured” state.
  3. Otherwise runs `gcalcli agenda <today>`.
  4. Counts today’s events from the printed agenda.
  5. Emits JSON for Waybar containing:
     - `text` — event count,
     - `tooltip` — full agenda,
     - `class` — status hint.
- **Dependencies**: `gcalcli`, `jq`, `grep`, `sed`.

### `gcal_click.sh`
- **Role**: translates Waybar mouse clicks into calendar actions.
- **Flow**:
  - `agenda` / `left` → open full-screen `gcal_tui.py` in `foot`; refresh Waybar on exit.
  - `calendar` / `right` → open plain `gcalcli` agenda in `foot`, press Enter to close.
  - `browser` / `middle` → open Google Calendar in `helium-browser`.
  - default → same as left click.
- **Dependencies**: `foot`, `python3`, `helium-browser`, Waybar (`pkill -RTMIN+1 waybar`).

### `gcal_tui.py`
- **Role**: curses month-view calendar.
- **Architecture**:
  - **Data layer**: reads events via `gcalcli agenda --tsv` and persists them in `~/.cache/gcalcli/events_cache.json`.
  - **UI layer**: renders month grid, day detail pane, and status/help bar.
  - **Interaction layer**: keyboard input for navigation, create/delete, and cache refresh.
- **Key behaviors**:
  - month navigation: left/right arrows,
  - day navigation: up/down arrows,
  - go to today: `g`,
  - refresh cache: `r`,
  - new event: `n`,
  - delete event: `d`,
  - quit: `q`.
- **Concurrency model**: background threads for I/O so the UI stays responsive.
- **Caching**:
  - per-month cache stored under a `YYYY-MM` key,
  - atomic writes (rename from `.tmp`),
  - reloaded if present, bypassed if missing.
- **Error handling**:
  - `gcalcli` timeouts / missing binary → empty calendar view,
  - crash traceback written to `/tmp/gcal_tui_error.log`.
- **Dependencies**: standard library `curses`, `calendar`, `datetime`, `json`, `subprocess`, `threading`, plus `gcalcli` on PATH.

## Data flow

### High-level user flow
```
User input
  ├─ Waybar widget
  │    ├─ Left click → gcal_click.sh → foot + gcal_tui.py
  │    ├─ Right click → gcal_click.sh → foot + gcalcli agenda
  │    └─ Middle click → gcal_click.sh → browser
  └─ Inside gcal_tui.py
       ├─ Load cache from ~/.cache/gcalcli/events_cache.json
       ├─ Background fetch via gcalcli if missing
       ├─ Draw month grid + selected day detail
       └─ Keyboard commands queue writes back through gcalcli
```

### Calendar/TUI flow
1. Load cache from disk.
2. For the requested month:
   - if cached → use cached events,
   - if missing → start background fetch thread.
3. Render the month grid with:
   - month/year header with optional loading spinner,
   - weekday headers,
   - event indicators,
   - today highlight,
   - selected day highlight.
4. Render selected-day detail pane (start time, title, all-day markers).
5. Input loop:
   - navigation triggers month/day changes and conditional fetches,
   - `n` prompts for a summary, creates via `gcalcli quick`, then refreshes cache,
   - `d` prompts for event deletion, deletes via `gcalcli`, then refreshes cache,
   - `r` drops cache for the current month and re-fetches,
   - `q` quits and triggers Waybar refresh.

## Environment assumptions
- `gcalcli` installed at `~/.local/bin/gcalcli`.
- OAuth credentials stored at `~/.config/gcalcli/oauth.json`.
- Terminal emulator: `foot`.
- Browser: `helium-browser`.
- Waybar on the host with a module configured to call `gcal.sh` and `gcal_click.sh`.
- Optional cache directory: `~/.cache/gcalcli/`.

## Notable conventions
- shell scripts emit JSON and use `jq` for structured output.
- UI keeps state in a small set of locals inside `gcal_tui.py`.
- month fetching is fire-and-forget from the user’s perspective; cursors keep moving while data loads.

## Current limitations / quirks
- no package manifest or test suite in the repo,
- arrow-key behavior inside the TUI differs from some standard calendars (up/down advance or retreat by one day),
- `gcalcli` results are parsed via split assumptions around TSV formatting,
- no explicit multi-calendar filtering is exposed in the UI.
