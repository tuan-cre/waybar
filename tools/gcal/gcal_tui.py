#!/usr/bin/env python3
"""
gcal_tui.py — Google Calendar month TUI for gcalcli
Interactive curses calendar with async event fetching.
Arrow keys to navigate, q to quit.
"""

import calendar
import curses
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

GCALCLI = os.path.expanduser("~/.local/bin/gcalcli")
API_HELPER = Path(__file__).with_name("gcal_api.py")
GCALCLI_PYTHON = Path.home() / ".local/share/pipx/venvs/gcalcli/bin/python"

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

CACHE_FILE = Path.home() / ".cache" / "gcalcli" / "events_cache.json"
ERROR_LOG = Path("/tmp/gcal_tui_error.log")
CACHE_LOCK = threading.RLock()
CACHE_TTL = 300
_fetching = set()
_refetch = set()
_fetch_errors = set()
_fetched_at = {}


def _ym_key(year, month):
    return f"{year:04d}-{month:02d}"


def _ym_from_key(key):
    y, m = key.split("-")
    return int(y), int(m)


def normalize_event(event):
    if not isinstance(event, (list, tuple)):
        return None
    if len(event) == 3:
        event_id, calendar_name, start_time, title, all_day = None, None, *event
    elif len(event) == 4:
        event_id, start_time, title, all_day = event
        calendar_name = None
    elif len(event) == 5:
        event_id, calendar_name, start_time, title, all_day = event
    else:
        return None
    if (event_id is not None and not isinstance(event_id, str)
            or calendar_name is not None and not isinstance(calendar_name, str)
            or not isinstance(start_time, str) or not isinstance(title, str)
            or type(all_day) is not bool):
        return None
    return (event_id or None, calendar_name or None,
            start_time, title, all_day)


def load_cache():
    """Read events_cache.json from disk, return {ym_key: events_dict} or {}."""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(cache, dict):
        return {}
    valid = {}
    for key, days in cache.items():
        try:
            year, month = _ym_from_key(key)
        except (AttributeError, ValueError, TypeError):
            continue
        if not 1 <= month <= 12 or not 1 <= year <= 9999:
            continue
        if not isinstance(days, dict):
            continue
        valid[key] = {}
        for day, events in days.items():
            try:
                day_num = int(day)
            except (TypeError, ValueError):
                continue
            if 1 <= day_num <= calendar.monthrange(year, month)[1] and isinstance(events, list):
                valid[key][str(day_num)] = [
                    normalized for event in events
                    if (normalized := normalize_event(event)) is not None
                ]
    return valid


def save_cache(cache):
    """Atomically write cache dict to disk."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with CACHE_LOCK, tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=CACHE_FILE.parent, delete=False
        ) as f:
            tmp = Path(f.name)
            json.dump(cache, f, separators=(",", ":"))
        tmp.replace(CACHE_FILE)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def save_cache_snapshot(events_cache):
    with CACHE_LOCK:
        save_cache({_ym_key(*ym): events for ym, events in events_cache.items()})


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

    Returns dict: {day: [(id, calendar, time, title, all_day), ...]} or None.
    """
    last_day = calendar.monthrange(year, month)[1]
    start_str = f"{year:04d}-{month:02d}-01"
    end_str = (date(year, month, last_day) + timedelta(days=1)).isoformat()

    try:
        result = subprocess.run(
            [GCALCLI, "--nocolor", "agenda", "--tsv", "--military",
             "--details=id", "--details=calendar",
             start_str, end_str],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    events = defaultdict(list)
    lines = result.stdout.splitlines()
    if not lines:
        return None
    columns = {name: i for i, name in enumerate(lines[0].split("\t"))}
    if not {"id", "calendar", "start_date", "start_time", "end_date",
            "end_time", "title"} <= columns.keys():
        return None

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) <= max(columns.values()):
            continue

        start_date = parts[columns["start_date"]]
        start_time = parts[columns["start_time"]]
        try:
            event_start = date.fromisoformat(start_date)
            event_end = date.fromisoformat(parts[columns["end_date"]])
        except ValueError:
            continue

        title = parts[columns["title"]]
        if not title.strip():
            continue

        is_all_day = not start_time.strip()
        end_time = parts[columns["end_time"]].strip()
        end_exclusive = event_end + timedelta(days=1) if end_time and end_time != "00:00" else event_end
        day = max(event_start, date(year, month, 1))
        month_end = date(year, month, last_day) + timedelta(days=1)
        end_exclusive = min(end_exclusive, month_end)
        event = (parts[columns["id"]], parts[columns["calendar"]],
                 start_time.strip(), title.strip(), is_all_day)
        while day < end_exclusive:
            events[day.day].append(event)
            day += timedelta(days=1)

    return dict(events)


