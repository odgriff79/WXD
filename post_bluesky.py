#!/usr/bin/env python3
"""
WXD Bluesky Poster - Generates AI commentary and posts to Bluesky.

Reads history_compact.json, analyzes run-to-run changes, generates
confidence indicators, triggers threshold alerts, and posts to Bluesky.

Usage:
    python post_bluesky.py                      # Normal post with chart
    python post_bluesky.py --changelog "msg"    # Post manual changelog
    python post_bluesky.py --weekly             # Post weekly git changelog (auto)
"""

import argparse
import json
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from collections import defaultdict

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

# Model display names (for posts and alerts)
MODEL_NAMES = {
    'gfs': 'GFS',
    'ecmwf_ifs': 'ECM',
    'ecmwf_aifs': 'AIFS',
    'gem': 'GEM'
}


def format_model_name(model_key: str) -> str:
    """Format model key for display in posts."""
    return MODEL_NAMES.get(model_key, model_key.upper().replace('_', ' '))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_run_label(fetched_at: str) -> str:
    """Determine which model run this fetch captures (00z or 12z)."""
    try:
        dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
        hour = dt.hour
        # 09:00 UTC fetch captures 00z run, 21:00 UTC captures 12z run
        if 6 <= hour < 18:
            return "00z run"
        else:
            return "12z run"
    except Exception:
        return ""


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
                                'model': format_model_name(model_key),
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
                coldest['model'] = format_model_name(model_key)
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


def check_model_divergence(data: dict) -> dict:
    """Check for strong model disagreement (>4°C) at any forecast time."""
    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    models = current.get('models', {})
    timestamps = current.get('timestamps', [])

    if len(models) < 2:
        return None

    max_divergence = {'diff': 0, 'date': None, 'models': []}

    for i, ts in enumerate(timestamps):
        model_means = {}
        for model_key, model_data in models.items():
            means = model_data.get('mean', [])
            if i < len(means) and means[i] is not None:
                model_means[model_key] = means[i]

        if len(model_means) >= 2:
            sorted_models = sorted(model_means.items(), key=lambda x: x[1])
            coldest = sorted_models[0]
            warmest = sorted_models[-1]
            diff = warmest[1] - coldest[1]

            if diff > max_divergence['diff']:
                max_divergence = {
                    'diff': round(diff, 1),
                    'date': ts[:10],
                    'coldest': format_model_name(coldest[0]),
                    'warmest': format_model_name(warmest[0]),
                    'coldest_temp': round(coldest[1], 1),
                    'warmest_temp': round(warmest[1], 1)
                }

    if max_divergence['diff'] > MODEL_DIVERGENCE_THRESHOLD:
        return max_divergence

    return None


def check_rapid_swing(data: dict) -> dict:
    """Check for rapid temperature swing (≥6°C change in 48h window).

    Only considers FUTURE swings (start_date >= today) to avoid
    narrating past weather events. Historical data is for run-to-run
    comparison, not for reporting what already happened.
    """
    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    mmm = current.get('multi_model_mean', [])
    timestamps = current.get('timestamps', [])

    if len(mmm) < 5 or len(timestamps) < 5:  # Need at least a few data points
        return None

    # Only look at future timestamps (>= today)
    today = utcnow().strftime('%Y-%m-%d')

    # Look for biggest 48h swing (4 x 12h intervals) in FUTURE only
    max_swing = {'swing': 0, 'start_date': None, 'end_date': None, 'direction': None}

    for i in range(len(mmm) - 4):
        start_date = timestamps[i][:10]
        # Skip historical swings - only report future forecast
        if start_date < today:
            continue
        if mmm[i] is not None and mmm[i + 4] is not None:
            swing = mmm[i + 4] - mmm[i]
            if abs(swing) > abs(max_swing['swing']):
                max_swing = {
                    'swing': round(swing, 1),
                    'start_date': start_date,
                    'end_date': timestamps[i + 4][:10],
                    'direction': 'warming' if swing > 0 else 'cooling'
                }

    if abs(max_swing['swing']) >= 6.0:
        return max_swing

    return None


