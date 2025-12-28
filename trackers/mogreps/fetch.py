#!/usr/bin/env python3
"""
WXD Tracker C - MOGREPS-G 850hPa Temperature Fetch

Fetches UK Met Office Global Ensemble (MOGREPS-G) data from AWS S3.
Uses NetCDF files with xarray for point extraction.

Data source: s3://met-office-global-ensemble-model-data/
Files: global-ensemble/YYYY/MM/DD/ThhmmZ/YYYYMMDDThhmmZ-PTxxxxH00M-temperature_on_pressure_levels.nc

Grid: Regular lat/lon (~20km global)
Members: 18 ensemble members
Runs: 4x daily (00z, 06z, 12z, 18z) with ~4h delay
"""

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
import warnings

# Suppress xarray FutureWarnings
warnings.filterwarnings('ignore', category=FutureWarning)

# London coordinates
LATITUDE = 51.5074
LONGITUDE = -0.1278
# MOGREPS uses 0-360 longitude convention
LONGITUDE_360 = 360 + LONGITUDE  # = 359.87

# Forecast configuration - 12-hourly intervals to match other trackers
# MOGREPS-G goes to 7 days (168h)
FORECAST_HOURS = list(range(0, 169, 12))  # 0, 12, 24, ..., 168 (15 files)
HISTORY_RUNS = 8   # 2 runs/day * 4 days (using 2 of the 4 daily runs)
RETENTION_DAYS = 7

# S3 bucket info
S3_BUCKET = "met-office-global-ensemble-model-data"
S3_PREFIX = "global-ensemble"

# Model info
MODEL = {
    "name": "mogreps-g",
    "description": "MOGREPS-G (18 members)",
    "members": 18,
    "runs": ["00z", "06z", "12z", "18z"],
    "delay_hours": 4
}


def utcnow():
    return datetime.now(timezone.utc)


def get_latest_run() -> tuple:
    """Determine the latest available model run based on current time."""
    now = utcnow()
    hour = now.hour

    # Account for ~4 hour processing delay
    available_hour = hour - MODEL["delay_hours"]

    if available_hour < 0:
        # Use previous day's 18z run
        run_date = now - timedelta(days=1)
        run_hour = 18
    elif available_hour < 6:
        # Use previous day's 18z run
        run_date = now - timedelta(days=1)
        run_hour = 18
    elif available_hour < 12:
        # Use today's 06z run
        run_date = now
        run_hour = 6
    elif available_hour < 18:
        # Use today's 12z run
        run_date = now
        run_hour = 12
    else:
        # Use today's 18z run
        run_date = now
        run_hour = 18

    # For 2x daily posting, prefer 00z and 12z
    # Adjust to nearest "main" run
    if run_hour in [6, 18]:
        # Check if we should use 00z or 12z instead
        pass  # Keep as is for now, more frequent updates

    return run_date.strftime("%Y/%m/%d"), f"{run_hour:02d}"


def get_run_label(run_hour: str) -> str:
    """Get human-readable run label."""
    return f"{run_hour}z"


def build_s3_path(run_date: str, run_hour: str, forecast_hour: int) -> str:
    """Build S3 path for a specific forecast hour file."""
    # run_date format: YYYY/MM/DD
    parts = run_date.split('/')
    date_compact = ''.join(parts)  # YYYYMMDD

    # Valid time = run_time + forecast_hour
    run_dt = datetime.strptime(f"{date_compact}{run_hour}", "%Y%m%d%H")
    valid_dt = run_dt + timedelta(hours=forecast_hour)
    valid_str = valid_dt.strftime("%Y%m%dT%H%MZ")

    # File path
    run_time_str = f"T{run_hour}00Z"
    filename = f"{valid_str}-PT{forecast_hour:04d}H00M-temperature_on_pressure_levels.nc"

    return f"{S3_PREFIX}/{run_date}/{run_time_str}/{filename}"


def fetch_forecast_hour(fs, run_date: str, run_hour: str, forecast_hour: int) -> dict:
    """Fetch one forecast hour from S3."""
    import xarray as xr

    s3_path = build_s3_path(run_date, run_hour, forecast_hour)
    full_path = f"{S3_BUCKET}/{s3_path}"

    try:
        print(f"    Fetching +{forecast_hour:03d}h...", end=" ", flush=True)

        with fs.open(full_path, 'rb') as f:
            ds = xr.open_dataset(f, engine='h5netcdf')

            # Select 850hPa (85000 Pa) and London
            point = ds['air_temperature'].sel(
                pressure=85000,
                latitude=LATITUDE,
                longitude=LONGITUDE_360,
                method='nearest'
            )

            # Get all ensemble members
            temps_k = point.values  # Kelvin
            temps_c = [float(t - 273.15) for t in temps_k]  # Celsius

            ds.close()

        if temps_c:
            print(f"-> {len(temps_c)} members, mean={mean(temps_c):.1f}C")
            return {
                "forecast_hour": forecast_hour,
                "members": [round(t, 2) for t in temps_c],
                "member_count": len(temps_c),
                "mean": round(mean(temps_c), 2),
                "min": round(min(temps_c), 2),
                "max": round(max(temps_c), 2),
                "spread": round(max(temps_c) - min(temps_c), 2)
            }
        else:
            print("no data")
            return None

    except FileNotFoundError:
        print("not available yet")
        return None
    except Exception as e:
        print(f"error: {e}")
        return None