def bg_fetch(events_cache, year, month):
    """Fetch events in background thread and store in shared cache."""
    ym = (year, month)
    try:
        fetched = fetch_events(year, month)
        with CACHE_LOCK:
            if fetched is None:
                _fetch_errors.add(ym)
            else:
                events_cache[ym] = fetched
                _fetched_at[ym] = time.monotonic()
                _fetch_errors.discard(ym)
                save_cache({_ym_key(*key): value
                            for key, value in events_cache.items()})
    except Exception:
        with CACHE_LOCK:
            _fetch_errors.add(ym)
    finally:
        with CACHE_LOCK:
            _fetching.discard(ym)
            if ym in _refetch:
                _refetch.discard(ym)
                _launch_bg_fetch_locked(events_cache, ym)


def _launch_bg_fetch_locked(events_cache, ym):
    _fetch_errors.discard(ym)
    _fetching.add(ym)
    threading.Thread(target=bg_fetch, args=(events_cache, *ym), daemon=True).start()


def start_bg_fetch(events_cache, year, month, force=False):
    """Fetch stale or missing month data without blocking the UI.

    Returns True if a fetch is active or started, False if the cache is fresh.
    """
    ym = (year, month)
    with CACHE_LOCK:
        if ym in _fetching:
            if force:
                _refetch.add(ym)
            return True
        if (not force and ym in events_cache
                and time.monotonic() - _fetched_at.get(ym, 0) < CACHE_TTL):
            return False
        _fetching.add(ym)
        _fetch_errors.discard(ym)
        threading.Thread(
            target=bg_fetch, args=(events_cache, year, month), daemon=True
        ).start()
    return True


def event_parts(event):
    """Return normalized (id, calendar, time, title, all_day) data."""
    return normalize_event(event) or (None, None, "", "", False)


