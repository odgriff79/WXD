#!/bin/bash
# WXD ICON Tracker - Cron script
# Runs 4x daily: 04:00, 10:00, 16:00, 22:00 UTC
# Crontab: 0 4,10,16,22 * * * /home/ubuntu/wxd/trackers/icon/cron_icon.sh

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
