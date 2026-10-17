# gcal — Project Overview

## Purpose
A lightweight desktop Google Calendar integration for a Waybar + foot + gcalcli setup.
It provides:
- a Waybar status module that shows today’s event count,
- a click handler that opens different calendar views,
- an interactive curses TUI for browsing and managing events.

Calendar reads use `gcalcli`; quick-add and exact-ID deletion use the API client
installed in gcalcli's pipx environment.

## Repository layout
```
tools/gcal/
├── gcal.sh           # Waybar calendar module (status + tooltip)
├── gcal_click.sh     # Waybar click handler (left/right/middle)
├── gcal_tui.py       # Interactive month-view calendar TUI
├── gcal_api.py       # Quick-add and exact event deletion via Calendar API
├── test_gcal_tui.py  # Unit tests for TUI, cache, and API behavior
└── PROJECTS.md       # Project overview
```

This directory has no README, Makefile, or requirements file; the Waybar config is at the repository root.

## File-by-file tour

### `gcal.sh`
- **Role**: Waybar custom module.
- **Flow**:
  1. Checks gcalcli's OAuth token at `$XDG_DATA_HOME/gcalcli/oauth` or its legacy path.
  2. If missing, emits JSON with a “not configured” state.
  3. Otherwise serves cached JSON immediately and refreshes stale data in the background.
  4. Counts today’s events from a one-day agenda range.
  5. Emits JSON for Waybar containing:
     - `text` — event count,
     - `tooltip` — today’s event list,
     - `class` — status hint.
- **Dependencies**: `gcalcli`, `jq`, `awk`, GNU `date`/`stat`, `timeout`, `pkill`.

### `gcal_click.sh`
- **Role**: translates Waybar mouse clicks into calendar actions.
- **Flow**:
  - `agenda` / `left` → open full-screen `gcal_tui.py` in `footclient`; refresh Waybar on exit.
  - `calendar` / `right` → open plain `gcalcli` agenda in `footclient`, press Enter to close.
  - `browser` / `middle` → open Google Calendar in `helium-browser`.
  - default → same as left click.
- **Dependencies**: `foot`, `python3`, `helium-browser`, Waybar (`pkill -RTMIN+1 waybar`).

### `gcal_tui.py`
- **Role**: curses month-view calendar.
- **Architecture**:
  - **Data layer**: reads IDs, calendar names, dates, and titles via `gcalcli agenda --tsv`; quick-add and exact-ID deletion use `gcal_api.py` with gcalcli's pipx credentials.
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
  - atomic writes through a unique temporary file,
  - cached data remains visible during background refresh and on fetch failure.
- **Error handling**:
  - `gcalcli` timeouts / missing binary → stale cache remains visible with a sync error,
  - crash traceback written to `/tmp/gcal_tui_error.log`.
- **Dependencies**: Python standard library, gcalcli via pipx, and its installed Google API client.

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
       ├─ Background fetch via gcalcli for stale/missing data
       ├─ Draw month grid + selected day detail
       └─ Quick-add and exact-ID deletion via gcal_api.py
```

### Calendar/TUI flow
1. Load cache from disk.
2. For the requested month:
    - show cached events immediately if present,
    - refresh in a background thread if missing, stale, or explicitly requested.
3. Render the month grid with:
   - month/year header with optional loading spinner,
   - weekday headers,
   - event indicators,
   - today highlight,
   - selected day highlight.
4. Render selected-day detail pane (start time, title, all-day markers).
5. Input loop:
    - navigation triggers month/day changes and conditional fetches,
    - `n` creates through the Calendar API, then inserts the returned event into the local cache,
    - `d` lists at most nine choices and deletes the selected event by exact ID,
    - `r` refreshes the current month without discarding the last good view,
    - `q` quits and triggers Waybar refresh.

## Environment assumptions
- `gcalcli` installed at `~/.local/bin/gcalcli`.
- OAuth credentials stored at `$XDG_DATA_HOME/gcalcli/oauth` (usually `~/.local/share/gcalcli/oauth`).
- Terminal emulator: `foot`.
- Browser: `helium-browser`.
- Waybar on the host with a module configured to call `gcal.sh` and `gcal_click.sh`.
- Optional cache directory: `~/.cache/gcalcli/`.

## Notable conventions
- shell scripts emit JSON and use `jq` for structured output.
- UI state stays in `gcal_tui.py`; shared cache/thread state is protected by one lock.
- month fetching is fire-and-forget from the user’s perspective; cursors keep moving while data loads.

## Current limitations / quirks
- tests run with `python3 -m unittest discover -v` from this directory,
- arrow-key behavior inside the TUI differs from some standard calendars (up/down advance or retreat by one day),
- `gcalcli` results are parsed from TSV headers; embedded tabs/newlines are unsupported,
- no explicit multi-calendar filtering is exposed in the UI.
