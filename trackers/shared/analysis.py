#!/usr/bin/env python3
"""
WXD Shared Analysis Module

Common analysis functions for all trackers:
- Trend persistence tracking
- Percentile framing (for ensemble models)
- Timing uncertainty analysis
- Run-on-run shift detection
- Cold/warm threshold checks
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# Common thresholds
COLD_THRESHOLD = -5
EXTREME_COLD = -8
WARM_THRESHOLD = 10

# Shift detection threshold
SIGNIFICANT_SHIFT = 2.0  # degrees C


def utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


# ============================================================================
# TREND PERSISTENCE TRACKING
# ============================================================================

def load_trend_state(state_path: Path) -> dict:
    """Load trend persistence state."""
    if state_path.exists():
        with open(state_path, 'r') as f:
            return json.load(f)
    return {
        "cold_signal_runs": 0,      # consecutive runs showing cold
        "warm_signal_runs": 0,      # consecutive runs showing warm
        "shift_direction": None,    # last shift direction
        "shift_runs": 0,            # consecutive runs shifting same direction
        "last_min_temp": None,      # track coldest member evolution
        "last_mean_temp": None,     # track mean evolution
    }


def save_trend_state(state_path: Path, state: dict) -> None:
    """Save trend persistence state."""
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


def update_trend_persistence(
    trend_state: dict,
    cold_info: Optional[dict],
    run_diff: Optional[dict]
) -> dict:
    """Update trend persistence counters and return trend analysis.

    Returns dict with:
        cold_persistence: number of consecutive runs showing cold
        warm_persistence: number of consecutive runs showing warm
        shift_persistence: number of consecutive runs shifting same direction
        trend_strengthening: bool if trend is strengthening
        trend_weakening: bool if trend is weakening
    """
    result = {
        "cold_persistence": 0,
        "warm_persistence": 0,
        "shift_persistence": 0,
        "trend_strengthening": False,
        "trend_weakening": False,
    }

    # Update cold signal persistence
    if cold_info and cold_info.get("temp") is not None:
        trend_state["cold_signal_runs"] = trend_state.get("cold_signal_runs", 0) + 1
        trend_state["warm_signal_runs"] = 0
        result["cold_persistence"] = trend_state["cold_signal_runs"]

        # Check if signal is strengthening (getting colder)
        last_temp = trend_state.get("last_mean_temp")
        if last_temp is not None and cold_info["temp"] < last_temp:
            result["trend_strengthening"] = True
        elif last_temp is not None and cold_info["temp"] > last_temp:
            result["trend_weakening"] = True

        trend_state["last_mean_temp"] = cold_info["temp"]
        if cold_info.get("min_temp"):
            trend_state["last_min_temp"] = cold_info["min_temp"]
    else:
        # Check for warm signal
        trend_state["cold_signal_runs"] = 0
        # Note: warm detection would need mean temps passed in

    # Update shift direction persistence
    if run_diff and not run_diff.get("confirming"):
        direction = run_diff.get("direction")
        if direction == trend_state.get("shift_direction"):
            trend_state["shift_runs"] = trend_state.get("shift_runs", 0) + 1
        else:
            trend_state["shift_direction"] = direction
            trend_state["shift_runs"] = 1
        result["shift_persistence"] = trend_state["shift_runs"]
    else:
        trend_state["shift_runs"] = 0
        trend_state["shift_direction"] = None

    return result


def format_trend_context(trend_analysis: dict) -> str:
    """Format trend persistence for Claude prompt context."""
    parts = []

    if trend_analysis["cold_persistence"] >= 2:
        parts.append(f"PERSISTENCE: Cold signal now showing for {trend_analysis['cold_persistence']} consecutive runs")
        if trend_analysis["trend_strengthening"]:
            parts.append("TREND: Signal strengthening (getting colder)")
        elif trend_analysis["trend_weakening"]:
            parts.append("TREND: Signal weakening (warming back)")

    if trend_analysis["shift_persistence"] >= 2:
        parts.append(f"DRIFT: Model has shifted same direction for {trend_analysis['shift_persistence']} consecutive runs")

    return "\n".join(parts) if parts else ""


# ============================================================================
# PERCENTILE FRAMING (for ensemble models)
# ============================================================================

def calculate_percentiles(
    values: List[float],
    percentiles: List[int] = [10, 25, 50, 75, 90]
) -> Dict[int, float]:
    """Calculate percentiles from a list of values."""
    if not values:
        return {}

    import numpy as np
    arr = np.array([v for v in values if v is not None])
    if len(arr) == 0:
        return {}

    result = {}
    for p in percentiles:
        result[p] = float(np.percentile(arr, p))
    return result


def analyze_ensemble_percentiles(data: dict) -> dict:
    """Analyze ensemble spread using percentiles.

    Returns dict with:
        coldest_p10: 10th percentile of coldest point
        coldest_p90: 90th percentile of coldest point
        spread_at_coldest: p90-p10 spread at coldest point
        spread_trend: 'widening', 'narrowing', or 'stable'
        agreement_level: 'high', 'medium', 'low' based on spread
    """
    runs = data.get("runs", [])
    if not runs:
        return {}

    current = runs[0]
    mean_temps = current.get("mean", [])
    min_temps = current.get("min", [])
    max_temps = current.get("max", [])

    if not mean_temps:
        return {}

    result = {}

    # Find coldest point index
    coldest_idx = None
    coldest_temp = None
    for i, temp in enumerate(mean_temps):
        if temp is not None:
            if coldest_temp is None or temp < coldest_temp:
                coldest_temp = temp
                coldest_idx = i

    if coldest_idx is not None and min_temps and max_temps:
        # Get spread at coldest point
        min_at_cold = min_temps[coldest_idx] if coldest_idx < len(min_temps) else None
        max_at_cold = max_temps[coldest_idx] if coldest_idx < len(max_temps) else None

        if min_at_cold is not None and max_at_cold is not None:
            spread = max_at_cold - min_at_cold
            result["coldest_p10"] = round(min_at_cold, 1)
            result["coldest_p90"] = round(max_at_cold, 1)
            result["spread_at_coldest"] = round(spread, 1)

            # Classify agreement level
            if spread < 4:
                result["agreement_level"] = "high"
            elif spread < 8:
                result["agreement_level"] = "medium"
            else:
                result["agreement_level"] = "low"

    # Compare spread evolution if we have previous run
    if len(runs) >= 2:
        prev = runs[1]
        prev_min = prev.get("min", [])
        prev_max = prev.get("max", [])

        if prev_min and prev_max and coldest_idx is not None:
            # Compare spread at similar forecast hour
            if coldest_idx < len(prev_min) and coldest_idx < len(prev_max):
                prev_spread = prev_max[coldest_idx] - prev_min[coldest_idx]
                curr_spread = result.get("spread_at_coldest", 0)

                if curr_spread > prev_spread + 1:
                    result["spread_trend"] = "widening"
                elif curr_spread < prev_spread - 1:
                    result["spread_trend"] = "narrowing"
                else:
                    result["spread_trend"] = "stable"

    return result


def format_percentile_context(percentile_analysis: dict) -> str:
    """Format percentile analysis for Claude prompt context."""
    parts = []

    if percentile_analysis.get("coldest_p10") is not None:
        p10 = percentile_analysis["coldest_p10"]
        p90 = percentile_analysis["coldest_p90"]
        parts.append(f"SPREAD: Coldest members show {p10}C, warmest {p90}C (range: {percentile_analysis.get('spread_at_coldest', '?')}C)")

    if percentile_analysis.get("agreement_level"):
        level = percentile_analysis["agreement_level"]
        if level == "high":
            parts.append("AGREEMENT: High ensemble agreement (tight spread)")
        elif level == "low":
            parts.append("AGREEMENT: Low ensemble agreement (wide spread, high uncertainty)")

    if percentile_analysis.get("spread_trend"):
        trend = percentile_analysis["spread_trend"]
        if trend == "widening":
            parts.append("EVOLUTION: Spread widening (increasing uncertainty)")
        elif trend == "narrowing":
            parts.append("EVOLUTION: Spread narrowing (converging)")

    return "\n".join(parts) if parts else ""


# ============================================================================
# TIMING UNCERTAINTY ANALYSIS
# ============================================================================

def analyze_timing_uncertainty(data: dict, threshold: float = COLD_THRESHOLD) -> dict:
    """Analyze timing uncertainty of when threshold is crossed.

    Returns dict with:
        first_crossing_date: earliest date threshold crossed
        last_crossing_date: latest date still below threshold
        timing_window_hours: hours between first and last crossing
        peak_cold_date: date of coldest point
        confidence: 'high', 'medium', 'low' based on timing spread
    """
    runs = data.get("runs", [])
    if not runs:
        return {}

    current = runs[0]
    timestamps = current.get("timestamps", [])

    # Use mean for ensemble, values for deterministic
    temps = current.get("mean", current.get("values", []))

    if not temps or not timestamps:
        return {}

    result = {}

    # Find first and last crossing of threshold
    first_crossing_idx = None
    last_crossing_idx = None
    coldest_idx = None
    coldest_temp = None

    for i, temp in enumerate(temps):
        if temp is not None:
            # Track coldest point
            if coldest_temp is None or temp < coldest_temp:
                coldest_temp = temp
                coldest_idx = i

            # Track threshold crossings
            if temp < threshold:
                if first_crossing_idx is None:
                    first_crossing_idx = i
                last_crossing_idx = i

    if first_crossing_idx is not None and coldest_idx is not None:
        try:
            first_dt = datetime.fromisoformat(timestamps[first_crossing_idx].replace('Z', '+00:00'))
            last_dt = datetime.fromisoformat(timestamps[last_crossing_idx].replace('Z', '+00:00'))
            cold_dt = datetime.fromisoformat(timestamps[coldest_idx].replace('Z', '+00:00'))

            result["first_crossing_date"] = first_dt.strftime('%Y-%m-%d')
            result["last_crossing_date"] = last_dt.strftime('%Y-%m-%d')
            result["peak_cold_date"] = cold_dt.strftime('%Y-%m-%d')

            window_hours = (last_dt - first_dt).total_seconds() / 3600
            result["timing_window_hours"] = round(window_hours, 0)

            # Classify confidence based on timing window
            if window_hours <= 24:
                result["confidence"] = "high"
            elif window_hours <= 72:
                result["confidence"] = "medium"
            else:
                result["confidence"] = "low"

        except Exception:
            pass

    return result


def format_timing_context(timing_analysis: dict) -> str:
    """Format timing uncertainty for Claude prompt context."""
    parts = []

    if timing_analysis.get("peak_cold_date"):
        parts.append(f"TIMING: Coldest point expected around {timing_analysis['peak_cold_date']}")

    if timing_analysis.get("timing_window_hours") is not None:
        hours = timing_analysis["timing_window_hours"]
        if hours > 24:
            days = round(hours / 24, 1)
            parts.append(f"WINDOW: Cold spell spans ~{days} days")

    if timing_analysis.get("confidence"):
        conf = timing_analysis["confidence"]
        if conf == "high":
            parts.append("TIMING CONFIDENCE: High (well-defined cold window)")
        elif conf == "low":
            parts.append("TIMING CONFIDENCE: Low (extended period of uncertainty)")

    return "\n".join(parts) if parts else ""


# ============================================================================
# COMMON ANALYSIS FUNCTIONS
# ============================================================================

def analyze_run_diff_ensemble(data: dict) -> Optional[dict]:
    """Compare current run to previous run for ensemble models.
    
    Compares by MATCHING VALID TIME, not array index.
    Returns confirming=True if runs agree (forecast unchanged).
    """
    runs = data.get("runs", [])
    if len(runs) < 2:
        return None

    current = runs[0]
    previous = runs[1]

    curr_mean = current.get("mean", [])
    prev_mean = previous.get("mean", [])
    curr_ts = current.get("timestamps", [])
    prev_ts = previous.get("timestamps", [])

    if not curr_mean or not prev_mean or not curr_ts or not prev_ts:
        return None

    # Build timestamp->value maps for matching by valid time
    curr_map = {ts[:13]: curr_mean[i] for i, ts in enumerate(curr_ts) 
                if i < len(curr_mean) and curr_mean[i] is not None}
    prev_map = {ts[:13]: prev_mean[i] for i, ts in enumerate(prev_ts)
                if i < len(prev_mean) and prev_mean[i] is not None}

    # Find max difference at MATCHING timestamps only
    max_diff = 0
    max_diff_ts = None
    matching_count = 0
    
    for ts_key in curr_map:
        if ts_key in prev_map:
            matching_count += 1
            diff = curr_map[ts_key] - prev_map[ts_key]
            if abs(diff) > abs(max_diff):
                max_diff = diff
                max_diff_ts = ts_key

    if matching_count < 3:
        return None

    if abs(max_diff) >= SIGNIFICANT_SHIFT:
        date = max_diff_ts[:10] if max_diff_ts else "unknown"
        direction = "warmer" if max_diff > 0 else "colder"
        return {"shift": round(max_diff, 1), "direction": direction, "date": date, "confirming": False}
    else:
        return {"shift": round(max_diff, 1), "direction": "steady", "confirming": True}


def analyze_run_diff_deterministic(data: dict) -> Optional[dict]:
    """Compare current run to previous run for deterministic models.

    CRITICAL: Compares by MATCHING VALID TIME, not array index.
    This prevents false shift claims when forecast naturally changes over time.
    
    Returns dict with shift, direction, date if significant shift found.
    Returns confirming=True if runs agree (no significant shift).
    """
    runs = data.get("runs", [])
    if len(runs) < 2:
        return None

    current = runs[0]
    previous = runs[1]

    curr_vals = current.get("values", [])
    prev_vals = previous.get("values", [])
    curr_ts = current.get("timestamps", [])
    prev_ts = previous.get("timestamps", [])

    if not curr_vals or not prev_vals or not curr_ts or not prev_ts:
        return None

    # Build timestamp->value maps for matching by valid time
    # Use first 13 chars of timestamp (YYYY-MM-DDTHH) for hourly matching
    curr_map = {}
    for i, ts in enumerate(curr_ts):
        if i < len(curr_vals) and curr_vals[i] is not None:
            curr_map[ts[:13]] = curr_vals[i]
    
    prev_map = {}
    for i, ts in enumerate(prev_ts):
        if i < len(prev_vals) and prev_vals[i] is not None:
            prev_map[ts[:13]] = prev_vals[i]

    # Find max difference at MATCHING timestamps only
    max_diff = 0
    max_diff_ts = None
    matching_count = 0

    for ts_key in curr_map:
        if ts_key in prev_map:
            matching_count += 1
            diff = curr_map[ts_key] - prev_map[ts_key]
            if abs(diff) > abs(max_diff):
                max_diff = diff
                max_diff_ts = ts_key

    if matching_count == 0:
        return None

    if abs(max_diff) >= SIGNIFICANT_SHIFT:
        date = max_diff_ts[:10] if max_diff_ts else "unknown"
        direction = "warmer" if max_diff > 0 else "colder"
        return {
            "shift": round(max_diff, 1),
            "direction": direction,
            "date": date,
            "confirming": False
        }
    else:
        # Runs agree - this is a confirming signal, not a shift
        return {
            "shift": round(max_diff, 1),
            "direction": "steady",
            "confirming": True
        }


def check_cold_threshold_ensemble(data: dict) -> Optional[dict]:
    """Check if ensemble mean crosses cold threshold.

    Returns dict with temp, min_temp, date, extreme if cold found.
    """
    runs = data.get("runs", [])
    if not runs:
        return None

    current = runs[0]
    mean_temps = current.get("mean", [])
    min_temps = current.get("min", [])
    timestamps = current.get("timestamps", [])

    if not mean_temps or not timestamps:
        return None

    # Find coldest point
    coldest_temp = None
    coldest_idx = None

    for i, temp in enumerate(mean_temps):
        if temp is not None and temp < COLD_THRESHOLD:
            if coldest_temp is None or temp < coldest_temp:
                coldest_temp = temp
                coldest_idx = i

    if coldest_temp is not None:
        date = timestamps[coldest_idx][:10] if coldest_idx < len(timestamps) else "unknown"
        min_temp = min_temps[coldest_idx] if min_temps and coldest_idx < len(min_temps) else coldest_temp
        return {
            "temp": round(coldest_temp, 1),
            "min_temp": round(min_temp, 1) if min_temp else None,
            "date": date,
            "extreme": coldest_temp <= EXTREME_COLD
        }

    return None


def check_cold_threshold_deterministic(data: dict) -> Optional[dict]:
    """Check if deterministic model crosses cold threshold.

    Returns dict with temp, date, extreme if cold found.
    """
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


# ============================================================================
# SIGNAL STRENGTH AND TIMING FRAMEWORK
# ============================================================================

def calculate_signal_strength(cold_info: dict, trend_analysis: dict) -> dict:
    """
    Calculate signal strength based on cold presence + run persistence.

    For single-model trackers, we consider:
    - Cold info present = signal exists
    - Persistence from trend_analysis

    Returns dict with:
        - level: 'locked' | 'strong' | 'emerging' | 'weak'
        - run_count: int
        - label: str
    """
    run_count = trend_analysis.get('cold_persistence', 0) if trend_analysis else 0
    has_cold = cold_info is not None and cold_info.get('temp') is not None

    if has_cold and run_count >= 5:
        level = 'high_confidence'
        label = f"High confidence (run {run_count})"
    elif has_cold and run_count >= 3:
        level = 'strong'
        label = f"Strong signal (run {run_count})"
    elif has_cold:
        level = 'emerging'
        label = "Emerging signal"
    else:
        level = 'weak'
        label = "No significant signal"

    return {
        'level': level,
        'run_count': run_count,
        'label': label
    }


def format_timing_window(cold_info: dict, timing_analysis: dict) -> dict:
    """
    Format timing as window with spread indicator.

    Returns dict with:
        - spread_label: 'tight' | 'moderate' | 'broad'
        - window: str (date or range)
        - label: str
    """
    if not cold_info:
        return None

    coldest_date = cold_info.get('date', '')

    # Check timing analysis for spread
    if timing_analysis and timing_analysis.get('spread_days'):
        spread_days = timing_analysis['spread_days']
        if spread_days <= 1:
            spread_label = 'tight'
        elif spread_days <= 2:
            spread_label = 'moderate'
        else:
            spread_label = 'broad'

        # Build window from timing analysis
        earliest = timing_analysis.get('earliest_date', coldest_date)
        latest = timing_analysis.get('latest_date', coldest_date)

        try:
            from datetime import datetime
            start_dt = datetime.fromisoformat(earliest[:10])
            end_dt = datetime.fromisoformat(latest[:10])
            window = f"{start_dt.strftime('%b %d')}-{end_dt.strftime('%b %d')}"
        except:
            window = coldest_date

        return {
            'spread_label': spread_label,
            'spread_days': round(spread_days, 1),
            'window': window,
            'label': f"Coldest period: {window} (±{round(spread_days)} days)"
        }

    # No spread info - just use the date
    return {
        'spread_label': 'tight',
        'spread_days': 0,
        'window': coldest_date,
        'label': f"Coldest around {coldest_date}"
    }


# ============================================================================
# FULL ANALYSIS PIPELINE
# ============================================================================

def run_full_analysis(
    data: dict,
    trend_state_path: Path,
    is_ensemble: bool = True
) -> Tuple[dict, dict, dict, dict, dict, dict, str]:
    """Run full analysis pipeline and return all results.

    Args:
        data: Loaded history.json data
        trend_state_path: Path to trend state file
        is_ensemble: True for ensemble models, False for deterministic

    Returns tuple of:
        run_diff: Run-on-run shift analysis
        cold_info: Cold threshold check
        trend_analysis: Trend persistence
        percentile_analysis: Percentile framing (ensemble only)
        timing_analysis: Timing uncertainty
        period_analysis: Period breakdown (short/mid/extended)
        full_context: Formatted context string for Claude
    """
    # Load trend state
    trend_state = load_trend_state(trend_state_path)

    # Run appropriate analysis
    if is_ensemble:
        run_diff = analyze_run_diff_ensemble(data)
        cold_info = check_cold_threshold_ensemble(data)
        percentile_analysis = analyze_ensemble_percentiles(data)
    else:
        run_diff = analyze_run_diff_deterministic(data)
        cold_info = check_cold_threshold_deterministic(data)
        percentile_analysis = {}

    # Trend persistence
    trend_analysis = update_trend_persistence(trend_state, cold_info, run_diff)
    save_trend_state(trend_state_path, trend_state)

    # Timing uncertainty
    timing_analysis = analyze_timing_uncertainty(data)

    # Period-based analysis
    period_analysis = analyze_by_period(data, is_ensemble)

    # Build full context for Claude
    context_parts = []

    # NEW: Signal strength (replaces vague confidence)
    signal_strength = calculate_signal_strength(cold_info, trend_analysis)
    if signal_strength and signal_strength['level'] != 'weak':
        context_parts.append(f"SIGNAL: {signal_strength['label']}")

    # NEW: Timing window
    timing_window = format_timing_window(cold_info, timing_analysis)
    if timing_window:
        context_parts.append(f"TIMING: {timing_window['label']}")

    if run_diff and not run_diff.get("confirming"):
        context_parts.append(f"SHIFT: Model moved {abs(run_diff['shift'])}C {run_diff['direction']} since last run around {run_diff['date']}")
    elif run_diff and run_diff.get("confirming"):
        context_parts.append("CONSISTENCY: Latest run confirms previous forecast (no significant change)")

    if cold_info:
        context_parts.append(f"COLD: Mean hits {cold_info['temp']}C on {cold_info['date']}")
        if cold_info.get('min_temp'):
            context_parts.append(f"COLDEST MEMBER: {cold_info['min_temp']}C")

    # Add period breakdown - KEY for commentary
    period_ctx = format_period_context(period_analysis)
    if period_ctx:
        context_parts.append(period_ctx)

    trend_ctx = format_trend_context(trend_analysis)
    if trend_ctx:
        context_parts.append(trend_ctx)

    percentile_ctx = format_percentile_context(percentile_analysis)
    if percentile_ctx:
        context_parts.append(percentile_ctx)

    # Note: Old timing context kept for compatibility but TIMING window above is preferred
    timing_ctx = format_timing_context(timing_analysis)
    if timing_ctx:
        context_parts.append(timing_ctx)

    full_context = "\n".join(context_parts) if context_parts else "No significant changes"

    return run_diff, cold_info, trend_analysis, percentile_analysis, timing_analysis, period_analysis, full_context


# ============================================================================
# PERIOD-BASED ANALYSIS
# ============================================================================

def analyze_by_period(data: dict, is_ensemble: bool = True) -> dict:
    """Analyze forecast by time period.
    
    Periods:
    - short_term: 0-72h (days 1-3) - highest confidence
    - mid_range: 72-144h (days 4-6) - medium confidence  
    - extended: 144h+ (day 7+) - lower confidence
    
    Returns dict with:
        short_term: {mean, min, max, cold_signal}
        mid_range: {mean, min, max, cold_signal}
        extended: {mean, min, max, cold_signal}
        uniform: bool - True if all periods show same pattern
        summary: str - 'cold_throughout', 'warming_late', 'cold_delayed', etc.
    """
    runs = data.get("runs", [])
    if not runs:
        return {}
    
    current = runs[0]
    timestamps = current.get("timestamps", [])
    
    # Use mean for ensemble, values for deterministic
    temps = current.get("mean", current.get("values", []))
    min_temps = current.get("min", []) if is_ensemble else []
    max_temps = current.get("max", []) if is_ensemble else []
    
    if not temps or not timestamps:
        return {}
    
    # Parse timestamps and categorize by period
    from datetime import datetime, timedelta
    
    try:
        first_ts = datetime.fromisoformat(timestamps[0].replace('Z', '+00:00'))
    except:
        return {}
    
    short_term = {"temps": [], "mins": [], "maxs": []}  # 0-72h
    mid_range = {"temps": [], "mins": [], "maxs": []}   # 72-144h
    extended = {"temps": [], "mins": [], "maxs": []}    # 144h+
    
    for i, ts_str in enumerate(timestamps):
        if i >= len(temps) or temps[i] is None:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            hours_from_start = (ts - first_ts).total_seconds() / 3600
            
            temp = temps[i]
            min_t = min_temps[i] if i < len(min_temps) else None
            max_t = max_temps[i] if i < len(max_temps) else None
            
            if hours_from_start <= 72:
                short_term["temps"].append(temp)
                if min_t: short_term["mins"].append(min_t)
                if max_t: short_term["maxs"].append(max_t)
            elif hours_from_start <= 144:
                mid_range["temps"].append(temp)
                if min_t: mid_range["mins"].append(min_t)
                if max_t: mid_range["maxs"].append(max_t)
            else:
                extended["temps"].append(temp)
                if min_t: extended["mins"].append(min_t)
                if max_t: extended["maxs"].append(max_t)
        except:
            continue
    
    # Calculate stats for each period
    def period_stats(period_data):
        temps = period_data["temps"]
        if not temps:
            return None
        return {
            "mean": round(sum(temps) / len(temps), 1),
            "min": round(min(temps), 1),
            "max": round(max(temps), 1),
            "cold_signal": min(temps) < COLD_THRESHOLD,
            "extreme_cold": min(temps) < EXTREME_COLD,
            "ensemble_min": round(min(period_data["mins"]), 1) if period_data["mins"] else None,
            "ensemble_max": round(max(period_data["maxs"]), 1) if period_data["maxs"] else None,
        }
    
    result = {
        "short_term": period_stats(short_term),
        "mid_range": period_stats(mid_range),
        "extended": period_stats(extended),
    }
    
    # Determine if pattern is uniform or divergent
    # IMPORTANT: Check both MIN (cold_signal) and MAX to detect warming within cold periods
    # For ensembles: also check ensemble_max - warmest members may show warming the mean hides
    patterns = []
    for period_name in ["short_term", "mid_range", "extended"]:
        stats = result.get(period_name)
        if stats:
            has_cold = stats["cold_signal"]  # min < -5C

            # Detect warming from MEAN temps
            temp_range = stats["max"] - stats["min"]
            mean_warming = stats["max"] > -3 or temp_range > 4

            # For ensembles: check if warmest MEMBERS show warming (ensemble_max)
            # This catches cases where mean is cold but some members show recovery
            ens_max = stats.get("ensemble_max")
            ensemble_warming = ens_max is not None and ens_max > -2  # Members reaching near-freezing

            has_warming = mean_warming or ensemble_warming

            if has_cold and has_warming:
                patterns.append("recovering")  # Cold min but warming max
            elif has_cold:
                patterns.append("cold")
            elif stats["mean"] > 5:
                patterns.append("mild")
            else:
                patterns.append("neutral")
    
    # Check TREND across periods: are means rising or falling?
    st_mean = result.get("short_term", {}).get("mean")
    mr_mean = result.get("mid_range", {}).get("mean")
    ext_mean = result.get("extended", {}).get("mean") if result.get("extended") else None

    trend_warming = False
    trend_cooling = False
    if st_mean is not None and mr_mean is not None:
        # Compare short_term to mid_range
        if mr_mean > st_mean + 1.5:  # >1.5C warming
            trend_warming = True
        elif mr_mean < st_mean - 1.5:  # >1.5C cooling
            trend_cooling = True

        # Also check extended if available
        if ext_mean is not None:
            if ext_mean > st_mean + 2:  # Significant warming trend
                trend_warming = True
            elif ext_mean < st_mean - 2:  # Significant cooling trend
                trend_cooling = True

    result["trend_warming"] = trend_warming
    result["trend_cooling"] = trend_cooling

    # Check uniformity - handle "recovering" as distinct from pure "cold"
    result["patterns"] = patterns  # Store for debugging
    unique_patterns = set(patterns)

    if len(unique_patterns) <= 1:
        result["uniform"] = True
        if patterns and patterns[0] == "cold":
            result["summary"] = "cold_throughout"
        elif patterns and patterns[0] == "recovering":
            result["summary"] = "cold_but_recovering"  # Shows warming throughout
        elif patterns and patterns[0] == "mild":
            result["summary"] = "mild_throughout"
        else:
            result["summary"] = "neutral_throughout"
    else:
        result["uniform"] = False
        # Determine pattern type - handle "recovering" explicitly
        if "recovering" in patterns:
            if patterns[-1] == "cold":
                result["summary"] = "cold_recovering_then_cold"  # Warming mid-period then cold again
            elif patterns[0] == "cold" or patterns[0] == "recovering":
                result["summary"] = "cold_early_recovering"  # Cold start, warming later
            else:
                result["summary"] = "mixed_with_recovery"
        elif patterns[0] == "cold" and patterns[-1] != "cold":
            result["summary"] = "cold_early_recovering"
        elif patterns[0] != "cold" and patterns[-1] == "cold":
            result["summary"] = "cold_delayed"
        elif patterns[0] == "cold" and len(patterns) > 2 and patterns[1] != "cold" and patterns[2] == "cold":
            result["summary"] = "cold_interrupted"
        else:
            result["summary"] = "mixed_pattern"
    
    return result


def format_period_context(period_analysis: dict) -> str:
    """Format period analysis for Claude prompt context.

    IMPORTANT: Always show RANGE (min to max) not just min, so warming trends are visible.
    """
    if not period_analysis:
        return ""

    parts = []
    summary = period_analysis.get("summary", "")
    patterns = period_analysis.get("patterns", [])

    # Always show pattern for debugging
    if patterns:
        parts.append(f"PATTERN: {' -> '.join(patterns)} ({summary.replace('_', ' ')})")

    # Helper to format period with FULL RANGE including ensemble spread
    def format_period(name: str, data: dict, label: str) -> str:
        if not data:
            return ""
        signal = "COLD" if data.get("cold_signal") else "OK"
        # ALWAYS show range to reveal warming within cold periods
        range_str = f"{data['min']}C to {data['max']}C"
        result = f"  {label}: mean {data['mean']}C, range {range_str} [{signal}]"

        # For ensembles: show member spread if available - this reveals warming in outliers
        ens_min = data.get("ensemble_min")
        ens_max = data.get("ensemble_max")
        if ens_min is not None and ens_max is not None:
            result += f" (members: {ens_min}C to {ens_max}C)"
        return result

    if period_analysis.get("uniform") and "recovering" not in summary:
        # Simple summary for truly uniform patterns (no warming)
        if summary == "cold_throughout":
            st = period_analysis.get("short_term", {})
            ext = period_analysis.get("extended", {})
            st_range = f"{st.get('min', '?')} to {st.get('max', '?')}" if st else "?"
            ext_range = f"{ext.get('min', '?')} to {ext.get('max', '?')}" if ext else "?"
            parts.append(f"PERIODS: Cold throughout - days 1-3 range {st_range}C, day 7+ range {ext_range}C")
        elif summary == "mild_throughout":
            parts.append("PERIODS: Mild throughout forecast")
        else:
            parts.append("PERIODS: Near-normal throughout")
    else:
        # Detailed breakdown showing FULL RANGE for each period
        # This makes warming trends visible even within cold periods
        parts.append("EXTENDED RANGE COVERAGE:")

        st = period_analysis.get("short_term")
        if st:
            parts.append(format_period("short_term", st, "Days 1-3"))

        mr = period_analysis.get("mid_range")
        if mr:
            parts.append(format_period("mid_range", mr, "Days 4-6"))

        ext = period_analysis.get("extended")
        if ext:
            parts.append(format_period("extended", ext, "Day 7+"))

        # CRITICAL: Explicit guidance for Claude on recovery patterns
        if "recovering" in patterns or "recovery" in summary:
            parts.append("NOTE: Recovery pattern detected - mention warming trend in commentary")

    # Add cross-period TREND info
    if period_analysis.get("trend_warming"):
        st = period_analysis.get("short_term", {}).get("mean", "?")
        ext = period_analysis.get("extended", {}).get("mean") or period_analysis.get("mid_range", {}).get("mean", "?")
        parts.append(f"TREND: Warming through forecast period ({st}C → {ext}C) - MUST MENTION")
    elif period_analysis.get("trend_cooling"):
        st = period_analysis.get("short_term", {}).get("mean", "?")
        ext = period_analysis.get("extended", {}).get("mean") or period_analysis.get("mid_range", {}).get("mean", "?")
        parts.append(f"TREND: Cooling through forecast period ({st}C → {ext}C) - MUST MENTION")

    return "\n".join(parts)
