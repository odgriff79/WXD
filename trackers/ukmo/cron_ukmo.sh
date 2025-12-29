#!/bin/bash
# WXD UKMO Tracker - Cron script
# Runs 2x daily: 05:00, 17:00 UTC (captures 00z and 12z runs with 4h delay)
# Crontab: 0 5,17 * * * /home/ubuntu/wxd/trackers/ukmo/cron_ukmo.sh

set -e

cd /home/ubuntu/wxd/trackers/ukmo

echo "=== WXD UKMO Fetch $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Activate venv and load credentials
source /home/ubuntu/wxd/venv/bin/activate
source ~/.wxd_env

# Fetch data
python fetch.py

# Post to Bluesky
python post.py

echo "=== Complete ==="
