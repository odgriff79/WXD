#!/bin/bash
# WXD ICON Tracker - Cron script

cd /home/ubuntu/wxd/trackers/icon
source /home/ubuntu/wxd/venv/bin/activate
source ~/.wxd_env

# Trap errors and record failure
trap 'python /home/ubuntu/wxd/tracker_state.py failure ICON "$error_msg"' ERR

echo "=== WXD ICON Fetch $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Fetch data
python fetch.py || { error_msg="fetch failed"; exit 1; }

# Post to Bluesky
python post.py || { error_msg="post failed"; exit 1; }

# Record success
python /home/ubuntu/wxd/tracker_state.py success ICON

echo "=== Complete ==="
