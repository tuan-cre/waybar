#!/bin/bash
# Waybar bluetooth indicator, replaces the blueman-tray status icon.
# Left click opens blueman-manager, right click toggles the adapter (bluetooth_toggle.sh).
powered=$(bluetoothctl show 2>/dev/null | awk -F': ' '/^[[:space:]]*Powered:/{print $2; exit}')

if [[ -z $powered ]]; then
  icon="󰂲"
  class="off"
  tooltip="No Bluetooth adapter found"
elif [[ $powered == yes ]]; then
  connected=$(bluetoothctl devices Connected 2>/dev/null | cut -d' ' -f3-)
  if [[ -n $connected ]]; then
    icon="󰂱"
    class="connected"
    tooltip="Connected:"$'\n'"$connected"
  else
    icon="󰂯"
    class="on"
    tooltip="Bluetooth on"$'\n'"No device connected"
  fi
else
  icon="󰂲"
  class="off"
  tooltip="Bluetooth off"
fi

# NOTE: Waybar requires \r for tooltip newlines (gh#3153), escape Pango markup (gh#4617)
tip=$(printf '%s' "$tooltip" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g' | tr '\n' '\r')
jq -nc --arg text "$icon" --arg class "$class" --arg tip "$tip" \
  '{text: $text, class: $class, tooltip: $tip}'
