#!/bin/bash
# run.sh — Waymark cold email engine cron entry point (Phases 1+2 sender)
#
# This is the launchd shim for com.waymark.followupengine. The plist fires
# every 15 minutes via StartInterval. The Python script self-gates against
# the spec's send window (9:00 AM - 4:30 PM ET, M-F, holidays skipped), so
# off-hours ticks no-op cleanly.
#
# --limit 25 is the per-tick cap. Pacing rules inside the script (12-28 min
# randomized gap, rolling 60-min burst cap, daily 25-send cap) keep the
# effective rate at roughly one send per tick during business hours.

set -euo pipefail
cd /Users/jamie/Documents/waymark-hr-group/followup_engine
mkdir -p logs
/usr/bin/python3 followup_engine.py --limit 25 >> logs/cron.log 2>&1
