#!/bin/bash
# Show memory usage matching fastfetch/btop (MemTotal - MemAvailable)
awk '
/MemTotal/ {total=$2}
/MemAvailable/ {avail=$2}
END {
  used = total - avail
  printf "%.1fG/%.1fG\n", used/1024/1024, total/1024/1024
}' /proc/meminfo
