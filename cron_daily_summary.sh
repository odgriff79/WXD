#!/bin/bash
# WXD Daily Summary - Cron script
# Runs once daily at 09:30 UTC
# Crontab: 30 9 * * * /home/ubuntu/wxd/cron_daily_summary.sh >> /home/ubuntu/wxd/cron_daily_summary.log 2>&1

set -e

cd /home/ubuntu/wxd

echo "=== WXD Daily Summary $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Activate venv and load credentials
source /home/ubuntu/wxd/venv/bin/activate
source ~/.wxd_env

# Run daily summary
python daily_summary.py

echo "=== Complete ==="
