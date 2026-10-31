#!/bin/bash
# Toggle the bluetooth adapter through the blueman applet's DBus interface,
# falling back to bluetoothctl when the applet is not running.
# Retriggers custom/bluetooth (signal 9) so the bar updates immediately.
state=$(dbus-send --session --print-reply --dest=org.blueman.Applet \
  /org/blueman/Applet org.blueman.Applet.GetBluetoothStatus 2>/dev/null |
  awk '/boolean/{print $2}')

if [[ $state == true || $state == false ]]; then
  [[ $state == true ]] && new=false || new=true
  dbus-send --session --type=method_call --dest=org.blueman.Applet \
    /org/blueman/Applet org.blueman.Applet.SetBluetoothStatus boolean:$new
else
  if [[ $(bluetoothctl show 2>/dev/null | awk -F': ' '/^[[:space:]]*Powered:/{print $2; exit}') == yes ]]; then
    bluetoothctl power off
  else
    bluetoothctl power on
  fi
fi

pkill -RTMIN+9 waybar
