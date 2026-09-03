#!/usr/bin/env python3
"""curses_tui_template.py — Copy-paste skeleton for Waybar curses TUIs.

Usage:
  cp _template/curses_tui_template.py mytool/mytool_tui.py
  # Fill 3 spots: CACHE/ERROR paths, fetch_data(), draw_main()
  # Optionally: draw_detail(), tabs, form dialogs

Theme: Void vibe — magenta accent #b48ead, border #5c5c6e, green #a3be8c,
       red #bf616a, blue #81a1c1. See style.css and wifitui.py for ref.
"""
import curses
import json
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
CACHE_PATH = Path.home() / ".cache" / "mytool_cache.json"  # or /tmp/mytool.json
ERROR_LOG = Path("/tmp/mytool_tui_error.log")

# ── Theme (Void) ───────────────────────────────────────────────────────
# Keep dynamic cp() like wifi/ui/colors.py for future expansion
_PAIRS: dict[tuple[int, int], int] = {}
_next_pair = 1

C_ACCENT = 5   # magenta #b48ead
C_GREEN = 2    # #a3be8c
C_RED = 1      # #bf616a
C_BLUE = 6     # #81a1c1
C_BORDER = 8   # #5c5c6e
C_TEXT = 7     # #c7c0d0 / white
C_HELP = 8     # muted gray

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def cp(fg: int, bg: int = -1) -> int:
    global _next_pair
    key = (fg, bg)
    if key not in _PAIRS:
        curses.init_pair(_next_pair, fg, bg)
        _PAIRS[key] = _next_pair
        _next_pair += 1
    return curses.color_pair(_PAIRS[key])


def init_colors() -> None:
    """Set up curses color pairs matching the terminal theme."""
    curses.start_color()
    curses.use_default_colors()
    # Pre-register common pairs (optional, cp() will lazy-init anyway)
    cp(C_ACCENT)
    cp(C_GREEN)
    cp(C_RED)
    cp(C_BLUE)
    cp(C_BORDER)
    cp(C_TEXT)
    cp(C_HELP)


# ── Cache (atomic) ─────────────────────────────────────────────────────
def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    tmp.replace(CACHE_PATH)


# ── Data layer (REPLACE ME) ────────────────────────────────────────────
def fetch_data() -> dict:
    """Fetch fresh data. Replace with sysfs/nmcli/gcalcli/etc."""
    # Example: sysfs read
    # try:
    #     return Path("/sys/class/power_supply/BAT1/capacity").read_text().strip()
    # except Exception:
    #     return {}
    #
    # Example: subprocess
    # try:
    #     r = subprocess.run(["mycli", "--json"], capture_output=True, text=True, timeout=5)
    #     return json.loads(r.stdout) if r.returncode == 0 else {}
    # except Exception:
    #     return {}
    return {"example": "data"}


# Background fetch helpers (optional — for slow I/O like gcal/daemons/wifi)
_cache_lock = threading.Lock()
_refreshing = False
_cache_data: dict = {}


def bg_fetch(key: str) -> None:
    global _refreshing
    data = fetch_data()
    with _cache_lock:
        _cache_data[key] = data
        save_cache(_cache_data)
        _refreshing = False


def start_bg_fetch(key: str) -> bool:
    """Fire off bg fetch if key not cached. Returns True if started."""
    global _refreshing
    with _cache_lock:
        if _refreshing or key in _cache_data:
            return False
        _refreshing = True
    t = threading.Thread(target=bg_fetch, args=(key,), daemon=True)
    t.start()
    return True


# ── Drawing helpers ────────────────────────────────────────────────────
def draw_header(stdscr: "curses.window", title: str) -> None:
    h, w = stdscr.getmaxyx()
    x_off = (w - len(title)) // 2
    stdscr.attron(cp(C_ACCENT) | curses.A_BOLD)
    try:
        stdscr.insstr(0, 0, "┌" + "─" * (w - 2) + "┐")
    except curses.error:
        pass
    stdscr.addstr(0, max(x_off, 0), title)
    stdscr.attroff(cp(C_ACCENT) | curses.A_BOLD)


def draw_footer(stdscr: "curses.window", help_text: str) -> None:
    h, w = stdscr.getmaxyx()
    stdscr.attron(cp(C_BORDER) | curses.A_BOLD)
    try:
        stdscr.insstr(h - 1, 0, "└" + "─" * (w - 2) + "┘")
    except curses.error:
        pass
    stdscr.attroff(cp(C_BORDER) | curses.A_BOLD)
    # help line above footer — caller should draw at h-2 or detail_start
    # example: stdscr.attron(cp(C_HELP)); stdscr.addstr(h-2, 4, help_text)


