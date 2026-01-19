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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean, stdev
from collections import defaultdict

# Import period analysis from shared module
import sys
sys.path.insert(0, 'trackers')
from shared.analysis import analyze_by_period, format_period_context

# Import post registry for feedback tracing
try:
    from lib.bluesky import register_post
    HAS_REGISTRY = True
except ImportError:
    HAS_REGISTRY = False
    register_post = None

# Import Met Office warnings
try:
    from daily_summary import fetch_metoffice_narrative, filter_warnings_48h
    HAS_METOFFICE = True
except ImportError:
    HAS_METOFFICE = False
    fetch_metoffice_narrative = None
    filter_warnings_48h = None


def fetch_current_warnings() -> str:
    """Fetch and format current Met Office warnings for Claude prompt.

    Uses filter_warnings_48h() for STRICT validation:
    - Only structured warning data (not forecast headers)
    - Must have date, level, AND regions
    - Within 48 hours only
    """
    if not HAS_METOFFICE or not fetch_metoffice_narrative:
        return ""

    try:
        mo_data = fetch_metoffice_narrative()
        uk_warn = mo_data.get("uk_warnings", "")

        # Use strict 48h filter - returns empty string if validation fails
        filtered = filter_warnings_48h(uk_warn) if filter_warnings_48h else ""

        if filtered:
            return f"MET OFFICE WARNINGS (VERIFIED, 48H): {filtered}"
        else:
            return "MET OFFICE WARNINGS: None currently in force. DO NOT invent or assume warnings."

    except Exception as e:
        print(f"  Warning fetch error: {e}")
        return ""

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
    from atproto import Client, models as atproto_models
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
    """Check ALL models hitting cold threshold, return details for each.

    Returns dict with:
        - models: list of all models crossing threshold with their coldest temp/date
        - coldest: the single coldest model (for backwards compat)
        - extreme: True if any model hits extreme threshold
        - multi_model: True if 2+ models cross threshold (strong signal)
    """
    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    models = current.get('models', {})
    timestamps = current.get('timestamps', [])

    # Find coldest point for each model
    model_coldest = []
    extreme_cold = False

    for model_key, model_data in models.items():
        means = model_data.get('mean', [])
        model_min = {'temp': 999, 'model': format_model_name(model_key), 'date': None}

        for i, val in enumerate(means):
            if val is not None and val < model_min['temp']:
                model_min['temp'] = val
                if i < len(timestamps):
                    model_min['date'] = timestamps[i][:10]

        # Check if this model crosses threshold
        if model_min['temp'] <= COLD_THRESHOLD:
            model_min['temp'] = round(model_min['temp'], 1)
            model_coldest.append(model_min)
            if model_min['temp'] <= EXTREME_COLD_THRESHOLD:
                extreme_cold = True

    if not model_coldest:
        return None

    # Sort by temperature (coldest first)
    model_coldest.sort(key=lambda x: x['temp'])

    return {
        'models': model_coldest,
        'coldest': model_coldest[0],  # Backwards compat - single coldest
        'temp': model_coldest[0]['temp'],  # Backwards compat
        'model': model_coldest[0]['model'],  # Backwards compat
        'date': model_coldest[0]['date'],  # Backwards compat
        'extreme': extreme_cold,
        'multi_model': len(model_coldest) >= 2,
        'type': 'extreme' if extreme_cold else 'cold'
    }


def get_peak_timing_from_raw(data: dict) -> str:
    """Get PEAK TIMING context from raw data, regardless of cold threshold.

    This finds the coldest point across all models and determines if it's
    PAST, TODAY, or FUTURE relative to today.

    Returns context string or None.
    """
    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    models = current.get('models', {})
    timestamps = current.get('timestamps', [])

    if not models or not timestamps:
        return None

    # Find coldest point across all models
    overall_coldest = {'temp': 999, 'date': None}

    for model_key, model_data in models.items():
        means = model_data.get('mean', [])
        for i, val in enumerate(means):
            if val is not None and val < overall_coldest['temp']:
                overall_coldest['temp'] = val
                if i < len(timestamps):
                    overall_coldest['date'] = timestamps[i][:10]

    if not overall_coldest['date']:
        return None

    try:
        today = datetime.now(timezone.utc).date()
        peak_date = datetime.strptime(overall_coldest['date'], '%Y-%m-%d').date()

        if peak_date < today:
            return f"PEAK TIMING: PAST - coldest point ({overall_coldest['temp']:.1f}C) was {peak_date.strftime('%a %b %d')}, we are now WARMING. Do NOT say 'peak holding' or 'cold persisting'."
        elif peak_date == today:
            return f"PEAK TIMING: TODAY - coldest point ({overall_coldest['temp']:.1f}C) is today, warming follows."
        else:
            days_away = (peak_date - today).days
            if days_away <= 2:
                return f"PEAK TIMING: SOON - coldest ({overall_coldest['temp']:.1f}C) arrives {peak_date.strftime('%a %b %d')}, still cooling."
            else:
                return f"PEAK TIMING: FUTURE - coldest ({overall_coldest['temp']:.1f}C) on {peak_date.strftime('%a %b %d')}, {days_away} days away."
    except:
        return None


