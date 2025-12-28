#!/bin/bash
# WXD ICON Tracker - Cron script
# Runs 2x daily: 04:30, 16:30 UTC (captures 00z and 12z runs)
# Note: Only 00z/12z runs have pressure-level 850hPa data
# Crontab: 30 4,16 * * * /home/ubuntu/wxd/trackers/icon/cron_icon.sh

set -e

cd /home/ubuntu/wxd/trackers/icon

echo "=== WXD ICON Fetch $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Activate venv and load credentials
source /home/ubuntu/wxd/venv/bin/activate
source ~/.wxd_env

# Fetch data
python fetch.py

# Post to Bluesky
python post.py

echo "=== Complete ==="
