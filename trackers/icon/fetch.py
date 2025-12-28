#!/usr/bin/env python3
"""
WXD Tracker B - ICON-EU-EPS 850hPa Temperature Fetch

Fetches ICON-EU ensemble 850hPa temperature data from DWD Open Data.
Uses GRIB2 files with point extraction for London coordinates.

Data source: https://opendata.dwd.de/weather/nwp/icon-eu-eps/grib/
Files: icon-eu-eps_europe_icosahedral_pressure-level_YYYYMMDDHH_FFF_850_t.grib2.bz2

Runs 4x daily: 00z, 06z, 12z, 18z (fetch at +4hr delay)
"""

import argparse
import bz2
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
import requests

# London coordinates
LATITUDE = 51.5074
LONGITUDE = -0.1278

# Forecast configuration - 12-hourly intervals to minimize downloads
# Available: hourly 0-48, then 3-hourly to 120
# Using: 0, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120 (11 files, ~110MB total)
FORECAST_HOURS = list(range(0, 121, 12))  # 0 to 120 hours, every 12h (5 days)
HISTORY_RUNS = 8  # 4 runs/day * 2 days
RETENTION_DAYS = 7

# DWD base URL for ICON-EU-EPS
DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-eu-eps/grib"

# Model info
# Note: Pressure-level 850hPa data only available for 00z and 12z runs
# (06z/18z only have model-level data, not pressure-level)
MODEL = {
    "name": "icon-eu-eps",
    "description": "ICON-EU Ensemble (40 members)",
    "members": 40,
    "runs": ["00z", "12z"],  # Only these have pressure-level 850hPa
    "delay_hours": 4
}


def utcnow():
    return datetime.now(timezone.utc)


def get_latest_run() -> tuple:
    """Determine the latest available model run based on current time.

    Note: Only 00z and 12z runs have pressure-level 850hPa data.
    """
    now = utcnow()
    hour = now.hour

    # Account for ~4 hour processing delay
    available_hour = hour - MODEL["delay_hours"]

    if available_hour < 0:
        # Use previous day's 12z run
        run_date = now - timedelta(days=1)
        run_hour = 12
    elif available_hour < 12:
        # Use today's 00z run
        run_date = now
        run_hour = 0
    else:
        # Use today's 12z run
        run_date = now
        run_hour = 12

    return run_date.strftime("%Y%m%d"), f"{run_hour:02d}"


def get_run_label(run_hour: str) -> str:
    """Get human-readable run label."""
    return f"{run_hour}z"


def build_file_url(run_date: str, run_hour: str, forecast_hour: int) -> str:
    """Build URL for a specific GRIB file."""
    filename = f"icon-eu-eps_europe_icosahedral_pressure-level_{run_date}{run_hour}_{forecast_hour:03d}_850_t.grib2.bz2"
    return f"{DWD_BASE}/{run_hour}/t/{filename}"


