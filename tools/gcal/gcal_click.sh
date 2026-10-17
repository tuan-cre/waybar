#!/usr/bin/env bash
# gcalcli click handler — opens calendar TUI or browser
# Left click: interactive calendar TUI (Google Calendar-like)
# Right click: quick agenda view
# Middle click: Google Calendar in browser

GCALCLI="$HOME/.local/bin/gcalcli"
TUI="$HOME/.config/waybar/tools/gcal/gcal_tui.py"

refresh_waybar() {
  pkill -RTMIN+1 -x waybar 2>/dev/null || true
}

case "$1" in
  agenda|left)
    footclient -E --title="gcalcli" --window-size-chars=85x30 -- python3 "$TUI"
    refresh_waybar
    ;;
  calendar|right)
    footclient -E --title="gcalcli" --window-size-chars=85x30 sh -c '"$1" --lineart fancy calm; echo; printf "Press Enter to close..."; read -r _' sh "$GCALCLI"
    ;;
  browser|middle)
    helium-browser --app=https://calendar.google.com
    ;;
  *)
    footclient -E --title="gcalcli" --window-size-chars=85x30 -- python3 "$TUI"
    refresh_waybar
    ;;
esac
