#!/usr/bin/env python3
"""
WXD Fetch Script - Retrieves ensemble weather data from Open-Meteo.

This script fetches raw JSON from the Open-Meteo ensemble API and saves
to data/ directory. No parsing or analysis - just data retrieval.

The VM runs this on a schedule; Claude Web reads the JSON from GitHub.
"""

import json
import requests
from datetime import datetime
from pathlib import Path

# London coordinates
LATITUDE = 51.5074
LONGITUDE = -0.1278

# Forecast configuration
FORECAST_DAYS = 14
HOURLY_VARIABLE = "temperature_850hPa"

# Model definitions
MODELS = {
    "gfs": {
        "api_name": "gfs_seamless",
        "description": "GFS Ensemble (31 members)"
    },
    "ecmwf": {
        "api_name": "ecmwf_ifs",
        "description": "ECMWF IFS Ensemble (51 members)"
    },
    "gem": {
        "api_name": "gem_global",
        "description": "GEM Ensemble (21 members)"
    }
}

BASE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


def fetch_model(model_key: str, model_config: dict) -> dict:
    """Fetch ensemble data for a single model."""
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": HOURLY_VARIABLE,
        "models": model_config["api_name"],
        "forecast_days": FORECAST_DAYS
    }

    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()

    # Add metadata
    data["_wxd_metadata"] = {
        "model": model_key,
        "description": model_config["description"],
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "location": {"latitude": LATITUDE, "longitude": LONGITUDE},
        "variable": HOURLY_VARIABLE
    }

    return data


def save_json(data: dict, filename: str, data_dir: Path) -> None:
    """Save JSON data to file."""
    filepath = data_dir / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {filepath}")


def main():
    """Fetch all models and save to data directory."""
    # Determine data directory (relative to script location)
    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)

    print(f"WXD Fetch - {datetime.utcnow().isoformat()}Z")
    print(f"Target: {LATITUDE}, {LONGITUDE} (London)")
    print(f"Variable: {HOURLY_VARIABLE}")
    print(f"Forecast days: {FORECAST_DAYS}")
    print()

    success_count = 0

    for model_key, model_config in MODELS.items():
        print(f"Fetching {model_config['description']}...")
        try:
            data = fetch_model(model_key, model_config)
            filename = f"{model_key}_ensemble.json"
            save_json(data, filename, data_dir)
            success_count += 1
        except requests.RequestException as e:
            print(f"  ERROR: {e}")
        except Exception as e:
            print(f"  ERROR: {e}")

    print()
    print(f"Complete: {success_count}/{len(MODELS)} models fetched")

    return 0 if success_count == len(MODELS) else 1


if __name__ == "__main__":
    exit(main())
