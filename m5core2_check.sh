#!/bin/sh
# Called by the Zabbix agent (see m5core2.conf).
#   m5core2_check.sh age            seconds since the last valid heartbeat (999999 if never seen)
#   m5core2_check.sh health [MAX]   1 = OK (heartbeat newer than MAX seconds, default 420), 0 = FAIL
#   m5core2_check.sh field NAME     last reported value of: up g n t bat
STATE="${M5CORE2_STATE:-/home/jkozik/projects/m5-core2-chk/state}/last_seen"

age() {
  if [ -f "$STATE" ]; then
    echo $(( $(date +%s) - $(stat -c %Y "$STATE") ))
  else
    echo 999999
  fi
}

case "$1" in
  age)
    age ;;
  health)
    max="${2:-420}"
    case "$max" in ''|*[!0-9]*) max=420 ;; esac
    if [ "$(age)" -le "$max" ]; then echo 1; else echo 0; fi ;;
  field)
    case "$2" in
      up|g|n|t|bat) [ -f "$STATE" ] && sed -n "s/.*\b$2=\(-\?[0-9]*\).*/\1/p" "$STATE" ;;
      *) echo "bad field" >&2; exit 1 ;;
    esac ;;
  *)
    echo "usage: $0 age | health [max_seconds] | field up|g|n|t|bat" >&2; exit 1 ;;
esac
