#!/usr/bin/env bash

MAX=20
SPEED=3

status=$(audtool --playback-status 2>/dev/null)

case "$status" in
  playing)
    symbol=""
    ;;
  paused)
    symbol=""
    ;;
  *)
    echo ""
    exit 0
    ;;
esac

text="$(audtool --current-song 2>/dev/null)    "
len=${#text}

now_ms=$(( $(date +%s%N) / 1000000 ))
offset=$(( (now_ms * SPEED / 500) % len ))
visible="${text:$offset:$MAX}"

if [ ${#visible} -lt $MAX ]; then
  visible="$visible${text:0:$((MAX - ${#visible}))}"
fi

pos=$(audtool --current-song-output-length-seconds 2>/dev/null)
total=$(audtool --current-song-length-seconds 2>/dev/null)
playlist=$(audtool --playlist-display 2>/dev/null)
current_pos=$(audtool --playlist-position 2>/dev/null)
total_tracks=$(audtool --playlist-length 2>/dev/null)

if [[ -n "$total" && "$total" -gt 0 ]]; then
  pct=$(( pos * 100 / total ))
  text="$symbol  $visible  $pct%"
else
  text="$symbol  $visible"
fi

if [[ -n "$playlist" && -n "$total_tracks" && -n "$current_pos" ]]; then
  start=$(( current_pos - 3 ))
  [[ $start -lt 1 ]] && start=1
  end=$(( current_pos + 3 ))
  [[ $end -gt $total_tracks ]] && end=$total_tracks

  tooltip="${total_tracks} tracks."
  [[ $start -gt 1 ]] && tooltip="$tooltip
..."
  for ((i=start; i<=end; i++)); do
    song=$(audtool --playlist-song "$i" 2>/dev/null | sed -r 's/^(.{20}).*$/\1.../' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; s/[[:space:]]\+/ /g')
    if [[ $i -eq $current_pos ]]; then
      tooltip="$tooltip
▶ $i | $song"
    else
      tooltip="$tooltip
  $i | $song"
    fi
  done
  [[ $end -lt $total_tracks ]] && tooltip="$tooltip
..."
else
  tooltip="$text"
fi

# Use Python for robust JSON encoding
# NOTE: Waybar requires \r for newlines in tooltip, not \n (gh#3153)
# NOTE: Waybar uses Pango markup - escape &, <, > to prevent blank tooltip (gh#4617)
WAYBAR_TEXT="$text" WAYBAR_TOOLTIP="$tooltip" python3 -uc '
import os, json
t = os.environ["WAYBAR_TEXT"].encode("utf-8", errors="replace").decode("utf-8")
p = os.environ["WAYBAR_TOOLTIP"].encode("utf-8", errors="replace").decode("utf-8")
p = p.replace("\n", "\r")
# Escape Pango markup special chars
import html
t = html.escape(t)
p = html.escape(p)
print(json.dumps({"text": t, "tooltip": p}, ensure_ascii=False))
'