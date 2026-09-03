#!/usr/bin/env python3
"""battery_tui.py — Battery status TUI for Waybar click."""
import curses
import subprocess
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BAT = "/sys/class/power_supply/BAT1"
ERROR_LOG = Path("/tmp/battery_tui_error.log")

# ── Theme (Void — same as _template) ─────────────────────────────────
C_DEFAULT = 1
C_HEADER = 2   # magenta #b48ead
C_BAR = 3      # green #a3be8c
C_LABEL = 4    # white
C_VALUE = 5    # cyan #81a1c1
C_HELP = 6     # gray #5c5c6e


def init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_DEFAULT, -1, -1)
    curses.init_pair(C_HEADER, 5, -1)   # magenta
    curses.init_pair(C_BAR, 2, -1)      # green
    curses.init_pair(C_LABEL, 7, -1)    # white
    curses.init_pair(C_VALUE, 6, -1)    # cyan
    curses.init_pair(C_HELP, 8, -1)     # gray


def read_sysfs(name):
    try:
        return Path(f"{BAT}/{name}").read_text().strip()
    except Exception:
        return "N/A"


def read_acpi():
    try:
        r = subprocess.run(
            ["acpi", "-V"], capture_output=True, text=True, timeout=5
        )
        return r.stdout
    except Exception:
        return ""


def get_battery_data():
    capacity = read_sysfs("capacity")
    status = read_sysfs("status")
    e_now = int(read_sysfs("energy_now") or 0)
    e_full = int(read_sysfs("energy_full") or 0)
    e_design = int(read_sysfs("energy_full_design") or 0)
    cycle_count = read_sysfs("cycle_count")
    model = read_sysfs("model_name")
    manufacturer = read_sysfs("manufacturer")
    technology = read_sysfs("technology")
    voltage = int(read_sysfs("voltage_now") or 0)

    health_pct = (e_full / e_design * 100) if e_design > 0 else 0
    acpi_out = read_acpi()

    temp = "N/A"
    for line in acpi_out.split("\n"):
        if "Thermal" in line and "degrees" in line:
            temp = line.split("degrees C")[0].split(",")[-1].strip() + "°C"
            break

    return {
        "capacity": capacity,
        "status": status,
        "energy_now": e_now,
        "energy_full": e_full,
        "energy_full_design": e_design,
        "health_pct": health_pct,
        "cycle_count": cycle_count,
        "model": model,
        "manufacturer": manufacturer,
        "technology": technology,
        "voltage": voltage,
        "temp": temp,
    }


def draw_progress_bar(scr, y, x, width, pct, pair):
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    scr.attron(curses.color_pair(pair))
    scr.addstr(y, x, bar[:width])
    scr.attroff(curses.color_pair(pair))


def draw_header(stdscr: "curses.window", title: str) -> None:
    h, w = stdscr.getmaxyx()
    x_off = (w - len(title)) // 2
    stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
    try:
        stdscr.insstr(0, 0, "┌" + "─" * (w - 2) + "┐")
    except curses.error:
        try:
            stdscr.insstr(0, 0, "+" + "-" * (w - 2) + "+")
        except curses.error:
            pass
    stdscr.addstr(0, max(x_off, 0), title)
    stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)


def draw_footer(stdscr: "curses.window") -> None:
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
    try:
        stdscr.insstr(h - 1, 0, "└" + "─" * (w - 2) + "┘")
    except curses.error:
        try:
            stdscr.insstr(h - 1, 0, "+" + "-" * (w - 2) + "+")
        except curses.error:
            pass
    stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)


