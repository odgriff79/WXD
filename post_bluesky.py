#!/usr/bin/env python3
"""
WXD Bluesky Poster - Generates AI commentary and posts to Bluesky.

Reads history_compact.json, analyzes run-to-run changes, generates
confidence indicators, triggers threshold alerts, and posts to Bluesky.
"""

import json
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

# Try imports - will fail gracefully if not installed
try:
    import matplotlib
    matplotlib.use('Agg')  # Headless
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from atproto import Client
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False


# Thresholds
COLD_THRESHOLD = -5.0  # Cold alert threshold
EXTREME_COLD_THRESHOLD = -8.0  # Extreme cold threshold
WARM_THRESHOLD = 10.0  # Warm threshold (summer)
RUN_DIFF_THRESHOLD = 2.0  # Flag if model shifts more than this
MODEL_DIVERGENCE_THRESHOLD = 4.0  # Inter-model disagreement threshold
HYSTERESIS_RUNS = 2  # Must appear in N consecutive runs to trigger


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_alert_state(state_path: Path) -> dict:
    """Load alert state for hysteresis tracking."""
    if state_path.exists():
        try:
            with open(state_path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        'cold_count': 0,
        'extreme_cold_count': 0,
        'warm_count': 0,
        'last_cold_alert': None,
        'last_extreme_cold_alert': None,
        'last_warm_alert': None
    }


def save_alert_state(state_path: Path, state: dict) -> None:
    """Save alert state for hysteresis tracking."""
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


def analyze_run_diff(data: dict) -> list:
    """Compare current run vs previous run, return significant shifts."""
    runs = data.get('runs', [])
    if len(runs) < 2:
        return []

    current = runs[0]
    previous = runs[1]

    diffs = []
    current_ts = current.get('timestamps', [])
    previous_ts = previous.get('timestamps', [])

    # Find common timestamps
    common_ts = set(current_ts) & set(previous_ts)

    for model_key in current.get('models', {}).keys():
        curr_model = current['models'].get(model_key, {})
        prev_model = previous.get('models', {}).get(model_key, {})

        if not curr_model or not prev_model:
            continue

        curr_means = curr_model.get('mean', [])
        prev_means = prev_model.get('mean', [])

        for ts in common_ts:
            try:
                curr_idx = current_ts.index(ts)
                prev_idx = previous_ts.index(ts)

                if curr_idx < len(curr_means) and prev_idx < len(prev_means):
                    curr_val = curr_means[curr_idx]
                    prev_val = prev_means[prev_idx]

                    if curr_val is not None and prev_val is not None:
                        diff = curr_val - prev_val
                        if abs(diff) >= RUN_DIFF_THRESHOLD:
                            diffs.append({
                                'model': model_key.upper().replace('_', ' '),
                                'timestamp': ts,
                                'diff': round(diff, 1),
                                'direction': 'warmed' if diff > 0 else 'cooled'
                            })
            except (ValueError, IndexError):
                continue

    # Sort by absolute diff, return top 3
    diffs.sort(key=lambda x: abs(x['diff']), reverse=True)
    return diffs[:3]


def check_cold_threshold(data: dict) -> dict:
    """Check if any model hits cold threshold, return details."""
    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    models = current.get('models', {})
    timestamps = current.get('timestamps', [])

    coldest = {'temp': 999, 'model': None, 'date': None}
    extreme_cold = False

    for model_key, model_data in models.items():
        means = model_data.get('mean', [])
        for i, val in enumerate(means):
            if val is not None and val < coldest['temp']:
                coldest['temp'] = val
                coldest['model'] = model_key.upper().replace('_', ' ')
                if i < len(timestamps):
                    coldest['date'] = timestamps[i][:10]  # Just date

    if coldest['temp'] <= EXTREME_COLD_THRESHOLD:
        extreme_cold = True

    if coldest['temp'] <= COLD_THRESHOLD:
        return {
            'temp': round(coldest['temp'], 1),
            'model': coldest['model'],
            'date': coldest['date'],
            'extreme': extreme_cold
        }

    return None


