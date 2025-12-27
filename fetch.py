#!/usr/bin/env python3
"""
WXD Fetch Script - Retrieves ensemble weather data from Open-Meteo.

Fetches current and previous model runs for trend comparison.
Files are timestamped and retained for rolling 7-day period.

The VM runs this on a schedule; Claude Web reads the JSON from GitHub.
"""

import json
import requests
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean

# London coordinates
LATITUDE = 51.5074
LONGITUDE = -0.1278

# Forecast configuration
FORECAST_DAYS = 14
PAST_DAYS = 3  # Include previous runs for comparison
HOURLY_VARIABLE = "temperature_850hPa"

# Retention policy
RETENTION_DAYS = 7

# Model definitions with run schedules
# delay_hours: typical hours after 00z/12z before data is available
MODELS = {
    "gfs": {
        "api_name": "gfs_seamless",
        "description": "GFS Ensemble (31 members)",
        "runs": ["00z", "06z", "12z", "18z"],
        "delay_hours": 3.5
    },
    "ecmwf_ifs": {
        "api_name": "ecmwf_ifs025",
        "description": "ECMWF IFS Ensemble (51 members)",
        "runs": ["00z", "12z"],
        "delay_hours": 7
    },
    "ecmwf_aifs": {
        "api_name": "ecmwf_aifs025",
        "description": "ECMWF AIFS Ensemble (51 members, AI-based)",
        "runs": ["00z", "12z"],
        "delay_hours": 7
    },
    "gem": {
        "api_name": "gem_global",
        "description": "GEM Ensemble (21 members)",
        "runs": ["00z", "12z"],
        "delay_hours": 4
    }
}

BASE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


def utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def get_model_run_info(model_key: str) -> dict:
    """Determine which model run we're likely capturing based on current time."""
    now = utcnow()
    hour = now.hour
    model = MODELS[model_key]
    delay = model["delay_hours"]

    # Determine likely model run based on time and delay
    # e.g., at 08:00 UTC with 3.5h delay, we'd have 00z run available
    available_init_hour = hour - delay

    if "18z" in model["runs"] and available_init_hour >= 18:
        likely_run = "18z"
    elif "12z" in model["runs"] and available_init_hour >= 12:
        likely_run = "12z"
    elif "06z" in model["runs"] and available_init_hour >= 6:
        likely_run = "06z"
    else:
        likely_run = "00z"

    return {
        "fetch_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "likely_run": likely_run,
        "runs_available": model["runs"],
        "typical_delay_hours": delay
    }


def fetch_model(model_key: str, model_config: dict) -> dict:
    """Fetch ensemble data for a single model with past days for comparison."""
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": HOURLY_VARIABLE,
        "models": model_config["api_name"],
        "forecast_days": FORECAST_DAYS,
        "past_days": PAST_DAYS
    }

    response = requests.get(BASE_URL, params=params, timeout=60)
    response.raise_for_status()

    data = response.json()

    # Add rich metadata for Claude.ai analysis
    run_info = get_model_run_info(model_key)
    data["_wxd_metadata"] = {
        "model": model_key,
        "description": model_config["description"],
        "fetched_at": utcnow().isoformat().replace("+00:00", "Z"),
        "location": {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "name": "London"
        },
        "variable": HOURLY_VARIABLE,
        "forecast_days": FORECAST_DAYS,
        "past_days": PAST_DAYS,
        "run_info": run_info
    }

    return data


def calculate_ensemble_stats(data: dict) -> dict:
    """Calculate ensemble mean, min, max, spread for each timestep."""
    hourly = data.get("hourly", {})
    timestamps = hourly.get("time", [])

    # Find all member columns (temperature_850hPa_member01, etc.)
    member_keys = [k for k in hourly.keys() if k.startswith("temperature_850hPa_member")]

    if not member_keys:
        return None

    stats = {
        "timestamps": timestamps,
        "mean": [],
        "min": [],
        "max": [],
        "spread": []
    }

    # Calculate stats for each timestep
    num_timesteps = len(timestamps)
    for i in range(num_timesteps):
        values = []
        for key in member_keys:
            val = hourly[key][i]
            if val is not None:
                values.append(val)

        if values:
            mean_val = round(mean(values), 2)
            min_val = round(min(values), 2)
            max_val = round(max(values), 2)
            spread_val = round(max_val - min_val, 2)
        else:
            mean_val = min_val = max_val = spread_val = None

        stats["mean"].append(mean_val)
        stats["min"].append(min_val)
        stats["max"].append(max_val)
        stats["spread"].append(spread_val)

    return stats


