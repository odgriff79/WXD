#!/usr/bin/env python3
"""
WXD ECMWF Fetch - Direct from ECMWF Open Data.

Fetches 850hPa temperature ensemble data for London from:
- IFS (51 members) - physics-based
- AIFS (51 members) - AI-based

Uses ECMWF Open Data (free, no nulls).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from ecmwf.opendata import Client
import xarray as xr

# London coordinates
LATITUDE = 51.5074
LONGITUDE = -0.1278  # Will be converted to 359.87 for ECMWF grid

# Forecast steps to retrieve (hours)
STEPS = [0, 24, 48, 72, 96, 120, 144, 168, 192, 216, 240]


def utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def get_latest_run() -> int:
    """Determine which model run to fetch (0 or 12)."""
    hour = utcnow().hour
    # 00z available ~7 UTC, 12z available ~19 UTC
    if hour >= 19:
        return 12
    elif hour >= 7:
        return 0
    else:
        # Before 7 UTC, use previous day's 12z
        return 12


def fetch_ecmwf_model(model: str, run_hour: int, data_dir: Path) -> dict:
    """
    Fetch ensemble data from ECMWF Open Data.

    Args:
        model: 'ifs' or 'aifs'
        run_hour: 0 or 12
        data_dir: Directory to save temp files

    Returns:
        Dict with ensemble data for all steps
    """
    client = Client(source="ecmwf", model=model)

    results = {
        "model": model,
        "run": f"{run_hour:02d}z",
        "fetched_at": utcnow().isoformat().replace("+00:00", "Z"),
        "location": {"latitude": LATITUDE, "longitude": LONGITUDE, "name": "London"},
        "variable": "temperature_850hPa",
        "unit": "celsius",
        "steps": {},
        "members": []
    }

    # Temp file for GRIB data
    grib_file = data_dir / f"temp_{model}_{run_hour}.grib2"

    try:
        for step in STEPS:
            print(f"    Step T+{step}h...", end=" ", flush=True)

            try:
                # Retrieve ensemble data
                client.retrieve(
                    time=run_hour,
                    step=step,
                    stream="enfo",
                    type="pf",  # Perturbed forecast (50 members)
                    param="t",
                    levelist=850,
                    target=str(grib_file)
                )

                # Also get control member
                control_file = data_dir / f"temp_{model}_{run_hour}_ctrl.grib2"
                client.retrieve(
                    time=run_hour,
                    step=step,
                    stream="enfo",
                    type="cf",  # Control forecast
                    param="t",
                    levelist=850,
                    target=str(control_file)
                )

                # Open and extract London data
                ds_pf = xr.open_dataset(str(grib_file), engine="cfgrib")
                ds_cf = xr.open_dataset(str(control_file), engine="cfgrib")

                # Convert longitude for ECMWF grid (0-360)
                lon = LONGITUDE if LONGITUDE >= 0 else 360 + LONGITUDE

                london_pf = ds_pf.sel(latitude=LATITUDE, longitude=lon, method="nearest")
                london_cf = ds_cf.sel(latitude=LATITUDE, longitude=lon, method="nearest")

                # Convert to Celsius and extract values
                pf_values = [round(float(t) - 273.15, 2) for t in london_pf.t.values]
                cf_value = round(float(london_cf.t.values) - 273.15, 2)

                # Store results
                all_members = [cf_value] + pf_values  # Control + 50 perturbed = 51
                results["steps"][f"T+{step}"] = {
                    "control": cf_value,
                    "members": all_members,
                    "mean": round(sum(all_members) / len(all_members), 2),
                    "min": round(min(all_members), 2),
                    "max": round(max(all_members), 2),
                    "spread": round(max(all_members) - min(all_members), 2)
                }

                if not results["members"]:
                    results["members"] = [f"member_{i:02d}" for i in range(len(all_members))]

                print(f"OK (mean: {results['steps'][f'T+{step}']['mean']}°C)")

                ds_pf.close()
                ds_cf.close()

            except Exception as e:
                print(f"ERROR: {e}")
                results["steps"][f"T+{step}"] = {"error": str(e)}

    finally:
        # Cleanup temp files
        for f in data_dir.glob(f"temp_{model}_*.grib2"):
            try:
                f.unlink()
            except:
                pass

    return results


def main():
    """Fetch ECMWF IFS and AIFS ensemble data."""
    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)

    now = utcnow()
    run_hour = get_latest_run()

    print(f"WXD ECMWF Fetch - {now.isoformat().replace('+00:00', 'Z')}")
    print(f"Target: {LATITUDE}, {LONGITUDE} (London)")
    print(f"Variable: temperature_850hPa")
    print(f"Model run: {run_hour:02d}z")
    print()

    models = ["ifs", "aifs"]
    success_count = 0

    for model in models:
        model_key = f"ecmwf_{model}"
        print(f"Fetching ECMWF {model.upper()} Ensemble (51 members)...")

        try:
            data = fetch_ecmwf_model(model, run_hour, data_dir)

            # Save timestamped file
            timestamp = now.strftime("%Y-%m-%d_%H%MZ")
            filename = f"{model_key}_{timestamp}.json"
            filepath = data_dir / filename

            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            print(f"  Saved: {filename}")

            # Save latest copy
            import shutil
            latest_path = data_dir / f"{model_key}_latest.json"
            if latest_path.exists():
                latest_path.unlink()
            shutil.copy(filepath, latest_path)
            print(f"  Latest: {model_key}_latest.json")

            success_count += 1

        except Exception as e:
            print(f"  ERROR: {e}")

        print()

    print(f"Complete: {success_count}/{len(models)} ECMWF models fetched")
    return 0 if success_count == len(models) else 1


if __name__ == "__main__":
    exit(main())