def get_temperature_trajectory(data: dict) -> str:
    """Get multi-model mean temperature trajectory for context.

    Shows daily noon temperatures so Claude can verify dates.
    """
    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    timestamps = current.get('timestamps', [])
    multi_model_mean = current.get('multi_model_mean', [])

    if not timestamps or not multi_model_mean:
        return None

    # Build daily noon trajectory
    trajectory = []
    seen_dates = set()

    for i, (ts, temp) in enumerate(zip(timestamps, multi_model_mean)):
        if temp is None:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            date_key = dt.date()
            # Take noon value (or first value for each day)
            if date_key not in seen_dates and (dt.hour == 12 or date_key not in seen_dates):
                seen_dates.add(date_key)
                trajectory.append(f"{dt.strftime('%a %b %d')}: {temp:+.1f}C")
        except:
            continue

    if not trajectory:
        return None

    # Only include first 12 days to keep context manageable
    trajectory = trajectory[:12]

    return "TEMPERATURE TRAJECTORY (multi-model mean, daily):\n" + "\n".join(trajectory)


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
    """Find the peak percentile (most members below threshold) across all models.

    Only considers FUTURE dates (from now onwards) - past dates are irrelevant.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    today_str = now.strftime('%Y-%m-%d')

    peak = {'model': None, 'date': None, 'pct': 0, 'threshold': 'cold'}

    for model_key, data in percentile_data.items():
        timestamps = data.get('timestamps', [])
        pct_cold = data.get('pct_below_cold', [])
        pct_extreme = data.get('pct_below_extreme', [])

        for i, ts in enumerate(timestamps):
            date_str = ts[:10]
            # Skip past dates - only report future forecasts
            if date_str < today_str:
                continue

            # Check extreme first
            if i < len(pct_extreme) and pct_extreme[i] > peak['pct']:
                peak = {
                    'model': format_model_name(model_key),
                    'date': date_str,
                    'pct': pct_extreme[i],
                    'threshold': 'extreme'
                }
            # Then cold (only if no extreme is higher)
            elif i < len(pct_cold) and pct_cold[i] > peak['pct']:
                peak = {
                    'model': format_model_name(model_key),
                    'date': date_str,
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

    IMPORTANT: Only counts distinct model runs (00z/12z cycles), not
    repeated script executions on the same data.
    """
    runs = data.get('runs', [])
    if not runs:
        return None

    current = runs[0]
    mmm = current.get('multi_model_mean', [])
    fetched_at = current.get('fetched_at', '')

    if not mmm:
        return None

    # Determine run ID (date + 00z/12z) to avoid counting same data twice
    run_label = get_run_label(fetched_at)
    run_date = fetched_at[:10] if fetched_at else ''
    current_run_id = f"{run_date}_{run_label}" if run_label else fetched_at[:16]

    # Check if this is actually a new run
    prev_run_id = alert_state.get('last_run_id', '')
    is_new_run = current_run_id != prev_run_id

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
            # Signal persists - only increment if this is a new run
            if is_new_run:
                new_count = prev_count + 1
                # Determine if strengthening or weakening vs previous run
                if prev_strength is not None and current_strength is not None:
                    if current_signal == 'cold':
                        trend = 'strengthening' if current_strength < prev_strength else 'weakening'
                    else:  # warm
                        trend = 'strengthening' if current_strength > prev_strength else 'weakening'
                else:
                    trend = 'steady'
                # Update state for new run
                alert_state['trend_run_count'] = new_count
                alert_state['trend_strength'] = current_strength
                alert_state['last_run_id'] = current_run_id
            else:
                # Same run - keep existing count and trend
                new_count = prev_count
                trend = 'steady'  # Can't determine trend within same run

            result = {
                'signal': current_signal,
                'run_count': new_count,
                'trend': trend,
                'strength': current_strength
            }
        else:
            # New signal or signal changed - always reset
            result = {
                'signal': current_signal,
                'run_count': 1,
                'trend': 'new',
                'strength': current_strength
            }

            alert_state['trend_signal'] = current_signal
            alert_state['trend_run_count'] = 1
            alert_state['trend_strength'] = current_strength
            alert_state['last_run_id'] = current_run_id
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
        alert_state['last_run_id'] = current_run_id

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


def _runs_to_duration(runs: int, runs_per_day: float = 2) -> str:
    """Convert run count to human-readable duration."""
    days = runs / runs_per_day
    if days < 2:
        return "since yesterday"
    elif days < 5:
        return f"~{int(round(days))} days"
    elif days < 10:
        return "~1 week"
    elif days < 17:
        return "~2 weeks"
    else:
        weeks = int(round(days / 7))
        return f"~{weeks} weeks"


def calculate_signal_strength(cold_info: dict, persistence_info: dict) -> dict:
    """
    Calculate signal strength based on model agreement + run persistence.

    Returns dict with:
        - level: 'high_confidence' | 'strong' | 'emerging' | 'weak'
        - models_agreeing: int (how many models show cold signal)
        - run_count: int (consecutive runs with signal)
        - label: str (human-readable label for context)

    Framework:
        - Locked: 4/4 models AND 5+ runs persistent
        - Strong: 3-4/4 models OR 3+ runs persistent
        - Emerging: 2/4 models, <3 runs
        - Weak: 1/4 models or no persistence
    """
    models_agreeing = 0
    run_count = 0

    if cold_info and cold_info.get('models'):
        models_agreeing = len(cold_info['models'])

    if persistence_info:
        run_count = persistence_info.get('run_count', 0)

    # Convert run count to duration for context
    duration = _runs_to_duration(run_count) if run_count >= 4 else ""

    # Determine signal level (don't expose run counts - they're noise)
    if models_agreeing >= 4 and run_count >= 5:
        level = 'high_confidence'
        label = f"High confidence ({models_agreeing}/4 models, tracked {duration})"
    elif models_agreeing >= 3 or run_count >= 3:
        level = 'strong'
        label = f"Strong signal ({models_agreeing}/4 models agreeing)"
    elif models_agreeing >= 2:
        level = 'emerging'
        label = f"Emerging signal ({models_agreeing}/4 models)"
    else:
        level = 'weak'
        label = "Weak/uncertain signal"

    return {
        'level': level,
        'models_agreeing': models_agreeing,
        'run_count': run_count,
        'label': label
    }


def format_timing_window(timing_info: dict, cold_info: dict) -> dict:
    """
    Format timing as a date window rather than single point with ±.

    Returns dict with:
        - spread_label: 'tight' | 'moderate' | 'broad'
        - spread_days: float
        - window: str (e.g., "Jan 3-5")
        - label: str (human-readable for context)
    """
    if not timing_info:
        # Fall back to cold_info dates if no timing spread calculated
        if cold_info and cold_info.get('models'):
            dates = [m['date'] for m in cold_info['models']]
            unique_dates = sorted(set(dates))
            if len(unique_dates) == 1:
                return {
                    'spread_label': 'tight',
                    'spread_days': 0,
                    'window': unique_dates[0],
                    'label': f"Coldest period: {unique_dates[0]}"
                }
            else:
                # Format as range
                from datetime import datetime
                try:
                    dts = [datetime.fromisoformat(d) for d in unique_dates]
                    start = min(dts).strftime('%b %d')
                    end = max(dts).strftime('%b %d')
                    spread = (max(dts) - min(dts)).days
                except:
                    start = unique_dates[0]
                    end = unique_dates[-1]
                    spread = len(unique_dates)

                if spread <= 1:
                    spread_label = 'tight'
                elif spread <= 2:
                    spread_label = 'moderate'
                else:
                    spread_label = 'broad'

                return {
                    'spread_label': spread_label,
                    'spread_days': spread,
                    'window': f"{start}-{end}",
                    'label': f"Coldest period: {start}-{end} (±{spread} days)"
                }
        return None

    spread_days = timing_info.get('spread_days', 0)

    # Determine spread label
    if spread_days <= 1:
        spread_label = 'tight'
    elif spread_days <= 2:
        spread_label = 'moderate'
    else:
        spread_label = 'broad'

    # Build window string from earliest/latest
    earliest = timing_info.get('earliest_date', '')[:10]
    latest = timing_info.get('latest_date', '')[:10]

    try:
        from datetime import datetime
        start_dt = datetime.fromisoformat(earliest)
        end_dt = datetime.fromisoformat(latest)
        window = f"{start_dt.strftime('%b %d')}-{end_dt.strftime('%b %d')}"
    except:
        window = f"{earliest} to {latest}"

    return {
        'spread_label': spread_label,
        'spread_days': round(spread_days, 1),
        'window': window,
        'label': f"Coldest period: {window} (±{round(spread_days)} days)"
    }


