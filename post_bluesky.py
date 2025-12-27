#!/usr/bin/env python3
"""
WXD Bluesky Poster - Generates AI commentary and posts to Bluesky.

Reads history_compact.json, pipes to Claude CLI for commentary,
generates a chart, and posts to Bluesky.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Try imports - will fail gracefully if not installed
try:
    import matplotlib
    matplotlib.use('Agg')  # Headless
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from atproto import Client
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_claude_commentary(data_path: Path) -> str:
    """Pipe JSON to Claude CLI and get commentary."""
    prompt = """You are WXD, a weather ensemble analysis bot. Analyse this 4-model ensemble 850hPa temperature data for London.

Write a Bluesky post (max 280 chars):
- Lead with the key finding (cold/warm signal, timing)
- Note model agreement or disagreement
- Keep it punchy and informative
- No hashtags, no emojis
- Use °C for temperatures

Data shows ensemble means from GFS, ECMWF IFS, ECMWF AIFS, and GEM models."""

    try:
        with open(data_path, 'r') as f:
            data = f.read()

        result = subprocess.run(
            ['claude', '-p', prompt],
            input=data,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            # Clean up the response
            text = result.stdout.strip()
            # Truncate to 300 chars (Bluesky limit)
            if len(text) > 300:
                text = text[:297] + "..."
            return text
        else:
            print(f"Claude CLI error: {result.stderr}")
            return None

    except subprocess.TimeoutExpired:
        print("Claude CLI timed out")
        return None
    except Exception as e:
        print(f"Error getting commentary: {e}")
        return None


def generate_chart(data_path: Path, output_path: Path) -> bool:
    """Generate 850hPa temperature chart from history_compact.json."""
    if not HAS_MATPLOTLIB:
        print("matplotlib not installed, skipping chart")
        return False

    try:
        with open(data_path, 'r') as f:
            data = json.load(f)

        if not data.get('runs'):
            print("No runs in data")
            return False

        run = data['runs'][0]  # Latest run
        timestamps = run.get('timestamps', [])
        models = run.get('models', {})

        if not timestamps or not models:
            print("No timestamps or models in data")
            return False

        # Parse timestamps
        dates = [datetime.fromisoformat(ts.replace('Z', '+00:00')) for ts in timestamps]

        # Dark theme
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 6))

        # Plot each model
        colors = {
            'gfs': '#FF6B6B',
            'ecmwf_ifs': '#4ECDC4',
            'ecmwf_aifs': '#45B7D1',
            'gem': '#96CEB4'
        }
        labels = {
            'gfs': 'GFS (31)',
            'ecmwf_ifs': 'IFS (51)',
            'ecmwf_aifs': 'AIFS (51)',
            'gem': 'GEM (21)'
        }

        for model_key, model_data in models.items():
            means = model_data.get('mean', [])
            if means:
                ax.plot(dates[:len(means)], means,
                       color=colors.get(model_key, 'white'),
                       label=labels.get(model_key, model_key),
                       linewidth=2)

        # Multi-model mean
        mmm = run.get('multi_model_mean', [])
        if mmm:
            ax.plot(dates[:len(mmm)], mmm, color='white', label='Multi-model mean',
                   linewidth=3, linestyle='--')

        # Formatting
        ax.set_xlabel('Date (UTC)', fontsize=12)
        ax.set_ylabel('850hPa Temperature (°C)', fontsize=12)
        ax.set_title(f'London 850hPa Ensemble Forecast\nFetched: {run.get("fetched_at", "Unknown")}',
                    fontsize=14)
        ax.legend(loc='upper right', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        fig.autofmt_xdate()

        # Add freezing line
        ax.axhline(y=0, color='cyan', linestyle=':', alpha=0.5, label='0°C')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, facecolor='#1a1a2e')
        plt.close()

        print(f"Chart saved: {output_path}")
        return True

    except Exception as e:
        print(f"Error generating chart: {e}")
        return False


def post_to_bluesky(text: str, image_path: Path = None, handle: str = None, password: str = None) -> bool:
    """Post to Bluesky with optional image."""
    if not HAS_ATPROTO:
        print("atproto not installed, skipping post")
        return False

    if not handle or not password:
        print("Bluesky credentials not provided")
        return False

    try:
        client = Client()
        client.login(handle, password)

        if image_path and image_path.exists():
            with open(image_path, 'rb') as f:
                image_data = f.read()
            # Upload image and post with it
            upload = client.upload_blob(image_data)
            embed = {
                '$type': 'app.bsky.embed.images',
                'images': [{
                    'alt': 'London 850hPa ensemble temperature forecast',
                    'image': upload.blob
                }]
            }
            client.send_post(text=text, embed=embed)
        else:
            client.send_post(text=text)

        print("Posted to Bluesky successfully")
        return True

    except Exception as e:
        print(f"Error posting to Bluesky: {e}")
        return False


def main():
    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_path = data_dir / "history_compact.json"
    chart_path = data_dir / "chart_latest.png"

    # Check for credentials in environment
    import os
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    print(f"WXD Bluesky Poster - {utcnow().isoformat()}")
    print()

    # Check data exists
    if not data_path.exists():
        print(f"ERROR: {data_path} not found. Run fetch.py first.")
        return 1

    # Generate commentary
    print("Generating AI commentary...")
    text = get_claude_commentary(data_path)
    if not text:
        print("ERROR: Failed to generate commentary")
        return 1
    print(f"Commentary ({len(text)} chars):")
    print(f"  {text}")
    print()

    # Generate chart
    print("Generating chart...")
    chart_ok = generate_chart(data_path, chart_path)
    print()

    # Post to Bluesky
    if bsky_handle and bsky_password:
        print("Posting to Bluesky...")
        image = chart_path if chart_ok else None
        post_ok = post_to_bluesky(text, image, bsky_handle, bsky_password)
        if not post_ok:
            return 1
    else:
        print("BSKY_HANDLE and BSKY_PASSWORD not set, skipping post")
        print("Set these environment variables to enable posting")

    print()
    print("Complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
