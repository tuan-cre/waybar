#!/usr/bin/env bash
# Waybar widget: OpenRouter free-model daily usage. Resets 07:00 VN.
set -u

emit() { # $1=text $2=tooltip $3=class $4=pct
  local text_esc tip_esc
  text_esc=$(printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
  tip_esc=$(printf '%b' "$2" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g' | tr '\n' '\r')
  jq -nc --arg t "$text_esc" --arg tip "$tip_esc" --arg c "$3" --argjson p "${4:-0}" \
    '{text: $t, tooltip: $tip, class: $c, percentage: $p}'
}

tmp=$(mktemp "${TMPDIR:-/tmp}/waybar-or.XXXXXX") || exit 0
trap 'rm -f "$tmp"' EXIT

# Check connectivity before the key so an offline session doesn't look like a
# configuration error. The request itself is the connectivity check when a key
# is available; otherwise use curl against the API host without credentials.
if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  online=$(curl -s --max-time 5 -o /dev/null -w '%{http_code}' https://openrouter.ai 2>/dev/null)
  if [ "$online" = "000" ]; then
    jq -nc '{text: "", tooltip: "offline", class: "hidden"}'
    exit 0
  fi
  emit "OR err" "OPENROUTER_API_KEY is not set" "error"
  exit 0
fi

resp=$(curl -s --max-time 10 -o "$tmp" -w '%{http_code}' \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" https://openrouter.ai/api/v1/key 2>/dev/null)
if [ "$resp" = "000" ]; then
  jq -nc '{text: "", tooltip: "offline", class: "hidden"}'
  exit 0
fi
if [ "$resp" != "200" ]; then
  emit "OR err" "OpenRouter /key HTTP $resp (resets 07:00 VN)" "error"
  exit 0
fi

used=$(jq -r '.data.free_model_daily_requests.used // empty' "$tmp" 2>/dev/null)
limit=$(jq -r '.data.free_model_daily_requests.limit // empty' "$tmp" 2>/dev/null)
daily_cost=$(jq -r '.data.usage_daily // empty' "$tmp" 2>/dev/null)

if [ -z "$used" ] || [ -z "$limit" ]; then
  emit "OR err" "OpenRouter: unexpected /key response" "error"
  exit 0
fi

pct=0
[ "$limit" -gt 0 ] 2>/dev/null && pct=$(( used * 100 / limit ))

class=""
[ "$pct" -ge 80 ] && class="warning"
[ "$pct" -ge 95 ] && class="critical"

tip="OpenRouter free models\nUsed: $used / $limit\nDay cost: \$${daily_cost:-?}\nResets 07:00 VN\nClick: open activity"
[ "$pct" -ge 80 ] && tip="$tip\nNear limit!"

emit "󰧑 $used" "$tip" "$class" "$pct"
