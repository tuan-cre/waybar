#!/usr/bin/env bash

TUI="$HOME/.config/waybar/tools/battery/battery_tui.py"

case "$1" in
  info|left)
    foot --title="battery" -- python3 "$TUI"
    ;;
  profile|right)
    powerprofilesctl launch
    ;;
  *)
    foot --title="battery" -- python3 "$TUI"
    ;;
esac
