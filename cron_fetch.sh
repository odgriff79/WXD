#!/bin/bash
# WXD Cron Fetch Script
# Fetches weather data and pushes to GitHub
# Schedule: 07:30 UTC (captures 00z runs) and 19:30 UTC (captures 12z runs)

set -e

WXD_DIR="$HOME/wxd"
cd "$WXD_DIR"

# Log start
echo "=== WXD Fetch $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> cron.log

# Activate virtual environment
source venv/bin/activate

# Fetch data (creates timestamped files, cleans up old ones)
python fetch.py >> cron.log 2>&1

# Commit and push all data files
# Use git add -A to handle new timestamped files and deleted old files
cd data
if [ -n "$(git status --porcelain)" ]; then
    TIMESTAMP=$(date -u +%Y-%m-%d_%H%MZ)
    cd "$WXD_DIR"
    git add data/
    git commit -m "Data update $TIMESTAMP"
    git push
    echo "Pushed: $TIMESTAMP" >> cron.log
else
    echo "No changes to commit" >> cron.log
fi

echo "=== Complete ===" >> cron.log
echo "" >> cron.log