def calculate_confidence(data: dict) -> str:
    """Calculate confidence indicator based on model agreement and spread."""
    runs = data.get('runs', [])
    if not runs:
        return '⚠️ Confidence: medium'

    current = runs[0]
    models = current.get('models', {})

    if len(models) < 2:
        return '⚠️ Confidence: medium'

    # Calculate inter-model disagreement at each timestep
    max_disagreements = []
    max_spreads = []

    timestamps = current.get('timestamps', [])
    num_ts = len(timestamps)

    for i in range(num_ts):
        model_means = []
        spreads = []

        for model_data in models.values():
            means = model_data.get('mean', [])
            spread = model_data.get('spread', [])

            if i < len(means) and means[i] is not None:
                model_means.append(means[i])
            if i < len(spread) and spread[i] is not None:
                spreads.append(spread[i])

        if len(model_means) >= 2:
            max_disagreements.append(max(model_means) - min(model_means))
        if spreads:
            max_spreads.append(max(spreads))

    if not max_disagreements:
        return '⚠️ Confidence: medium'

    # Use 75th percentile of disagreement and spread
    max_disagreements.sort()
    max_spreads.sort()

    p75_disagree = max_disagreements[int(len(max_disagreements) * 0.75)] if max_disagreements else 0
    p75_spread = max_spreads[int(len(max_spreads) * 0.75)] if max_spreads else 0

    # High confidence: models agree within 2C, low spread
    if p75_disagree <= 2.0 and p75_spread <= 8.0:
        return '✅ Confidence: high'
    # Low confidence: major disagreement or very high spread
    elif p75_disagree > MODEL_DIVERGENCE_THRESHOLD or p75_spread > 15.0:
        return '❓ Confidence: low'
    else:
        return '⚠️ Confidence: medium'


def format_run_diff_text(diffs: list) -> str:
    """Format run-to-run diffs for inclusion in post."""
    if not diffs:
        return ""

    # Just use the biggest shift
    d = diffs[0]
    return f"{d['model']} {d['direction']} {abs(d['diff'])}°C since last run"


