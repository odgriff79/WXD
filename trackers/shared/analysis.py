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
    if run_diff:
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

    Returns dict with shift, direction, date if significant shift found.
    """
    runs = data.get("runs", [])
    if len(runs) < 2:
        return None

    current = runs[0]
    previous = runs[1]

    curr_mean = current.get("mean", [])
    prev_mean = previous.get("mean", [])

    if not curr_mean or not prev_mean:
        return None

    # Find max difference in overlapping range
    min_len = min(len(curr_mean), len(prev_mean))
    max_diff = 0
    max_diff_idx = 0

    for i in range(min_len):
        if curr_mean[i] is not None and prev_mean[i] is not None:
            diff = curr_mean[i] - prev_mean[i]
            if abs(diff) > abs(max_diff):
                max_diff = diff
                max_diff_idx = i

    if abs(max_diff) >= SIGNIFICANT_SHIFT:
        timestamps = current.get("timestamps", [])
        date = timestamps[max_diff_idx][:10] if max_diff_idx < len(timestamps) else "unknown"
        direction = "warmer" if max_diff > 0 else "colder"
        return {
            "shift": round(max_diff, 1),
            "direction": direction,
            "date": date
        }

    return None


def analyze_run_diff_deterministic(data: dict) -> Optional[dict]:
    """Compare current run to previous run for deterministic models.

    Returns dict with shift, direction, date if significant shift found.
    """
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

    if abs(max_diff) >= SIGNIFICANT_SHIFT:
        timestamps = current.get("timestamps", [])
        date = timestamps[max_diff_idx][:10] if max_diff_idx < len(timestamps) else "unknown"
        direction = "warmer" if max_diff > 0 else "colder"
        return {
            "shift": round(max_diff, 1),
            "direction": direction,
            "date": date
        }

    return None


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
# FULL ANALYSIS PIPELINE
# ============================================================================

def run_full_analysis(
    data: dict,
    trend_state_path: Path,
    is_ensemble: bool = True
) -> Tuple[dict, dict, dict, dict, dict, str]:
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

    # Build full context for Claude
    context_parts = []

    if run_diff:
        context_parts.append(f"SHIFT: Model moved {abs(run_diff['shift'])}C {run_diff['direction']} since last run around {run_diff['date']}")

    if cold_info:
        context_parts.append(f"COLD: Mean hits {cold_info['temp']}C on {cold_info['date']}")
        if cold_info.get('min_temp'):
            context_parts.append(f"COLDEST MEMBER: {cold_info['min_temp']}C")

    trend_ctx = format_trend_context(trend_analysis)
    if trend_ctx:
        context_parts.append(trend_ctx)

    percentile_ctx = format_percentile_context(percentile_analysis)
    if percentile_ctx:
        context_parts.append(percentile_ctx)

    timing_ctx = format_timing_context(timing_analysis)
    if timing_ctx:
        context_parts.append(timing_ctx)

    full_context = "\n".join(context_parts) if context_parts else "No significant changes"

    return run_diff, cold_info, trend_analysis, percentile_analysis, timing_analysis, full_context
