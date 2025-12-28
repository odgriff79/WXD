#!/usr/bin/env python3
"""
WXD Tracker C - MOGREPS Ensemble Analysis & Posting

UK Met Office Global Ensemble (18 members).
Runs 4x daily but we post 2x daily (00z, 12z).

Features:
- Run-on-run shift detection
- Cold/warm threshold alerts
- Trend persistence tracking
- Percentile framing
- Timing uncertainty analysis
- Claude CLI commentary with enriched context
- Bluesky posting with chart
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for shared imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.analysis import (
    COLD_THRESHOLD, EXTREME_COLD, WARM_THRESHOLD,
    utcnow, run_full_analysis
)

# Try to import atproto for Bluesky
try:
    from atproto import Client, models as atproto_models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False


def get_run_label(fetched_at: str) -> str:
    """Determine which model run this fetch captures."""
    try:
        dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
        hour = dt.hour
        if 4 <= hour < 10:
            return "00z"
        elif 10 <= hour < 16:
            return "06z"
        elif 16 <= hour < 22:
            return "12z"
        else:
            return "18z"
    except:
        return None


def load_alert_state(state_path: Path) -> dict:
    """Load alert state for intro tracking."""
    if state_path.exists():
        with open(state_path, 'r') as f:
            return json.load(f)
    return {"intro_posted": False}


def save_alert_state(state_path: Path, state: dict) -> None:
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


def get_claude_commentary(data_path: Path, full_context: str, run_diff: dict, cold_info: dict) -> tuple:
    """Get Claude CLI commentary for MOGREPS data with enriched context."""
    prompt = f"""You are WXD MOGREPS tracker. Write brief commentary on UK Met Office ensemble (18 members) 850hPa temperature data for London.

Write a Bluesky post (max 250 chars). This is the official UK weather service's global ensemble model.

STYLE:
- Start with "MOGREPS:" to identify this tracker
- Note any significant changes from last run
- If trend is persisting across multiple runs, mention it
- If ensemble agreement is notable (tight or wide spread), mention it briefly
- Mention timing if confidence is relevant
- Keep it brief and factual

ANALYSIS CONTEXT:
{full_context}

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
        return f"MOGREPS: Ensemble mean reaches {cold_info['temp']}C at 850hPa around {cold_info['date']}.", True
    elif run_diff:
        return f"MOGREPS: Model shifted {abs(run_diff['shift'])}C {run_diff['direction']} since last run.", True
    else:
        return "MOGREPS: No significant changes in latest run.", True


