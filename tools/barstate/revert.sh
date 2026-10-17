#!/usr/bin/env bash
# revert.sh — cleanly undo the barstate experiment.
# 1. stop daemon  2. remove CSS import  3. restore transparent bg  4. restart waybar
set -u

STYLE="$HOME/.config/waybar/style.css"
DIR="$HOME/.config/waybar/tools/barstate"

pkill -f "barstate/barstate.sh" 2>/dev/null || true

# drop the import line (if present)
if [ -f "$STYLE" ]; then
  grep -v 'bar-state.css' "$STYLE" > "$STYLE.tmp" && mv "$STYLE.tmp" "$STYLE"
  # restore static transparent background on #waybar (if missing)
  if ! grep -q "background: transparent;" "$STYLE"; then
    python3 - "$STYLE" <<'EOF'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace("#waybar {\n  font-weight:", "#waybar {\n  background: transparent;\n  font-weight:")
open(p, "w").write(s)
EOF
  fi
fi

rm -f "${XDG_RUNTIME_DIR:-/tmp}/barstate.state" "${XDG_RUNTIME_DIR:-/tmp}/barstate.lock"

pkill waybar 2>/dev/null || true
sleep 1
(waybar > /tmp/waybar.log 2>&1 &)
echo "reverted: daemon stopped, import removed, waybar restarted"
echo "Also delete this autostart line from ~/.config/hypr/hyprland.lua:"
echo '  hl.exec_cmd("$HOME/.config/waybar/tools/barstate/barstate.sh &")'