def fetch_mogreps_data(run_date: str = None, run_hour: str = None, data_dir: Path = None) -> dict:
    """Fetch complete MOGREPS-G forecast."""
    import s3fs

    if run_date is None or run_hour is None:
        run_date, run_hour = get_latest_run()

    print(f"  Run: {run_date} {run_hour}z")

    # Connect to S3 (anonymous access)
    fs = s3fs.S3FileSystem(anon=True)

    forecasts = []
    for fh in FORECAST_HOURS:
        result = fetch_forecast_hour(fs, run_date, run_hour, fh)
        if result:
            forecasts.append(result)

    if not forecasts:
        raise ValueError("No forecast data retrieved")

    # Build timestamps from forecast hours
    parts = run_date.split('/')
    date_compact = ''.join(parts)
    run_dt = datetime.strptime(f"{date_compact}{run_hour}", "%Y%m%d%H")
    run_dt = run_dt.replace(tzinfo=timezone.utc)

    timestamps = []
    means = []
    mins = []
    maxs = []
    spreads = []

    for fc in forecasts:
        valid_time = run_dt + timedelta(hours=fc["forecast_hour"])
        timestamps.append(valid_time.isoformat().replace("+00:00", "Z"))
        means.append(fc["mean"])
        mins.append(fc["min"])
        maxs.append(fc["max"])
        spreads.append(fc["spread"])

    return {
        "fetched_at": utcnow().isoformat().replace("+00:00", "Z"),
        "run_date": run_date,
        "run_hour": run_hour,
        "run_label": get_run_label(run_hour),
        "location": {"latitude": LATITUDE, "longitude": LONGITUDE, "name": "London"},
        "variable": "temperature_850hPa",
        "units": "C",
        "model": MODEL["name"],
        "description": MODEL["description"],
        "members": MODEL["members"],
        "timestamps": timestamps,
        "mean": means,
        "min": mins,
        "max": maxs,
        "spread": spreads,
        "forecast_hours": [fc["forecast_hour"] for fc in forecasts]
    }


def update_history(current_summary: dict, data_dir: Path) -> None:
    """Update rolling history file."""
    history_path = data_dir / "history.json"

    if history_path.exists():
        with open(history_path, "r") as f:
            history = json.load(f)
    else:
        history = {
            "location": current_summary["location"],
            "variable": current_summary["variable"],
            "model": current_summary["model"],
            "runs": []
        }

    run_entry = {
        "fetched_at": current_summary["fetched_at"],
        "run_date": current_summary["run_date"],
        "run_hour": current_summary["run_hour"],
        "timestamps": current_summary["timestamps"],
        "mean": current_summary["mean"],
        "min": current_summary["min"],
        "max": current_summary["max"],
        "spread": current_summary["spread"]
    }

    history["runs"].insert(0, run_entry)
    history["runs"] = history["runs"][:HISTORY_RUNS]

    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)
    print(f"  History updated: {len(history['runs'])} runs")


def cleanup_old_files(data_dir: Path, days: int) -> int:
    """Remove files older than N days."""
    import time
    cutoff = time.time() - (days * 24 * 60 * 60)
    deleted = 0

    for f in data_dir.glob("*.json"):
        if f.name in ["summary_latest.json", "history.json", "alert_state.json",
                      "preview_summary.json"]:
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except:
            pass

    return deleted


def send_ntfy_alert(message: str) -> None:
    """Send alert via ntfy."""
    import requests
    try:
        requests.post(
            "https://ntfy.sh/wxd-alerts",
            data=f"[MOGREPS] {message}".encode('utf-8'),
            timeout=10
        )
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description='WXD MOGREPS Tracker - Fetch AWS S3 data')
    parser.add_argument('--preview', '-p', action='store_true',
                       help='Preview mode: save to isolated files')
    parser.add_argument('--run-date', help='Specific run date (YYYY/MM/DD)')
    parser.add_argument('--run-hour', help='Specific run hour (00/06/12/18)')
    args = parser.parse_args()

    preview = args.preview

    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)

    now = utcnow()
    mode_str = "PREVIEW MODE (isolated)" if preview else "Production"
    print(f"WXD MOGREPS-G Fetch - {now.isoformat().replace('+00:00', 'Z')} [{mode_str}]")
    print(f"Target: {LATITUDE}, {LONGITUDE} (London)")
    print(f"Source: AWS S3 ({S3_BUCKET})")
    print(f"Model: {MODEL['description']}")
    print()

    try:
        print("Fetching MOGREPS-G 850hPa temperature...")
        data = fetch_mogreps_data(args.run_date, args.run_hour, data_dir)

        print()
        print(f"Retrieved {len(data['timestamps'])} forecast hours")
        print(f"  First: {data['timestamps'][0]}")
        print(f"  Last:  {data['timestamps'][-1]}")

        if preview:
            summary_path = data_dir / "preview_summary.json"
            with open(summary_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"\nPreview summary saved: preview_summary.json (isolated)")
        else:
            # Timestamped file
            time_str = now.strftime("%Y-%m-%d_%H%MZ")
            summary_filename = f"summary_{time_str}.json"
            summary_path = data_dir / summary_filename
            with open(summary_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"\nSummary saved: {summary_filename}")

            # Latest copy
            latest_path = data_dir / "summary_latest.json"
            import shutil
            if latest_path.exists():
                latest_path.unlink()
            shutil.copy(summary_path, latest_path)
            print(f"Summary latest: summary_latest.json")

            # Update history
            update_history(data, data_dir)

            # Cleanup
            print(f"\nCleaning up files older than {RETENTION_DAYS} days...")
            deleted = cleanup_old_files(data_dir, RETENTION_DAYS)
            print(f"  Removed {deleted} old files")

        print()
        print("Complete: MOGREPS-G data fetched successfully")
        if preview:
            print("Preview data saved (production files unchanged)")

        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        if not preview:
            send_ntfy_alert(f"Fetch FAILED: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