def generate_summary(all_model_data: dict, data_dir: Path, timestamp: datetime) -> None:
    """Generate summary JSON with ensemble means for all models."""
    summary = {
        "fetched_at": timestamp.isoformat().replace("+00:00", "Z"),
        "location": {"latitude": LATITUDE, "longitude": LONGITUDE, "name": "London"},
        "variable": HOURLY_VARIABLE,
        "models": {}
    }

    # Get timestamps from first model (they should all match)
    timestamps = None

    for model_key, data in all_model_data.items():
        stats = calculate_ensemble_stats(data)
        if stats:
            if timestamps is None:
                timestamps = stats["timestamps"]
            summary["models"][model_key] = {
                "mean": stats["mean"],
                "min": stats["min"],
                "max": stats["max"],
                "spread": stats["spread"]
            }

    summary["timestamps"] = timestamps

    # Calculate multi-model mean (average of model means)
    if timestamps and summary["models"]:
        multi_model_mean = []
        for i in range(len(timestamps)):
            model_means = []
            for model_stats in summary["models"].values():
                val = model_stats["mean"][i]
                if val is not None:
                    model_means.append(val)
            if model_means:
                multi_model_mean.append(round(mean(model_means), 2))
            else:
                multi_model_mean.append(None)
        summary["multi_model_mean"] = multi_model_mean

    # Save timestamped summary
    time_str = timestamp.strftime("%Y-%m-%d_%H%MZ")
    summary_filename = f"summary_{time_str}.json"
    summary_path = data_dir / summary_filename
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Summary saved: {summary_filename}")

    # Save latest copy
    latest_path = data_dir / "summary_latest.json"
    if latest_path.exists():
        latest_path.unlink()
    import shutil
    shutil.copy(summary_path, latest_path)
    print(f"  Summary latest: summary_latest.json")


def get_filename(model_key: str, timestamp: datetime) -> str:
    """Generate timestamped filename for a model fetch."""
    # Format: gfs_2025-12-27_0730Z.json
    time_str = timestamp.strftime("%Y-%m-%d_%H%MZ")
    return f"{model_key}_{time_str}.json"


def save_json(data: dict, filename: str, data_dir: Path) -> None:
    """Save JSON data to file."""
    filepath = data_dir / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {filepath.name}")


def save_latest_copy(model_key: str, filename: str, data_dir: Path) -> None:
    """Create/update a 'latest' file for easy access (copy, not symlink for git)."""
    import shutil
    latest_path = data_dir / f"{model_key}_latest.json"
    source_path = data_dir / filename

    # Always copy (symlinks don't work on GitHub - they just store filename as text)
    if latest_path.exists() or latest_path.is_symlink():
        latest_path.unlink()
    shutil.copy(source_path, latest_path)
    print(f"  Latest: {latest_path.name} (copy of {filename})")


def cleanup_old_files(data_dir: Path, retention_days: int) -> int:
    """Remove files older than retention period. Returns count deleted."""
    cutoff = utcnow() - timedelta(days=retention_days)
    deleted = 0

    for filepath in data_dir.glob("*_????-??-??_????Z.json"):
        # Parse timestamp from filename
        try:
            # Extract date part: model_2025-12-27_0730Z.json
            name = filepath.stem  # model_2025-12-27_0730Z
            parts = name.rsplit("_", 2)  # ['model', '2025-12-27', '0730Z']
            if len(parts) >= 3:
                date_str = parts[-2]  # 2025-12-27
                time_str = parts[-1].replace("Z", "")  # 0730
                dt_str = f"{date_str} {time_str}"
                file_dt = datetime.strptime(dt_str, "%Y-%m-%d %H%M")
                file_dt = file_dt.replace(tzinfo=timezone.utc)

                if file_dt < cutoff:
                    filepath.unlink()
                    print(f"  Deleted old: {filepath.name}")
                    deleted += 1
        except (ValueError, IndexError):
            continue  # Skip files that don't match expected pattern

    return deleted


def main():
    """Fetch all models and save timestamped files."""
    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)

    now = utcnow()
    print(f"WXD Fetch - {now.isoformat().replace('+00:00', 'Z')}")
    print(f"Target: {LATITUDE}, {LONGITUDE} (London)")
    print(f"Variable: {HOURLY_VARIABLE}")
    print(f"Forecast days: {FORECAST_DAYS}, Past days: {PAST_DAYS}")
    print()

    success_count = 0
    all_model_data = {}

    for model_key, model_config in MODELS.items():
        print(f"Fetching {model_config['description']}...")
        try:
            data = fetch_model(model_key, model_config)
            filename = get_filename(model_key, now)
            save_json(data, filename, data_dir)
            save_latest_copy(model_key, filename, data_dir)
            all_model_data[model_key] = data
            success_count += 1
        except requests.RequestException as e:
            print(f"  ERROR: {e}")
        except Exception as e:
            print(f"  ERROR: {e}")

    print()

    # Generate summary with ensemble stats
    if all_model_data:
        print("Generating ensemble summary...")
        try:
            generate_summary(all_model_data, data_dir, now)
        except Exception as e:
            print(f"  ERROR generating summary: {e}")

    print()

    # Cleanup old files
    print(f"Cleaning up files older than {RETENTION_DAYS} days...")
    deleted = cleanup_old_files(data_dir, RETENTION_DAYS)
    print(f"  Removed {deleted} old files")

    print()
    print(f"Complete: {success_count}/{len(MODELS)} models fetched")

    return 0 if success_count == len(MODELS) else 1


if __name__ == "__main__":
    exit(main())
