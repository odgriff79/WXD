#!/bin/bash
# WXD Chart Sync - Copy charts to docs/ and push to GitHub
# Run after chart generation to update GitHub Pages

set -e

cd /home/ubuntu/wxd

echo "=== WXD Chart Sync $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Create charts directory if needed
mkdir -p docs/charts

# Copy latest charts
echo "Copying charts..."

if [ -f data/chart_latest.png ]; then
    cp data/chart_latest.png docs/charts/main.png
    echo "  main.png updated"
fi

if [ -f trackers/icon/data/chart_latest.png ]; then
    cp trackers/icon/data/chart_latest.png docs/charts/icon.png
    echo "  icon.png updated"
fi

if [ -f trackers/ukmo/data/chart_latest.png ]; then
    cp trackers/ukmo/data/chart_latest.png docs/charts/ukmo.png
    echo "  ukmo.png updated"
fi

if [ -f trackers/mogreps/data/chart_latest.png ]; then
    cp trackers/mogreps/data/chart_latest.png docs/charts/mogreps.png
    echo "  mogreps.png updated"
fi

# Add charts (force to ensure new files are added)
git add -f docs/charts/*.png 2>/dev/null || true

# Check if any charts staged
if git diff --cached --quiet docs/charts/; then
    echo "No chart changes to commit"
    exit 0
fi

# Commit and push
echo "Pushing to GitHub..."
git commit -m "Update charts $(date -u +%Y-%m-%d\ %H:%M)Z"
git push

echo "=== Complete ==="