def _main(scr):
    curses.curs_set(0)
    curses.set_escdelay(25)
    init_colors()
    scr.timeout(200)

    stdscr = scr
    data = get_battery_data()

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

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
                data = get_battery_data()
            continue

        # ── Header border ──
        draw_header(stdscr, " ⚡ Battery ")

        bar_w = min(40, w - 8)
        try:
            pct = int(data["capacity"])
        except (ValueError, TypeError):
            pct = 0

        # ── Big percentage ──
        pct_str = f"{pct}%"
        stdscr.attron(curses.color_pair(C_LABEL) | curses.A_BOLD)
        try:
            stdscr.addstr(3, (w - len(pct_str)) // 2, pct_str)
        except curses.error:
            pass
        stdscr.attroff(curses.color_pair(C_LABEL) | curses.A_BOLD)

        # ── Progress bar ──
        bar_x = (w - bar_w) // 2
        try:
            draw_progress_bar(stdscr, 5, bar_x, bar_w, pct, C_BAR)
        except curses.error:
            pass

        # ── Detail rows ──
        y = 7

        rows = [
            ("Status:", status_map(data["status"])),
            ("Health:", f"{data['health_pct']:.0f}% ({data['energy_full'] / 1000000:.0f}/{data['energy_full_design'] / 1000000:.0f} Wh)"),
            ("Cycles:", str(data["cycle_count"])),
            ("Temp:", data["temp"]),
            ("Model:", f"{data['manufacturer']} {data['model']}"),
            ("Voltage:", f"{data['voltage'] / 1000000:.3f}V"),
        ]

        for label, value in rows:
            if y >= h - 3:
                break
            stdscr.attron(curses.color_pair(C_LABEL))
            try:
                stdscr.addstr(y, 4, f"{label:8s} ")
            except curses.error:
                pass
            stdscr.attroff(curses.color_pair(C_LABEL))
            stdscr.attron(curses.color_pair(C_VALUE))
            try:
                stdscr.addstr(y, 14, value[: w - 16])
            except curses.error:
                pass
            stdscr.attroff(curses.color_pair(C_VALUE))
            y += 1

        # ── Separator ──
        y += 1
        if y < h - 2:
            stdscr.attron(curses.color_pair(C_HEADER))
            try:
                stdscr.insstr(y, 0, "─" * (w - 1))
            except curses.error:
                try:
                    stdscr.insstr(y, 0, "-" * (w - 1))
                except curses.error:
                    pass
            stdscr.attroff(curses.color_pair(C_HEADER))
            y += 1

        # ── Footer help ──
        help_text = "r refresh  |  q quit  |  any key to close"
        if h > y + 2:
            stdscr.attron(curses.color_pair(C_HELP))
            try:
                stdscr.addstr(y, 4, help_text)
            except curses.error:
                pass
            stdscr.attroff(curses.color_pair(C_HELP))

        # ── Bottom border ──
        draw_footer(stdscr)

        stdscr.refresh()

        # ── Input ──
        key = stdscr.getch()
        if key == -1:
            continue
        if key in (ord("q"), 27):
            break
        elif key == ord("r"):
            data = get_battery_data()
            continue
        else:
            # ignore any other key (spurious input on terminal open, etc.)
            continue


def status_map(s):
    return {
        "Charging": "Charging",
        "Discharging": "Discharging",
        "Not charging": "On AC (not charging)",
        "Full": "Fully charged",
    }.get(s, s)


def main(scr):
    try:
        _main(scr)
    except Exception:
        tb = traceback.format_exc()
        with open(ERROR_LOG, "w") as f:
            f.write(tb)
        try:
            scr.clear()
            scr.refresh()
            h, w = scr.getmaxyx()
            for i, line in enumerate(tb.split("\n")):
                if i >= h - 1:
                    break
                line = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in line)
                try:
                    scr.addstr(i, 0, line[: w - 1])
                except curses.error:
                    pass
            scr.addstr(min(len(tb.split("\n")), h - 1), 0, f"See {ERROR_LOG} — press any key")
            scr.getch()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    except Exception:
        tb = traceback.format_exc()
        with open(ERROR_LOG, "w") as f:
            f.write(tb)
        sys.stdout.write("\n" + "=" * 50 + "\n")
        sys.stdout.write("BATTERY TUI CRASHED\n")
        sys.stdout.write("=" * 50 + "\n")
        sys.stdout.write(tb)
        sys.stdout.write(f"\nSee {ERROR_LOG}\n")
        sys.stdout.write("Press Enter to close...")
        sys.stdout.flush()
        try:
            input()
        except Exception:
            pass
