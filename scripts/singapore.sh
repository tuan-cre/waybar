#!/bin/bash
# Singapore (SGT) clock for Waybar, shown next to local time.
# Text: SGT time, colored by whether the Singapore office is likely working.
# Tooltip: SGT + local time, the offset between the zones, and the current status.

read -r hour min dow < <(TZ=Asia/Singapore date '+%-H %-M %u')
sg_time=$(TZ=Asia/Singapore date '+%H:%M')
sg_date=$(TZ=Asia/Singapore date '+%A, %d %B %Y')
local_time=$(date '+%H:%M')

# Offset between the zones, derived from their UTC offsets (no hardcoded +1).
tz_minutes() {
  local off=$1 sign=1
  [[ ${off:0:1} == - ]] && sign=-1
  echo $(( sign * (10#${off:1:2} * 60 + 10#${off:3:2}) ))
}
diff=$(( $(tz_minutes "$(TZ=Asia/Singapore date +%z)") - $(tz_minutes "$(date +%z)") ))

if (( diff == 0 )); then
  offset="the same time as you"
else
  abs=${diff#-}
  rel=""
  (( abs / 60 > 0 )) && rel="$(( abs / 60 ))h"
  (( abs % 60 > 0 )) && rel="${rel}$(( abs % 60 ))m"
  if (( diff > 0 )); then
    offset="${rel} ahead of you"
  else
    offset="${rel} behind you"
  fi
fi

# Singapore office hours: Mon-Fri 09:00-18:00 SGT, lunch 12:00-13:00.
if (( dow >= 6 )); then
  class="off"; status="Weekend - likely off"
elif (( hour < 9 )); then
  class="off"; status="Before office hours"
elif (( hour == 12 )); then
  class="lunch"; status="Lunch break"
elif (( hour < 18 )); then
  class="office"; status="Office hours"
else
  class="off"; status="After office hours"
fi

text="SG ${sg_time}"
tooltip="Singapore   ${sg_time}"$'\n'"${sg_date}"$'\n\n'"Your time   ${local_time}"$'\n'"SGT is ${offset}"$'\n\n'"${status}"$'\n'"Office hours: Mon-Fri 09:00-18:00 SGT"

# NOTE: Waybar requires \r for tooltip newlines (gh#3153), escape Pango markup (gh#4617)
tip=$(printf '%s' "$tooltip" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g' | tr '\n' '\r')
jq -nc --arg text "$text" --arg class "$class" --arg tip "$tip" \
  '{text: $text, class: $class, tooltip: $tip}'