def check_grib_tools_available() -> bool:
    """Check if eccodes grib_ls is installed."""
    try:
        result = subprocess.run(['grib_ls', '-V'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False


def extract_london_point(grib_path: Path) -> list:
    """
    Extract London grid point values from GRIB file using eccodes grib_ls.
    Returns list of temperature values in Celsius.
    """
    try:
        # Use grib_ls with -l option for nearest point extraction
        # Format: -l lat,lon,mode (mode 1 = nearest neighbor)
        result = subprocess.run(
            ['grib_ls', '-l', f'{LATITUDE},{LONGITUDE},1', '-p', 'perturbationNumber', str(grib_path)],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            print(f"    grib_ls error: {result.stderr}")
            return []

        # Parse output - grib_ls outputs a table with columns
        # The -l option adds "value" column with interpolated value
        # Example output:
        # perturbationNumber value
        # 1                  273.15
        # 2                  274.20
        # ...
        values = []
        lines = result.stdout.strip().split('\n')

        for line in lines:
            # Skip header lines and empty lines
            if not line or 'perturbationNumber' in line or 'messages' in line:
                continue

            parts = line.split()
            if len(parts) >= 2:
                try:
                    # Last column should be the value
                    temp_kelvin = float(parts[-1])
                    temp_celsius = temp_kelvin - 273.15
                    values.append(temp_celsius)
                except ValueError:
                    continue

        return values

    except subprocess.TimeoutExpired:
        print("    grib_ls timeout")
        return []
    except Exception as e:
        print(f"    grib_ls error: {e}")
        return []


def fetch_forecast_hour(run_date: str, run_hour: str, forecast_hour: int, work_dir: Path) -> dict:
    """
    Fetch and process one forecast hour.
    Returns dict with member temperatures.
    """
    url = build_file_url(run_date, run_hour, forecast_hour)

    try:
        # Download compressed file
        print(f"    Fetching +{forecast_hour:03d}h...", end=" ", flush=True)
        response = requests.get(url, timeout=120)

        if response.status_code == 404:
            print("not available yet")
            return None

        response.raise_for_status()
        compressed_size = len(response.content) / 1024 / 1024
        print(f"({compressed_size:.1f}MB)", end=" ", flush=True)

        # Save compressed file
        bz2_path = work_dir / f"temp_{forecast_hour:03d}.grib2.bz2"
        with open(bz2_path, 'wb') as f:
            f.write(response.content)

        # Decompress
        grib_path = work_dir / f"temp_{forecast_hour:03d}.grib2"
        with bz2.open(bz2_path, 'rb') as f_in:
            with open(grib_path, 'wb') as f_out:
                f_out.write(f_in.read())

        # Remove compressed file immediately
        bz2_path.unlink()

        # Extract London point
        temps = extract_london_point(grib_path)

        # Remove decompressed file
        grib_path.unlink()

        if temps:
            # Sanity check: expect ~40 ensemble members
            if len(temps) < 35 or len(temps) > 45:
                print(f"WARNING: Expected ~40 members, got {len(temps)}")
            print(f"→ {len(temps)} members, mean={mean(temps):.1f}°C")
            return {
                "forecast_hour": forecast_hour,
                "members": temps,
                "member_count": len(temps),
                "mean": round(mean(temps), 2),
                "min": round(min(temps), 2),
                "max": round(max(temps), 2),
                "spread": round(max(temps) - min(temps), 2)
            }
        else:
            print("no data extracted - check wgrib2 output")
            return None

    except requests.RequestException as e:
        print(f"download error: {e}")
        return None
    except Exception as e:
        print(f"error: {e}")
        return None


def fetch_icon_data(run_date: str = None, run_hour: str = None) -> dict:
    """
    Fetch complete ICON-EU-EPS forecast.
    Processes files one at a time to minimize disk usage.
    """
    if run_date is None or run_hour is None:
        run_date, run_hour = get_latest_run()

    print(f"  Run: {run_date} {run_hour}z")

    # Check eccodes grib_ls
    if not check_grib_tools_available():
        raise RuntimeError("eccodes grib_ls not installed - required for GRIB processing")

    # Use temp directory for processing
    with tempfile.TemporaryDirectory() as work_dir:
        work_path = Path(work_dir)

        forecasts = []
        for fh in FORECAST_HOURS:
            result = fetch_forecast_hour(run_date, run_hour, fh, work_path)
            if result:
                forecasts.append(result)

    if not forecasts:
        raise ValueError("No forecast data retrieved")

    # Build timestamps from forecast hours
    run_dt = datetime.strptime(f"{run_date}{run_hour}", "%Y%m%d%H")
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
        "units": "C",  # Converted from Kelvin
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
    try:
        requests.post(
            "https://ntfy.sh/wxd-alerts",
            data=f"[ICON] {message}".encode('utf-8'),
            timeout=10
        )
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description='WXD ICON Tracker - Fetch DWD GRIB data')
    parser.add_argument('--preview', '-p', action='store_true',
                       help='Preview mode: save to isolated files')
    parser.add_argument('--run-date', help='Specific run date (YYYYMMDD)')
    parser.add_argument('--run-hour', help='Specific run hour (00/06/12/18)')
    args = parser.parse_args()

    preview = args.preview

    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)

    now = utcnow()
    mode_str = "PREVIEW MODE (isolated)" if preview else "Production"
    print(f"WXD ICON-EU-EPS Fetch - {now.isoformat().replace('+00:00', 'Z')} [{mode_str}]")
    print(f"Target: {LATITUDE}, {LONGITUDE} (London)")
    print(f"Source: DWD Open Data GRIB2")
    print(f"Model: {MODEL['description']}")
    print()

    try:
        print("Fetching ICON-EU-EPS 850hPa temperature...")
        data = fetch_icon_data(args.run_date, args.run_hour)

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
        print("Complete: ICON-EU-EPS data fetched successfully")
        if preview:
            print("Preview data saved (production files unchanged)")

        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        if not preview:
            send_ntfy_alert(f"Fetch FAILED: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
