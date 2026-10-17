# Curses TUI Template — Copy-Paste Skeleton

Same Void theme across all Waybar tools: `style.css` `#b48ead` magenta accent, `#5c5c6e` border, `#a3be8c` green, `#bf616a` red, `#81a1c1` blue, `#c7c0d0` text.

This is **copy-paste**, not a shared import — keeps each `*tui.py` self-contained so `foot -- python3 tool_tui.py` stays portable.

## Quick start

```sh
cp ~/.config/waybar/tools/_template/curses_tui_template.py ~/.config/waybar/tools/mytool/mytool_tui.py
# edit 3 spots:
# 1. CACHE_PATH / ERROR_LOG names
# 2. fetch_data() -> your sysfs/nmcli/gcalcli/subprocess logic
# 3. draw_main() -> your layout (rows, progress bar, calendar grid, table)
# optional: draw_detail(), tabs, FormDialog
chmod +x mytool_tui.py
foot --title="mytool" -- python3 mytool_tui.py
```

## Template structure (mirrors gcal — most complete)

```
Paths:      APP_DIR, CACHE_PATH, ERROR_LOG
Theme:      cp() dynamic + init_colors()  # from wifi/ui/colors.py:17 + gcal:65
Cache:      load_cache()/save_cache() atomic tmp.replace  # gcal:58
Data:       fetch_data() + bg_fetch()/start_bg_fetch() threading optional
Draw:       draw_header(title)  # ┌─┐ magenta bold
            draw_main(data, spinner, loading) -> y
            draw_footer(help)   # └─┘
Loop:       _main(stdscr): curs_set(0), escdelay(25), timeout(200), spinner SPINNER="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            small-term guard, header/body/separator/footer, getch() handle q/Esc/r/arrows/Tab
Crash:      main() try/_main except -> ERROR_LOG + draw tb on stdscr + curses.wrapper(main)
```

## Keymap (normalized)

* `q`/`Q`/`Esc` quit
* `r` refresh (clear cache + bg_fetch)
* `↑/↓` nav, `←/→` month/page, `Tab` tabs, `Enter`/`Space` action
* `e` edit/mask, `d` delete/disconnect, `g` today/home
* `h<15 w<45` guard — show "Terminal too small" then block `timeout(-1)` until resize or q

## Theme details

```python
C_ACCENT=5  # magenta #b48ead header/title
C_GREEN=2   # active/connected
C_RED=1     # masked/error
C_BLUE=6    # info/BSSID
C_BORDER=8  # ─│ border/help
C_TEXT=7    # body
SPINNER="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# borders: ┌─┐/└─┘, header centered, separator ─, footer help C_HELP muted
```

See `battery_tui.py:72` (simple), `daemons_tui.py:266` (tabs+search), `gcal_tui.py:532` (calendar+threads), `wifi/ui/app.py:57` (class-based Table+Dialog) for examples after migration.

## Waybar wrapper (normalize)

```sh
# _click.sh
TUI="$HOME/.config/waybar/tools/mytool/mytool_tui.py"
foot --title="mytool" --window-size-chars=85x30 -- python3 "$TUI"
  pkill -RTMIN+1 -x waybar  # -x: exact match, or you also kill waybar-vis (RTMIN default-kills it)
# config
"custom/mytool": { "exec": "mytool_waybar.sh", "return-type": "json", "on-click": "mytool_click.sh" }
```

## Checklist for new TUI

- [ ] copy template, rename CACHE/ERROR_LOG
- [ ] implement fetch_data() + optional threading
- [ ] implement draw_main() using cp(C_*) colors
- [ ] set min_h/w guard
- [ ] test: `python3 -m py_compile mytool_tui.py`, `foot -- python3`, resize, `q`/`r`, check `/tmp/mytool_error.log`