def get_claude_commentary(data_path: Path, run_diff_text: str, confidence: str) -> str:
    """Pipe JSON to Claude CLI and get commentary."""
    extra_context = ""
    if run_diff_text:
        extra_context += f"\n\nNOTE: {run_diff_text}"
    extra_context += f"\n\nConfidence indicator to append: {confidence}"

    prompt = f"""You are WXD, a weather ensemble analysis bot. Analyse this 4-model ensemble 850hPa temperature data for London.

Write a Bluesky post (max 250 chars to leave room for confidence indicator):
- Lead with the key finding (cold/warm signal, timing)
- Note model agreement or disagreement
- Keep it punchy and informative
- No hashtags, no emojis (confidence emoji added separately)
- Use °C for temperatures
{extra_context}

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
            text = result.stdout.strip()
            # Truncate to 270 chars to leave room for confidence
            if len(text) > 270:
                text = text[:267] + "..."
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

        # Model colors and labels
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

        # Plot min/max shading for each model (faint)
        for model_key, model_data in models.items():
            mins = model_data.get('min', [])
            maxs = model_data.get('max', [])
            if mins and maxs and len(mins) == len(maxs):
                ax.fill_between(
                    dates[:len(mins)], mins, maxs,
                    color=colors.get(model_key, 'white'),
                    alpha=0.1
                )

        # Plot mean lines for each model
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

        # Threshold lines
        ax.axhline(y=0, color='cyan', linestyle=':', alpha=0.5, linewidth=1)
        ax.axhline(y=COLD_THRESHOLD, color='cyan', linestyle='--', alpha=0.7, linewidth=1.5)
        ax.axhline(y=WARM_THRESHOLD, color='orange', linestyle='--', alpha=0.7, linewidth=1.5)

        # Add threshold labels on right side
        ax.text(dates[-1], COLD_THRESHOLD, f' {COLD_THRESHOLD}°C',
                color='cyan', alpha=0.7, va='center', fontsize=9)
        ax.text(dates[-1], WARM_THRESHOLD, f' {WARM_THRESHOLD}°C',
                color='orange', alpha=0.7, va='center', fontsize=9)

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

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, facecolor='#1a1a2e')
        plt.close()

        print(f"Chart saved: {output_path}")
        return True

    except Exception as e:
        print(f"Error generating chart: {e}")
        import traceback
        traceback.print_exc()
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
    state_path = data_dir / "alert_state.json"

    # Check for credentials in environment
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    print(f"WXD Bluesky Poster - {utcnow().isoformat()}")
    print()

    # Check data exists
    if not data_path.exists():
        print(f"ERROR: {data_path} not found. Run fetch.py first.")
        return 1

    # Load data
    with open(data_path, 'r') as f:
        data = json.load(f)

    # Load alert state
    alert_state = load_alert_state(state_path)

    # Analyze run-to-run differences
    print("Analyzing run-to-run changes...")
    run_diffs = analyze_run_diff(data)
    run_diff_text = format_run_diff_text(run_diffs)
    if run_diffs:
        print(f"  Significant shifts: {run_diff_text}")
    else:
        print("  No significant shifts detected")

    # Calculate confidence
    print("Calculating confidence...")
    confidence = calculate_confidence(data)
    print(f"  Confidence: {confidence}")

    # Check cold thresholds
    print("Checking cold thresholds...")
    cold_info = check_cold_threshold(data)
    cold_alert = None

    if cold_info:
        print(f"  Cold signal: {cold_info['temp']}°C ({cold_info['model']}) on {cold_info['date']}")

        if cold_info['extreme']:
            alert_state['extreme_cold_count'] += 1
            if alert_state['extreme_cold_count'] >= HYSTERESIS_RUNS:
                cold_alert = {
                    'type': 'extreme',
                    'temp': cold_info['temp'],
                    'model': cold_info['model'],
                    'date': cold_info['date']
                }
                print(f"  EXTREME COLD ALERT triggered (count: {alert_state['extreme_cold_count']})")
        else:
            alert_state['extreme_cold_count'] = 0

        alert_state['cold_count'] += 1
        if alert_state['cold_count'] >= HYSTERESIS_RUNS and not cold_alert:
            cold_alert = {
                'type': 'cold',
                'temp': cold_info['temp'],
                'model': cold_info['model'],
                'date': cold_info['date']
            }
            print(f"  COLD ALERT triggered (count: {alert_state['cold_count']})")
    else:
        print("  No cold signal")
        # Reset counts after 2 runs without threshold
        if alert_state['cold_count'] > 0:
            alert_state['cold_count'] -= 1
        if alert_state['extreme_cold_count'] > 0:
            alert_state['extreme_cold_count'] -= 1

    # Save alert state
    save_alert_state(state_path, alert_state)
    print()

    # Generate main commentary
    print("Generating AI commentary...")
    text = get_claude_commentary(data_path, run_diff_text, confidence)
    if not text:
        print("ERROR: Failed to generate commentary")
        return 1

    # Append confidence indicator
    main_text = f"{text} {confidence}"
    print(f"Main post ({len(main_text)} chars):")
    print(f"  {main_text}")
    print()

    # Generate chart
    print("Generating chart...")
    chart_ok = generate_chart(data_path, chart_path)
    print()

    # Post to Bluesky
    if bsky_handle and bsky_password:
        # Post main update
        print("Posting main update to Bluesky...")
        image = chart_path if chart_ok else None
        post_ok = post_to_bluesky(main_text, image, bsky_handle, bsky_password)
        if not post_ok:
            return 1

        # Post cold alert if triggered
        if cold_alert:
            if cold_alert['type'] == 'extreme':
                alert_text = f"⚠️ Extreme cold signal: {cold_alert['model']} showing {cold_alert['temp']}°C at 850hPa for {cold_alert['date']}. Significant snow/ice risk for UK if verified."
            else:
                alert_text = f"❄️ Cold signal: {cold_alert['model']} showing {cold_alert['temp']}°C at 850hPa for {cold_alert['date']}. Elevated snow risk for UK uplands."

            print(f"Posting cold alert ({len(alert_text)} chars):")
            print(f"  {alert_text}")
            post_to_bluesky(alert_text, None, bsky_handle, bsky_password)
    else:
        print("BSKY_HANDLE and BSKY_PASSWORD not set, skipping post")
        print("Set these environment variables to enable posting")

    print()
    print("Complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
