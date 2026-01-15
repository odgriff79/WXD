#!/usr/bin/env python3
"""
WXD Tracker D - UKMO Deterministic 850hPa Temperature Fetch

Fetches UK Met Office Global deterministic model data from Open-Meteo.
Single deterministic run (no ensemble members) - used as benchmark line.

Runs 2x daily: 00z, 12z (with ~4 hour licensing delay)
"""

import argparse
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
import requests

# Retry config for API timeouts
MAX_RETRIES = 7
RETRY_DELAYS = [60, 120, 300, 600, 900, 1800, 3600]  # 1m, 2m, 5m, 10m, 15m, 30m, 60m

# London coordinates
LATITUDE = 51.5074
LONGITUDE = -0.1278

# Forecast configuration
FORECAST_DAYS = 7  # UKMO Global goes to ~7 days
HISTORY_RUNS = 8   # 2 runs/day * 4 days
RETENTION_DAYS = 7

# Open-Meteo API
API_URL = "https://api.open-meteo.com/v1/forecast"

# Model info
MODEL = {
    "name": "ukmo",
    "description": "UKMO Global Deterministic (~10km)",
    "type": "deterministic",
    "delay_hours": 4  # Met Office licensing delay
}


def utcnow():
    return datetime.now(timezone.utc)


def get_run_label(fetched_at: str) -> str:
    """Determine which model run this fetch likely captures."""
    try:
        dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
        hour = dt.hour
        # With 4h delay: 00z available ~04:00, 12z available ~16:00
        if 4 <= hour < 16:
            return "00z"
        else:
            return "12z"
    except:
        return None


def fetch_ukmo_data(data_dir: Path) -> dict:
    """Fetch UKMO deterministic 850hPa data from Open-Meteo."""

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "temperature_850hPa",
        "models": "ukmo_global_deterministic_10km",
        "forecast_days": FORECAST_DAYS,
        "timezone": "UTC"
    }

    # Retry loop for API timeouts
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            if attempt > 0:
                delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                print(f"  Retry {attempt}/{MAX_RETRIES} after {delay}s...")
                time.sleep(delay)
            print(f"  Fetching from Open-Meteo...")
            response = requests.get(API_URL, params=params, timeout=180)
            response.raise_for_status()
            break
        except (requests.exceptions.Timeout, requests.exceptions.HTTPError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                print(f"  Failed: {e}")
                continue
            raise last_error

    data = response.json()
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_850hPa", [])

    if not times or not temps:
        raise ValueError("No data returned from API")

    # Filter out None values and build clean arrays
    valid_data = [(t, v) for t, v in zip(times, temps) if v is not None]
    if not valid_data:
        raise ValueError("All temperature values are None")

    timestamps = [f"{t}:00Z" for t, v in valid_data]
    temperatures = [round(v, 2) for t, v in valid_data]

    fetched_at = utcnow().isoformat().replace("+00:00", "Z")
    run_label = get_run_label(fetched_at)

    # For deterministic model, min/max/mean are all the same (single value)
    # But we still compute stats for 12-hourly samples to match other trackers

    # Sample at 12-hourly intervals for consistency with ensemble trackers
    sampled_times = []
    sampled_temps = []
    for i in range(0, len(timestamps), 12):
        sampled_times.append(timestamps[i])
        sampled_temps.append(temperatures[i])

    return {
        "fetched_at": fetched_at,
        "run_label": run_label,
        "location": {"latitude": LATITUDE, "longitude": LONGITUDE, "name": "London"},
        "variable": "temperature_850hPa",
        "units": "C",
        "model": MODEL["name"],
        "description": MODEL["description"],
        "type": MODEL["type"],
        "timestamps": sampled_times,
        "values": sampled_temps,
        # For compatibility with ensemble format
        "mean": sampled_temps,
        "min": sampled_temps,
        "max": sampled_temps,
        "spread": [0.0] * len(sampled_temps)
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
        "run_label": current_summary["run_label"],
        "timestamps": current_summary["timestamps"],
        "values": current_summary["values"],
        "mean": current_summary["mean"],
        "min": current_summary["min"],
        "max": current_summary["max"]
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
    try:
        requests.post(
            "https://ntfy.sh/wxd-alerts",
            data=f"[UKMO] {message}".encode('utf-8'),
            timeout=10
        )
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description='WXD UKMO Tracker - Fetch Open-Meteo data')
    parser.add_argument('--preview', '-p', action='store_true',
                       help='Preview mode: save to isolated files')
    args = parser.parse_args()

    preview = args.preview

    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)

    now = utcnow()
    mode_str = "PREVIEW MODE (isolated)" if preview else "Production"
    print(f"WXD UKMO Fetch - {now.isoformat().replace('+00:00', 'Z')} [{mode_str}]")
    print(f"Target: {LATITUDE}, {LONGITUDE} (London)")
    print(f"Source: Open-Meteo API (ukmo_global_deterministic_10km)")
    print(f"Model: {MODEL['description']}")
    print()

    try:
        print("Fetching UKMO 850hPa temperature...")
        data = fetch_ukmo_data(data_dir)

        print()
        print(f"Retrieved {len(data['timestamps'])} data points (12-hourly)")
        print(f"  First: {data['timestamps'][0]}")
        print(f"  Last:  {data['timestamps'][-1]}")
        print(f"  Run:   {data['run_label']}")

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
        print("Complete: UKMO data fetched successfully")
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
