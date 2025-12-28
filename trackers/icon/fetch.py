#!/usr/bin/env python3
"""
WXD Tracker B - ICON Ensemble Fetch

Fetches ICON ensemble data from Open-Meteo.
Runs 4x daily: 00z, 06z, 12z, 18z (fetch at +4hr: 04:00, 10:00, 16:00, 22:00 UTC)

ICON-EPS: 40 ensemble members, German DWD model
"""

import argparse
import json
import requests
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

# London coordinates
LATITUDE = 51.5074
LONGITUDE = -0.1278

# Forecast configuration
FORECAST_DAYS = 7  # ICON has shorter horizon than GFS/ECM
PAST_DAYS = 1
HOURLY_VARIABLE = "temperature_850hPa"

# Retention
RETENTION_DAYS = 7
HISTORY_RUNS = 8  # 4 runs/day * 2 days

# ICON model config
MODEL = {
    "api_name": "icon_seamless",
    "description": "ICON Ensemble (40 members)",
    "members": 40,
    "runs": ["00z", "06z", "12z", "18z"],
    "delay_hours": 4
}


def utcnow():
    return datetime.now(timezone.utc)


def get_run_label(fetched_at: str) -> str:
    """Determine which model run this fetch captures."""
    try:
        dt = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
        hour = dt.hour
        # 04:00 fetch = 00z, 10:00 = 06z, 16:00 = 12z, 22:00 = 18z
        if 3 <= hour < 9:
            return "00z"
        elif 9 <= hour < 15:
            return "06z"
        elif 15 <= hour < 21:
            return "12z"
        else:
            return "18z"
    except:
        return None


def fetch_icon_data() -> dict:
    """Fetch ICON ensemble data from Open-Meteo."""
    url = "https://ensemble-api.open-meteo.com/v1/ensemble"

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": HOURLY_VARIABLE,
        "models": MODEL["api_name"],
        "forecast_days": FORECAST_DAYS,
        "past_days": PAST_DAYS,
    }

    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()
    data = response.json()

    # Add metadata
    data["_wxd_metadata"] = {
        "model": "icon",
        "description": MODEL["description"],
        "fetched_at": utcnow().isoformat().replace("+00:00", "Z"),
        "location": {"latitude": LATITUDE, "longitude": LONGITUDE, "name": "London"},
        "variable": HOURLY_VARIABLE,
        "forecast_days": FORECAST_DAYS,
        "run_info": {
            "fetch_time": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "likely_run": get_run_label(utcnow().isoformat()),
            "runs_available": MODEL["runs"],
            "typical_delay_hours": MODEL["delay_hours"]
        }
    }

    return data


def calculate_ensemble_stats(data: dict) -> dict:
    """Calculate ensemble mean, min, max, spread from raw data."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])

    # Find all ensemble member columns
    member_keys = [k for k in hourly.keys() if k.startswith(HOURLY_VARIABLE + "_member")]

    if not member_keys or not times:
        return None

    stats = {
        "timestamps": times,
        "mean": [],
        "min": [],
        "max": [],
        "spread": [],
        "members": len(member_keys)
    }

    for i in range(len(times)):
        values = []
        for key in member_keys:
            val = hourly[key][i]
            if val is not None:
                values.append(val)

        if values:
            mean_val = mean(values)
            min_val = min(values)
            max_val = max(values)
            stats["mean"].append(round(mean_val, 2))
            stats["min"].append(round(min_val, 2))
            stats["max"].append(round(max_val, 2))
            stats["spread"].append(round(max_val - min_val, 2))
        else:
            stats["mean"].append(None)
            stats["min"].append(None)
            stats["max"].append(None)
            stats["spread"].append(None)

    return stats


def generate_summary(data: dict, data_dir: Path, timestamp: datetime, preview: bool = False) -> None:
    """Generate summary JSON with ensemble stats."""
    stats = calculate_ensemble_stats(data)

    if not stats:
        print("  ERROR: Could not calculate stats")
        return

    summary = {
        "fetched_at": timestamp.isoformat().replace("+00:00", "Z"),
        "location": {"latitude": LATITUDE, "longitude": LONGITUDE, "name": "London"},
        "variable": HOURLY_VARIABLE,
        "model": "icon",
        "description": MODEL["description"],
        "timestamps": stats["timestamps"],
        "mean": stats["mean"],
        "min": stats["min"],
        "max": stats["max"],
        "spread": stats["spread"],
        "members": stats["members"]
    }

    if preview:
        summary_path = data_dir / "preview_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"  Preview summary saved: preview_summary.json (isolated)")
    else:
        # Timestamped file
        time_str = timestamp.strftime("%Y-%m-%d_%H%MZ")
        summary_filename = f"summary_{time_str}.json"
        summary_path = data_dir / summary_filename
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"  Summary saved: {summary_filename}")

        # Latest copy
        latest_path = data_dir / "summary_latest.json"
        import shutil
        if latest_path.exists():
            latest_path.unlink()
        shutil.copy(summary_path, latest_path)
        print(f"  Summary latest: summary_latest.json")

        # Update history
        update_history(summary, data_dir)


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
            "model": "icon",
            "runs": []
        }

    run_entry = {
        "fetched_at": current_summary["fetched_at"],
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
                      "preview_summary.json", "preview_icon.json"]:
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
            data=f"[ICON] {message}".encode('utf-8'),
            timeout=10
        )
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description='WXD ICON Tracker - Fetch ensemble data')
    parser.add_argument('--preview', '-p', action='store_true',
                       help='Preview mode: fetch to isolated files')
    args = parser.parse_args()

    preview = args.preview

    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)

    now = utcnow()
    mode_str = "PREVIEW MODE (isolated)" if preview else "Production"
    print(f"WXD ICON Fetch - {now.isoformat().replace('+00:00', 'Z')} [{mode_str}]")
    print(f"Target: {LATITUDE}, {LONGITUDE} (London)")
    print(f"Variable: {HOURLY_VARIABLE}")
    print(f"Model: {MODEL['description']}")
    print()

    try:
        print(f"Fetching {MODEL['description']}...")
        data = fetch_icon_data()

        if preview:
            preview_path = data_dir / "preview_icon.json"
            with open(preview_path, "w") as f:
                json.dump(data, f)
            print(f"  Saved: preview_icon.json (isolated)")
        else:
            time_str = now.strftime("%Y-%m-%d_%H%MZ")
            filename = f"icon_{time_str}.json"
            filepath = data_dir / filename
            with open(filepath, "w") as f:
                json.dump(data, f)
            print(f"  Saved: {filename}")

            # Latest copy
            latest_path = data_dir / "icon_latest.json"
            import shutil
            if latest_path.exists():
                latest_path.unlink()
            shutil.copy(filepath, latest_path)
            print(f"  Latest: icon_latest.json")

        print()
        print("Generating summary...")
        generate_summary(data, data_dir, now, preview=preview)

        if not preview:
            print()
            print(f"Cleaning up files older than {RETENTION_DAYS} days...")
            deleted = cleanup_old_files(data_dir, RETENTION_DAYS)
            print(f"  Removed {deleted} old files")

        print()
        print("Complete: ICON data fetched successfully")
        if preview:
            print("Preview data saved (production files unchanged)")

        return 0

    except requests.RequestException as e:
        print(f"ERROR: {e}")
        if not preview:
            send_ntfy_alert(f"Fetch FAILED: {e}")
        return 1
    except Exception as e:
        print(f"ERROR: {e}")
        if not preview:
            send_ntfy_alert(f"Fetch FAILED: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