def draw_calendar(stdscr, year, month, events, selected_day, loading=False,
                  spinner_char=" "):
    """Draw the month calendar grid. Returns y after the grid."""
    height, width = stdscr.getmaxyx()

    cal = calendar.Calendar()
    month_days = cal.monthdays2calendar(year, month)

    cell_w = max((width - 8) // 7, 6)
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
                    _, _, ev_time, ev_title, is_all_day = event_parts(day_events[ev_idx])
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

    for event in day_events:
        _, _, ev_time, ev_title, is_all_day = event_parts(event)
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
        key = stdscr.get_wch()
        if key in ("\n", "\r", curses.KEY_ENTER):
            return "".join(value)
        if key == 27:  # Esc
            return None
        if key in ("\x7f", "\b", 127, curses.KEY_BACKSPACE, 8):
            if value:
                value.pop()
        elif isinstance(key, str) and key.isprintable() and len(value) < max_w:
            value.append(key)
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
    Returns (display title, quick-add text) or None on cancel.
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
    return text, f"{text} on {month_abbr} {day}, {year}"

def delete_event_prompt(stdscr, events, day, year, month):
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
    selectable = min(len(day_events), 9, max_w, max(0, y - 1))
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
    for idx, event in enumerate(day_events[:selectable]):
        title = event_parts(event)[3]
        try:
            stdscr.addstr(list_y - idx, x, f"{idx+1}:{title[:max_w-3]}")
        except curses.error:
            pass
    stdscr.refresh()
    # read a single digit input
    key = stdscr.getch()
    curses.curs_set(0)
    stdscr.timeout(200)
    if selectable and ord('1') <= key <= ord(str(selectable)):
        idx = key - ord('1')
        event_id, calendar_name, _, _, _ = event_parts(day_events[idx])
        if not event_id or not calendar_name:
            return "Refresh calendar before deleting"
        return calendar_name, event_id
    return None  # cancelled


def _created_event_items(payload):
    resource = payload["event"]
    calendar_name = payload["calendar"]
    start = resource["start"]
    end = resource["end"]
    all_day = "date" in start

    if all_day:
        start_date = date.fromisoformat(start["date"])
        end_exclusive = date.fromisoformat(end["date"])
        start_time = ""
    else:
        start_dt = datetime.fromisoformat(
            start["dateTime"].replace("Z", "+00:00")
        ).astimezone()
        end_dt = datetime.fromisoformat(
            end["dateTime"].replace("Z", "+00:00")
        ).astimezone()
        start_date = start_dt.date()
        end_exclusive = end_dt.date()
        if end_dt.strftime("%H:%M") != "00:00":
            end_exclusive += timedelta(days=1)
        start_time = start_dt.strftime("%H:%M")

    if end_exclusive <= start_date:
        end_exclusive = start_date + timedelta(days=1)
    event = (resource["id"], calendar_name, start_time,
             resource.get("summary", ""), all_day)
    items = []
    day = start_date
    while day < end_exclusive:
        items.append(((day.year, day.month), day.day, event))
        day += timedelta(days=1)
    return items


def _quick_add_bg(ym, text, result_list):
    """Create an event asynchronously and return its API record."""
    try:
        r = subprocess.run(
            [str(GCALCLI_PYTHON), str(API_HELPER), "quick", text],
            capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            result_list.append((True, "✓ Event created", C_EVENT, ym,
                                json.loads(r.stdout)))
        else:
            result_list.append((False, r.stderr.strip() or "✗ Failed",
                                C_TODAY, ym, None))
    except subprocess.TimeoutExpired:
        result_list.append((False, "✗ Timed out", C_TODAY, ym, None))
    except (FileNotFoundError, OSError) as e:
        result_list.append((False, f"✗ {e}", C_TODAY, ym, None))
    except (json.JSONDecodeError, TypeError) as e:
        result_list.append((False, f"✗ Invalid event response: {e}", C_TODAY,
                            ym, None))


def _delete_event_bg(result_list, ym, calendar_name, event_id):
    try:
        if not GCALCLI_PYTHON.is_file():
            raise FileNotFoundError("gcalcli pipx Python not found")
        result = subprocess.run(
            [str(GCALCLI_PYTHON), str(API_HELPER), "delete", calendar_name,
             event_id],
            capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            result_list.append((True, "✔ Deleted", C_EVENT, ym, event_id))
        else:
            message = result.stderr.strip()[-40:] or "✗ Delete failed"
            result_list.append((False, f"✗ {message}", C_TODAY, ym, event_id))
    except subprocess.TimeoutExpired:
        result_list.append((False, "✗ Timed out", C_TODAY, ym, event_id))
    except (FileNotFoundError, OSError) as exc:
        result_list.append((False, f"✗ {exc}", C_TODAY, ym, event_id))


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
        _ym_from_key(k): {int(dk): [tuple(e) for e in evs]
                          for dk, evs in v.items()}
        for k, v in disk_cache.items()
    }

    # ── Refresh the current month in the background; retain cached view ──
    loading_ym = (year, month)
    start_bg_fetch(events_cache, year, month, force=True)

    # ── State ──
    spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    sp_idx = 0
    status_msg = None
    status_color = C_HELP
    status_until = 0
    create_result = []  # list: thread stores (msg, color) here when done
    creating_now = False  # True while the Calendar API request is running
    pending_event = None
    delete_result = []
    deleting_now = False
    pending_delete = None

    def set_status(message, color):
        nonlocal status_msg, status_color, status_until
        status_msg, status_color = message, color
        status_until = time.monotonic() + 2

    stdscr.timeout(200)

    while True:
        sp_idx = (sp_idx + 1) % len(spinner_chars)
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        if height < 27 or width < 70:
            msg = f"Terminal too small — need 70×27, got {width}×{height}"
            try:
                if height > 0 and width > 1:
                    stdscr.addnstr(0, 0, msg, width - 1)
                if height > 2 and width > 1:
                    stdscr.addnstr(2, 0, "Resize terminal or press q to quit",
                                   width - 1)
            except curses.error:
                pass
            stdscr.refresh()
            # Block until resize or quit (override main loop timeout)
            stdscr.timeout(-1)
            while True:
                key = stdscr.getch()
                if key == ord('q'):
                    return
                h2, w2 = stdscr.getmaxyx()
                if h2 >= 27 and w2 >= 70:
                    height, width = h2, w2
                    break
            stdscr.timeout(200)
            stdscr.erase()
            continue

        # Check if background fetch completed
        with CACHE_LOCK:
            loading = loading_ym in _fetching if loading_ym else False
            failed = loading_ym in _fetch_errors if loading_ym else False
            events = events_cache.get((year, month), {})
        if pending_event and pending_event[0] == (year, month):
            events = dict(events)
            events[pending_event[1]] = [
                *events.get(pending_event[1], []),
                (None, None, "", f"Creating: {pending_event[2]}", False),
            ]
        if pending_delete and pending_delete[0] == (year, month):
            _, event_id = pending_delete
            events = {
                day: [event for event in day_events
                      if event_parts(event)[0] != event_id]
                for day, day_events in events.items()
            }
        if loading_ym and not loading:
            if failed:
                set_status("Calendar sync failed — press r to retry", C_TODAY)
                with CACHE_LOCK:
                    _fetch_errors.discard(loading_ym)
            loading_ym = None

        # Check if quick-add completed
        if create_result:
            succeeded, message, color, changed_ym, payload = create_result.pop(0)
            creating_now = False
            set_status(message, color)
            pending_event = None
            if succeeded:
                try:
                    with CACHE_LOCK:
                        for event_ym, day, event in _created_event_items(payload):
                            day_events = events_cache.setdefault(
                                event_ym, {}).setdefault(day, [])
                            if not any(event_parts(existing)[0] == event[0]
                                       for existing in day_events):
                                day_events.append(event)
                        save_cache_snapshot(events_cache)
                except (KeyError, OSError, TypeError, ValueError):
                    set_status("Created; event could not be cached", C_TODAY)
                if changed_ym == (year, month):
                    with CACHE_LOCK:
                        events = events_cache.get((year, month), {})
            else:
                if changed_ym == (year, month):
                    with CACHE_LOCK:
                        events = events_cache.get((year, month), {})

        if delete_result:
            succeeded, message, color, changed_ym, event_id = delete_result.pop(0)
            deleting_now = False
            pending_delete = None
            set_status(message, color)
            if succeeded:
                with CACHE_LOCK:
                    for day_events in events_cache.get(changed_ym, {}).values():
                        day_events[:] = [event for event in day_events
                                         if event_parts(event)[0] != event_id]
                save_cache_snapshot(events_cache)

        is_loading = (loading_ym is not None)
        if status_msg and time.monotonic() >= status_until:
            status_msg = None

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
        elif deleting_now:
            stdscr.attron(curses.color_pair(C_HELP))
            try:
                stdscr.addstr(height - 1, 2, " ⟳ Deleting event...")
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
        if is_loading or creating_now or deleting_now:
            stdscr.timeout(200)
        elif status_msg:
            stdscr.timeout(max(1, int((status_until - time.monotonic()) * 1000)))
        else:
            stdscr.timeout(-1)
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
            start_bg_fetch(events_cache, year, month, force=True)
            loading_ym = (year, month)

        elif key == ord('n') and not creating_now and not deleting_now:
            # Prompt immediately; calendar lookup and creation run in background.
            event_input = quick_add_prompt(stdscr, year, month, selected_day)
            if event_input:
                title, raw = event_input
                creating_now = True
                pending_event = ((year, month), selected_day, title)
                t = threading.Thread(
                    target=_quick_add_bg,
                    args=((year, month), raw, create_result),
                    daemon=True,
                )
                t.start()
        elif key == ord('d') and not deleting_now and not creating_now:
            # delete selected event if any
            del_msg = delete_event_prompt(stdscr, events, selected_day,
                                          year, month)
            if isinstance(del_msg, tuple):
                deleting_now = True
                pending_delete = ((year, month), del_msg[1])
                threading.Thread(
                    target=_delete_event_bg,
                    args=(delete_result, (year, month), *del_msg),
                    daemon=True,
                ).start()
            elif del_msg:
                set_status(del_msg, C_TODAY)

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
            d = date(year, month, selected_day) - timedelta(days=1)
            year, month, selected_day = d.year, d.month, d.day
            if start_bg_fetch(events_cache, year, month):
                loading_ym = (year, month)

        elif key == curses.KEY_DOWN:
            d = date(year, month, selected_day) + timedelta(days=1)
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