def calculate_confidence(data: dict) -> str:
    """DEPRECATED - kept for backwards compatibility. Use calculate_signal_strength instead."""
    # Return empty string - we use the new signal/timing system now
    return ""


def format_run_diff_text(diffs: list) -> str:
    """Format run-to-run diffs for inclusion in post.

    CRITICAL: Make direction unambiguous for Claude:
    - cooled = model forecast got COLDER = supporting cold trend
    - warmed = model forecast got WARMER = backing off from cold
    """
    if not diffs:
        return ""

    # Just use the biggest shift
    d = diffs[0]
    diff_val = abs(d['diff'])

    if d['direction'] == 'cooled':
        # Model got colder - supporting cold signal
        return f"{d['model']} dropped {diff_val}°C colder since last run (reinforcing cold trend)"
    else:
        # Model got warmer - backing off from cold
        return f"{d['model']} rose {diff_val}°C warmer since last run (backing off cold signal)"


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
                           persistence_info: dict, timing_info: dict,
                           cold_info: dict = None, period_info: dict = None,
                           data: dict = None) -> str:
    """Format all analysis results into context for Claude CLI prompt."""
    context_parts = []
    peak_timing_set = False  # Track if PEAK TIMING was added

    # NEW: Signal strength (replaces old confidence)
    signal_strength = calculate_signal_strength(cold_info, persistence_info)
    if signal_strength and signal_strength['level'] != 'weak':
        context_parts.append(f"SIGNAL: {signal_strength['label']}")

    # NEW: Timing window (replaces old timing uncertainty)
    timing_window = format_timing_window(timing_info, cold_info)
    if timing_window:
        context_parts.append(f"TIMING: {timing_window['label']}")

    # Cold threshold - EXPLICIT ranked list so Claude doesn't misread JSON
    if cold_info and cold_info.get('models'):
        models = cold_info['models']
        ranked = ", ".join([f"{m['model']} {m['temp']}°C on {m['date']}" for m in models])
        context_parts.append(f"COLD RANKING (coldest first): {ranked}")

        # CRITICAL: Check if peak is PAST, TODAY, or FUTURE
        today = datetime.now(timezone.utc).date()
        peak_dates = []
        for m in models:
            try:
                peak_date = datetime.strptime(m['date'][:10], '%Y-%m-%d').date()
                peak_dates.append(peak_date)
            except:
                pass

        if peak_dates:
            earliest_peak = min(peak_dates)
            latest_peak = max(peak_dates)

            if latest_peak < today:
                context_parts.append(f"PEAK TIMING: PAST - coldest point was {latest_peak.strftime('%a %b %d')}, we are now WARMING. Do NOT say 'peak holding'.")
                peak_timing_set = True
            elif earliest_peak <= today <= latest_peak:
                context_parts.append(f"PEAK TIMING: NOW - coldest point is around today ({today.strftime('%a %b %d')}), transition imminent.")
                peak_timing_set = True
            else:
                context_parts.append(f"PEAK TIMING: FUTURE - coldest point arrives {earliest_peak.strftime('%a %b %d')}, we are still COOLING.")
                peak_timing_set = True

    # CRITICAL: If cold_info didn't provide peak timing, calculate from raw data
    # This prevents "peak holding" garbage when we're actually warming
    if not peak_timing_set and data:
        raw_peak_timing = get_peak_timing_from_raw(data)
        if raw_peak_timing:
            context_parts.append(raw_peak_timing)

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

    # Trend persistence (additional detail)
    if persistence_info:
        signal = persistence_info.get('signal')
        trend = persistence_info.get('trend', '')

        if signal == 'neutral' and trend == 'cleared':
            prev = persistence_info.get('prev_signal', 'signal')
            context_parts.append(f"TREND: {prev.title()} signal has cleared")
        elif signal and trend:
            if trend == 'strengthening':
                context_parts.append(f"TREND: Signal strengthening (getting {'colder' if signal == 'cold' else 'warmer'})")
            elif trend == 'weakening':
                context_parts.append(f"TREND: Signal weakening (less {'cold' if signal == 'cold' else 'warm'} than previous runs)")

    # Period breakdown
    if period_info:
        period_ctx = format_period_context(period_info)
        if period_ctx:
            context_parts.append(period_ctx)

    # CRITICAL: Add temperature trajectory so Claude can verify dates
    if data:
        trajectory = get_temperature_trajectory(data)
        if trajectory:
            context_parts.append(trajectory)

    # NOTE: Old CONFIDENCE line removed - replaced by SIGNAL above

    return "\n".join(context_parts)


