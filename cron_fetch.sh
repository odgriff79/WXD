#!/bin/bash
# WXD Cron Fetch Script
# Fetches weather data, pushes to GitHub, posts to Bluesky
# Schedule: 08:30 UTC (captures 00z runs) and 20:30 UTC (captures 12z runs)

# NO set -e: we handle errors explicitly to ensure logging and alerts

WXD_DIR="$HOME/wxd"
cd "$WXD_DIR"

# Load credentials
[ -f "$HOME/.wxd_env" ] && source "$HOME/.wxd_env"

# Error handler - sends ntfy alert and records failure in tracker state
alert_failure() {
    local msg="$1"
    echo "ERROR: $msg" >> cron.log
    python tracker_state.py failure tracker_a "$msg" 2>/dev/null || true
    if [ -n "$NTFY_CHANNEL" ]; then
        curl -s -d "WXD CRON FAILED: $msg" "ntfy.sh/$NTFY_CHANNEL" > /dev/null 2>&1
    fi
}

# Log start
echo "=== WXD Fetch $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> cron.log

# Activate virtual environment
source venv/bin/activate

# Fetch data
if ! python fetch.py >> cron.log 2>&1; then
    alert_failure "fetch.py failed"
    echo "=== Failed ===" >> cron.log
    exit 1
fi

# Pull before push to avoid conflicts with local edits
# Stash any local changes first (data files from fetch)
echo "Syncing with remote..." >> cron.log
git stash -q >> cron.log 2>&1 || true
if ! git pull --rebase origin main >> cron.log 2>&1; then
    git stash pop -q >> cron.log 2>&1 || true
    alert_failure "git pull --rebase failed"
    echo "=== Failed ===" >> cron.log
    exit 1
fi
git stash pop -q >> cron.log 2>&1 || true

# Commit and push data files
cd "$WXD_DIR"
if [ -n "$(git status --porcelain data/)" ]; then
    TIMESTAMP=$(date -u +%Y-%m-%d_%H%MZ)
    git add data/
    if ! git commit -m "Data update $TIMESTAMP" >> cron.log 2>&1; then
        alert_failure "git commit failed"
        echo "=== Failed ===" >> cron.log
        exit 1
    fi
    if ! git push >> cron.log 2>&1; then
        alert_failure "git push failed"
        echo "=== Failed ===" >> cron.log
        exit 1
    fi
    echo "Pushed: $TIMESTAMP" >> cron.log
else
    echo "No data changes to commit" >> cron.log
fi

# Post to Bluesky
if [ -n "$BSKY_HANDLE" ] && [ -n "$BSKY_PASSWORD" ]; then
    echo "Posting to Bluesky..." >> cron.log
    if ! python post_bluesky.py >> cron.log 2>&1; then
        alert_failure "post_bluesky.py failed"
        # Continue anyway - data was pushed
    fi

    # Push chart
    if [ -f "data/chart_latest.png" ]; then
        git add data/chart_latest.png
        if [ -n "$(git status --porcelain data/chart_latest.png)" ]; then
            git pull --rebase origin main >> cron.log 2>&1 || true
            git commit -m "Update chart $(date -u +%Y-%m-%d_%H%MZ)" >> cron.log 2>&1 || true
            git push >> cron.log 2>&1 || echo "Chart push failed (non-fatal)" >> cron.log
            echo "Pushed chart_latest.png" >> cron.log
        fi
    fi
else
    alert_failure "Bluesky credentials not set"
fi

# Record success in tracker state
python tracker_state.py success tracker_a 2>/dev/null || true

echo "=== Complete ===" >> cron.log
echo "" >> cron.log