def check_warm_threshold(data: dict) -> dict:
    """Check for warm threshold (+10°C/+15°C) - only active Apr-Sep."""
    # Check if we're in warm season
    now = utcnow()
    if now.month < 4 or now.month > 9:
        return None  # Only active Apr-Sep

    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    models = current.get('models', {})
    timestamps = current.get('timestamps', [])

    warmest = {'temp': -999, 'model': None, 'date': None}
    extreme_warm = False

    for model_key, model_data in models.items():
        means = model_data.get('mean', [])
        for i, val in enumerate(means):
            if val is not None and val > warmest['temp']:
                warmest['temp'] = val
                warmest['model'] = format_model_name(model_key)
                if i < len(timestamps):
                    warmest['date'] = timestamps[i][:10]

    if warmest['temp'] >= 15.0:
        extreme_warm = True

    if warmest['temp'] >= WARM_THRESHOLD:
        return {
            'temp': round(warmest['temp'], 1),
            'model': warmest['model'],
            'date': warmest['date'],
            'extreme': extreme_warm
        }

    return None


def analyze_percentile_framing(data_dir: Path) -> dict:
    """
    Count what % of ensemble members are below key thresholds.
    Reads raw model files to access individual members.
    Returns dict with model -> {timestamp -> pct_below_threshold}
    """
    results = {}
    thresholds = [COLD_THRESHOLD, EXTREME_COLD_THRESHOLD]  # -5, -8

    for model_key in ['gfs', 'ecmwf_ifs', 'ecmwf_aifs', 'gem']:
        model_path = data_dir / f"{model_key}_latest.json"
        if not model_path.exists():
            continue

        try:
            with open(model_path, 'r') as f:
                model_data = json.load(f)

            hourly = model_data.get('hourly', {})
            timestamps = hourly.get('time', [])

            # Find all member columns
            member_keys = [k for k in hourly.keys() if k.startswith('temperature_850hPa_member')]
            if not member_keys:
                continue

            model_results = {'timestamps': [], 'pct_below_cold': [], 'pct_below_extreme': []}

            for i, ts in enumerate(timestamps):
                values = []
                for key in member_keys:
                    if i < len(hourly[key]) and hourly[key][i] is not None:
                        values.append(hourly[key][i])

                if values:
                    pct_cold = round(100 * sum(1 for v in values if v < COLD_THRESHOLD) / len(values), 0)
                    pct_extreme = round(100 * sum(1 for v in values if v < EXTREME_COLD_THRESHOLD) / len(values), 0)
                    model_results['timestamps'].append(ts)
                    model_results['pct_below_cold'].append(pct_cold)
                    model_results['pct_below_extreme'].append(pct_extreme)

            results[model_key] = model_results

        except Exception as e:
            print(f"  Percentile error for {model_key}: {e}")
            continue

    return results


def find_peak_percentile(percentile_data: dict) -> dict:
    """Find the peak percentile (most members below threshold) across all models."""
    peak = {'model': None, 'date': None, 'pct': 0, 'threshold': 'cold'}

    for model_key, data in percentile_data.items():
        timestamps = data.get('timestamps', [])
        pct_cold = data.get('pct_below_cold', [])
        pct_extreme = data.get('pct_below_extreme', [])

        for i, ts in enumerate(timestamps):
            # Check extreme first
            if i < len(pct_extreme) and pct_extreme[i] > peak['pct']:
                peak = {
                    'model': format_model_name(model_key),
                    'date': ts[:10],
                    'pct': pct_extreme[i],
                    'threshold': 'extreme'
                }
            # Then cold (only if no extreme is higher)
            elif i < len(pct_cold) and pct_cold[i] > peak['pct']:
                peak = {
                    'model': format_model_name(model_key),
                    'date': ts[:10],
                    'pct': pct_cold[i],
                    'threshold': 'cold'
                }

    # Only return if significant (>20% of members)
    if peak['pct'] >= 20:
        return peak
    return None