def get_claude_commentary(data_path: Path, run_diff_text: str, confidence: str,
                          percentile_info: dict = None, bimodal_info: dict = None,
                          persistence_info: dict = None, timing_info: dict = None,
                          cold_info: dict = None, previous_post: str = None) -> tuple:
    """Pipe JSON to Claude CLI and get commentary. Returns (text, is_fallback).

    Args:
        previous_post: Text of previous post from this tracker for narrative continuity
    """
    import time

    # Calculate period analysis from data
    try:
        with open(data_path, 'r' ) as f:
            data = json.load(f)
        period_info = analyze_by_period(data, is_ensemble=True)
    except:
        period_info = None
    # Build previous post context for narrative continuity
    if previous_post:
        previous_post_section = f"""
YOUR PREVIOUS POST (for narrative continuity):
{previous_post}

NARRATIVE CONTINUITY - PATIENCE OVER DRAMA:
- Previous post is CONTEXT only - current ANALYSIS data is the source of truth
- DO NOT dramatise small differences between this run and last
- If data is broadly similar: "Little changed from previous run" or just report current state without comparison
- If marginally different: "This run slightly warmer/colder" - no drama, wait for confirmation
- Only flag significant change if: ALL models moved the same way, OR change is large (>3°C ensemble mean shift)
- If previous run said one thing and this run says the opposite, DO NOT say "models have flipped" - say "back towards earlier levels, uncertainty remains"
- If previous post mentioned a feature not in current data, DO NOT repeat it
- Vary your language - don't use the same phrases as before
- When in doubt, be measured - avoid see-sawing headlines
"""
    else:
        previous_post_section = ""

    # Build analysis context
    # Fetch current Met Office warnings
    warnings_data = fetch_current_warnings()

    analysis_context = format_analysis_context(
        run_diff_text, confidence,
        percentile_info, bimodal_info,
        persistence_info, timing_info,
        cold_info=cold_info,
        period_info=period_info,
        data=data  # For peak timing calculation regardless of cold threshold
    )

    # Determine if this is a significant event (multi-model agreement, high percentile)
    is_significant = False
    if cold_info and cold_info.get('multi_model'):
        is_significant = True
    if percentile_info and percentile_info.get('pct', 0) >= 80:
        is_significant = True

    # Allow longer posts for significant events
    max_chars = 450 if is_significant else 250

    # Get current date for prompt context
    now_for_prompt = datetime.now(timezone.utc)
    today_str = now_for_prompt.strftime("%A %d %B %Y")  # e.g., "Sunday 04 January 2026"

    prompt = f"""You are WXD, a weather ensemble analysis bot. Write commentary on this 4-model ensemble 850hPa temperature data for London.

TODAY IS: {today_str} (UTC)

Write a Bluesky post (max {max_chars} chars). This is the MAIN COMMENTARY - alerts with specific temps follow as thread replies.

DATE REFERENCES - CRITICAL:
- NEVER use vague terms like "the weekend", "Saturday", "next week" without explicit dates
- ALWAYS include the date number: "Saturday 4th", "Sun-Mon 5th-6th", "by Wednesday 8th"
- If today is Saturday/Sunday, "the weekend" is NOW or YESTERDAY - be explicit
- Example BAD: "cold for the weekend" or "by Saturday" (which one? past or future?)
- Example GOOD: "cold locked in through Sunday 5th" or "sharp cold arriving Friday 10th"

STYLE:
- NO PREFIX - don't start with "London 850hPa..." or similar. Just start talking.
- FORECAST FOCUS: The value is predicting what's COMING, not reporting current weather
- If today matches what we've been tracking, acknowledge briefly then pivot to what's NEXT
- Today as context: "Cold holding as forecast, models now show recovery by Thursday 16th"
- Today as revelation (BAD): "Cold peak arriving today!" - we knew this was coming, that's not news
- NEVER use "arriving" for something we've tracked for days/weeks - use "holding", "as forecast", "as tracked"
- Don't parrot the example phrases verbatim every time - vary your language with natural synonyms that don't sound pretentious
- The chart shows days 1-7+, your commentary should cover that range
- Mention model agreement/disagreement where notable
- Only mention run-on-run changes if they are significant and confirmed (see RUN-ON-RUN CHANGES section)
- Can mention ONE key temperature to anchor the story

PEAK TIMING - CRITICAL (READ THIS CAREFULLY):
- The ANALYSIS below contains "PEAK TIMING:" which tells you if the coldest point is PAST, TODAY, or FUTURE
- If PEAK TIMING says "PAST": STOP. The cold peak HAS ALREADY HAPPENED. You MUST NOT say "peak arriving", "cold holding", "peak persisting". The correct framing is "peak passed [date], now warming" or "cold easing after [date] peak"
- If PEAK TIMING says "TODAY": The peak is NOW. Say "peak today" or "coldest point today", NOT "peak arriving"
- If PEAK TIMING says "FUTURE": You CAN say "cold arriving" or "peak approaching"
- VIOLATION: Any post saying "peak arriving/holding/persisting" when PEAK TIMING is PAST will be WRONG

RUN-ON-RUN CHANGES - PATIENCE REQUIRED:
- Small changes (1-3°C in one or two models) are NORMAL model variability, not news
- DO NOT dramatise every shift: avoid "backed off significantly", "firming up", "models have flipped"
- For marginal changes: "This run marginally warmer/colder" - then WAIT for next run to confirm
- Only escalate language when: (a) multiple consecutive runs agree, OR (b) ALL models shift together, OR (c) change exceeds normal variability
- If this run reverses yesterday's direction, DO NOT treat it as significant - say "back towards previous levels" not "models have reversed"
- Avoid see-sawing narratives: if recent runs have bounced around, acknowledge uncertainty rather than declaring a new trend each time
- Sometimes the honest answer is "little changed, models still uncertain"

MULTI-RUN TRENDS - ONLY IF SUSTAINED:
- If ANALYSIS contains "MULTI-RUN TREND:", this means 3+ consecutive runs show the same direction
- Only then mention trending: "models have consistently trended colder/warmer over recent runs"
- A single run shift is NOT a trend - do not treat it as one

END-OF-FORECAST TRENDS - IMPORTANT:
- If ANALYSIS contains "END-OF-FORECAST:", there's a late trend reversal at the end of the forecast period
- Late cold return = temps dropping at very end - MENTION THIS ("cold returning by end of period")
- Late warming = temps rising at very end - MENTION THIS ("warming appearing at end of period")
- Do NOT ignore the end of the forecast just because the near-term is the main story

SIGNAL AND TIMING FRAMEWORK:
- SIGNAL tells you event confidence: "high_confidence" = certain it's happening, "strong" = very likely, "emerging" = developing
- TIMING tells you the date window and spread (e.g., "Jan 3-5, ±2 days")
- NEVER say "confidence low" when SIGNAL is "high_confidence" - the event IS happening, only timing varies
- When signal is high_confidence/strong, lead with certainty: "Cold highly likely for next week" not "Cold possible"
- Use the TIMING window as a range: "coldest period Jan 3-5" not "coldest on Jan 4"
- If models agree on event but differ on exact day, that's NORMAL for 5+ day forecasts - not low confidence

CLARITY ON TIMEFRAMES:
- COLD RANKING shows which model forecasts the coldest FUTURE temperature (minimum in forecast period)
- You CAN mention both current temps AND forecast minimums - but BE EXPLICIT about timeframes
- BAD: "GFS coldest... ECM coldest right now" (confusing - which is coldest?)
- GOOD: "ECM showing -8°C today, but GFS dips coldest to -9°C by Jan 4th" (clear timeframes)

EXTENDED RANGE COVERAGE - CRITICAL:
- Do NOT ignore days 5-10+ just because the main story is near-term
- If the extended range shows a trend reversal (warming after cold, or vice versa), MENTION IT
- When cold is the headline, note if milder conditions return later in the period
- When mild is the headline, note if cold signals appear in the extended range
- If "recovering" pattern detected, YOU MUST mention the warming trend
- Check the RANGE for each period - if max temp is much higher than min, that's warming
- NEVER describe a period as just "cold" if the max shows significant warming
- Example: "Sharp cold through Sunday 5th, but models hint at milder conditions returning around 10th-12th"

TEMPERATURE OSCILLATIONS - IMPORTANT:
- A forecast may show multiple significant temperature swings: cold→warm→cold or warm→cold→warm
- If PATTERN shows oscillation (e.g., "cold -> recovering -> cold"), describe ALL transitions
- Example: "Sharp cold Mon-Tue 6th-7th, brief warming Wed 8th to -1C, then another cold dip by Sat 11th"
- Each significant swing (>3C) deserves mention if it indicates a trend shift
- Don't just pick the coldest point - show the journey through the forecast period

FORMAT:
- NO markdown (no **, no #, no _) - Bluesky is plain text only
- No hashtags, no emojis, no headers
- Use °C for temperatures

TONE:
- FACTUAL and measured - not tabloid headlines
- PLAIN LANGUAGE for casual weather fans
- PATIENT with model variability - small changes don't need commentary
- If uncertain, say so: "models still showing spread" rather than picking a narrative
LANGUAGE:
- Use varied, natural phrasing - avoid repetition
- For small changes: "marginally warmer/colder", "slight adjustment", "little changed"
- For confirmed trends: "consistently showing", "sustained shift over recent runs"
- AVOID run-on-run drama: "backed off significantly", "firming up", "models have flipped", "reversed course"
- AVOID sensational terms: dramatic, slammed, plunged, locked in, major shift, prolonged, decisive
- No jargon like "regime", "synoptic", "conviction"

MET OFFICE WARNINGS - ABSOLUTE RULES (VIOLATION = MISINFORMATION):
- ONLY mention warnings if the text "MET OFFICE WARNINGS (VERIFIED" appears in this prompt
- If warning data says "None currently in force" - DO NOT mention warnings AT ALL. Not even "no warnings". Just don't mention warnings.
- CRITICAL: Warnings may be for RAIN, WIND, FOG or other hazards - NOT necessarily cold/snow/ice
- DO NOT link warnings to cold weather or "cold pattern" unless the warning explicitly mentions "snow" or "ice"
- If hazard type is unknown, just say "Yellow warnings in force" without implying winter weather
- If warning data IS provided with actual warnings, you MUST QUOTE VERBATIM:
  * Type: Yellow/Amber/Red (exact color from data)
  * Hazard: Snow/Ice/Rain/Wind (exact hazard from data)
  * Issuer: "Met Office" (ALWAYS attribute)
  * Dates: COPY EXACTLY from the data - do not paraphrase
  * Regions: COPY EXACTLY from the data - do not paraphrase
- NEVER fabricate, extrapolate, or assume warning details beyond what's explicitly provided
- NEVER mention "long-range warnings" unless explicitly stated in the data
- NEVER say "warnings expected", "warnings likely", "warnings issued for [future date]", or "warnings in place"
- NEVER say "Yellow warning" without the exact dates and regions from the data
- If you cannot COPY VERBATIM from the warning data, DO NOT mention any warning
- TEST: Can you point to the exact text in this prompt that supports your warning claim? If not, DELETE IT.

EVIDENCE-BASED CLAIMS - CRITICAL:
- Every factual claim must be traceable to the ANALYSIS data below
- If you state a temperature, it must appear in the data
- If you state a date range, it must appear in the data
- If you mention model agreement/disagreement, it must be in the data
- DO NOT infer, extrapolate, or assume information not explicitly provided
- When uncertain, be vaguer rather than more specific

ANALYSIS CONTEXT:
{analysis_context}

{warnings_data}
{previous_post_section}
Data shows ensemble means from GFS, ECM, AIFS, and GEM models."""

    try:
        with open(data_path, 'r') as f:
            data_str = f.read()
            data_json = json.loads(data_str)

        # First attempt
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            input=None,
            capture_output=True,
            text=True,
            timeout=180
        )

        if result.returncode == 0:
            text = result.stdout.strip()
            # Allow longer text - split_for_posting() will handle multi-post threading
            # Max ~900 chars = 3 posts of ~290 chars each
            max_len = 900 if is_significant else 600
            if len(text) > max_len:
                # Trim at sentence boundary if possible
                truncated = text[:max_len]
                last_period = truncated.rfind('. ')
                if last_period > max_len * 0.7:
                    text = truncated[:last_period + 1]
                else:
                    last_space = truncated.rfind(' ')
                    text = truncated[:last_space] if last_space > max_len * 0.7 else truncated
            return text, False

        # Check if auth error
        if is_auth_error(result.stderr):
            print("  Claude CLI auth error detected, retrying in 30s...")
            time.sleep(30)

            # Retry once
            result = subprocess.run(
                ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
                input=None,
                capture_output=True,
                text=True,
                timeout=180
            )

            if result.returncode == 0:
                text = result.stdout.strip()
                # Allow longer text - split_for_posting() will handle multi-post threading
                max_len = 900 if is_significant else 600
                if len(text) > max_len:
                    truncated = text[:max_len]
                    last_period = truncated.rfind('. ')
                    if last_period > max_len * 0.7:
                        text = truncated[:last_period + 1]
                    else:
                        last_space = truncated.rfind(' ')
                        text = truncated[:last_space] if last_space > max_len * 0.7 else truncated
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
                # Convert None to np.nan for matplotlib compatibility
                mins_arr = np.array([x if x is not None else np.nan for x in mins], dtype=float)
                maxs_arr = np.array([x if x is not None else np.nan for x in maxs], dtype=float)
                ax.fill_between(
                    dates[:len(mins)], mins_arr, maxs_arr,
                    color=colors.get(model_key, 'white'),
                    alpha=0.1
                )

        # Plot mean lines for each model
        for model_key, model_data in models.items():
            means = model_data.get('mean', [])
            if means:
                # Convert None to np.nan for matplotlib compatibility
                means_arr = np.array([x if x is not None else np.nan for x in means], dtype=float)
                ax.plot(dates[:len(means)], means_arr,
                       color=colors.get(model_key, 'white'),
                       label=labels.get(model_key, model_key),
                       linewidth=2)

        # Multi-model mean
        mmm = run.get('multi_model_mean', [])
        if mmm:
            # Convert None to np.nan for matplotlib compatibility
            mmm_arr = np.array([x if x is not None else np.nan for x in mmm], dtype=float)
            ax.plot(dates[:len(mmm)], mmm_arr, color='white', label='Multi-model mean',
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

        # Title shows run clearly with date (e.g., "28 Dec 00z")
        if run_label:
            try:
                dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
                date_str = dt.strftime('%d %b')  # e.g., "28 Dec"
                run_time = run_label.replace(' run', '')  # "00z" or "12z"
                ax.set_title(f'London 850hPa Ensemble Forecast ({date_str} {run_time})',
                            fontsize=14)
            except:
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
                    reply_to: dict = None, root_post: dict = None,
                    tracker: str = None, model: str = None) -> dict:
    """Post to Bluesky with optional image. Returns post reference for threading.

    Args:
        text: Post text
        image_path: Optional image to attach
        handle: Bluesky handle
        password: App password
        reply_to: Optional dict with 'uri' and 'cid' to reply to (for threading)
        root_post: Optional dict with 'uri' and 'cid' of thread root (for multi-level threads)
        tracker: Tracker name for post registry (e.g., 'Main', 'weekly')
        model: Model name for post registry

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

        # Build reply reference if threading (must use proper atproto models)
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

        # Register post for feedback tracing
        if HAS_REGISTRY and register_post and tracker:
            register_post(
                uri=response.uri,
                tracker=tracker,
                model=model,
                text_preview=text[:100]
            )

        # Return post reference for threading
        return {
            'uri': response.uri,
            'cid': response.cid
        }

    except Exception as e:
        print(f"Error posting to Bluesky: {e}")
        return None


def get_weekly_dev_commits() -> list:
    """Get meaningful dev commits from the past week (filter out automated data updates)."""
    try:
        result = subprocess.run(
            ['git', 'log', '--since=1 week ago', '--oneline', '--no-merges'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []

        commits = result.stdout.strip().split('\n')

        # Filter out automated commits (data updates, chart syncs)
        skip_patterns = [
            'Update chart', 'Data update', 'Update charts',
            'Sync charts', 'update data', 'Auto-update'
        ]

        meaningful = []
        for commit in commits:
            parts = commit.split(' ', 1)
            if len(parts) > 1:
                msg = parts[1]
                if not any(pattern.lower() in msg.lower() for pattern in skip_patterns):
                    meaningful.append(msg)

        return meaningful
    except Exception:
        return []


def get_weekly_weather_context() -> dict:
    """Gather weather tracking context from the past week."""
    context = {
        'warnings_tracked': [],
        'cold_signals': False,
        'models_tracked': ['GFS', 'ECM', 'AIFS', 'GEM', 'ICON', 'UKMO', 'MOGREPS'],
        'cold_duration': 0,
        'cold_temp': None
    }

    # Check alert state for cold signal history (correct file!)
    state_path = Path(__file__).parent / "data" / "alert_state.json"
    if state_path.exists():
        try:
            with open(state_path) as f:
                state = json.load(f)
                if state.get('trend_signal') == 'cold':
                    context['cold_signals'] = True
                    context['cold_duration'] = state.get('trend_run_count', 0)
                    context['cold_temp'] = state.get('trend_strength')
                    context['cold_count'] = state.get('cold_count', 0)
        except:
            pass

    return context


def generate_weekly_recap(dry_run: bool = False) -> list:
    """Generate meaningful weekly recap thread using Claude CLI."""

    dev_commits = get_weekly_dev_commits()
    weather_ctx = get_weekly_weather_context()

    # Build context for Claude
    dev_updates = "\n".join(f"- {c}" for c in dev_commits[:10]) if dev_commits else "No significant code changes this week."

    today = datetime.now(timezone.utc)
    week_start = (today - timedelta(days=7)).strftime('%d %b')
    week_end = today.strftime('%d %b')

    prompt = f"""You are WXD, writing a weekly recap thread for your Bluesky followers. This is a friendly, informal update about what's been happening with the weather tracking bot.

