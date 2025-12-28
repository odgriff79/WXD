#!/usr/bin/env python3
"""
WXD Tracker D - UKMO Deterministic Analysis & Posting

Single-model deterministic tracker for UK Met Office Global.
Runs 2x daily: ~05:00 UTC (00z), ~17:00 UTC (12z)

Features:
- Run-on-run shift detection
- Cold/warm threshold alerts
- Claude CLI commentary
- Bluesky posting with chart
"""

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Thresholds (same as main tracker)
COLD_THRESHOLD = -5
EXTREME_COLD = -8
WARM_THRESHOLD = 10

# Try to import atproto for Bluesky
try:
    from atproto import Client, models as atproto_models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False


def utcnow():
    return datetime.now(timezone.utc)


def load_alert_state(state_path: Path) -> dict:
    """Load alert state for hysteresis tracking."""
    if state_path.exists():
        with open(state_path, 'r') as f:
            return json.load(f)
    return {
        "cold_count": 0,
        "extreme_cold_count": 0,
        "intro_posted": False
    }


def save_alert_state(state_path: Path, state: dict) -> None:
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


def analyze_run_diff(data: dict) -> dict:
    """Compare current run to previous run."""
    runs = data.get("runs", [])
    if len(runs) < 2:
        return None

    current = runs[0]
    previous = runs[1]

    curr_vals = current.get("values", [])
    prev_vals = previous.get("values", [])

    if not curr_vals or not prev_vals:
        return None

    # Find max difference in overlapping range
    min_len = min(len(curr_vals), len(prev_vals))
    max_diff = 0
    max_diff_idx = 0

    for i in range(min_len):
        if curr_vals[i] is not None and prev_vals[i] is not None:
            diff = curr_vals[i] - prev_vals[i]
            if abs(diff) > abs(max_diff):
                max_diff = diff
                max_diff_idx = i

    if abs(max_diff) >= 2.0:  # Significant shift threshold
        timestamps = current.get("timestamps", [])
        date = timestamps[max_diff_idx][:10] if max_diff_idx < len(timestamps) else "unknown"
        direction = "warmer" if max_diff > 0 else "colder"
        return {
            "shift": round(max_diff, 1),
            "direction": direction,
            "date": date
        }

    return None


def check_cold_threshold(data: dict) -> dict:
    """Check if UKMO crosses cold threshold."""
    runs = data.get("runs", [])
    if not runs:
        return None

    current = runs[0]
    values = current.get("values", [])
    timestamps = current.get("timestamps", [])

    if not values or not timestamps:
        return None

    # Find coldest point
    coldest_temp = None
    coldest_idx = None

    for i, temp in enumerate(values):
        if temp is not None and temp < COLD_THRESHOLD:
            if coldest_temp is None or temp < coldest_temp:
                coldest_temp = temp
                coldest_idx = i

    if coldest_temp is not None:
        date = timestamps[coldest_idx][:10] if coldest_idx < len(timestamps) else "unknown"
        return {
            "temp": round(coldest_temp, 1),
            "date": date,
            "extreme": coldest_temp <= EXTREME_COLD
        }

    return None


def get_claude_commentary(data_path: Path, run_diff: dict, cold_info: dict) -> tuple:
    """Get Claude CLI commentary for UKMO data."""
    context_parts = []

    if run_diff:
        context_parts.append(f"SHIFT: UKMO moved {abs(run_diff['shift'])}C {run_diff['direction']} since last run around {run_diff['date']}")

    if cold_info:
        context_parts.append(f"COLD: UKMO shows {cold_info['temp']}C on {cold_info['date']}")

    context = "\n".join(context_parts) if context_parts else "No significant changes"

    prompt = f"""You are WXD UKMO tracker. Write brief commentary on UK Met Office deterministic 850hPa temperature data for London.

Write a Bluesky post (max 250 chars). This is the official UK weather service's global model.

STYLE:
- Start with "UKMO:" to identify this tracker
- Note any significant changes from last run
- Mention the cold/warm signal if present
- Keep it brief and factual

CONTEXT:
{context}

FORMAT:
- Plain text only (no markdown, emojis, hashtags)
- Use C for temperatures"""

    try:
        with open(data_path, 'r') as f:
            data_str = f.read()

        result = subprocess.run(
            ['claude', '-p', prompt, '--max-tokens', '150'],
            input=data_str,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:280], False

    except Exception as e:
        print(f"  Claude CLI error: {e}")

    # Fallback
    if cold_info:
        return f"UKMO: Model shows {cold_info['temp']}C at 850hPa around {cold_info['date']}.", True
    elif run_diff:
        return f"UKMO: Model shifted {abs(run_diff['shift'])}C {run_diff['direction']} since last run.", True
    else:
        return "UKMO: No significant changes in latest run.", True


