#!/usr/bin/env bash
# Audacious status for waybar — scrolling marquee (every tick) + playlist
# tooltip (cached 10s, refreshed in background).
# NOTE: Waybar requires \r for tooltip newlines (gh#3153) and Pango
# markup escaping for &, <, > (gh#4617).

MAX=20
SPEED=3
CACHE_DIR="$HOME/.cache/waybar-audacious"
TOOLTIP_CACHE="$CACHE_DIR/tooltip.txt"
LOCK_DIR="$CACHE_DIR/lock"
TTL="${AUD_TOOLTIP_TTL:-10}"

mkdir -p "$CACHE_DIR"

# Single JSON emitter (text + tooltip, escaped).
emit() {
  local text_esc tip_esc
  text_esc=$(printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
  tip_esc=$(printf '%s' "$2" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g' | tr '\n' '\r')
  jq -nc --arg text "$text_esc" --arg tip "$tip_esc" '{text: $text, tooltip: $tip}'
}

# Builds the ±3 playlist tooltip (slow: ~7 audtool calls). Prints to stdout.
build_tooltip() {
  local playlist="$1" current_pos="$2" total_tracks="$3" fallback="$4"
  local start end i song tooltip
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
    printf '%s' "$tooltip"
  else
    printf '%s' "$fallback"
  fi
}

refresh_tooltip_bg() {
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCK_DIR" 2>/dev/null || date +%s) ))
    [ "$lock_age" -gt 300 ] && rmdir "$LOCK_DIR" 2>/dev/null
    mkdir "$LOCK_DIR" 2>/dev/null || return 0
  fi
  (
    playlist=$(audtool --playlist-display 2>/dev/null)
    current_pos=$(audtool --playlist-position 2>/dev/null)
    total_tracks=$(audtool --playlist-length 2>/dev/null)
    build_tooltip "$playlist" "$current_pos" "$total_tracks" "" > "$TOOLTIP_CACHE.tmp" \
      && mv "$TOOLTIP_CACHE.tmp" "$TOOLTIP_CACHE"
    rmdir "$LOCK_DIR"
    pkill -RTMIN+2 -x waybar 2>/dev/null || true
  ) &
}

is_fresh() {
  [ -f "$TOOLTIP_CACHE" ] || return 1
  [ $(( $(date +%s) - $(stat -c %Y "$TOOLTIP_CACHE") )) -lt "$TTL" ]
}

status=$(audtool --playback-status 2>/dev/null)

case "$status" in
  playing) symbol="" ;;
  paused)  symbol="" ;;
  *) exit 0 ;; # exec-if hides us unless playing/paused; nothing to show
esac

# --- fast path: marquee text (~4 audtool calls) ---
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

if [[ -n "$total" && "$total" -gt 0 ]]; then
  pct=$(( pos * 100 / total ))
  text="$symbol  $visible  $pct%"
else
  text="$symbol  $visible"
fi

# --- slow path: tooltip from cache, refresh behind when stale ---
if is_fresh; then
  tooltip=$(cat "$TOOLTIP_CACHE")
else
  if [ -f "$TOOLTIP_CACHE" ]; then
    tooltip=$(cat "$TOOLTIP_CACHE")
  else
    tooltip="$text"
  fi
  refresh_tooltip_bg
fi

emit "$text" "$tooltip"
