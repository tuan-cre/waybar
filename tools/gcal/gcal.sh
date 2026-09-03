#!/usr/bin/env bash
# Waybar calendar module — gcalcli integration
# Counts today's events from agenda output. Shows full agenda as tooltip.

GCALCLI="$HOME/.local/bin/gcalcli"
OAUTH_FILE="$HOME/.config/gcalcli/oauth.json"

if [ ! -f "$OAUTH_FILE" ]; then
  jq -nc '{text: "", tooltip: "Calendar not configured — click to set up", class: "not-configured"}'
  exit 0
fi

raw=$($GCALCLI --nocolor --lineart unicode agenda "$(date +%Y-%m-%d)" 2>&1)
rc=$?

if [ $rc -ne 0 ]; then
  jq -nc '{text: " !", tooltip: "gcalcli error — check auth", class: "error"}'
  exit 0
fi

output=$(echo "$raw" | sed '/./,$!d')
today_label=$(date +"%b %d")
count=$(echo "$output" | grep -c "$today_label")

jq -nc --arg tooltip "$output" --argjson count "$count" '{
  text: " \($count)",
  tooltip: $tooltip
}'