WEEK: {week_start} - {week_end}

WEATHER CONTEXT THIS WEEK:
- Models tracked: {', '.join(weather_ctx['models_tracked'])}
- Cold signal active: {weather_ctx.get('cold_signals', False)}
- Cold tracking: {weather_ctx.get('cold_duration', 0)} consecutive runs (~{weather_ctx.get('cold_duration', 0)//2} days)
- Coldest temp tracked: {weather_ctx.get('cold_temp', 'N/A')}°C at 850hPa
- Cold alerts issued: {weather_ctx.get('cold_count', 0)}
NOTE: If cold_signals is True with high duration, it was a COLD week with warnings - do NOT say it was mild/quiet!

DEV UPDATES THIS WEEK:
{dev_updates}

Write 4-6 posts (each max 280 chars). Detail is good - expand on the dev updates.

Post 1: Weather context opener - what the week looked like for tracking (use the stats above)
Posts 2-5: Dev updates - expand on items from the DEV UPDATES list, one topic per post, go into detail
Post 6 (optional): Looking ahead if there's something concrete

CRITICAL: Only expand on things in the DEV UPDATES list. Do NOT invent lessons, wisdom, or filler content. Every claim must trace back to a commit message above.

STYLE:
- Friendly, casual tone - talking to weather enthusiasts
- No emojis except 🧵 at start of first post to indicate thread
- Don't list commit messages literally - translate to human-readable updates
- Be honest about what happened - don't invent events
- NEVER mention chart updates, data syncs, or automated git commits - these are noise, not news
- Focus on actual features, fixes, improvements that matter to users
- Do NOT add [1/6] numbering - that's added automatically later

FORMAT RULES - CRITICAL:
- Return ONLY the actual post text, nothing else
- Separate posts with --- on its own line
- First post MUST start with 🧵
- NO meta-commentary, NO "let me write", NO explaining what you're doing
- Just the posts themselves, ready to publish

Example output:
🧵 Weekly recap: [actual content here]
---
[second post content]
---
[third post if needed]"""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0 and result.stdout.strip():
            raw = result.stdout.strip()
            posts = [p.strip() for p in raw.split('---') if p.strip()]

            # Add thread numbering
            if len(posts) > 1:
                import re
                numbered = []
                for i, post in enumerate(posts):
                    # Strip any existing numbering Claude might have added
                    post = re.sub(r'^\[\d+/\d+\]\s*', '', post)
                    # Truncate if needed
                    max_len = 280 - len(f"[{i+1}/{len(posts)}] ")
                    if len(post) > max_len:
                        post = post[:max_len-3] + "..."
                    numbered.append(f"[{i+1}/{len(posts)}] {post}")
                return numbered
            return posts

    except Exception as e:
        print(f"Claude CLI error: {e}")

    # Fallback
    return [f"🧵 WXD weekly recap: Tracked 7 models across {weather_ctx.get('cold_duration', 0)//2 or 7} days of forecasts. More detailed recaps coming soon!"]


def post_weekly(handle: str = None, password: str = None, dry_run: bool = False) -> int:
    """Post weekly recap thread to Bluesky."""
    if not handle or not password:
        print("ERROR: BSKY_HANDLE and BSKY_PASSWORD not set")
        return 1

    print("Generating weekly recap...")
    posts = generate_weekly_recap(dry_run=dry_run)

    if not posts:
        print("Failed to generate weekly recap")
        return 1

    print(f"Weekly recap thread ({len(posts)} posts):")
    for i, post in enumerate(posts):
        print(f"  [{i+1}] ({len(post)} chars): {post[:80]}...")

    if dry_run:
        print("\n" + "="*50)
        print("PREVIEW (not posting):")
        for i, post in enumerate(posts):
            print(f"\n--- Post {i+1} ---")
            print(post)
        print("="*50)
        return 0

    # Post as thread
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from lib.bluesky import BlueskyClient

        client = BlueskyClient()
        results = client.post_thread(posts, tracker='weekly', model=None)

        if results:
            print("Weekly recap posted successfully")
            return 0
        else:
            print("Failed to post weekly recap")
            return 1
    except Exception as e:
        print(f"Bluesky error: {e}")
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

    if post_to_bluesky(message, None, handle, password, tracker='changelog', model=None):
        print("Changelog posted successfully")
        return 0
    else:
        print("Failed to post changelog")
        return 1


def main():
    parser = argparse.ArgumentParser(description='WXD Bluesky Poster')
    parser.add_argument('--changelog', '-c', type=str, help='Post a changelog/update message')
    parser.add_argument('--weekly', '-w', action='store_true', help='Post weekly summary')
    parser.add_argument('--dry-run', '-n', action='store_true', help='Preview mode - run analysis but do not post to Bluesky')
    parser.add_argument('--preview', '-p', action='store_true', help='Use preview data (from fetch.py --preview) instead of production data')
    args = parser.parse_args()

    dry_run = args.dry_run
    use_preview_data = args.preview

    # Preview mode implies dry-run (never post with preview data)
    if use_preview_data:
        dry_run = True

    if dry_run or use_preview_data:
        print("=" * 50)
        if use_preview_data:
            print("FRESH PREVIEW MODE - using isolated preview data, will NOT post")
        else:
            print("DRY RUN MODE - will NOT post to Bluesky")
        print("=" * 50)
        print()

    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_path = data_dir / "history_compact.json"
    preview_summary_path = data_dir / "preview_summary.json"
    chart_path = data_dir / "chart_latest.png" if not use_preview_data else data_dir / "preview_chart.png"
    state_path = data_dir / "alert_state.json"

    # Check for credentials in environment
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    # Handle changelog mode
    if args.changelog:
        return post_changelog(args.changelog, bsky_handle, bsky_password)

    # Handle weekly recap mode
    if args.weekly:
        return post_weekly(bsky_handle, bsky_password, dry_run=dry_run)

    print(f"WXD Bluesky Poster - {utcnow().isoformat()}")
    print()

    # Check data exists
    if use_preview_data:
        if not preview_summary_path.exists():
            print(f"ERROR: {preview_summary_path} not found. Run fetch.py --preview first.")
            return 1
    else:
        if not data_path.exists():
            print(f"ERROR: {data_path} not found. Run fetch.py first.")
            return 1

    # Load data
    if use_preview_data:
        # Load fresh preview data and merge with existing history for trend analysis
        with open(preview_summary_path, 'r') as f:
            preview_summary = json.load(f)

        # Convert preview summary to run format
        preview_run = {
            "fetched_at": preview_summary.get("fetched_at"),
            "timestamps": preview_summary.get("timestamps", []),
            "models": preview_summary.get("models", {})
        }

        # Load existing history for trend comparison
        if data_path.exists():
            with open(data_path, 'r') as f:
                history_data = json.load(f)
            existing_runs = history_data.get("runs", [])
        else:
            existing_runs = []

        # Create data structure with preview as current run
        data = {
            "location": preview_summary.get("location", {}),
            "variable": preview_summary.get("variable", ""),
            "runs": [preview_run] + existing_runs
        }
        print(f"Using PREVIEW data (fresh fetch) + {len(existing_runs)} historical runs for trends")

        # Write combined data for Claude CLI to read
        preview_data_path = data_dir / "preview_combined.json"
        with open(preview_data_path, 'w') as f:
            json.dump(data, f, indent=2)
        data_path = preview_data_path  # Use this for Claude CLI
    else:
        with open(data_path, 'r') as f:
            data = json.load(f)

    # Log data provenance for audit
    runs = data.get('runs', [])
    if runs:
        current_run = runs[0]
        fetched_at = current_run.get('fetched_at', 'unknown')
        run_label = get_run_label(fetched_at)
        timestamps = current_run.get('timestamps', [])
        first_ts = timestamps[0] if timestamps else 'unknown'
        print(f"Data: fetched {fetched_at[:19]}Z, {run_label}, first_ts={first_ts}")

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
        models_crossing = cold_info.get('models', [])
        print(f"  Cold signal: {len(models_crossing)} models below -5°C")
        for m in models_crossing:
            print(f"    {m['model']}: {m['temp']}°C on {m['date']}")

        if cold_info['extreme']:
            alert_state['extreme_cold_count'] += 1
            if alert_state['extreme_cold_count'] >= HYSTERESIS_RUNS:
                cold_alert = cold_info  # Pass full info including all models
                cold_alert['type'] = 'extreme'
                print(f"  EXTREME COLD ALERT triggered (count: {alert_state['extreme_cold_count']})")
        else:
            alert_state['extreme_cold_count'] = 0

        alert_state['cold_count'] += 1
        if alert_state['cold_count'] >= HYSTERESIS_RUNS and not cold_alert:
            cold_alert = cold_info  # Pass full info including all models
            cold_alert['type'] = 'cold'
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

    # Save alert state (includes trend persistence) - skip in preview mode
    if not use_preview_data:
        save_alert_state(state_path, alert_state)
    else:
        print("  (skipping state save in preview mode)")
    print()

    # Load previous post for narrative continuity
    previous_post = alert_state.get('last_posted_commentary')
    if previous_post:
        print(f"  Previous post loaded ({len(previous_post)} chars)")

    # Generate main commentary with all analysis context
    print("Generating AI commentary...")
    text, is_fallback = get_claude_commentary(
        data_path, run_diff_text, confidence,
        percentile_info=percentile_info,
        bimodal_info=bimodal_info,
        persistence_info=persistence_info,
        timing_info=timing_info,
        cold_info=cold_info,  # For significant event detection
        previous_post=previous_post
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

    # Split long text into multiple posts if needed (Bluesky limit ~300 chars)
    def split_for_posting(text, max_chars=290):
        """Split text into posts, breaking at sentence boundaries."""
        if len(text) <= max_chars:
            return [text]

        posts = []
        remaining = text
        while remaining:
            if len(remaining) <= max_chars:
                posts.append(remaining)
                break
            # Find last sentence break within limit
            chunk = remaining[:max_chars]
            last_period = chunk.rfind('. ')
            if last_period > max_chars // 2:
                posts.append(remaining[:last_period + 1].strip())
                remaining = remaining[last_period + 2:].strip()
            else:
                # No good break point - break at space
                last_space = chunk.rfind(' ')
                if last_space > 0:
                    posts.append(remaining[:last_space].strip() + "...")
                    remaining = remaining[last_space + 1:].strip()
                else:
                    posts.append(chunk + "...")
                    remaining = remaining[max_chars:].strip()
        return posts

    main_posts = split_for_posting(main_text)

    # Build ALL posts first (main + alerts), then number them all [X/total]
    all_posts = []  # List of (text, has_image, label) tuples

    # Add main posts
    for i, post in enumerate(main_posts):
        label = "MAIN" if i == 0 else f"MAIN CONT"
        has_image = (i == 0)
        all_posts.append((post, has_image, label))

    # Build alert texts and add to list
    # Cold alert
    if cold_alert:
        models_crossing = cold_alert.get('models', [])
        is_multi = cold_alert.get('multi_model', False)
        is_extreme = cold_alert.get('extreme', False)

        if is_multi and len(models_crossing) >= 2:
            model_temps = ", ".join([f"{m['model']} {m['temp']}°C" for m in models_crossing])
            if is_extreme:
                alert_text = f"⚠️ Multi-model extreme cold: {model_temps} at 850hPa around {cold_alert['date']}. {len(models_crossing)}/4 models agree - significant snow/ice risk."
            else:
                alert_text = f"❄️ Multi-model cold signal: {model_temps} at 850hPa around {cold_alert['date']}. {len(models_crossing)}/4 models below -5°C - elevated snow risk."
        else:
            if is_extreme:
                alert_text = f"⚠️ Extreme cold signal: {cold_alert['model']} showing {cold_alert['temp']}°C at 850hPa for {cold_alert['date']}. Significant snow/ice risk if verified."
            else:
                alert_text = f"❄️ Cold signal: {cold_alert['model']} showing {cold_alert['temp']}°C at 850hPa for {cold_alert['date']}. Elevated snow risk for UK uplands."
        all_posts.append((alert_text, False, "COLD ALERT"))

    # Warm alert (summer only)
    if warm_alert:
        if warm_alert.get('extreme'):
            alert_text = f"🌡️ Extreme warmth signal: {warm_alert['model']} showing {warm_alert['temp']}°C at 850hPa for {warm_alert['date']}. Potential heatwave conditions."
        else:
            alert_text = f"☀️ Warm signal: {warm_alert['model']} showing {warm_alert['temp']}°C at 850hPa for {warm_alert['date']}. Above-average temperatures expected."
        all_posts.append((alert_text, False, "WARM ALERT"))

    # Divergence alert
    if divergence_info and divergence_info['diff'] > 6.0:
        alert_text = f"⚡ Model disagreement: {divergence_info['diff']}°C gap for {divergence_info['date']}. {divergence_info['coldest']} at {divergence_info['coldest_temp']}°C vs {divergence_info['warmest']} at {divergence_info['warmest_temp']}°C. Low confidence."
        all_posts.append((alert_text, False, "DIVERGENCE ALERT"))

    # Swing alert
    if swing_info and abs(swing_info['swing']) >= 8.0:
        alert_text = f"🔄 Pattern flip: {abs(swing_info['swing'])}°C {swing_info['direction']} expected {swing_info['start_date']} to {swing_info['end_date']}. Major temperature change incoming."
        all_posts.append((alert_text, False, "SWING ALERT"))

    # Percentile alert
    if percentile_info and percentile_info.get('pct', 0) >= 80:
        pct = int(percentile_info['pct'])
        model = percentile_info['model'].upper()
        date = percentile_info['date']
        threshold_key = percentile_info.get('threshold', 'cold')
        threshold_temp = '-8°C' if threshold_key == 'extreme' else '-5°C'
        alert_text = f"📊 High confidence: {pct}% of {model} ensemble members below {threshold_temp} by {date}. Strong agreement on cold signal."
        all_posts.append((alert_text, False, "PERCENTILE ALERT"))

    # Now number ALL posts with [X/total] - but only if more than 1 post
    total_posts = len(all_posts)
    numbered_posts = []
    for i, (text, has_image, label) in enumerate(all_posts):
        if total_posts > 1:
            numbered_text = f"[{i+1}/{total_posts}] {text}"
        else:
            numbered_text = text  # Single post - no numbering needed
        numbered_posts.append((numbered_text, has_image, label))

    # Post to Bluesky (or show preview in dry-run mode)
    if dry_run:
        print("=" * 50)
        print("PREVIEW - Would post the following:")
        print("=" * 50)
        print()
        for i, (text, has_image, label) in enumerate(numbered_posts):
            print(f"[{label}] ({len(text)} chars):")
            print(f"  {text}")
            if has_image:
                print(f"  Image: {chart_path if chart_ok else 'None'}")
            print()
        main_post_ref = {'uri': 'dry-run', 'cid': 'dry-run'}
    elif bsky_handle and bsky_password:
        print(f"Posting thread to Bluesky ({total_posts} posts)...")
        image = chart_path if chart_ok else None

        # First post with image (root of thread)
        first_text, _, first_label = numbered_posts[0]
        main_post_ref = post_to_bluesky(first_text, image, bsky_handle, bsky_password,
                                        tracker='Main', model='4-model-ensemble')
        if not main_post_ref:
            return 1
        root_post = main_post_ref

        # All subsequent posts as replies in thread
        last_ref = main_post_ref
        for i, (text, _, label) in enumerate(numbered_posts[1:], 2):
            print(f"  Posting [{i}/{total_posts}] {label}...")
            last_ref = post_to_bluesky(text, None, bsky_handle, bsky_password,
                                       reply_to=last_ref, root_post=root_post,
                                       tracker='Main', model='4-model-ensemble')
            if not last_ref:
                print(f"  Warning: post {i} failed")
                break
    else:
        print("BSKY_HANDLE and BSKY_PASSWORD not set, skipping post")
        print("Set these environment variables to enable posting")
        main_post_ref = None

    # Sync charts to GitHub Pages after successful post
    if main_post_ref and not dry_run:
        print("Syncing charts to GitHub...")
        try:
            subprocess.run(["/home/ubuntu/wxd/sync_charts.sh"], check=False, capture_output=True)
            print("  Chart sync complete")
        except Exception as e:
            print(f"  Chart sync failed: {e}")

        # Save main commentary for narrative continuity
        # Use the raw text before confidence indicator was appended
        main_commentary = text if text else ""
        alert_state['last_posted_commentary'] = main_commentary
        save_alert_state(state_path, alert_state)
        print(f"  Saved commentary for next run ({len(main_commentary)} chars)")

    print()
    print("Complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
