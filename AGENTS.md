# AGENTS.md

Personal Waybar + Hyprland status bar. There is no root build, test runner, lint
config, or CI: `config` and `style.css` drive the live bar, `scripts/` are
one-shot modules, and each `tools/<name>/` is a self-contained widget.

## Layout

- `config` — live Waybar config. It contains `//` comments, so `jq` and strict
  JSON parsers reject it; preserve comments when editing.
- `style.css` — GTK CSS (Void theme). State classes emitted by scripts
  (`.error`, `.hidden`, `.connected`, etc.) are styled here.
- `scripts/` — shared modules: memory, audacious, openrouter, vpn, bluetooth,
  singapore.
- `tools/<name>/` — self-contained widgets. Convention: `*_waybar.sh` /
  `gcal.sh` prints JSON, `*_click.sh` opens the TUI in `footclient`, and
  `*_tui.py` is the curses UI. `tools/_template/README.md` is the canonical
  pattern; copy it rather than adding shared imports.
- `tools/daemons` and `tools/wifi` are git submodules with their own remotes,
  READMEs, and tests. Commit inside the submodule; the parent only records the
  gitlink. A root `git status` showing `M tools/wifi` usually means dirty
  submodule contents, not a root edit.

## Commands

Tests are per tool; run them from the tool directory:

```sh
cd tools/gcal && python3 -m unittest discover -v
cd tools/daemons && python3 -m unittest discover
cd tools/wifi && .venv/bin/python -m unittest test_wifi
cd tools/vis && make test
```

- Single gcal test: `cd tools/gcal && python3 -m unittest test_gcal_tui.CalendarDataTests.test_fetch_includes_month_end_and_preserves_ids`
- Syntax check a TUI: `python3 -m py_compile tools/gcal/gcal_tui.py`
- Build the visualizer: `cd tools/vis && make` (needs `libpipewire-0.3` via
  `pkg-config`); `make install` writes to `/usr/local`.

## Waybar wiring

- Tooltip newlines must be literal `\r`, not `\n`, and Pango markup characters
  `& < >` must be escaped. Existing status scripts all do this; copy the
  pattern.
- Signal numbers are a hardcoded contract between `config` and scripts: `1`
  gcal, `2` audacious, `3` daemons, `5` openrouter, `8` vpn, `9` bluetooth.
  Change both sides together.
- Refresh with `pkill -RTMIN+N -x waybar`. Keep `-x`; without it `pkill` can
  also kill `waybar-vis`.
- Do not use `SIGUSR2` to reload config/style here: `tools/barstate/barstate.sh`
  documents it as unreliable (kills `waybar-vis`, crashes on tray re-init).
  Restart Waybar instead.

## Tool gotchas

- **gcal**: reads with `~/.local/bin/gcalcli`. Quick-add/delete run
  `gcal_api.py` through gcalcli's pipx Python
  (`~/.local/share/pipx/venvs/gcalcli/bin/python`) because system Python lacks
  the Google client. `gcal.sh` cache is `~/.cache/waybar-gcal/gcal.json`; the
  TUI cache is `~/.cache/gcalcli/events_cache.json` — they are different files.
  Tests mock `subprocess.run` and need no network.
- **wifi**: `backend.py` is the only place that calls `nmcli`. `.venv/` is
  gitignored but required by the Waybar command. `test_wifi.py` is mocked by
  default; `--live` changes the real connection.
- **daemons**: read `tools/daemons/AGENTS.md` first (config loaded once at
  import, cache versioning, polkit timeouts, curses loop untested).
- **vis**: `tools/vis/waybar-vis` is a tracked binary; `make` overwrites it.
- **barstate**: `tools/barstate/revert.sh` edits `style.css` in place and
  restarts Waybar; review it before running.

## Conventions

- Curses TUIs are copy-paste from `tools/_template/curses_tui_template.py`, not
  a shared package. Keep each `*_tui.py` standalone so
  `foot -- python3 tool_tui.py` works.
- Python code is stdlib-only unless a tool explicitly uses the wifi `.venv` or
  gcalcli's pipx env; do not add requirements.
- Errors go to `/tmp/<tool>_tui_error.log`; caches use atomic tmp-file +
  rename.
- `openrouter.env` is a live secret (gitignored). Never print or commit it;
  `scripts/openrouter.sh` expects `OPENROUTER_API_KEY` in the environment.
- No root formatter/linter; match surrounding shell/Python style. The daemons
  submodule CI runs `python3 -m unittest discover -v` on Python 3.12 and
  shellchecks its two entrypoints.
