#!/usr/bin/env bash
# barstate.sh — darken waybar when any window is open, transparent when empty.
# Polling (no socat dep). Writes tools/barstate/bar-state.css on change only,
# then asks waybar to reload CSS. Companion: revert.sh
set -u

DIR="$HOME/.config/waybar/tools/barstate"
STATE_CSS="$DIR/bar-state.css"
STATE_FILE="${XDG_RUNTIME_DIR:-/tmp}/barstate.state"
INTERVAL="${BARSTATE_INTERVAL:-1}"

BG_EMPTY="transparent"
BG_BUSY="rgba(5, 5, 8, 0.85)"

# single instance
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/barstate.lock"
flock -n 9 || exit 0

write_state() {
  if [ "$1" = "busy" ]; then
    printf '#waybar { background: %s; }\n' "$BG_BUSY" > "$STATE_CSS.tmp"
  else
    printf '#waybar { background: %s; }\n' "$BG_EMPTY" > "$STATE_CSS.tmp"
  fi
  mv "$STATE_CSS.tmp" "$STATE_CSS"
  printf '%s' "$1" > "$STATE_FILE"
  # NOTE: SIGUSR2 reload is unreliable here (kills waybar-vis / crashes on
  # tray re-init), so do a full bar restart on state change instead.
  pkill waybar 2>/dev/null || true
  sleep 0.5
  (waybar > /tmp/waybar-barstate.log 2>&1 &)
  disown 2>/dev/null || true
}

current="__init__"
[ -f "$STATE_FILE" ] && current="$(cat "$STATE_FILE")"

while true; do
  ws="$(hyprctl activeworkspace -j 2>/dev/null | jq .id 2>/dev/null)"
  count="$(hyprctl clients -j 2>/dev/null | jq --argjson ws "${ws:-0}" '[.[] | select(.mapped == true and ((.hidden // false) | not) and ((.workspace.name // "") | startswith("special") | not) and .workspace.id == $ws)] | length' 2>/dev/null)"
  [ -z "$count" ] && { sleep "$INTERVAL"; continue; }
  if [ "$count" -gt 0 ]; then want="busy"; else want="empty"; fi
  if [ "$want" != "$current" ]; then
    write_state "$want"
    current="$want"
  fi
  sleep "$INTERVAL"
done
