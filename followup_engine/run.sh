#!/bin/bash
# run.sh — Waymark cold email engine cron entry point
#
# Hardened June 12, 2026:
#   - Explicit minimal PATH (no inheritance from launchd's empty env)
#   - Absolute python path pinned to a variable
#   - .env sourced in bash before python (defense in depth; python-dotenv
#     also loads it, but exported vars cover any spawned subprocess)
#   - Brief DNS-availability gate so a tick that fires before network is
#     ready waits up to ~25s instead of crashing
#
# NOTE: this script alone does NOT fix the macOS TCC permission issue that
# is the actual blocker for the launchd ticks. TCC fix lives in
# System Settings -> Privacy & Security -> Full Disk Access.

set -euo pipefail

export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

PROJECT_DIR=/Users/jamie/Documents/waymark-hr-group/followup_engine
PYTHON=/usr/bin/python3

cd "$PROJECT_DIR"
mkdir -p logs

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# Wait up to ~25s for DNS to be ready (sleep/wake cycles can leave
# launchd ticks firing before mDNSResponder is fully back).
for i in 1 2 3 4 5; do
    if /usr/bin/dscacheutil -q host -a name oauth2.googleapis.com >/dev/null 2>&1; then
        break
    fi
    sleep 5
done

"$PYTHON" followup_engine.py --limit 25 >> logs/cron.log 2>&1
