#!/bin/bash
# WXD Cron Fetch Script
# Fetches weather data and pushes to GitHub

set -e

WXD_DIR="$HOME/wxd"
cd "$WXD_DIR"

# Activate virtual environment
source venv/bin/activate

# Fetch data
python fetch.py

# Commit and push if there are changes
if git diff --quiet data/; then
    echo "No changes to commit"
else
    TIMESTAMP=$(date -u +%Y-%m-%d_%H%MZ)
    git add data/*.json
    git commit -m "Update $TIMESTAMP"
    git push
    echo "Pushed update: $TIMESTAMP"
fi
