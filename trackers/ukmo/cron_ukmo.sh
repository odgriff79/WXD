#!/bin/bash
# WXD UKMO Tracker - Cron script

cd /home/ubuntu/wxd/trackers/ukmo
source /home/ubuntu/wxd/venv/bin/activate
source ~/.wxd_env

trap 'python /home/ubuntu/wxd/tracker_state.py failure UKMO' ERR

echo "=== WXD UKMO Fetch $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

python fetch.py || exit 1
python post.py || exit 1

python /home/ubuntu/wxd/tracker_state.py success UKMO
echo "=== Complete ==="