def detect_bimodal_distribution(data_dir: Path) -> dict:
    """
    Detect if ensemble shows bimodal split (2 distinct temperature clusters).
    Simple approach: check if there's a gap in the distribution.
    """
    results = {}

    for model_key in ['gfs', 'ecmwf_ifs', 'ecmwf_aifs', 'gem']:
        model_path = data_dir / f"{model_key}_latest.json"
        if not model_path.exists():
            continue

        try:
            with open(model_path, 'r') as f:
                model_data = json.load(f)

            hourly = model_data.get('hourly', {})
            timestamps = hourly.get('time', [])

            member_keys = [k for k in hourly.keys() if k.startswith('temperature_850hPa_member')]
            if len(member_keys) < 10:  # Need enough members for meaningful split
                continue

            # Check each timestamp for bimodal distribution
            for i, ts in enumerate(timestamps):
                values = []
                for key in member_keys:
                    if i < len(hourly[key]) and hourly[key][i] is not None:
                        values.append(hourly[key][i])

                if len(values) < 10:
                    continue

                # Sort values and look for gap
                sorted_vals = sorted(values)
                n = len(sorted_vals)

                # Find largest gap in distribution
                max_gap = 0
                gap_idx = 0
                for j in range(1, n):
                    gap = sorted_vals[j] - sorted_vals[j-1]
                    if gap > max_gap:
                        max_gap = gap
                        gap_idx = j

                # Bimodal if gap > 3°C and both clusters have meaningful membership (>25%)
                if max_gap >= 3.0:
                    cold_cluster = sorted_vals[:gap_idx]
                    warm_cluster = sorted_vals[gap_idx:]

                    cold_pct = round(100 * len(cold_cluster) / n)
                    warm_pct = round(100 * len(warm_cluster) / n)

                    # Both clusters need at least 25% of members
                    if cold_pct >= 25 and warm_pct >= 25:
                        cold_mean = round(mean(cold_cluster), 1)
                        warm_mean = round(mean(warm_cluster), 1)

                        results[model_key] = {
                            'timestamp': ts,
                            'date': ts[:10],
                            'cold_pct': cold_pct,
                            'warm_pct': warm_pct,
                            'cold_mean': cold_mean,
                            'warm_mean': warm_mean,
                            'gap': round(max_gap, 1)
                        }
                        break  # Take first significant bimodal instance

        except Exception as e:
            print(f"  Bimodal error for {model_key}: {e}")
            continue

    return results


def track_trend_persistence(data: dict, alert_state: dict) -> dict:
    """
    Track how many consecutive runs a cold/warm signal has appeared.
    Updates alert_state and returns persistence info for Claude.
    """
    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    mmm = current.get('multi_model_mean', [])

    if not mmm:
        return None

    # Find minimum multi-model mean (coldest point in forecast)
    valid_mmm = [v for v in mmm if v is not None]
    if not valid_mmm:
        return None

    min_temp = min(valid_mmm)
    max_temp = max(valid_mmm)

    # Determine current signal type
    current_signal = None
    if min_temp < COLD_THRESHOLD:
        current_signal = 'cold'
    elif max_temp > WARM_THRESHOLD:
        current_signal = 'warm'

    # Get previous persistence state
    prev_signal = alert_state.get('trend_signal', None)
    prev_count = alert_state.get('trend_run_count', 0)
    prev_strength = alert_state.get('trend_strength', None)  # min_temp of previous run

    # Calculate current strength (how far below/above threshold)
    if current_signal == 'cold':
        current_strength = min_temp
    elif current_signal == 'warm':
        current_strength = max_temp
    else:
        current_strength = None

    result = None

    if current_signal:
        if current_signal == prev_signal:
            # Signal persists - increment count
            new_count = prev_count + 1

            # Determine if strengthening or weakening
            if prev_strength is not None and current_strength is not None:
                if current_signal == 'cold':
                    trend = 'strengthening' if current_strength < prev_strength else 'weakening'
                else:  # warm
                    trend = 'strengthening' if current_strength > prev_strength else 'weakening'
            else:
                trend = 'steady'

            result = {
                'signal': current_signal,
                'run_count': new_count,
                'trend': trend,
                'strength': current_strength
            }

            # Update state
            alert_state['trend_run_count'] = new_count
            alert_state['trend_strength'] = current_strength
        else:
            # New signal or signal changed
            result = {
                'signal': current_signal,
                'run_count': 1,
                'trend': 'new',
                'strength': current_strength
            }

            alert_state['trend_signal'] = current_signal
            alert_state['trend_run_count'] = 1
            alert_state['trend_strength'] = current_strength
    else:
        # No signal - reset
        if prev_signal:
            result = {
                'signal': 'neutral',
                'run_count': 0,
                'trend': 'cleared',
                'prev_signal': prev_signal
            }
        alert_state['trend_signal'] = None
        alert_state['trend_run_count'] = 0
        alert_state['trend_strength'] = None

    return result


