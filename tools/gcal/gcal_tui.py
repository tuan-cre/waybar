#!/usr/bin/env python3
"""
gcal_tui.py — Google Calendar month TUI for gcalcli
Interactive curses calendar with async event fetching.
Arrow keys to navigate, q to quit.
"""

import calendar
import curses
import functools
import json
import os
import subprocess
import sys
import threading
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

GCALCLI = os.path.expanduser("~/.local/bin/gcalcli")

# ── Theme (Void — same as _template) ─────────────────────────────────
# Color pair indices — keep template mapping: ACCENT=magenta #b48ead, etc.
C_DEFAULT = 1
C_HEADER = 2    # magenta #b48ead (C_ACCENT in template)
C_TODAY = 3     # reversed
C_WEEKDAY = 4   # muted gray
C_EVENT = 5     # green #a3be8c
C_EVENT_DOT = 6 # cyan #81a1c1
C_BORDER = 7    # muted #5c5c6e
C_HELP = 8      # muted
C_DAY_NUM = 9 # bright white

APP_DIR = Path(__file__).resolve().parent
CACHE_FILE = Path.home() / ".cache" / "gcalcli" / "events_cache.json"
ERROR_LOG = Path("/tmp/gcal_tui_error.log")


def _ym_key(year, month):
    return f"{year:04d}-{month:02d}"


def _ym_from_key(key):
    y, m = key.split("-")
    return int(y), int(m)


