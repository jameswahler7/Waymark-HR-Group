#!/bin/bash
LAST_RUN=""
while true; do
    CURRENT_HOUR=$(date +"%H")
    CURRENT_DATE=$(date +"%Y-%m-%d")
    if [ "$CURRENT_HOUR" = "08" ] && [ "$LAST_RUN" != "$CURRENT_DATE" ]; then
        bash /Users/jamie/Documents/waymark-hr-group/followup_engine/run.sh
        LAST_RUN=$CURRENT_DATE
    fi
    sleep 60
done