def draw_main(stdscr: "curses.window", data: dict, spinner_char: str = " ", loading: bool = False) -> int:
    """Draw main content. Return y after content for footer/detail."""
    h, w = stdscr.getmaxyx()
    y = 2
    # Example rows — replace with real layout
    stdscr.attron(cp(C_TEXT) | curses.A_BOLD)
    try:
        stdscr.addstr(y, 4, f"Data: {data}")
    except curses.error:
        pass
    stdscr.attroff(cp(C_TEXT) | curses.A_BOLD)
    y += 2
    if loading:
        stdscr.attron(cp(C_BLUE))
        try:
            stdscr.addstr(y, 4, f" {spinner_char} Loading...")
        except curses.error:
            pass
        stdscr.attroff(cp(C_BLUE))
        y += 1
    return y


# ── Main loop ──────────────────────────────────────────────────────────
def _main(stdscr: "curses.window") -> None:
    curses.curs_set(0)
    curses.set_escdelay(25)
    init_colors()
    stdscr.timeout(200)

    # Load cache + start bg fetch if needed
    global _cache_data
    _cache_data.update(load_cache())
    # Example: start_bg_fetch("2026-09")

    spinner_idx = 0
    status_msg: str | None = None
    status_color = C_HELP

    while True:
        spinner_idx = (spinner_idx + 1) % len(SPINNER)
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        # ── Small terminal guard (adjust per tool) ──
        if h < 15 or w < 45:
            try:
                stdscr.addstr(0, 0, f"Terminal too small — need 45×15, got {w}×{h}")
                stdscr.addstr(2, 0, "Resize or press q to quit")
            except curses.error:
                pass
            stdscr.refresh()
            stdscr.timeout(-1)
            k = stdscr.getch()
            if k in (ord("q"), ord("Q"), 27):
                return
            h2, w2 = stdscr.getmaxyx()
            if h2 >= 15 and w2 >= 45:
                stdscr.timeout(200)
            continue

        # ── Header ──
        draw_header(stdscr, " MyTool ")

        # ── Body ──
        is_loading = _refreshing
        data = _cache_data.get("example", fetch_data() if not _cache_data else _cache_data)
        # For bg mode: data = _cache_data.get(key, {})
        grid_end = draw_main(stdscr, data, SPINNER[spinner_idx], is_loading)

        # ── Separator (optional) ──
        sep_y = grid_end + 1
        if sep_y < h - 2:
            stdscr.attron(cp(C_BORDER))
            try:
                stdscr.addstr(sep_y, 0, "─" * (w - 1))
            except curses.error:
                pass
            stdscr.attroff(cp(C_BORDER))

        # ── Footer / status ──
        help_text = " ↑/↓ nav  |  r refresh  |  q quit"
        if status_msg:
            stdscr.attron(cp(status_color) | curses.A_BOLD)
            try:
                stdscr.addstr(h - 2, 4, status_msg[: w - 8])
            except curses.error:
                pass
            stdscr.attroff(cp(status_color) | curses.A_BOLD)
        elif is_loading:
            stdscr.attron(cp(C_HELP))
            try:
                stdscr.addstr(h - 2, 4, " ⟳ Syncing...")
            except curses.error:
                pass
            stdscr.attroff(cp(C_HELP))
        else:
            stdscr.attron(cp(C_HELP))
            try:
                stdscr.addstr(h - 2, 4, help_text)
            except curses.error:
                pass
            stdscr.attroff(cp(C_HELP))

        draw_footer(stdscr, "")
        stdscr.refresh()

        # ── Input ──
        key = stdscr.getch()
        if key == -1:
            continue
        status_msg = None

        if key in (ord("q"), ord("Q"), 27):
            break
        elif key in (ord("r"), ord("R")):
            # Example refresh: clear cache + refetch
            # _cache_data.clear(); start_bg_fetch("key")
            # or direct: data = fetch_data()
            pass
        elif key == curses.KEY_UP:
            pass
        elif key == curses.KEY_DOWN:
            pass
        elif key == curses.KEY_RESIZE:
            continue


def main(stdscr: "curses.window") -> None:
    try:
        _main(stdscr)
    except Exception:
        tb = traceback.format_exc()
        with open(ERROR_LOG, "w") as f:
            f.write(tb)
        try:
            stdscr.clear()
            stdscr.refresh()
            h, w = stdscr.getmaxyx()
            for i, line in enumerate(tb.split("\n")):
                if i >= h - 1:
                    break
                line = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in line)
                try:
                    stdscr.addstr(i, 0, line[: w - 1])
                except curses.error:
                    pass
            stdscr.addstr(min(len(tb.split("\n")), h - 1), 0, "See {} — press any key".format(ERROR_LOG))
            stdscr.getch()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        tb = traceback.format_exc()
        with open(ERROR_LOG, "w") as f:
            f.write(tb)
        print(f"CRASHED — see {ERROR_LOG}", file=sys.stderr)
        print(tb, file=sys.stderr)
        sys.exit(1)
