#!/bin/bash
# Show memory usage matching fastfetch/btop (MemTotal - MemAvailable)
# Text: computed every run (cheap, ~3ms).
# Tooltip: top 10 processes by RSS, cached 10s (expensive ps+sort, ~17ms).
read -r total avail < <(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END{print t, a}' /proc/meminfo)
used=$((total - avail))
text=$(awk -v u="$used" -v t="$total" 'BEGIN{printf "%.1fG/%.1fG", u/1024/1024, t/1024/1024}')

CACHE_DIR="$HOME/.cache/waybar-memory"
CACHE_TIP="$CACHE_DIR/tooltip.txt"
TTL=10
mkdir -p "$CACHE_DIR"

tooltip=""
if [ -f "$CACHE_TIP" ]; then
  age=$(( $(date +%s) - $(stat -c %Y "$CACHE_TIP") ))
  [ "$age" -lt "$TTL" ] && tooltip=$(cat "$CACHE_TIP")
fi
if [ -z "$tooltip" ]; then
  tooltip=$(ps -eo comm,rss --no-headers 2>/dev/null | awk '{rss[$1] += $2} END {for (c in rss) printf "%s %d\n", c, rss[c]}' | sort -k2 -nr | head -n 10 | awk -v t="$total" '{
    printf "%s  %.1f%%  %.1fG\n", $1, $2 / t * 100, $2 / 1024 / 1024
  }')
  printf '%s' "$tooltip" > "$CACHE_TIP.tmp" && mv "$CACHE_TIP.tmp" "$CACHE_TIP"
fi

# NOTE: Waybar requires \r for tooltip newlines (gh#3153), escape Pango markup (gh#4617)
text_esc=$(printf '%s' "$text" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
tip_esc=$(printf '%s' "$tooltip" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g' | tr '\n' '\r')
jq -nc --arg text "$text_esc" --arg tip "$tip_esc" '{text: $text, tooltip: $tip}'