def generate_chart(data: dict, chart_path: Path) -> bool:
    """Generate UKMO chart."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime

        runs = data.get("runs", [])
        if not runs:
            return False

        current = runs[0]
        timestamps = current.get("timestamps", [])
        values = current.get("values", [])

        if not timestamps or not values:
            return False

        # Parse dates
        dates = [datetime.fromisoformat(t.replace('Z', '+00:00')) for t in timestamps]

        # Convert None to NaN for matplotlib
        import numpy as np
        vals_arr = np.array([float(x) if x is not None else np.nan for x in values])

        # Create plot
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot UKMO line (deterministic - single line, no spread)
        ax.plot(dates, vals_arr, color='#ff6b6b', linewidth=2.5, label='UKMO Global', marker='o', markersize=4)

        # Threshold lines
        ax.axhline(y=COLD_THRESHOLD, color='blue', linestyle='--', alpha=0.5, linewidth=1)
        ax.axhline(y=0, color='white', linestyle='-', alpha=0.3, linewidth=1)

        # Labels
        ax.text(dates[-1], COLD_THRESHOLD, f' {COLD_THRESHOLD}C', color='blue', alpha=0.7, va='center', fontsize=9)

        # Title with date
        fetched_at = current.get("fetched_at", "")
        run_label = current.get("run_label", "")
        try:
            dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
            date_str = dt.strftime('%d %b')
            title = f'London 850hPa - UKMO Deterministic ({date_str} {run_label})'
        except:
            title = f'London 850hPa - UKMO Deterministic ({run_label})'

        ax.set_title(title, fontsize=14)
        ax.set_xlabel('Date (UTC)', fontsize=12)
        ax.set_ylabel('850hPa Temperature (C)', fontsize=12)
        ax.legend(loc='upper right', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        fig.autofmt_xdate()

        # Watermark
        fig.text(0.99, 0.01, 'WXD UKMO Tracker | wxd-london.bsky.social',
                fontsize=8, color='gray', alpha=0.6, ha='right', va='bottom')

        plt.tight_layout()
        plt.savefig(chart_path, dpi=150, facecolor='#1a1a2e')
        plt.close()

        print(f"  Chart saved: {chart_path.name}")
        return True

    except Exception as e:
        print(f"  Chart error: {e}")
        return False


def post_to_bluesky(text: str, image_path: Path = None, handle: str = None, password: str = None) -> dict:
    """Post to Bluesky."""
    if not HAS_ATPROTO or not handle or not password:
        return None

    try:
        client = Client()
        client.login(handle, password)

        if image_path and image_path.exists():
            with open(image_path, 'rb') as f:
                img_data = f.read()
            upload = client.upload_blob(img_data)
            embed = atproto_models.AppBskyEmbedImages.Main(
                images=[atproto_models.AppBskyEmbedImages.Image(
                    alt="UKMO deterministic 850hPa temperature forecast",
                    image=upload.blob
                )]
            )
            response = client.send_post(text=text, embed=embed)
        else:
            response = client.send_post(text=text)

        return {"uri": response.uri, "cid": response.cid}

    except Exception as e:
        print(f"  Bluesky error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='WXD UKMO Tracker - Analysis & Posting')
    parser.add_argument('--dry-run', '-n', action='store_true', help='Preview without posting')
    parser.add_argument('--preview', '-p', action='store_true', help='Use preview data')
    parser.add_argument('--intro', action='store_true', help='Post introduction message')
    args = parser.parse_args()

    dry_run = args.dry_run or args.preview

    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    history_path = data_dir / "history.json"
    chart_path = data_dir / "chart_latest.png"
    state_path = data_dir / "alert_state.json"

    if args.preview:
        history_path = data_dir / "preview_summary.json"
        chart_path = data_dir / "preview_chart.png"

    # Credentials
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    print(f"WXD UKMO Tracker - {utcnow().isoformat()}")
    if dry_run:
        print("DRY RUN MODE - will NOT post")
    print()

    # Load alert state
    alert_state = load_alert_state(state_path)

    # Handle intro message
    if args.intro and not alert_state.get("intro_posted"):
        intro_msg = """Introducing WXD UKMO Tracker

Now tracking the UK Met Office Global model (~10km) for London 850hPa.

UKMO runs 2x daily (00z/12z). Posts tagged "UKMO:" as deterministic benchmark."""

        print("Posting introduction message...")
        if not dry_run:
            result = post_to_bluesky(intro_msg, handle=bsky_handle, password=bsky_password)
            if result:
                alert_state["intro_posted"] = True
                save_alert_state(state_path, alert_state)
                print("  Intro posted successfully")
            else:
                print("  Failed to post intro")
        else:
            print(f"  PREVIEW: {intro_msg}")
        return 0

    # Check data exists
    if not history_path.exists():
        print(f"ERROR: {history_path} not found. Run fetch.py first.")
        return 1

    # Load data
    with open(history_path, 'r') as f:
        data = json.load(f)

    # For preview mode, wrap single summary as history format
    if args.preview and "runs" not in data:
        data = {"runs": [data]}

    # Log provenance
    runs = data.get("runs", [])
    if runs:
        fetched_at = runs[0].get("fetched_at", "unknown")
        run_label = runs[0].get("run_label", "?")
        print(f"Data: fetched {fetched_at[:19]}Z, {run_label}")

    # Analyze
    print("Analyzing run-on-run changes...")
    run_diff = analyze_run_diff(data)
    if run_diff:
        print(f"  Shift: {run_diff['shift']}C {run_diff['direction']}")
    else:
        print("  No significant shift")

    print("Checking cold threshold...")
    cold_info = check_cold_threshold(data)
    if cold_info:
        print(f"  Cold signal: {cold_info['temp']}C on {cold_info['date']}")
    else:
        print("  No cold signal")

    # Generate chart
    print("Generating chart...")
    chart_ok = generate_chart(data, chart_path)

    # Get commentary
    print("Generating commentary...")
    text, is_fallback = get_claude_commentary(history_path, run_diff, cold_info)
    print(f"  Commentary ({len(text)} chars):")
    print(f"  {text}")

    if dry_run:
        print()
        print("=" * 50)
        print("PREVIEW (not posting):")
        print(text)
        print("=" * 50)
        return 0

    # Post
    print()
    print("Posting to Bluesky...")
    result = post_to_bluesky(
        text,
        image_path=chart_path if chart_ok else None,
        handle=bsky_handle,
        password=bsky_password
    )

    if result:
        print("  Posted successfully")
        save_alert_state(state_path, alert_state)
    else:
        print("  Failed to post")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
