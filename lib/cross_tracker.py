#!/usr/bin/env python3
"""
WXD Cross-Tracker Analysis Module

Provides unified access to all tracker data for:
- Model comparisons (specific or all)
- Historical lookups (yesterday's run, specific timestamps)
- Query parsing for natural language questions
- Context building for Claude responses

Models tracked:
- Main tracker: GFS, ECMWF IFS, ECMWF AIFS, GEM
- ICON: 40-member ensemble
- UKMO: Deterministic
- MOGREPS: 18-member ensemble
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Model definitions - maps user-friendly names to data locations
MODELS = {
    # Main tracker models (data/summary_latest.json)
    'gfs': {
        'tracker': 'main',
        'field': 'gfs',
        'description': 'GFS (NOAA)',
        'type': 'deterministic',
    },
    'ecmwf': {
        'tracker': 'main',
        'field': 'ecmwf_ifs',
        'description': 'ECMWF IFS',
        'type': 'deterministic',
        'aliases': ['ifs', 'ecmwf_ifs'],
    },
    'aifs': {
        'tracker': 'main',
        'field': 'ecmwf_aifs',
        'description': 'ECMWF AIFS (AI)',
        'type': 'deterministic',
        'aliases': ['ecmwf_aifs'],
    },
    'gem': {
        'tracker': 'main',
        'field': 'gem',
        'description': 'GEM (Canada)',
        'type': 'deterministic',
    },
    # Separate trackers
    'icon': {
        'tracker': 'icon',
        'field': 'mean',
        'description': 'ICON-EU (40 members)',
        'type': 'ensemble',
        'data_path': 'trackers/icon/data',
    },
    'ukmo': {
        'tracker': 'ukmo',
        'field': 'values',
        'description': 'UKMO Global',
        'type': 'deterministic',
        'data_path': 'trackers/ukmo/data',
    },
    'mogreps': {
        'tracker': 'mogreps',
        'field': 'mean',
        'description': 'MOGREPS-G (18 members)',
        'type': 'ensemble',
        'data_path': 'trackers/mogreps/data',
    },
}

# All model names for "compare all"
ALL_MODELS = list(MODELS.keys())

# Aliases for query parsing
MODEL_ALIASES = {
    'ifs': 'ecmwf',
    'ecmwf_ifs': 'ecmwf',
    'ecmwf_aifs': 'aifs',
    'european': 'ecmwf',
    'american': 'gfs',
    'canadian': 'gem',
    'german': 'icon',
    'uk': 'ukmo',
    'met office': 'ukmo',
    'metoffice': 'ukmo',
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse various timestamp formats."""
    formats = [
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S.%f%z',
        '%Y-%m-%dT%H:%M',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def get_data_age(fetched_at: str) -> Tuple[str, float]:
    """Get human-readable age and hours since fetch."""
    ts = parse_timestamp(fetched_at)
    if not ts:
        return "unknown", 999

    age_hours = (utcnow() - ts).total_seconds() / 3600

    if age_hours < 1:
        age_str = f"{int(age_hours * 60)}m"
    elif age_hours < 24:
        age_str = f"{age_hours:.1f}h"
    else:
        age_str = f"{age_hours / 24:.1f}d"

    return age_str, age_hours


def load_tracker_data(tracker: str, data_type: str = 'latest') -> Optional[Dict]:
    """Load data for a specific tracker.

    Args:
        tracker: 'main', 'icon', 'ukmo', or 'mogreps'
        data_type: 'latest' or 'history'

    Returns:
        Parsed JSON data or None if not found
    """
    if tracker == 'main':
        base_path = PROJECT_ROOT / 'data'
    else:
        base_path = PROJECT_ROOT / 'trackers' / tracker / 'data'

    if data_type == 'latest':
        file_path = base_path / 'summary_latest.json'
    else:
        file_path = base_path / 'history.json'

    if not file_path.exists():
        return None

    try:
        with open(file_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def load_model_data(model_name: str) -> Optional[Dict]:
    """Load current data for a specific model.

    Returns dict with:
        - values: list of temperature values
        - timestamps: list of timestamps
        - fetched_at: when data was fetched
        - run_label: run identifier (00z, 12z, etc.)
        - description: model description
        - age_str: human-readable age
        - age_hours: numeric age in hours
    """
    model_name = model_name.lower()
    model_name = MODEL_ALIASES.get(model_name, model_name)

    if model_name not in MODELS:
        return None

    model_info = MODELS[model_name]
    tracker = model_info['tracker']

    data = load_tracker_data(tracker, 'latest')
    if not data:
        return None

    # Extract values based on tracker type
    if tracker == 'main':
        models_data = data.get('models', {})
        field = model_info['field']
        if field not in models_data:
            return None
        model_data = models_data[field]
        values = model_data.get('mean', [])
        timestamps = data.get('timestamps', [])
        run_label = data.get('run_label', '')
    else:
        field = model_info['field']
        values = data.get(field, data.get('mean', []))
        timestamps = data.get('timestamps', [])
        run_label = data.get('run_label', '')

    fetched_at = data.get('fetched_at', '')
    age_str, age_hours = get_data_age(fetched_at)

    return {
        'model': model_name,
        'values': values,
        'timestamps': timestamps,
        'fetched_at': fetched_at,
        'run_label': run_label,
        'description': model_info['description'],
        'type': model_info['type'],
        'age_str': age_str,
        'age_hours': age_hours,
    }


def load_all_models() -> Dict[str, Dict]:
    """Load current data for all models."""
    result = {}
    for model_name in ALL_MODELS:
        data = load_model_data(model_name)
        if data:
            result[model_name] = data
    return result


def load_models(model_list: List[str]) -> Dict[str, Dict]:
    """Load current data for a list of models."""
    if 'all' in [m.lower() for m in model_list]:
        return load_all_models()

    result = {}
    for model_name in model_list:
        data = load_model_data(model_name)
        if data:
            result[model_name.lower()] = data
    return result


def find_coldest_point(data: Dict) -> Tuple[float, str, int]:
    """Find coldest temperature, date, and index in model data."""
    values = data.get('values', [])
    timestamps = data.get('timestamps', [])

    if not values:
        return 0.0, 'N/A', -1

    min_val = min(values)
    min_idx = values.index(min_val)
    min_ts = timestamps[min_idx] if min_idx < len(timestamps) else 'N/A'

    # Parse timestamp to readable date
    if min_ts != 'N/A':
        ts = parse_timestamp(min_ts)
        if ts:
            min_ts = ts.strftime('%a %d %b')

    return min_val, min_ts, min_idx


def find_warmest_point(data: Dict) -> Tuple[float, str, int]:
    """Find warmest temperature, date, and index in model data."""
    values = data.get('values', [])
    timestamps = data.get('timestamps', [])

    if not values:
        return 0.0, 'N/A', -1

    max_val = max(values)
    max_idx = values.index(max_val)
    max_ts = timestamps[max_idx] if max_idx < len(timestamps) else 'N/A'

    if max_ts != 'N/A':
        ts = parse_timestamp(max_ts)
        if ts:
            max_ts = ts.strftime('%a %d %b')

    return max_val, max_ts, max_idx


def compare_two_models(model_a: str, model_b: str) -> Optional[Dict]:
    """Compare two specific models."""
    data_a = load_model_data(model_a)
    data_b = load_model_data(model_b)

    if not data_a or not data_b:
        return None

    cold_a = find_coldest_point(data_a)
    cold_b = find_coldest_point(data_b)

    warm_a = find_warmest_point(data_a)
    warm_b = find_warmest_point(data_b)

    return {
        'model_a': {
            'name': model_a,
            'data': data_a,
            'coldest': {'temp': cold_a[0], 'date': cold_a[1]},
            'warmest': {'temp': warm_a[0], 'date': warm_a[1]},
        },
        'model_b': {
            'name': model_b,
            'data': data_b,
            'coldest': {'temp': cold_b[0], 'date': cold_b[1]},
            'warmest': {'temp': warm_b[0], 'date': warm_b[1]},
        },
        'cold_diff': cold_a[0] - cold_b[0],
        'timing_diff': cold_a[1] != cold_b[1],
    }


def find_agreement_and_divergence(models_data: Dict[str, Dict]) -> Dict:
    """Analyze agreement and divergence across all loaded models."""
    if not models_data:
        return {}

    # Find coldest point for each model
    cold_points = {}
    for name, data in models_data.items():
        temp, date, _ = find_coldest_point(data)
        cold_points[name] = {'temp': temp, 'date': date}

    # Calculate stats
    temps = [cp['temp'] for cp in cold_points.values()]
    dates = [cp['date'] for cp in cold_points.values()]

    if not temps:
        return {}

    avg_temp = sum(temps) / len(temps)
    temp_spread = max(temps) - min(temps)
    coldest_model = min(cold_points.items(), key=lambda x: x[1]['temp'])
    warmest_model = max(cold_points.items(), key=lambda x: x[1]['temp'])

    # Check date agreement
    unique_dates = list(set(dates))
    date_agreement = len(unique_dates) == 1

    return {
        'cold_points': cold_points,
        'avg_coldest_temp': avg_temp,
        'temp_spread': temp_spread,
        'coldest_model': coldest_model[0],
        'coldest_temp': coldest_model[1]['temp'],
        'coldest_date': coldest_model[1]['date'],
        'warmest_model': warmest_model[0],
        'warmest_temp': warmest_model[1]['temp'],
        'date_agreement': date_agreement,
        'unique_dates': unique_dates,
    }


def detect_models_in_query(text: str) -> List[str]:
    """Parse user query to extract model names mentioned."""
    text_lower = text.lower()
    found = []

    # Check for "all models" type queries
    all_patterns = [
        'all models', 'all the models', 'all trackers', 'every model',
        'everything', 'all of them', 'models showing', 'models show',
        'what do the models', 'what are the models', 'cross tracker',
        'compare all', 'full comparison', 'they all show', 'do they all',
        'all show', 'they all', 'each model', 'every tracker',
    ]
    if any(p in text_lower for p in all_patterns):
        return ['all']

    # Check each model and its aliases
    for model_name in ALL_MODELS:
        if model_name in text_lower:
            found.append(model_name)

    for alias, model_name in MODEL_ALIASES.items():
        if alias in text_lower and model_name not in found:
            found.append(model_name)

    return found


def detect_target_date(text: str) -> Optional[datetime]:
    """Detect if user is asking about a specific date.

    Returns datetime if a specific date is mentioned, None otherwise.
    """
    text_lower = text.lower()
    now = utcnow()

    # Day names
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    days_short = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

    for i, (day, day_short) in enumerate(zip(days, days_short)):
        if day in text_lower or day_short in text_lower:
            # Find next occurrence of this day
            current_weekday = now.weekday()
            target_weekday = i
            days_ahead = (target_weekday - current_weekday) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next week if today
            target = now + timedelta(days=days_ahead)
            return target.replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    # Date patterns: "23rd", "23 Jan", "Jan 23"
    date_pattern = r'(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s*)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)?'
    match = re.search(date_pattern, text_lower)
    if match:
        day_num = int(match.group(1))
        month_str = match.group(2)

        month_map = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                     'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}

        if month_str:
            month = month_map.get(month_str, now.month)
        else:
            month = now.month

        year = now.year
        # Handle year boundary
        if month < now.month or (month == now.month and day_num < now.day):
            year += 1

        try:
            return datetime(year, month, day_num, 12, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            pass

    # "tomorrow", "today"
    if 'tomorrow' in text_lower:
        return (now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    if 'today' in text_lower:
        return now.replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    return None


def detect_date_range(text: str) -> Optional[Tuple[datetime, datetime]]:
    """Detect if user is asking about a date range.

    Supports patterns like:
    - "Wednesday to Saturday"
    - "Wed - Sat"
    - "from Thursday to Sunday"
    - "between Monday and Friday"

    Returns (start_date, end_date) or None if no range found.
    """
    text_lower = text.lower()
    now = utcnow()

    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    days_short = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

    # Build pattern for day names
    day_pattern = '|'.join(days + days_short)

    # Range patterns: "X to Y", "X - Y", "from X to Y", "between X and Y"
    range_patterns = [
        rf'from\s+({day_pattern})\s+to\s+({day_pattern})',
        rf'between\s+({day_pattern})\s+and\s+({day_pattern})',
        rf'({day_pattern})\s*(?:to|-)\s*({day_pattern})',
    ]

    for pattern in range_patterns:
        match = re.search(pattern, text_lower)
        if match:
            start_day_str = match.group(1)
            end_day_str = match.group(2)

            # Convert day name to index
            def day_to_index(day_str):
                for i, (full, short) in enumerate(zip(days, days_short)):
                    if day_str == full or day_str == short:
                        return i
                return None

            start_idx = day_to_index(start_day_str)
            end_idx = day_to_index(end_day_str)

            if start_idx is not None and end_idx is not None:
                current_weekday = now.weekday()

                # Calculate days ahead for start
                start_ahead = (start_idx - current_weekday) % 7
                if start_ahead == 0:
                    start_ahead = 7

                # Calculate days ahead for end
                end_ahead = (end_idx - current_weekday) % 7
                if end_ahead == 0:
                    end_ahead = 7
                # End must be after start
                if end_ahead <= start_ahead:
                    end_ahead += 7

                start_date = (now + timedelta(days=start_ahead)).replace(
                    hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
                )
                end_date = (now + timedelta(days=end_ahead)).replace(
                    hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
                )

                return (start_date, end_date)

    # Also support "the weekend" = Saturday to Sunday
    if 'weekend' in text_lower:
        current_weekday = now.weekday()
        sat_ahead = (5 - current_weekday) % 7
        if sat_ahead == 0:
            sat_ahead = 7
        sat = (now + timedelta(days=sat_ahead)).replace(
            hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
        )
        sun = sat + timedelta(days=1)
        return (sat, sun)

    return None


def get_temps_for_range(data: Dict, start_date: datetime, end_date: datetime) -> List[Tuple[datetime, float]]:
    """Get temperatures for a date range from model data.

    Returns list of (date, temp) tuples for each day in range.
    """
    values = data.get('values', [])
    timestamps = data.get('timestamps', [])

    if not values or not timestamps:
        return []

    results = []
    current = start_date
    while current <= end_date:
        result = get_temp_for_date(data, current)
        if result:
            temp, time_str = result
            results.append((current, temp))
        current += timedelta(days=1)

    return results


def get_temp_for_date(data: Dict, target_date: datetime) -> Optional[Tuple[float, str]]:
    """Get temperature for a specific date from model data.

    Returns (temp, timestamp_str) or None if date not in data.
    """
    values = data.get('values', [])
    timestamps = data.get('timestamps', [])

    if not values or not timestamps:
        return None

    target_date_only = target_date.date()

    for i, ts_str in enumerate(timestamps):
        ts = parse_timestamp(ts_str)
        if ts and ts.date() == target_date_only:
            return (values[i], ts.strftime('%H:%M'))

    # Try to find closest match within same day
    closest_idx = None
    closest_diff = float('inf')
    for i, ts_str in enumerate(timestamps):
        ts = parse_timestamp(ts_str)
        if ts:
            diff = abs((ts - target_date).total_seconds())
            if diff < closest_diff and ts.date() == target_date_only:
                closest_diff = diff
                closest_idx = i

    if closest_idx is not None:
        ts = parse_timestamp(timestamps[closest_idx])
        return (values[closest_idx], ts.strftime('%H:%M') if ts else '??')

    return None


def detect_time_reference(text: str) -> Dict[str, str]:
    """Parse time references in query.

    Returns dict mapping context to time reference:
    - 'default': applies to all models not specifically mentioned
    - model_name: specific time for that model
    """
    text_lower = text.lower()
    result = {'default': 'latest'}

    # Common time patterns
    if 'yesterday' in text_lower:
        result['default'] = 'yesterday'
    elif 'this morning' in text_lower:
        result['default'] = 'today_morning'
    elif 'last night' in text_lower:
        result['default'] = 'yesterday_evening'

    # Specific run times
    run_pattern = r'(\d{1,2})z'
    matches = re.findall(run_pattern, text_lower)
    if matches:
        result['run_hour'] = matches[0]

    # "yesterday's X" pattern
    yesterday_model = re.search(r"yesterday'?s?\s+(\w+)", text_lower)
    if yesterday_model:
        model = yesterday_model.group(1)
        model = MODEL_ALIASES.get(model, model)
        if model in ALL_MODELS:
            result[model] = 'yesterday'

    return result


def parse_model_query(text: str) -> Dict:
    """Parse a natural language query about models.

    Returns:
        {
            'models': ['gfs', 'icon'],
            'times': {'default': 'latest', 'gfs': 'yesterday'},
            'comparison_type': 'difference' | 'all' | 'single',
            'target_date': datetime or None,
            'date_range': (start, end) or None
        }
    """
    models = detect_models_in_query(text)
    times = detect_time_reference(text)
    target_date = detect_target_date(text)
    date_range = detect_date_range(text)

    # If date range found, target_date should be None (range takes precedence)
    if date_range:
        target_date = None

    if not models:
        # No specific models mentioned - might be general question
        models = []

    if 'all' in models:
        comparison_type = 'all'
    elif len(models) >= 2:
        comparison_type = 'difference'
    elif len(models) == 1:
        comparison_type = 'single'
    else:
        comparison_type = 'general'

    return {
        'models': models,
        'times': times,
        'comparison_type': comparison_type,
        'target_date': target_date,
        'date_range': date_range,
    }


def load_historical_run(tracker: str, target_time: str) -> Optional[Dict]:
    """Load a specific historical run from history.json.

    Args:
        tracker: 'main', 'icon', 'ukmo', or 'mogreps'
        target_time: 'yesterday', 'yesterday_0z', 'yesterday_12z', or ISO timestamp

    Returns:
        Historical data entry or None
    """
    history = load_tracker_data(tracker, 'history')
    if not history:
        return None

    now = utcnow()
    runs = history.get('runs', [])
    if not runs:
        return None

    # Determine target timestamp
    if target_time == 'yesterday':
        target_date = (now - timedelta(days=1)).date()
        # Find any run from yesterday
        for run in reversed(runs):
            run_ts = parse_timestamp(run.get('fetched_at', ''))
            if run_ts and run_ts.date() == target_date:
                return run
    elif target_time.startswith('yesterday_'):
        hour = target_time.split('_')[1].replace('z', '')
        target_date = (now - timedelta(days=1)).date()
        for run in reversed(runs):
            run_label = run.get('run_label', '')
            run_ts = parse_timestamp(run.get('fetched_at', ''))
            if run_ts and run_ts.date() == target_date:
                if hour in run_label or run_label.startswith(hour):
                    return run
    else:
        # Try to parse as ISO timestamp
        target_ts = parse_timestamp(target_time)
        if target_ts:
            # Find closest run
            for run in reversed(runs):
                run_ts = parse_timestamp(run.get('fetched_at', ''))
                if run_ts and abs((run_ts - target_ts).total_seconds()) < 3600 * 6:
                    return run

    return None


def build_comparison_context(models: List[str] = None, parsed_query: Dict = None, date_range: Tuple[datetime, datetime] = None) -> str:
    """Build formatted context string for Claude.

    Can be called with:
    - models=['gfs', 'icon'] for specific comparison
    - models=['all'] for all models
    - parsed_query from parse_model_query() for complex queries (includes target_date)
    - date_range=(start, end) for range comparison
    """
    target_date = None
    if parsed_query:
        models = parsed_query.get('models', [])
        target_date = parsed_query.get('target_date')
        # Check for date range in parsed query
        if not date_range:
            date_range = parsed_query.get('date_range')

    if not models:
        models = ['all']

    if 'all' in models:
        models_data = load_all_models()
    else:
        models_data = load_models(models)

    if not models_data:
        return "No model data available."

    lines = []
    now = utcnow()

    # Header - include date range or target date if specified
    if date_range:
        start_str = date_range[0].strftime('%A %d %b')
        end_str = date_range[1].strftime('%A %d %b')
        lines.append(f"CROSS-TRACKER DATA FOR {start_str.upper()} TO {end_str.upper()} ({now.strftime('%d %b %H:%M')} UTC):")
    elif target_date:
        date_str = target_date.strftime('%A %d %b')
        lines.append(f"CROSS-TRACKER DATA FOR {date_str.upper()} ({now.strftime('%d %b %H:%M')} UTC):")
    else:
        lines.append(f"CROSS-TRACKER DATA ({now.strftime('%d %b %H:%M')} UTC):")
    lines.append("")

    # Data freshness
    freshness = []
    for name, data in sorted(models_data.items(), key=lambda x: x[1].get('age_hours', 999)):
        freshness.append(f"{name.upper()}: {data['age_str']} old ({data.get('run_label', '?')})")
    lines.append("Data freshness: " + ", ".join(freshness))
    lines.append("")

    # If date range specified, show temps for each day in range
    if date_range:
        start_date, end_date = date_range
        lines.append(f"TEMPERATURES BY DAY:")
        lines.append("")

        # Track trends per model
        model_trends = {}

        current = start_date
        while current <= end_date:
            date_str = current.strftime('%A %d %b')
            lines.append(f"  {date_str}:")
            temps_for_date = {}
            for name, data in models_data.items():
                result = get_temp_for_date(data, current)
                if result:
                    temp, time_str = result
                    temps_for_date[name] = temp
                    lines.append(f"    {name.upper()}: {temp:.1f}C")
                    # Track for trend
                    if name not in model_trends:
                        model_trends[name] = []
                    model_trends[name].append((current, temp))
                else:
                    lines.append(f"    {name.upper()}: No data")
            lines.append("")
            current += timedelta(days=1)

        # Add trend summary for range
        lines.append("TRENDS OVER RANGE:")
        for name, temps in model_trends.items():
            if len(temps) >= 2:
                first_temp = temps[0][1]
                last_temp = temps[-1][1]
                coldest = min(temps, key=lambda x: x[1])
                warmest = max(temps, key=lambda x: x[1])
                delta = last_temp - first_temp
                trend_dir = "warming" if delta > 0 else "cooling" if delta < 0 else "flat"
                lines.append(f"  {name.upper()}: {trend_dir} ({delta:+.1f}C), coldest {coldest[0].strftime('%a')}: {coldest[1]:.1f}C")

    # If target date specified, show temps for that date
    elif target_date:
        date_str = target_date.strftime('%A %d %b')
        lines.append(f"TEMPERATURES FOR {date_str}:")
        temps_for_date = {}
        for name, data in models_data.items():
            result = get_temp_for_date(data, target_date)
            if result:
                temp, time_str = result
                temps_for_date[name] = temp
                lines.append(f"  {name.upper()}: {temp:.1f}C")
            else:
                lines.append(f"  {name.upper()}: No data for this date")

        # Summary for target date
        if temps_for_date:
            temps = list(temps_for_date.values())
            coldest_model = min(temps_for_date.items(), key=lambda x: x[1])
            warmest_model = max(temps_for_date.items(), key=lambda x: x[1])
            spread = max(temps) - min(temps)
            lines.append("")
            lines.append(f"FOR {date_str}:")
            lines.append(f"  Coldest: {coldest_model[0].upper()} at {coldest_model[1]:.1f}C")
            lines.append(f"  Warmest: {warmest_model[0].upper()} at {warmest_model[1]:.1f}C")
            lines.append(f"  Spread: {spread:.1f}C")
    else:
        # No target date - show overall coldest/warmest
        lines.append("MODEL SUMMARIES:")
        for name, data in models_data.items():
            cold_temp, cold_date, _ = find_coldest_point(data)
            warm_temp, warm_date, _ = find_warmest_point(data)
            lines.append(f"  {name.upper()} ({data['description']}):")
            lines.append(f"    Coldest: {cold_temp:.1f}C on {cold_date}")
            lines.append(f"    Warmest: {warm_temp:.1f}C on {warm_date}")

        # Agreement/divergence analysis
        if len(models_data) > 1:
            lines.append("")
            analysis = find_agreement_and_divergence(models_data)
            if analysis:
                lines.append("COMPARISON:")
                lines.append(f"  Coldest model: {analysis['coldest_model'].upper()} at {analysis['coldest_temp']:.1f}C")
                lines.append(f"  Warmest model: {analysis['warmest_model'].upper()} at {analysis['warmest_temp']:.1f}C")
                lines.append(f"  Spread: {analysis['temp_spread']:.1f}C")

                if analysis['date_agreement']:
                    lines.append(f"  Timing: All models agree on {analysis['unique_dates'][0]}")
                else:
                    lines.append(f"  Timing differs: {', '.join(analysis['unique_dates'])}")

    return "\n".join(lines)


def is_model_comparison_query(text: str) -> bool:
    """Check if a query is asking about model comparison."""
    text_lower = text.lower()

    # Comparison keywords
    comparison_words = [
        'compare', 'comparison', 'differ', 'difference', 'vs', 'versus',
        'agree', 'disagree', 'showing', 'models show', 'trackers',
        'all models', 'which model', 'coldest model', 'warmest model',
    ]

    if any(word in text_lower for word in comparison_words):
        return True

    # Check if multiple models mentioned
    models = detect_models_in_query(text)
    if len(models) >= 2 or 'all' in models:
        return True

    # Single model questions like "what's ICON showing?"
    if models and any(q in text_lower for q in ['showing', 'show', 'says', 'forecast']):
        return True

    return False


def build_model_query_response_context(text: str) -> Optional[str]:
    """Build context for Claude when user asks about models.

    Returns None if not a model comparison query.
    """
    if not is_model_comparison_query(text):
        return None

    parsed = parse_model_query(text)
    return build_comparison_context(parsed_query=parsed)


# Quick test
if __name__ == '__main__':
    print("=== Cross-Tracker Module Test ===\n")

    # Test loading all models
    print("Loading all models...")
    all_data = load_all_models()
    print(f"Loaded {len(all_data)} models: {list(all_data.keys())}\n")

    # Test comparison context
    print("=== Full Comparison Context ===")
    print(build_comparison_context(['all']))

    print("\n=== Query Parsing Tests ===")
    queries = [
        "How does GFS differ from ICON?",
        "What are all the models showing?",
        "Compare UKMO and MOGREPS",
        "Is ECMWF colder than GEM?",
        "What's the latest from ICON?",
    ]
    for q in queries:
        parsed = parse_model_query(q)
        print(f"Q: {q}")
        print(f"   Models: {parsed['models']}, Type: {parsed['comparison_type']}")
