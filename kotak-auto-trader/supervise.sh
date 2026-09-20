#!/bin/bash
# SELF-HEALING runner: restarts the bot automatically if it ever crashes.
# Use:  chmod +x supervise.sh   then   nohup ./supervise.sh &
# (On VPS, a systemd service is even better - same idea.)
cd "$(dirname "$0")"
while true; do
  echo "$(date '+%F %T') starting main.py" >> supervise.log
  python3 main.py
  echo "$(date '+%F %T') main.py exited ($?). Restarting in 15s..." >> supervise.log
  sleep 15
done
