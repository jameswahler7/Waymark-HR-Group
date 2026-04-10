#!/bin/bash
source /Users/jamie/Documents/waymark-hr-group/followup_engine/.env
export ANTHROPIC_API_KEY
cd /Users/jamie/Documents/waymark-hr-group/followup_engine
/usr/bin/python3 followup_engine.py >> logs/cron.log 2>&1