def calculate_timing_uncertainty(data: dict) -> dict:
    """
    When models agree on event but disagree on timing.
    Find when each model first crosses threshold and calculate spread.
    """
    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    models = current.get('models', {})
    timestamps = current.get('timestamps', [])

    if len(models) < 2 or not timestamps:
        return None

    # Find when each model first crosses cold threshold
    cold_crossings = {}

    for model_key, model_data in models.items():
        means = model_data.get('mean', [])
        for i, val in enumerate(means):
            if val is not None and val < COLD_THRESHOLD:
                if i < len(timestamps):
                    cold_crossings[model_key] = {
                        'timestamp': timestamps[i],
                        'index': i,
                        'temp': val
                    }
                break

    # Need at least 2 models to cross for comparison
    if len(cold_crossings) < 2:
        return None

    # Calculate timing spread
    indices = [v['index'] for v in cold_crossings.values()]
    min_idx = min(indices)
    max_idx = max(indices)

    # Each index is 12 hours (compact history uses 12-hourly data)
    spread_hours = (max_idx - min_idx) * 12

    # Only report if spread > 24 hours
    if spread_hours <= 24:
        return None

    # Find earliest and latest crossing
    earliest = min(cold_crossings.items(), key=lambda x: x[1]['index'])
    latest = max(cold_crossings.items(), key=lambda x: x[1]['index'])

    # Calculate middle date
    earliest_ts = earliest[1]['timestamp']
    latest_ts = latest[1]['timestamp']

    try:
        earliest_dt = datetime.fromisoformat(earliest_ts.replace('Z', '+00:00'))
        latest_dt = datetime.fromisoformat(latest_ts.replace('Z', '+00:00'))
        mid_dt = earliest_dt + (latest_dt - earliest_dt) / 2
        mid_date = mid_dt.strftime('%b %d')
    except:
        mid_date = earliest_ts[:10]

    spread_days = spread_hours / 24

    return {
        'event': 'cold',
        'threshold': COLD_THRESHOLD,
        'mid_date': mid_date,
        'spread_days': round(spread_days, 1),
        'earliest_model': format_model_name(earliest[0]),
        'earliest_date': earliest[1]['timestamp'][:10],
        'latest_model': format_model_name(latest[0]),
        'latest_date': latest[1]['timestamp'][:10],
        'models_crossing': len(cold_crossings),
        'models_total': len(models)
    }


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


def is_auth_error(stderr: str) -> bool:
    """Check if error is authentication related."""
    auth_keywords = ['unauthorized', 'login', 'authenticate', 'session expired',
                     'auth', 'token', 'credential', 'sign in', 'not logged in']
    stderr_lower = stderr.lower()
    return any(kw in stderr_lower for kw in auth_keywords)


def send_ntfy_alert(message: str) -> None:
    """Send push notification via ntfy.sh."""
    try:
        subprocess.run(
            ['curl', '-s', '-d', message, 'https://ntfy.sh/wxd-alerts'],
            timeout=10,
            capture_output=True
        )
        print(f"  Sent ntfy alert: {message}")
    except Exception as e:
        print(f"  Failed to send ntfy alert: {e}")


def generate_fallback_post(data: dict) -> str:
    """Generate basic auto-post when Claude CLI fails."""
    runs = data.get('runs', [])
    if not runs:
        return "London 850hPa update: Data available. Chart attached."

    current = runs[0]
    models = current.get('models', {})
    timestamps = current.get('timestamps', [])

    # Find coldest and warmest model predictions
    extremes = []
    for model_key, model_data in models.items():
        means = model_data.get('mean', [])
        if means:
            valid_means = [m for m in means if m is not None]
            if valid_means:
                extremes.append({
                    'model': format_model_name(model_key),
                    'min': min(valid_means),
                    'max': max(valid_means)
                })

    if not extremes:
        return "London 850hPa update: Data available. Chart attached."

    # Find overall coldest
    coldest = min(extremes, key=lambda x: x['min'])
    warmest = max(extremes, key=lambda x: x['max'])

    # Get forecast date range
    if timestamps:
        start_date = timestamps[0][:10]
        end_date = timestamps[-1][:10] if len(timestamps) > 1 else start_date
        date_range = f"{start_date} to {end_date}"
    else:
        date_range = "coming days"

    return f"London 850hPa update: {coldest['model']} coldest at {coldest['min']:.1f}°C, {warmest['model']} warmest at {warmest['max']:.1f}°C for {date_range}. Chart attached."