def load_cache():
    """Read events_cache.json from disk, return {ym_key: events_dict} or {}."""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(cache):
    """Atomically write cache dict to disk."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"))
    tmp.replace(CACHE_FILE)


def init_colors():
    """Set up curses color pairs matching the terminal theme."""
    curses.start_color()
    curses.use_default_colors()

    curses.init_pair(C_DEFAULT, -1, -1)
    curses.init_pair(C_HEADER, 5, -1)  # magenta
    curses.init_pair(C_TODAY, 7, 5)    # light fg on magenta bg
    curses.init_pair(C_WEEKDAY, 8, -1) # muted gray
    curses.init_pair(C_EVENT, 2, -1)   # green
    curses.init_pair(C_EVENT_DOT, 6, -1)  # cyan
    curses.init_pair(C_BORDER, 8, -1)  # muted border
    curses.init_pair(C_HELP, 8, -1)    # muted help
    curses.init_pair(C_DAY_NUM, 7, -1) # white


def fetch_events(year, month):
    """Fetch events for a given month via gcalcli TSV output.

    Returns dict: {day: [(start_time, title, is_all_day), ...]}
    """
    last_day = calendar.monthrange(year, month)[1]
    start_str = f"{year:04d}-{month:02d}-01"
    end_str = f"{year:04d}-{month:02d}-{last_day:02d}"

    try:
        result = subprocess.run(
            [GCALCLI, "--nocolor", "agenda", "--tsv", "--military",
             start_str, end_str],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}

    events = defaultdict(list)
    lines = result.stdout.strip().split("\n")
    if len(lines) < 2:
        return events

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue

        start_date, start_time, *_rest = parts
        try:
            day = int(start_date.split("-")[2])
        except (IndexError, ValueError):
            continue

        title = parts[4]
        if not title.strip():
            continue

        is_all_day = (not start_time or start_time.strip() == ""
                      or start_time.strip() == "00:00")
        events[day].append((start_time.strip(), title.strip(), is_all_day))

    return dict(events)


def bg_fetch(events_cache, year, month):
    """Fetch events in background thread and store in shared cache."""
    events_cache[(year, month)] = fetch_events(year, month)
    disk = {_ym_key(*ym): ev for ym, ev in events_cache.items()}
    save_cache(disk)


def start_bg_fetch(events_cache, year, month):
    """Fire off a background fetch if the month isn't cached yet.

    Returns True if a fetch was started, False if already cached.
    """
    if (year, month) in events_cache:
        return False
    t = threading.Thread(
        target=bg_fetch, args=(events_cache, year, month),
        daemon=True,
    )
    t.start()
    return True


def draw_calendar(stdscr, year, month, events, selected_day, loading=False,
                  spinner_char=" "):
    """Draw the month calendar grid. Returns y after the grid."""
    height, width = stdscr.getmaxyx()

    cal = calendar.Calendar()
    month_days = cal.monthdays2calendar(year, month)

    cell_w = max((width - 4) // 7, 10)
    cel_h = 3

    today = date.today()

    # ── Header ──
    spinner = f" {spinner_char} " if loading else "   "
    header = f"{spinner}◀  {calendar.month_name[month]} {year}  ▶"
    x_offset = (width - len(header)) // 2
    stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
    stdscr.addstr(0, max(x_offset, 0), header)
    stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)

    # ── Day-of-week headers ──
    days_abbr = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    stdscr.attron(curses.color_pair(C_WEEKDAY) | curses.A_BOLD)
    for i, d in enumerate(days_abbr):
        x = 2 + i * (cell_w + 1)
        stdscr.addstr(2, x, f" {d:<{cell_w-1}}")
    stdscr.attroff(curses.color_pair(C_WEEKDAY) | curses.A_BOLD)

    # ── Horizontal divider ──
    div_y = 3
    stdscr.attron(curses.color_pair(C_BORDER))
    try:
        stdscr.addstr(div_y, 0, " " + "─" * (width - 2) + " ")
    except curses.error:
        pass
    stdscr.attroff(curses.color_pair(C_BORDER))

    # ── Day cells ──
    num_weeks = len(month_days)
    for row_idx, week in enumerate(month_days):
        row_y = div_y + 1 + row_idx * cel_h

        for col_idx, (day_num, _weekday) in enumerate(week):
            if day_num == 0:
                continue

            x = 2 + col_idx * (cell_w + 1)
            is_today = (year == today.year and month == today.month
                        and day_num == today.day)
            is_selected = (selected_day == day_num)

            # Day number
            day_str = f" {day_num:<{cell_w-1}}"
            if is_today:
                stdscr.attron(curses.color_pair(C_TODAY) | curses.A_BOLD)
                stdscr.addstr(row_y, x, day_str)
                stdscr.attroff(curses.color_pair(C_TODAY) | curses.A_BOLD)
            elif is_selected:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addstr(row_y, x, day_str)
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.attron(curses.color_pair(C_DAY_NUM))
                stdscr.addstr(row_y, x, day_str)
                stdscr.attroff(curses.color_pair(C_DAY_NUM))

            # Event lines
            day_events = events.get(day_num, [])
            max_events = cel_h - 1

            for ev_idx in range(max_events):
                ev_y = row_y + 1 + ev_idx
                if ev_y >= height - 1:
                    break
                if ev_idx < len(day_events):
                    ev_time, ev_title, is_all_day = day_events[ev_idx]
                    if is_all_day:
                        color = C_EVENT_DOT
                        prefix = "■ "
                    else:
                        color = C_EVENT
                        prefix = "• "

                    time_str = (f"{ev_time[:5]} " if not is_all_day and ev_time
                                else "")
                    display = f"{prefix}{time_str}{ev_title}"
                    if len(display) > cell_w - 1:
                        display = display[:cell_w - 3] + "…"
                    stdscr.attron(curses.color_pair(color))
                    try:
                        stdscr.addstr(ev_y, x + 1, display[:cell_w - 1])
                    except curses.error:
                        pass
                    stdscr.attroff(curses.color_pair(color))
                else:
                    try:
                        stdscr.addstr(ev_y, x, " " * cell_w)
                    except curses.error:
                        pass

    grid_bottom = div_y + 1 + num_weeks * cel_h

    # ── Vertical grid lines ──
    stdscr.attron(curses.color_pair(C_BORDER))
    for col_idx in range(8):
        x = 1 + col_idx * (cell_w + 1)
        for row_idx in range(num_weeks):
            row_y = div_y + 1 + row_idx * cel_h
            for line_off in range(cel_h):
                try:
                    stdscr.addstr(row_y + line_off, x, "│")
                except curses.error:
                    pass
    stdscr.attroff(curses.color_pair(C_BORDER))

    return grid_bottom + 1


def draw_detail(stdscr, year, month, events, selected_day, start_y):
    """Show events for the selected day below the calendar."""
    height, width = stdscr.getmaxyx()

    if start_y < height:
        stdscr.attron(curses.color_pair(C_HEADER))
        try:
            stdscr.addstr(start_y, 0, "─" * width)
        except curses.error:
            pass
        stdscr.attroff(curses.color_pair(C_HEADER))

    if selected_day is None:
        return

    try:
        day_date = date(year, month, selected_day)
    except ValueError:
        return

    day_name = day_date.strftime("%A")
    date_str = f" {day_name}, {calendar.month_name[month]} {selected_day}, {year} "

    line = start_y + 1
    if line < height:
        stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
        stdscr.addstr(line, max((width - len(date_str)) // 2, 0), date_str)
        stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)

    day_events = events.get(selected_day, [])
    line += 1

    if not day_events:
        if line < height:
            stdscr.attron(curses.color_pair(C_HELP))
            stdscr.addstr(line, 4, "  No events scheduled")
            stdscr.attroff(curses.color_pair(C_HELP))
        return

    for ev_time, ev_title, is_all_day in day_events:
        if line >= height - 1:
            break
        if is_all_day:
            stdscr.attron(curses.color_pair(C_EVENT_DOT))
            display = f"  ■  {ev_title}"
        else:
            stdscr.attron(curses.color_pair(C_EVENT))
            t = f"{ev_time[:5]}  " if ev_time else "      "
            display = f"  {t}{ev_title}"
        try:
            stdscr.addstr(line, 4, display[:width - 6])
        except curses.error:
            pass
        stdscr.attroff(curses.color_pair(C_EVENT_DOT))
        stdscr.attroff(curses.color_pair(C_EVENT))
        line += 1


def read_line(stdscr, y, x, max_w):
    """Read a line of text with getch(). Returns string or None on Esc."""
    value = []
    while True:
        key = stdscr.getch()
        if key in (ord('\n'), ord('\r')):
            return "".join(value)
        if key == 27:  # Esc
            return None
        if key in (127, curses.KEY_BACKSPACE, 8):
            if value:
                value.pop()
        elif 32 <= key <= 126 and len(value) < max_w:
            value.append(chr(key))
        else:
            continue  # skip redraw on unhandled keys
        display = "".join(value) + " " * (max_w - len(value))
        try:
            stdscr.addstr(y, x, display[:max_w])
            stdscr.move(y, x + len(value))
        except curses.error:
            pass
        stdscr.refresh()


def quick_add_prompt(stdscr, year, month, day):
    """Enhanced prompt for event creation with date context and defaults.

    Shows the selected date, a hint line with example format, accepts natural
    language input, and appends the date for reliable placement.
    Returns full text string or None on cancel.
    """
    height, width = stdscr.getmaxyx()

    day_date = date(year, month, day)
    date_str = day_date.strftime("%a, %b %d")  # e.g. "Mon, Jun 4"

    prompt = f" Add event for {date_str}: "
    y = min(height - 3, 17)
    x = 2
    max_w = max(width - x - len(prompt) - 4, 25)

    # Hint line — show example format
    hint = " e.g. Lunch @ 12pm with John  (Esc to cancel)"
    stdscr.attron(curses.color_pair(C_HELP))
    try:
        stdscr.addstr(y - 1, x, hint[:width - x - 1])
    except curses.error:
        pass
    stdscr.attroff(curses.color_pair(C_HELP))

    # Input line with reversed background
    stdscr.attron(curses.A_REVERSE)
    stdscr.addstr(y, 0, " " * width)
    stdscr.attroff(curses.A_REVERSE)
    stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
    stdscr.addstr(y, x, prompt)
    stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)
    stdscr.refresh()

    stdscr.timeout(-1)
    curses.curs_set(2)
    text = read_line(stdscr, y, x + len(prompt), max_w)
    curses.curs_set(0)
    stdscr.timeout(200)

    if not text or not text.strip():
        return None

    text = text.strip()
    month_abbr = calendar.month_abbr[month]
    return f"{text} on {month_abbr} {day}"

def delete_event_prompt(stdscr, events, day, year, month, primary_cal=None):
    """Prompt user to select an event on the given day to delete.
    Returns status string on attempt, or None if cancelled/no action."""
    day_events = events.get(day, [])
    if not day_events:
        return "No events to delete"
    height, width = stdscr.getmaxyx()
    prompt = " Delete event #: "
    y = min(height - 2, 18)
    x = 2
    max_w = max(width - x - len(prompt) - 4, 20)
    stdscr.attron(curses.A_REVERSE)
    stdscr.addstr(y, 0, " " * width)
    stdscr.attroff(curses.A_REVERSE)
    stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
    stdscr.addstr(y, x, prompt)
    stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)
    stdscr.refresh()
    stdscr.timeout(-1)
    curses.curs_set(2)
    # show list briefly above prompt
    list_y = y - 1
    for idx, (_, title, _) in enumerate(day_events[:max_w]):
        try:
            stdscr.addstr(list_y - idx, x, f"{idx+1}:{title[:max_w-3]}")
        except curses.error:
            pass
    stdscr.refresh()
    # read a single digit input
    key = stdscr.getch()
    curses.curs_set(0)
    stdscr.timeout(200)
    if ord('1') <= key <= ord(str(min(9, len(day_events)))):
        idx = key - ord('1')
        _, title, _ = day_events[idx]
        # build gcalcli delete command
        day_str = f"{year:04d}-{month:02d}-{day:02d}"
        next_day = date(year, month, day) + timedelta(days=1)
        end_str = next_day.strftime("%Y-%m-%d")
        cmd = [GCALCLI, "--nocolor", "delete", "--iamaexpert"]
        cal = primary_cal or _get_primary_cal()
        if cal:
            cmd += ["--calendar", cal]
        cmd += [title, day_str, end_str]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                stdin=subprocess.DEVNULL,
            )
            if "Deleted!" in result.stdout:
                return "✔ Deleted"
            if result.stderr.strip():
                return f"✗ {result.stderr.strip()[-40:]}"
            return "✗ Delete failed"
        except subprocess.TimeoutExpired:
            return "✗ Timed out"
        except Exception as e:
            return f"✗ {e}"
    return None  # cancelled


@functools.lru_cache(maxsize=1)
def _get_primary_cal():
    """Return the primary calendar email from gcalcli list (cached)."""
    try:
        r = subprocess.run(
            [GCALCLI, "list", "--nocolor"],
            capture_output=True, text=True, timeout=10,
        )
        for line in r.stdout.strip().split("\n"):
            for tok in line.split():
                if "@" in tok:
                    return tok.strip()
    except Exception:
        pass
    return None


def _quick_add_bg(cache, ym, text, result_list, calendar):
    """Run gcalcli quick in a thread, store (success, msg) in result_list."""
    try:
        cmd = [GCALCLI, "quick", "--default-reminders"]
        if calendar:
            cmd += ["--calendar", calendar]
        cmd.append(text)
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            if ym in cache:
                del cache[ym]
            result_list.append(("✓ Event created", C_EVENT))
        else:
            result_list.append((r.stderr.strip() or "✗ Failed", C_TODAY))
    except subprocess.TimeoutExpired:
        result_list.append(("✗ Timed out", C_TODAY))
    except (FileNotFoundError, OSError) as e:
        result_list.append((f"✗ {e}", C_TODAY))


def main(stdscr):
    """Curses application entry point — template wrapper draws tb on stdscr."""
    try:
        _main(stdscr)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        with open(ERROR_LOG, "w") as _f:
            _f.write(tb)
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
            nb_lines = len(tb.split("\n"))
            stdscr.addstr(min(nb_lines, h - 1), 0,
                          "See /tmp/gcal_tui_error.log — press any key to exit")
        except Exception:
            pass
        stdscr.getch()


def _main(stdscr):
    """Curses application entry point."""
    curses.curs_set(0)
    curses.set_escdelay(25)
    init_colors()

    today = date.today()
    year, month = today.year, today.month
    selected_day = today.day

    # Shared cache: (year, month) -> events dict
    disk_cache = load_cache()
    events_cache = {
        _ym_from_key(k): {int(dk): dv for dk, dv in v.items()}
        for k, v in disk_cache.items()
    }

    # ── Fire all fetches in background — show calendar immediately ──
    loading_ym = (year, month)
    start_bg_fetch(events_cache, year, month)
    for dy in [-1, 1]:
        ny, nm = year, month + dy
        if nm > 12:
            nm, ny = 1, year + 1
        elif nm < 1:
            nm, ny = 12, year - 1
        start_bg_fetch(events_cache, ny, nm)

    # ── State ──
    spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    sp_idx = 0
    status_msg = None
    status_color = C_HELP
    create_result = []  # list: thread stores (msg, color) here when done
    creating_now = False  # True while gcalcli quick is running in bg
    primary_cal = None  # fetched lazily on first 'n' press

    stdscr.timeout(200)

    while True:
        sp_idx = (sp_idx + 1) % len(spinner_chars)
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        if height < 18 or width < 70:
            msg = f"Terminal too small — need 70×18, got {width}×{height}"
            stdscr.addstr(0, 0, msg)
            stdscr.addstr(2, 0, "Resize terminal or press q to quit")
            stdscr.refresh()
            # Block until resize or quit (override main loop timeout)
            stdscr.timeout(-1)
            while True:
                key = stdscr.getch()
                if key == ord('q'):
                    return
                h2, w2 = stdscr.getmaxyx()
                if h2 >= 18 and w2 >= 70:
                    height, width = h2, w2
                    break
            stdscr.timeout(200)
            stdscr.erase()
            continue

        # Check if background fetch completed
        if loading_ym and loading_ym in events_cache:
            loading_ym = None

        # Check if quick-add completed
        if create_result:
            status_msg, status_color = create_result.pop(0)
            creating_now = False
            start_bg_fetch(events_cache, year, month)
            disk = {_ym_key(*ym): ev for ym, ev in events_cache.items()}
            save_cache(disk)
            loading_ym = (year, month)

        is_loading = (loading_ym is not None)

        events = events_cache.get((year, month), {})

        # Clamp selected day
        max_day = calendar.monthrange(year, month)[1]
        if selected_day > max_day:
            selected_day = max_day

        # ── Draw ──
        grid_end = draw_calendar(stdscr, year, month, events, selected_day,
                                 loading=is_loading,
                                 spinner_char=spinner_chars[sp_idx])

        detail_start = max(grid_end, 4)
        draw_detail(stdscr, year, month, events, selected_day, detail_start)

        # Status / help line
        if status_msg:
            stdscr.attron(curses.color_pair(status_color) | curses.A_BOLD)
            try:
                stdscr.addstr(height - 1, 2, status_msg)
            except curses.error:
                pass
            stdscr.attroff(curses.color_pair(status_color) | curses.A_BOLD)
        elif creating_now:
            stdscr.attron(curses.color_pair(C_HELP))
            try:
                stdscr.addstr(height - 1, 2, " ⟳ Creating event...")
            except curses.error:
                pass
            stdscr.attroff(curses.color_pair(C_HELP))
        elif is_loading:
            stdscr.attron(curses.color_pair(C_HELP))
            try:
                stdscr.addstr(height - 1, 2, " ⟳ Syncing...")
            except curses.error:
                pass
            stdscr.attroff(curses.color_pair(C_HELP))
        else:
            stdscr.attron(curses.color_pair(C_HELP))
            try:
                stdscr.addstr(height - 1, 2,
                    " ← → month  |  ↑ ↓ day  |  n new  |  d delete  |  g today  |  r refresh  |  q quit")
            except curses.error:
                pass
            stdscr.attroff(curses.color_pair(C_HELP))

        stdscr.refresh()

        # ── Input ──
        key = stdscr.getch()

        if key == -1:  # timeout — redraw spinner
            continue

        # Clear status message on any keypress
        status_msg = None

        if key == ord('q'):
            break

        elif key == ord('g'):
            year, month = today.year, today.month
            selected_day = today.day
            if start_bg_fetch(events_cache, year, month):
                loading_ym = (year, month)

        elif key == ord('r'):
            if (year, month) in events_cache:
                del events_cache[(year, month)]
            disk = {_ym_key(*ym): ev for ym, ev in events_cache.items()}
            save_cache(disk)
            start_bg_fetch(events_cache, year, month)
            loading_ym = (year, month)

        elif key == ord('n') and not creating_now:
            # quick add new event — lazy fetch primary calendar
            if primary_cal is None:
                primary_cal = _get_primary_cal()
            raw = quick_add_prompt(stdscr, year, month, selected_day)
            if raw:
                creating_now = True
                t = threading.Thread(
                    target=_quick_add_bg,
                    args=(events_cache, (year, month), raw, create_result,
                          primary_cal),
                    daemon=True,
                )
                t.start()
        elif key == ord('d'):
            # delete selected event if any
            del_msg = delete_event_prompt(stdscr, events, selected_day,
                                          year, month, primary_cal)
            if del_msg and del_msg.startswith("✔"):
                status_msg = del_msg
                status_color = C_EVENT
                if (year, month) in events_cache:
                    del events_cache[(year, month)]
                disk = {_ym_key(*ym): ev for ym, ev in events_cache.items()}
                save_cache(disk)
                start_bg_fetch(events_cache, year, month)
                loading_ym = (year, month)
            elif del_msg:
                status_msg = del_msg
                status_color = C_TODAY

        elif key == curses.KEY_LEFT:
            month -= 1
            if month == 0:
                month, year = 12, year - 1
            selected_day = min(selected_day,
                               calendar.monthrange(year, month)[1])
            if start_bg_fetch(events_cache, year, month):
                loading_ym = (year, month)

        elif key == curses.KEY_RIGHT:
            month += 1
            if month == 13:
                month, year = 1, year + 1
            selected_day = min(selected_day,
                               calendar.monthrange(year, month)[1])
            if start_bg_fetch(events_cache, year, month):
                loading_ym = (year, month)

        elif key == curses.KEY_UP:
            d = date(year, month, selected_day) + timedelta(days=1)
            year, month, selected_day = d.year, d.month, d.day
            if start_bg_fetch(events_cache, year, month):
                loading_ym = (year, month)

        elif key == curses.KEY_DOWN:
            d = date(year, month, selected_day) - timedelta(days=1)
            year, month, selected_day = d.year, d.month, d.day
            if start_bg_fetch(events_cache, year, month):
                loading_ym = (year, month)


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        with open(ERROR_LOG, "w") as _f:
            _f.write(tb)
        print(f"gcal_tui.py crashed — see {ERROR_LOG}", file=sys.stderr)
        sys.exit(1)
