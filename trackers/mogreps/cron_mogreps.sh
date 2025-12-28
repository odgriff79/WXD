#!/bin/bash
# WXD MOGREPS Tracker - Cron script
# Runs 2x daily: 05:30, 17:30 UTC (captures 00z and 12z runs with ~4h delay)
# MOGREPS runs 4x daily but we post 2x for consistency with other trackers
# Crontab: 30 5,17 * * * /home/ubuntu/wxd/trackers/mogreps/cron_mogreps.sh

set -e

cd /home/ubuntu/wxd/trackers/mogreps

echo "=== WXD MOGREPS Fetch $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Activate venv and load credentials
source /home/ubuntu/wxd/venv/bin/activate
source ~/.wxd_env

# Fetch data
python fetch.py

# Post to Bluesky
python post.py

echo "=== Complete ==="