def format_analysis_context(run_diff_text: str, confidence: str,
                           percentile_info: dict, bimodal_info: dict,
                           persistence_info: dict, timing_info: dict) -> str:
    """Format all analysis results into context for Claude CLI prompt."""
    context_parts = []

    # Run-to-run shifts
    if run_diff_text:
        context_parts.append(f"RUN SHIFT: {run_diff_text}")

    # Percentile framing
    if percentile_info:
        threshold_name = "extreme cold (<-8°C)" if percentile_info['threshold'] == 'extreme' else "cold (<-5°C)"
        context_parts.append(
            f"PERCENTILE: {int(percentile_info['pct'])}% of {percentile_info['model']} members below {threshold_name} by {percentile_info['date']}"
        )

    # Bimodal detection
    if bimodal_info:
        # Pick most dramatic bimodal split
        for model, info in bimodal_info.items():
            model_name = format_model_name(model)
            context_parts.append(
                f"BIMODAL: {model_name} split - {info['cold_pct']}% cold scenario ({info['cold_mean']}°C) vs {info['warm_pct']}% mild ({info['warm_mean']}°C) for {info['date']}"
            )
            break  # Just report first/most significant

    # Trend persistence
    if persistence_info:
        signal = persistence_info.get('signal')
        run_count = persistence_info.get('run_count', 0)
        trend = persistence_info.get('trend', '')

        if signal == 'neutral' and trend == 'cleared':
            prev = persistence_info.get('prev_signal', 'signal')
            context_parts.append(f"TREND: {prev.title()} signal has cleared")
        elif signal and run_count >= 2:
            if trend == 'strengthening':
                # Plain language: getting colder/warmer
                direction = "getting colder" if signal == 'cold' else "getting warmer"
                context_parts.append(f"TREND: {signal.title()} signal for {run_count} consecutive runs and {direction}")
            elif trend == 'weakening':
                # Plain language: easing, less extreme than before
                direction = "less cold than previous runs" if signal == 'cold' else "less warm than previous runs"
                context_parts.append(f"TREND: {signal.title()} signal for {run_count} runs but {direction}")
            else:
                context_parts.append(f"TREND: {signal.title()} signal now in {run_count} consecutive runs")

    # Timing uncertainty
    if timing_info:
        context_parts.append(
            f"TIMING: Cold arrives ~{timing_info['mid_date']} ±{timing_info['spread_days']} days ({timing_info['models_crossing']}/{timing_info['models_total']} models crossing threshold)"
        )

    # Confidence
    context_parts.append(f"CONFIDENCE: {confidence}")

    return "\n".join(context_parts)


