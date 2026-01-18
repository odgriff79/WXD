#!/usr/bin/env python3
"""
WXD Tracker B - ICON Ensemble Analysis & Posting

Single-model tracker for ICON EPS (40 members).
Runs 4x daily: 04:00, 10:00, 16:00, 22:00 UTC

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
from shared.commentary import (
    generate_full_thread, post_thread_to_bluesky
)



def get_run_label(fetched_at: str) -> str:
    """Determine which model run this fetch captures."""
    try:
        dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
        hour = dt.hour
        if 3 <= hour < 9:
            return "00z"
        elif 9 <= hour < 15:
            return "06z"
        elif 15 <= hour < 21:
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




def generate_chart(data: dict, chart_path: Path) -> bool:
    """Generate ICON ensemble chart with run-to-run progression overlay."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime
        import numpy as np

        runs = data.get("runs", [])
        if not runs:
            return False

        current = runs[0]
        timestamps = current.get("timestamps", [])
        mean_temps = current.get("mean", [])

        if not timestamps or not mean_temps:
            return False

        # Create plot
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6))

        # Color palette for runs (newest to oldest)
        run_colors = ['cyan', '#00b3b3', '#008080', '#006666', '#004d4d', '#003333']
        max_runs_to_show = min(len(runs), 6)

        # Plot older runs first (so current is on top)
        for i in range(max_runs_to_show - 1, -1, -1):
            run = runs[i]
            ts = run.get("timestamps", [])
            mean_vals = run.get("mean", [])
            min_vals = run.get("min", [])
            max_vals = run.get("max", [])

            if not ts or not mean_vals:
                continue

            # Parse dates
            dates = [datetime.fromisoformat(t.replace('Z', '+00:00')) for t in ts]
            mean_arr = np.array([float(x) if x is not None else np.nan for x in mean_vals])

            # Get run label for legend
            fetched_at = run.get("fetched_at", "")
            run_label = get_run_label(fetched_at)
            try:
                dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
                label = f"{dt.strftime('%d %b')} {run_label}"
            except:
                label = run_label or f"Run {i+1}"

            color = run_colors[min(i, len(run_colors)-1)]

            if i == 0:
                # Current run - show spread and mean prominently
                if min_vals and max_vals:
                    min_arr = np.array([float(x) if x is not None else np.nan for x in min_vals])
                    max_arr = np.array([float(x) if x is not None else np.nan for x in max_vals])
                    ax.fill_between(dates, min_arr, max_arr, alpha=0.3, color=color, label='ICON spread')
                ax.plot(dates, mean_arr, color=color, linewidth=2.5,
                       label=f"{label} (latest)", marker='o', markersize=4, zorder=10)
            else:
                # Previous runs - thinner, faded, dashed
                alpha = 0.7 - (i * 0.1)
                alpha = max(alpha, 0.3)
                ax.plot(dates, mean_arr, color=color, linewidth=1.5,
                       label=label, linestyle='--', alpha=alpha, zorder=5-i)

        # Threshold lines
        ax.axhline(y=COLD_THRESHOLD, color='blue', linestyle='--', alpha=0.5, linewidth=1)
        ax.axhline(y=0, color='white', linestyle='-', alpha=0.3, linewidth=1)

        # Labels
        dates = [datetime.fromisoformat(t.replace('Z', '+00:00')) for t in timestamps]
        ax.text(dates[-1], COLD_THRESHOLD, f' {COLD_THRESHOLD}C', color='blue', alpha=0.7, va='center', fontsize=9)

        # Title
        fetched_at = current.get("fetched_at", "")
        run_label = get_run_label(fetched_at)
        try:
            dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
            date_str = dt.strftime('%d %b')
            title = f'London 850hPa - ICON Run Progression ({date_str} {run_label} latest)'
        except:
            title = f'London 850hPa - ICON Run Progression'

        ax.set_title(title, fontsize=14)
        ax.set_xlabel('Date (UTC)', fontsize=12)
        ax.set_ylabel('850hPa Temperature (C)', fontsize=12)
        ax.legend(loc='upper right', fontsize=9, framealpha=0.8)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        fig.autofmt_xdate()

        # Watermark
        fig.text(0.99, 0.01, 'WXD ICON Tracker | wxd-london.bsky.social',
                fontsize=8, color='gray', alpha=0.6, ha='right', va='bottom')

        plt.tight_layout()
        plt.savefig(chart_path, dpi=150, facecolor='#1a1a2e')
        plt.close()

        print(f"  Chart saved: {chart_path.name} ({max_runs_to_show} runs)")
        return True

    except Exception as e:
        print(f"  Chart error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='WXD ICON Tracker - Analysis & Posting')
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

    print(f"WXD ICON Tracker - {utcnow().isoformat()}")
    if dry_run:
        print("DRY RUN MODE - will NOT post")
    print()

    # Load alert state
    alert_state = load_alert_state(state_path)

    # Handle intro message
    if args.intro and not alert_state.get("intro_posted"):
        intro_msg = """Introducing WXD ICON Tracker

Now tracking the German ICON ensemble (40 members) for London 850hPa.

ICON runs 2x daily (00z/12z). Threaded posts with chart and alerts when significant."""

        print("Posting introduction message...")
        if not dry_run:
            success = post_thread_to_bluesky(
                posts=[intro_msg],
                handle=bsky_handle,
                password=bsky_password,
                tracker='ICON',
                model='icon-eu-eps'
            )
            if success:
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
        run_label = get_run_label(fetched_at)
        print(f"Data: fetched {fetched_at[:19]}Z, {run_label}")

    # Run full analysis with shared module
    print("Running full analysis...")
    trend_state_path = data_dir / "trend_state.json"
    run_diff, cold_info, trend_analysis, percentile_analysis, timing_analysis, period_analysis, full_context = \
        run_full_analysis(data, trend_state_path, is_ensemble=True)

    # Load previous post for narrative continuity
    previous_post = None
    if trend_state_path.exists():
        try:
            with open(trend_state_path, 'r') as f:
                trend_state = json.load(f)
                previous_post = trend_state.get('last_posted_commentary')
                if previous_post:
                    print(f"  Previous post loaded ({len(previous_post)} chars)")
        except:
            pass

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

    # Generate full thread with shared module (story-first, threading, alerts)
    print("Generating commentary thread...")
    posts, is_fallback = generate_full_thread(
        model_name="ICON",
        full_context=full_context,
        cold_info=cold_info,
        trend_analysis=trend_analysis,
        percentile_analysis=percentile_analysis,
        run_diff=run_diff,
        is_ensemble=True,
        previous_post=previous_post
    )

    print(f"  Generated {len(posts)} posts:")
    for i, post in enumerate(posts):
        print(f"    [{i+1}] ({len(post)} chars): {post[:80]}...")

    if dry_run:
        print()
        print("=" * 50)
        print("PREVIEW (not posting):")
        for i, post in enumerate(posts):
            print(f"\n--- Post {i+1} ---")
            print(post)
        print("=" * 50)
        return 0

    # Post thread
    print()
    print("Posting thread to Bluesky...")
    success = post_thread_to_bluesky(
        posts=posts,
        image_path=str(chart_path) if chart_ok else None,
        handle=bsky_handle,
        password=bsky_password,
        alt_text="ICON ensemble 850hPa temperature forecast",
        tracker='ICON',
        model='icon-eu-eps'
    )

    if success:
        print("  Thread posted successfully")
        save_alert_state(state_path, alert_state)
        # Save main commentary for narrative continuity (first post without thread numbering)
        main_commentary = posts[0] if posts else ""
        # Strip thread numbering [1/X] prefix if present
        if main_commentary.startswith('['):
            bracket_end = main_commentary.find('] ')
            if bracket_end > 0:
                main_commentary = main_commentary[bracket_end + 2:]
        try:
            with open(trend_state_path, 'r') as f:
                trend_state = json.load(f)
            trend_state['last_posted_commentary'] = main_commentary
            with open(trend_state_path, 'w') as f:
                json.dump(trend_state, f, indent=2)
            print(f"  Saved commentary for next run ({len(main_commentary)} chars)")
        except Exception as e:
            print(f"  Warning: Could not save commentary: {e}")
        # Sync charts to GitHub Pages
        print("  Syncing charts to GitHub...")
        try:
            subprocess.run(["/home/ubuntu/wxd/sync_charts.sh"], check=False, capture_output=True)
            print("  Chart sync complete")
        except Exception as e:
            print(f"  Chart sync failed: {e}")
    else:
        print("  Failed to post thread")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
