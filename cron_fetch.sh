#!/bin/bash
# WXD Cron Fetch Script
# Fetches weather data, pushes to GitHub, optionally posts to Bluesky
# Schedule: 09:00 UTC (captures 00z runs) and 21:00 UTC (captures 12z runs)

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

# Post to Bluesky if credentials are set
cd "$WXD_DIR"
if [ -n "$BSKY_HANDLE" ] && [ -n "$BSKY_PASSWORD" ]; then
    echo "Posting to Bluesky..." >> cron.log
    python post_bluesky.py >> cron.log 2>&1 || echo "Bluesky post failed" >> cron.log
else
    echo "Bluesky credentials not set, skipping post" >> cron.log
fi

echo "=== Complete ===" >> cron.log
echo "" >> cron.log