def get_claude_commentary(data_path: Path, run_diff_text: str, confidence: str,
                          percentile_info: dict = None, bimodal_info: dict = None,
                          persistence_info: dict = None, timing_info: dict = None) -> tuple:
    """Pipe JSON to Claude CLI and get commentary. Returns (text, is_fallback)."""
    import time

    # Build analysis context
    analysis_context = format_analysis_context(
        run_diff_text, confidence,
        percentile_info, bimodal_info,
        persistence_info, timing_info
    )

    prompt = f"""You are WXD, a weather ensemble analysis bot. Analyse this 4-model ensemble 850hPa temperature data for London.

Write a Bluesky post (max 250 chars to leave room for confidence indicator):
- Lead with the key finding (cold/warm signal, timing)
- Use the ANALYSIS CONTEXT below to add depth - weave in percentile/bimodal/persistence info naturally
- If run-to-run shifts are noted, mention which model shifted
- Timing uncertainty is valuable ("cold arrives Dec 30 ±2 days")
- PLAIN LANGUAGE ONLY - write for casual weather fans, not meteorologists
- Avoid jargon like "conviction", "regime", "synoptic" - say "all models agree" not "model consensus"
- Be direct: "cold easing" not "losing conviction", "models show" not "signal persists"
- Keep it punchy and engaging
- No hashtags, no emojis (confidence emoji added separately)
- Use °C for temperatures

ANALYSIS CONTEXT:
{analysis_context}

Data shows ensemble means from GFS, ECM, AIFS, and GEM models."""

    try:
        with open(data_path, 'r') as f:
            data_str = f.read()
            data_json = json.loads(data_str)

        # First attempt
        result = subprocess.run(
            ['claude', '-p', prompt],
            input=data_str,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            text = result.stdout.strip()
            if len(text) > 270:
                text = text[:267] + "..."
            return text, False

        # Check if auth error
        if is_auth_error(result.stderr):
            print("  Claude CLI auth error detected, retrying in 30s...")
            time.sleep(30)

            # Retry once
            result = subprocess.run(
                ['claude', '-p', prompt],
                input=data_str,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                text = result.stdout.strip()
                if len(text) > 270:
                    text = text[:267] + "..."
                return text, False

            # Still failing - use fallback
            print("  CLAUDE CLI AUTH FAILED - using fallback - reauth required")
            send_ntfy_alert("WXD: Claude CLI auth failed. SSH to VM and run 'claude' to reauth.")
            fallback = generate_fallback_post(data_json)
            return fallback, True

        # Non-auth error
        print(f"Claude CLI error: {result.stderr}")
        return None, False

    except subprocess.TimeoutExpired:
        print("Claude CLI timed out")
        # Try fallback on timeout too
        try:
            with open(data_path, 'r') as f:
                data_json = json.load(f)
            fallback = generate_fallback_post(data_json)
            return fallback, True
        except:
            return None, False
    except Exception as e:
        print(f"Error getting commentary: {e}")
        return None, False


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
            'ecmwf_ifs': 'ECM (51)',
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
        fetched_at = run.get("fetched_at", "Unknown")
        run_label = get_run_label(fetched_at)

        # Title shows run clearly (e.g., "00z run" or "12z run")
        if run_label:
            ax.set_title(f'London 850hPa Ensemble Forecast ({run_label})',
                        fontsize=14)
        else:
            ax.set_title(f'London 850hPa Ensemble Forecast\nFetched: {fetched_at}',
                        fontsize=14)

        ax.legend(loc='upper right', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        fig.autofmt_xdate()

        # Watermark
        fig.text(0.99, 0.01, 'wxd-london.bsky.social | Free to use with attribution',
                 fontsize=8, color='gray', alpha=0.6,
                 ha='right', va='bottom', transform=fig.transFigure)

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


def post_to_bluesky(text: str, image_path: Path = None, handle: str = None, password: str = None,
                    reply_to: dict = None) -> dict:
    """Post to Bluesky with optional image. Returns post reference for threading.

    Args:
        text: Post text
        image_path: Optional image to attach
        handle: Bluesky handle
        password: App password
        reply_to: Optional dict with 'uri' and 'cid' to reply to (for threading)

    Returns:
        dict with 'uri' and 'cid' of posted message, or None on failure
    """
    if not HAS_ATPROTO:
        print("atproto not installed, skipping post")
        return None

    if not handle or not password:
        print("Bluesky credentials not provided")
        return None

    try:
        client = Client()
        client.login(handle, password)

        # Build reply reference if threading
        reply_ref = None
        if reply_to and reply_to.get('uri') and reply_to.get('cid'):
            reply_ref = {
                'root': {'uri': reply_to['uri'], 'cid': reply_to['cid']},
                'parent': {'uri': reply_to['uri'], 'cid': reply_to['cid']}
            }

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
            response = client.send_post(text=text, embed=embed, reply_to=reply_ref)
        else:
            response = client.send_post(text=text, reply_to=reply_ref)

        print("Posted to Bluesky successfully")

        # Return post reference for threading
        return {
            'uri': response.uri,
            'cid': response.cid
        }

    except Exception as e:
        print(f"Error posting to Bluesky: {e}")
        return None


def get_weekly_commits() -> list:
    """Get git commits from the past week."""
    try:
        result = subprocess.run(
            ['git', 'log', '--since=1 week ago', '--oneline', '--no-merges'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split('\n')
        return []
    except Exception:
        return []


def generate_weekly_changelog() -> str:
    """Generate weekly changelog from git commits."""
    commits = get_weekly_commits()

    if not commits:
        return None  # No commits this week, skip posting

    # Summarize commits (strip commit hashes, keep messages)
    messages = []
    for commit in commits[:5]:  # Max 5 commits to fit in post
        # Format: "abc1234 Commit message here"
        parts = commit.split(' ', 1)
        if len(parts) > 1:
            messages.append(parts[1])

    if not messages:
        return None

    # Build summary
    if len(commits) == 1:
        summary = f"🔧 WXD this week: {messages[0]}"
    else:
        bullet_points = "; ".join(messages[:3])
        if len(commits) > 3:
            summary = f"🔧 WXD this week ({len(commits)} updates): {bullet_points}..."
        else:
            summary = f"🔧 WXD this week: {bullet_points}"

    # Truncate if needed
    if len(summary) > 300:
        summary = summary[:297] + "..."

    return summary


def post_weekly(handle: str = None, password: str = None) -> int:
    """Post weekly changelog to Bluesky."""
    if not handle or not password:
        print("ERROR: BSKY_HANDLE and BSKY_PASSWORD not set")
        return 1

    summary = generate_weekly_changelog()
    if not summary:
        print("No commits this week, skipping post")
        return 0  # Not an error, just nothing to post

    print(f"Posting weekly changelog ({len(summary)} chars):")
    print(f"  {summary}")

    if post_to_bluesky(summary, None, handle, password):
        print("Weekly changelog posted successfully")
        return 0
    else:
        print("Failed to post weekly changelog")
        return 1


def post_changelog(message: str, handle: str = None, password: str = None) -> int:
    """Post a changelog/update message to Bluesky."""
    if not handle or not password:
        print("ERROR: BSKY_HANDLE and BSKY_PASSWORD not set")
        return 1

    # Prepend emoji if not present
    if not message.startswith('🔧'):
        message = f"🔧 WXD update: {message}"

    # Truncate if needed
    if len(message) > 300:
        message = message[:297] + "..."

    print(f"Posting changelog ({len(message)} chars):")
    print(f"  {message}")

    if post_to_bluesky(message, None, handle, password):
        print("Changelog posted successfully")
        return 0
    else:
        print("Failed to post changelog")
        return 1


def main():
    parser = argparse.ArgumentParser(description='WXD Bluesky Poster')
    parser.add_argument('--changelog', '-c', type=str, help='Post a changelog/update message')
    parser.add_argument('--weekly', '-w', action='store_true', help='Post weekly summary')
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_path = data_dir / "history_compact.json"
    chart_path = data_dir / "chart_latest.png"
    state_path = data_dir / "alert_state.json"

    # Check for credentials in environment
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    # Handle changelog mode
    if args.changelog:
        return post_changelog(args.changelog, bsky_handle, bsky_password)

    # Handle weekly changelog mode
    if args.weekly:
        return post_weekly(bsky_handle, bsky_password)

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

    # Check model divergence
    print("Checking model divergence...")
    divergence_info = check_model_divergence(data)
    if divergence_info:
        print(f"  Divergence: {divergence_info['diff']}°C gap on {divergence_info['date']}")
    else:
        print("  No significant divergence")

    # Check rapid swing
    print("Checking rapid swings...")
    swing_info = check_rapid_swing(data)
    if swing_info:
        print(f"  Swing: {abs(swing_info['swing'])}°C {swing_info['direction']} from {swing_info['start_date']} to {swing_info['end_date']}")
    else:
        print("  No rapid swings")

    # Check warm thresholds (Apr-Sep only)
    print("Checking warm thresholds...")
    warm_info = check_warm_threshold(data)
    warm_alert = None
    if warm_info:
        print(f"  Warm signal: {warm_info['temp']}°C ({warm_info['model']}) on {warm_info['date']}")
        alert_state['warm_count'] = alert_state.get('warm_count', 0) + 1
        if alert_state['warm_count'] >= HYSTERESIS_RUNS:
            warm_alert = warm_info
            print(f"  WARM ALERT triggered (count: {alert_state['warm_count']})")
    else:
        print("  No warm signal (or out of season)")
        if alert_state.get('warm_count', 0) > 0:
            alert_state['warm_count'] -= 1

    # NEW: Percentile framing analysis
    print("Analyzing percentile framing...")
    percentile_data = analyze_percentile_framing(data_dir)
    percentile_info = find_peak_percentile(percentile_data)
    if percentile_info:
        print(f"  Peak: {int(percentile_info['pct'])}% of {percentile_info['model']} below threshold on {percentile_info['date']}")
    else:
        print("  No significant percentile signals")

    # NEW: Bimodal detection
    print("Detecting bimodal distributions...")
    bimodal_info = detect_bimodal_distribution(data_dir)
    if bimodal_info:
        for model, info in bimodal_info.items():
            print(f"  {model.upper()}: {info['cold_pct']}% cold vs {info['warm_pct']}% mild (gap: {info['gap']}°C)")
    else:
        print("  No bimodal splits detected")

    # NEW: Trend persistence
    print("Tracking trend persistence...")
    persistence_info = track_trend_persistence(data, alert_state)
    if persistence_info:
        signal = persistence_info.get('signal', 'neutral')
        run_count = persistence_info.get('run_count', 0)
        trend = persistence_info.get('trend', '')
        if signal != 'neutral':
            print(f"  {signal.title()} signal: run #{run_count}, {trend}")
        elif trend == 'cleared':
            print(f"  Signal cleared (was {persistence_info.get('prev_signal', 'unknown')})")
    else:
        print("  No trend persistence data")

    # NEW: Timing uncertainty
    print("Calculating timing uncertainty...")
    timing_info = calculate_timing_uncertainty(data)
    if timing_info:
        print(f"  Cold arrives ~{timing_info['mid_date']} ±{timing_info['spread_days']} days")
    else:
        print("  No significant timing spread")

    # Save alert state (includes trend persistence)
    save_alert_state(state_path, alert_state)
    print()

    # Generate main commentary with all analysis context
    print("Generating AI commentary...")
    text, is_fallback = get_claude_commentary(
        data_path, run_diff_text, confidence,
        percentile_info=percentile_info,
        bimodal_info=bimodal_info,
        persistence_info=persistence_info,
        timing_info=timing_info
    )
    if not text:
        print("ERROR: Failed to generate commentary")
        return 1

    if is_fallback:
        print("  (Using fallback post - Claude CLI unavailable)")
        main_text = text  # Fallback doesn't get confidence appended
    else:
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
        main_post_ref = post_to_bluesky(main_text, image, bsky_handle, bsky_password)
        if not main_post_ref:
            return 1

        # Post alerts as REPLIES to main post (creates thread)
        # Post cold alert if triggered
        if cold_alert:
            if cold_alert['type'] == 'extreme':
                alert_text = f"⚠️ Extreme cold signal: {cold_alert['model']} showing {cold_alert['temp']}°C at 850hPa for {cold_alert['date']}. Significant snow/ice risk for UK if verified."
            else:
                alert_text = f"❄️ Cold signal: {cold_alert['model']} showing {cold_alert['temp']}°C at 850hPa for {cold_alert['date']}. Elevated snow risk for UK uplands."

            print(f"Posting cold alert as reply ({len(alert_text)} chars):")
            print(f"  {alert_text}")
            post_to_bluesky(alert_text, None, bsky_handle, bsky_password, reply_to=main_post_ref)

        # Post warm alert if triggered (summer only)
        if warm_alert:
            if warm_alert.get('extreme'):
                alert_text = f"🌡️ Extreme warmth signal: {warm_alert['model']} showing {warm_alert['temp']}°C at 850hPa for {warm_alert['date']}. Potential heatwave conditions."
            else:
                alert_text = f"☀️ Warm signal: {warm_alert['model']} showing {warm_alert['temp']}°C at 850hPa for {warm_alert['date']}. Above-average temperatures expected."

            print(f"Posting warm alert as reply ({len(alert_text)} chars):")
            print(f"  {alert_text}")
            post_to_bluesky(alert_text, None, bsky_handle, bsky_password, reply_to=main_post_ref)

        # Post divergence alert if significant (one-off, no hysteresis needed)
        if divergence_info and divergence_info['diff'] > 6.0:  # Only post for really big gaps
            alert_text = f"⚡ Model disagreement: {divergence_info['diff']}°C gap for {divergence_info['date']}. {divergence_info['coldest']} at {divergence_info['coldest_temp']}°C vs {divergence_info['warmest']} at {divergence_info['warmest_temp']}°C. Low confidence."

            print(f"Posting divergence alert as reply ({len(alert_text)} chars):")
            print(f"  {alert_text}")
            post_to_bluesky(alert_text, None, bsky_handle, bsky_password, reply_to=main_post_ref)

        # Post swing alert if dramatic pattern change
        if swing_info and abs(swing_info['swing']) >= 8.0:  # Only post for really big swings
            alert_text = f"🔄 Pattern flip: {abs(swing_info['swing'])}°C {swing_info['direction']} expected {swing_info['start_date']} to {swing_info['end_date']}. Major temperature change incoming."

            print(f"Posting swing alert as reply ({len(alert_text)} chars):")
            print(f"  {alert_text}")
            post_to_bluesky(alert_text, None, bsky_handle, bsky_password, reply_to=main_post_ref)
    else:
        print("BSKY_HANDLE and BSKY_PASSWORD not set, skipping post")
        print("Set these environment variables to enable posting")

    print()
    print("Complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
