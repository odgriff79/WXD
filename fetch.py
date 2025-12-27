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
    "ecmwf": {
        "api_name": "ecmwf_ifs",
        "description": "ECMWF IFS Ensemble (51 members)",
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


def save_latest_symlink(model_key: str, filename: str, data_dir: Path) -> None:
    """Create/update a 'latest' file for easy access."""
    latest_path = data_dir / f"{model_key}_latest.json"
    source_path = data_dir / filename

    # On Windows, copy instead of symlink; on Unix, use symlink
    if os.name == 'nt':
        import shutil
        if latest_path.exists():
            latest_path.unlink()
        shutil.copy(source_path, latest_path)
    else:
        if latest_path.exists() or latest_path.is_symlink():
            latest_path.unlink()
        latest_path.symlink_to(filename)
    print(f"  Latest: {latest_path.name} -> {filename}")


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

    for model_key, model_config in MODELS.items():
        print(f"Fetching {model_config['description']}...")
        try:
            data = fetch_model(model_key, model_config)
            filename = get_filename(model_key, now)
            save_json(data, filename, data_dir)
            save_latest_symlink(model_key, filename, data_dir)
            success_count += 1
        except requests.RequestException as e:
            print(f"  ERROR: {e}")
        except Exception as e:
            print(f"  ERROR: {e}")

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