def generate_chart(data: dict, chart_path: Path) -> bool:
    """Generate MOGREPS ensemble chart."""
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
        mean_temps = current.get("mean", [])
        min_temps = current.get("min", [])
        max_temps = current.get("max", [])

        if not timestamps or not mean_temps:
            return False

        # Parse dates
        dates = [datetime.fromisoformat(t.replace('Z', '+00:00')) for t in timestamps]

        # Convert None to NaN for matplotlib
        import numpy as np
        mean_arr = np.array([float(x) if x is not None else np.nan for x in mean_temps])
        min_arr = np.array([float(x) if x is not None else np.nan for x in min_temps]) if min_temps else None
        max_arr = np.array([float(x) if x is not None else np.nan for x in max_temps]) if max_temps else None

        # Create plot
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot spread
        if min_arr is not None and max_arr is not None:
            ax.fill_between(dates, min_arr, max_arr, alpha=0.3, color='#ff9f43', label='MOGREPS spread')

        # Plot mean
        ax.plot(dates, mean_arr, color='#ff9f43', linewidth=2, label='MOGREPS mean')

        # Threshold lines
        ax.axhline(y=COLD_THRESHOLD, color='blue', linestyle='--', alpha=0.5, linewidth=1)
        ax.axhline(y=0, color='white', linestyle='-', alpha=0.3, linewidth=1)

        # Labels
        ax.text(dates[-1], COLD_THRESHOLD, f' {COLD_THRESHOLD}C', color='blue', alpha=0.7, va='center', fontsize=9)

        # Title with date
        fetched_at = current.get("fetched_at", runs[0].get("fetched_at", ""))
        run_label = current.get("run_hour", "")
        if run_label:
            run_label = f"{run_label}z"
        try:
            dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
            date_str = dt.strftime('%d %b')
            title = f'London 850hPa - MOGREPS-G Ensemble ({date_str} {run_label})'
        except:
            title = f'London 850hPa - MOGREPS-G Ensemble ({run_label})'

        ax.set_title(title, fontsize=14)
        ax.set_xlabel('Date (UTC)', fontsize=12)
        ax.set_ylabel('850hPa Temperature (C)', fontsize=12)
        ax.legend(loc='upper right', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        fig.autofmt_xdate()

        # Watermark
        fig.text(0.99, 0.01, 'WXD MOGREPS Tracker | wxd-london.bsky.social',
                fontsize=8, color='gray', alpha=0.6, ha='right', va='bottom')

        plt.tight_layout()
        plt.savefig(chart_path, dpi=150, facecolor='#1a1a2e')
        plt.close()

        print(f"  Chart saved: {chart_path.name}")
        return True

    except Exception as e:
        print(f"  Chart error: {e}")
        return False


def post_to_bluesky(text: str, image_path: Path = None, reply_to: dict = None,
                    root_post: dict = None, handle: str = None, password: str = None) -> dict:
    """Post to Bluesky with optional threading support.

    Args:
        text: Post text
        image_path: Optional image to attach
        reply_to: Optional dict with 'uri' and 'cid' to reply to (for threading)
        root_post: Optional dict with 'uri' and 'cid' of thread root (for multi-level threads)
        handle: Bluesky handle
        password: App password

    Returns:
        dict with 'uri' and 'cid' of posted message, or None on failure
    """
    if not HAS_ATPROTO or not handle or not password:
        return None

    try:
        client = Client()
        client.login(handle, password)

        # Build reply reference if threading
        reply_ref = None
        if reply_to and reply_to.get('uri') and reply_to.get('cid'):
            # Use root_post if provided, otherwise reply_to is both parent and root
            root = root_post if root_post else reply_to

            # Create StrongRef objects manually for robust threading
            parent_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
                uri=reply_to['uri'],
                cid=reply_to['cid']
            )
            root_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
                uri=root['uri'],
                cid=root['cid']
            )
            reply_ref = atproto_models.AppBskyFeedPost.ReplyRef(
                parent=parent_ref,
                root=root_ref
            )

        if image_path and image_path.exists():
            with open(image_path, 'rb') as f:
                img_data = f.read()
            upload = client.upload_blob(img_data)
            embed = atproto_models.AppBskyEmbedImages.Main(
                images=[atproto_models.AppBskyEmbedImages.Image(
                    alt="MOGREPS ensemble 850hPa temperature forecast",
                    image=upload.blob
                )]
            )
            response = client.send_post(text=text, embed=embed, reply_to=reply_ref)
        else:
            response = client.send_post(text=text, reply_to=reply_ref)

        return {"uri": response.uri, "cid": response.cid}

    except Exception as e:
        print(f"  Bluesky error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='WXD MOGREPS Tracker - Analysis & Posting')
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

    print(f"WXD MOGREPS Tracker - {utcnow().isoformat()}")
    if dry_run:
        print("DRY RUN MODE - will NOT post")
    print()

    # Load alert state
    alert_state = load_alert_state(state_path)

    # Handle intro message
    if args.intro and not alert_state.get("intro_posted"):
        intro_msg = """Introducing WXD MOGREPS Tracker

Now tracking the UK Met Office Global Ensemble (18 members) for London 850hPa.

MOGREPS runs 4x daily. Posts tagged "MOGREPS:" as UK ensemble benchmark."""

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
        run_hour = runs[0].get("run_hour", "?")
        print(f"Data: fetched {fetched_at[:19]}Z, {run_hour}z")

    # Run full analysis with shared module
    print("Running full analysis...")
    trend_state_path = data_dir / "trend_state.json"
    run_diff, cold_info, trend_analysis, percentile_analysis, timing_analysis, full_context = \
        run_full_analysis(data, trend_state_path, is_ensemble=True)

    if run_diff:
        print(f"  Shift: {run_diff['shift']}C {run_diff['direction']}")
    else:
        print("  No significant shift")

    if cold_info:
        print(f"  Cold signal: {cold_info['temp']}C on {cold_info['date']}")
    else:
        print("  No cold signal")

    if trend_analysis.get("cold_persistence", 0) >= 2:
        print(f"  Trend: Cold persisting for {trend_analysis['cold_persistence']} runs")

    if percentile_analysis.get("agreement_level"):
        print(f"  Agreement: {percentile_analysis['agreement_level']} ({percentile_analysis.get('spread_at_coldest', '?')}C spread)")

    # Generate chart
    print("Generating chart...")
    chart_ok = generate_chart(data, chart_path)

    # Get commentary with enriched context
    print("Generating commentary...")
    text, is_fallback = get_claude_commentary(history_path, full_context, run_diff, cold_info)
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
