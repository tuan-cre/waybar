#!/usr/bin/env bash
# Waybar calendar module — gcalcli integration (cached).
# Serves cache instantly; refreshes in background when stale.
# Shows today's event count and event list as a tooltip.

GCALCLI="${GCALCLI:-$HOME/.local/bin/gcalcli}"
OAUTH_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/gcalcli/oauth"
LEGACY_OAUTH_FILE="$HOME/.gcalcli_oauth"
CACHE_DIR="$HOME/.cache/waybar-gcal"
CACHE_JSON="$CACHE_DIR/gcal.json"
ERROR_FILE="$CACHE_DIR/refresh-error"
ERROR_LOG="$CACHE_DIR/refresh-error.log"
LOCK_DIR="$CACHE_DIR/lock"
TTL="${GCAL_TTL:-600}" # 10 min
BACKOFF="${GCAL_BACKOFF:-300}" # 5 min between retries after a failed refresh

mkdir -p "$CACHE_DIR"

if [ ! -f "$OAUTH_FILE" ] && [ ! -f "$LEGACY_OAUTH_FILE" ]; then
  jq -nc '{text: "", tooltip: "Calendar not configured — click to set up", class: "not-configured"}'
  exit 0
fi

serve_cache() {
  if [ -f "$CACHE_JSON" ]; then
    local failed=false
    local note=""
    if [ -f "$ERROR_FILE" ]; then
      failed=true
      if in_backoff; then
        left=$(( BACKOFF - ( $(date +%s) - $(stat -c %Y "$ERROR_FILE") ) ))
        note=" (retry in $(( (left + 59) / 60 ))m)"
      fi
    fi
    jq -c --argjson failed "$failed" --arg note "$note" '
      if $failed then
        .class = "error" | .tooltip += "\nCalendar refresh failed" + $note + "; showing cached data"
      else . end
      | .tooltip |= (gsub("\n"; "\r") | gsub("&"; "\u0026amp;") | gsub("<"; "\u0026lt;") | gsub(">"; "\u0026gt;"))
    ' "$CACHE_JSON" && return 0
  fi
  return 1
}

is_fresh() {
  [ -f "$CACHE_JSON" ] || return 1
  age=$(( $(date +%s) - $(stat -c %Y "$CACHE_JSON") ))
  [ "$age" -lt "$TTL" ]
}

# Failsafe: after a failed refresh, wait BACKOFF seconds before trying again so
# an expired/revoked token can't make waybar respawn gcalcli on every cycle.
in_backoff() {
  [ -f "$ERROR_FILE" ] || return 1
  age=$(( $(date +%s) - $(stat -c %Y "$ERROR_FILE") ))
  [ "$age" -lt "$BACKOFF" ]
}

refresh_bg() {
  # failsafe: don't hammer gcalcli while backing off from a failure
  in_backoff && return 0
  # single background refresh at a time; break stale locks (>5 min = crashed run)
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCK_DIR") ))
    [ "$lock_age" -gt 300 ] && rmdir "$LOCK_DIR" 2>/dev/null
    mkdir "$LOCK_DIR" 2>/dev/null || return 0
  fi
  (
    today=$(date +%Y-%m-%d)
    tomorrow=$(date -d "$today +1 day" +%Y-%m-%d)
    # One TSV query supplies both the count and concise tooltip.
    err_tmp="$CACHE_DIR/refresh-error.tmp"
    tsv=$(timeout 60 "$GCALCLI" --nocolor agenda --tsv --military --details=title "$today" "$tomorrow" 2>"$err_tmp")
    rc=$?
    if [ "$rc" -eq 0 ]; then
      if parsed=$(printf '%s\n' "$tsv" | awk -F '\t' '
        NR == 1 {
          for (i = 1; i <= NF; i++) col[$i] = i
          next
        }
        NF {
          time = (col["start_time"] ? $(col["start_time"]) : "")
          title = (col["title"] ? $(col["title"]) : $NF)
          if (!title) next
          if (time) print time "  " title
          else print "All day  " title
          count++
        }
        END {
          if (NR < 1 || !col["start_time"] || !col["title"]) exit 1
          print "\034" count+0
        }
      '); then
        count=${parsed##*$'\034'}
        output=${parsed%$'\034'*}
      else
        parsed=
      fi
      if [ -n "$parsed" ] && jq -nc --arg tooltip "$output" --argjson count "$count" '{text: " \($count)", tooltip: $tooltip}' > "$CACHE_JSON.tmp" && mv "$CACHE_JSON.tmp" "$CACHE_JSON"; then
        rm -f "$ERROR_FILE" "$ERROR_LOG" "$err_tmp"
      else
        rm -f "$CACHE_JSON.tmp"
        { printf 'parse failed\n'; cat "$err_tmp"; } > "$ERROR_LOG"
        printf 'refresh failed\n' > "$ERROR_FILE"
        rm -f "$err_tmp"
      fi
    else
      { printf 'gcalcli exit %s\n' "$rc"; cat "$err_tmp"; } > "$ERROR_LOG"
      printf 'refresh failed\n' > "$ERROR_FILE"
      rm -f "$err_tmp"
    fi
    pkill -RTMIN+1 -x waybar 2>/dev/null || true
    rmdir "$LOCK_DIR" 2>/dev/null || true
  ) &
}

if is_fresh && serve_cache; then
  :
else
  # stale/missing: serve whatever we have instantly, refresh behind
  serve_cache || {
    if [ -f "$ERROR_FILE" ]; then
      jq -nc '{text: " !", tooltip: "Calendar refresh failed", class: "error"}'
    else
      jq -nc '{text: " …", tooltip: "Loading calendar…"}'
    fi
  }
  refresh_bg
fi
