#!/usr/bin/env python3
"""
SSW Monitor for WXD - GEFS Ensemble-Based (Hardened)
Computes true SSW probability from GEFS 31-member ensemble

Based on standard major SSW criterion:
  Zonal-mean zonal wind at 10 hPa, 60°N reverses to easterly (U10 < 0)

Run with --debug on first use to verify NOMADS variable/coord names.
"""
import xarray as xr
import numpy as np
import json
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === CONFIG ===
OUTPUT_DIR = Path('/home/owen/wxd/ssw')
CACHE_DIR = OUTPUT_DIR / 'cache'

# SSW detection thresholds (m/s)
THRESHOLDS = {
    'ssw_trigger': 0,      # Easterly = major SSW (standard definition)
    'vulnerable': 10,      # Vortex weakening
}

# Alert probability thresholds (% of ensemble members)
PROB_THRESHOLDS = {
    'watch': 10,           # >= 10% members
    'alert': 25,           # >= 25% members
    'strong': 50,          # >= 50% members
}

# Forecast window for SSW detection (days)
LEAD_WINDOW = (5, 16)

# === DYNAMIC DIMENSION DETECTION ===
# GEFS uses various naming conventions; detect dynamically
ENS_CANDIDATES = ("ens", "member", "ens_member", "ensmem", "ensemble")
TIME_CANDIDATES = ("time", "valid_time", "forecast_time")
LAT_CANDIDATES = ("lat", "latitude")
LON_CANDIDATES = ("lon", "longitude")
LEV_CANDIDATES = ("lev", "isobaric", "isobaricInhPa", "level", "plev")

# Variable name candidates for U-wind on pressure levels
UGRD_CANDIDATES = ("ugrdprs", "ugrd", "u", "uwnd")


def pick_dim(da, candidates, context=""):
    """Find first matching dimension name from candidates."""
    for c in candidates:
        if c in da.dims:
            return c
    raise ValueError(f"[{context}] None of {candidates} found in dims={list(da.dims)}")


def pick_coord(ds, candidates, context=""):
    """Find first matching coordinate name from candidates."""
    for c in candidates:
        if c in ds.coords:
            return c
    raise ValueError(f"[{context}] None of {candidates} found in coords={list(ds.coords)}")


def pick_var(ds, candidates, context=""):
    """Find first matching variable name from candidates."""
    for c in candidates:
        if c in ds.data_vars:
            return c
    raise ValueError(f"[{context}] None of {candidates} found in vars={list(ds.data_vars)}")


def get_gefs_cycle_url(run_date: datetime, cycle: str = '00') -> str:
    """
    Construct GEFS OPeNDAP URL for given date/cycle.
    
    GEFS via NOMADS OPeNDAP is at:
      https://nomads.ncep.noaa.gov/dods/gefs/gefs{YYYYMMDD}/gefs_pgrb2ap5_{CC}z
    
    Verify by checking: https://nomads.ncep.noaa.gov/dods/gefs/
    """
    date_str = run_date.strftime('%Y%m%d')
    # pgrb2ap5 = pressure gribs, 0.5 degree, all members
    # Alternatives that may exist: gefs_pgrb2sp25 (0.25deg), etc.
    return f"https://nomads.ncep.noaa.gov/dods/gefs/gefs{date_str}/gefs_pgrb2ap5_{cycle}z"


def debug_dataset_structure(url: str):
    """
    One-time debug: print dataset structure to verify variable/coord names.
    Run this on the Oracle VM first to confirm naming conventions.
    """
    print(f"\n{'='*60}")
    print(f"DEBUG: Inspecting GEFS dataset structure")
    print(f"URL: {url}")
    print(f"{'='*60}\n")
    
    try:
        ds = xr.open_dataset(url)
        
        print("COORDINATES:")
        for name, coord in ds.coords.items():
            print(f"  {name}: shape={coord.shape}, dtype={coord.dtype}")
            if len(coord) <= 10:
                print(f"      values: {coord.values}")
            else:
                print(f"      first 5: {coord.values[:5]}")
                print(f"      last 5:  {coord.values[-5:]}")
        
        print("\nDIMENSIONS:")
        for dim, size in ds.dims.items():
            print(f"  {dim}: {size}")
        
        print("\nDATA VARIABLES:")
        for name, var in ds.data_vars.items():
            print(f"  {name}: dims={var.dims}, shape={var.shape}")
        
        print("\n" + "="*60)
        print("DETECTION TEST:")
        try:
            lev_coord = pick_coord(ds, LEV_CANDIDATES, "level")
            print(f"  Level coord: '{lev_coord}' -> values: {ds[lev_coord].values[:10]}...")
        except ValueError as e:
            print(f"  Level coord: FAILED - {e}")
        
        try:
            ugrd_var = pick_var(ds, UGRD_CANDIDATES, "U-wind")
            print(f"  U-wind var: '{ugrd_var}' -> dims: {ds[ugrd_var].dims}")
        except ValueError as e:
            print(f"  U-wind var: FAILED - {e}")
        
        ds.close()
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def fetch_gefs_u10_ensemble(run_date: datetime = None, cycle: str = '00') -> dict:
    """
    Fetch 10hPa zonal wind from GEFS ensemble via OPeNDAP.
    Returns zonal-mean U-wind at 60°N for all ensemble members.
    
    Uses dynamic dimension detection to handle NOMADS naming variations.
    """
    if run_date is None:
        run_date = datetime.now(timezone.utc)
    
    url = get_gefs_cycle_url(run_date, cycle)
    logger.info(f"Fetching GEFS from: {url}")
    
    try:
        ds = xr.open_dataset(url)
        
        # === DYNAMIC DETECTION ===
        lev_coord = pick_coord(ds, LEV_CANDIDATES, "level")
        lat_coord = pick_coord(ds, LAT_CANDIDATES, "latitude")
        lon_coord = pick_coord(ds, LON_CANDIDATES, "longitude")
        ugrd_var = pick_var(ds, UGRD_CANDIDATES, "U-wind")
        
        logger.info(f"Detected: lev={lev_coord}, lat={lat_coord}, lon={lon_coord}, var={ugrd_var}")
        
        # === SELECT 10 hPa LEVEL ===
        # GEFS typically uses hPa (millibars), but check units
        lev_values = ds[lev_coord].values
        
        # Find closest level to 10 hPa
        target_level = 10
        if lev_values.max() > 1100:
            # Stored in Pa, convert target
            target_level = 1000  # 10 hPa = 1000 Pa
        
        u_wind = ds[ugrd_var]
        
        # Select level FIRST (with nearest), then lat band
        u_wind = u_wind.sel(**{lev_coord: target_level}, method='nearest')
        
        # === SELECT 60°N LATITUDE BAND ===
        # Check latitude direction (N→S vs S→N)
        lat_vals = ds[lat_coord].values
        lat_ascending = lat_vals[0] < lat_vals[-1]
        
        # 58-62°N band for 60°N zonal mean
        if lat_ascending:
            lat_slice = slice(58, 62)
        else:
            lat_slice = slice(62, 58)
        
        # Apply lat slice SEPARATELY
        u_wind = u_wind.sel(**{lat_coord: lat_slice})
        
        # === ZONAL MEAN ===
        # Average over longitude and latitude band
        zonal_mean = u_wind.mean(dim=[lon_coord, lat_coord])
        
        # === DETECT ENSEMBLE AND TIME DIMS ===
        ens_dim = pick_dim(zonal_mean, ENS_CANDIDATES, "ensemble")
        time_dim = pick_dim(zonal_mean, TIME_CANDIDATES, "time")
        
        logger.info(f"Zonal mean dims: {zonal_mean.dims}, ens={ens_dim}, time={time_dim}")
        
        n_members = zonal_mean.sizes[ens_dim]
        
        ds.close()
        
        return {
            'success': True,
            'data': zonal_mean,
            'ens_dim': ens_dim,
            'time_dim': time_dim,
            'run_date': run_date.isoformat(),
            'cycle': cycle,
            'n_members': n_members,
            'url': url,
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch GEFS: {e}")
        return {'success': False, 'error': str(e), 'run_date': run_date.isoformat()}


def compute_ssw_probability(zonal_mean_data: xr.DataArray,
                            ens_dim: str,
                            time_dim: str,
                            lead_window_days: tuple = LEAD_WINDOW) -> dict:
    """
    Compute SSW probability from ensemble U10 data.
    
    SSW probability = % of members where min(U10) < 0 over forecast window
    
    Uses timestamp-based window detection (not step count) for robustness.
    """
    # === COMPUTE TIME WINDOW FROM ACTUAL TIMESTAMPS ===
    times = zonal_mean_data[time_dim].values
    t0 = times[0]
    
    # Convert to days from forecast start
    dt_days = (times - t0) / np.timedelta64(1, 'D')
    
    # Boolean mask for lead window
    mask = (dt_days >= lead_window_days[0]) & (dt_days <= lead_window_days[1])
    valid_indices = np.where(mask)[0]
    
    if len(valid_indices) == 0:
        logger.warning(f"No timesteps in window day {lead_window_days[0]}-{lead_window_days[1]}")
        # Fallback: use all available
        valid_indices = np.arange(len(times))
    
    # Subset to forecast window
    window_data = zonal_mean_data.isel(**{time_dim: valid_indices})
    
    # === COMPUTE STATISTICS ===
    # For each member: find minimum U10 in window
    min_u10_per_member = window_data.min(dim=time_dim)
    
    n_members = zonal_mean_data.sizes[ens_dim]
    
    # Count members with reversal (U10 < 0 = major SSW criterion)
    n_reversals = int((min_u10_per_member < THRESHOLDS['ssw_trigger']).sum().values)
    n_vulnerable = int((min_u10_per_member < THRESHOLDS['vulnerable']).sum().values)
    
    ssw_prob = (n_reversals / n_members) * 100
    vulnerable_prob = (n_vulnerable / n_members) * 100
    
    # Ensemble mean and spread
    ens_mean = float(window_data.mean().values)
    ens_min = float(min_u10_per_member.min().values)
    ens_max = float(min_u10_per_member.max().values)
    
    # Current analysis (first timestep, ensemble mean)
    current_u10 = float(zonal_mean_data.isel(**{time_dim: 0}).mean(dim=ens_dim).values)
    
    # Actual window range used
    actual_days = (dt_days[valid_indices[0]], dt_days[valid_indices[-1]])
    
    return {
        'ssw_probability': round(ssw_prob, 1),
        'vulnerable_probability': round(vulnerable_prob, 1),
        'n_members': n_members,
        'n_reversals': n_reversals,
        'ensemble_mean_u10': round(ens_mean, 1),
        'ensemble_min_u10': round(ens_min, 1),
        'ensemble_max_u10': round(ens_max, 1),
        'current_u10': round(current_u10, 1),
        'lead_window': f"Day {actual_days[0]:.1f}-{actual_days[1]:.1f}",
        'n_timesteps_in_window': len(valid_indices),
    }


def determine_alert_level(ssw_prob: float, current_u10: float) -> dict:
    """
    Determine alert level based on probability and current state.
    """
    if ssw_prob >= PROB_THRESHOLDS['strong']:
        level = 'STRONG'
        color = 'red'
    elif ssw_prob >= PROB_THRESHOLDS['alert']:
        level = 'ALERT'
        color = 'orange'
    elif ssw_prob >= PROB_THRESHOLDS['watch']:
        level = 'WATCH'
        color = 'yellow'
    else:
        level = 'NORMAL'
        color = 'green'
    
    # Vortex state description
    if current_u10 > 30:
        vortex_state = 'strong'
    elif current_u10 > 15:
        vortex_state = 'moderate'
    elif current_u10 > 0:
        vortex_state = 'weak'
    else:
        vortex_state = 'reversed'
    
    return {
        'level': level,
        'color': color,
        'vortex_state': vortex_state,
        'should_alert': level in ['ALERT', 'STRONG'],
    }


def get_ecmwf_chart_url(run_date: datetime = None) -> str:
    """
    Get ECMWF extended zonal wind chart URL for corroboration.
    
    This is the correct ECMWF product: Sub-seasonal range ensemble U10@60N.
    Just returns the URL (no fragile API parsing).
    """
    if run_date is None:
        run_date = datetime.now(timezone.utc)
    
    # ECMWF extended range: 00z and 12z runs
    base_time = run_date.strftime('%Y%m%d') + '0000'
    
    return (
        f"https://charts.ecmwf.int/products/extended-zonal-mean-zonal-wind"
        f"?area=nh&base_time={base_time}"
    )


def select_gefs_cycle(now: datetime) -> tuple[datetime, str]:
    """
    Select which GEFS cycle to use based on current time.
    Allow 4-5 hours for GEFS processing/availability.
    """
    hour = now.hour
    
    # Cycle availability (approximate):
    # 00z ready by ~05z, 06z ready by ~11z, 12z ready by ~17z, 18z ready by ~23z
    if 5 <= hour < 11:
        return now, '00'
    elif 11 <= hour < 17:
        return now, '06'
    elif 17 <= hour < 23:
        return now, '12'
    else:
        # After 23z or before 05z: use yesterday's 18z
        if hour < 5:
            return now - timedelta(days=1), '18'
        else:
            return now, '18'


def run_ssw_monitor(debug: bool = False) -> dict:
    """
    Main monitoring routine.
    """
    run_time = datetime.now(timezone.utc)
    logger.info(f"SSW monitor starting at {run_time.isoformat()}")
    
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Select GEFS cycle
    run_date, cycle = select_gefs_cycle(run_time)
    
    # Debug mode: just inspect dataset structure
    if debug:
        url = get_gefs_cycle_url(run_date, cycle)
        success = debug_dataset_structure(url)
        return {'debug': True, 'success': success, 'url': url}
    
    # Fetch GEFS ensemble data
    gefs_result = fetch_gefs_u10_ensemble(run_date, cycle)
    
    if not gefs_result['success']:
        # Try previous cycle as fallback
        logger.warning(f"Primary cycle failed, trying fallback...")
        prev_cycles = [('18', -1), ('12', 0), ('06', 0), ('00', 0)]
        cycle_idx = {'00': 0, '06': 1, '12': 2, '18': 3}[cycle]
        
        for i in range(1, 4):
            fallback_idx = (cycle_idx - i) % 4
            fb_cycle = ['00', '06', '12', '18'][fallback_idx]
            fb_date = run_date - timedelta(days=1) if fallback_idx > cycle_idx else run_date
            
            gefs_result = fetch_gefs_u10_ensemble(fb_date, fb_cycle)
            if gefs_result['success']:
                logger.info(f"Fallback succeeded: {fb_date.strftime('%Y%m%d')}/{fb_cycle}z")
                break
    
    if not gefs_result['success']:
        error_output = {
            'timestamp': run_time.isoformat(),
            'status': 'error',
            'error': gefs_result.get('error', 'Unknown error'),
        }
        # Still save error state
        (OUTPUT_DIR / 'ssw_status.json').write_text(json.dumps(error_output, indent=2))
        return error_output
    
    # Compute SSW probability
    ssw_stats = compute_ssw_probability(
        gefs_result['data'],
        gefs_result['ens_dim'],
        gefs_result['time_dim']
    )
    
    # Determine alert level
    alert_info = determine_alert_level(
        ssw_stats['ssw_probability'],
        ssw_stats['current_u10']
    )
    
    # Get ECMWF chart URL for corroboration
    ecmwf_url = get_ecmwf_chart_url(run_date)
    
    # Compile output
    output = {
        'timestamp': run_time.isoformat(),
        'model_run': f"{run_date.strftime('%Y%m%d')}/{cycle}z",
        'status': 'ok',
        
        # Primary metrics (what WeatherIsCool shows)
        'ssw_probability_pct': ssw_stats['ssw_probability'],
        'vulnerable_probability_pct': ssw_stats['vulnerable_probability'],
        'current_u10_60n_ms': ssw_stats['current_u10'],
        
        # Ensemble statistics
        'ensemble': {
            'n_members': ssw_stats['n_members'],
            'n_reversals': ssw_stats['n_reversals'],
            'mean_u10': ssw_stats['ensemble_mean_u10'],
            'min_u10': ssw_stats['ensemble_min_u10'],
            'max_u10': ssw_stats['ensemble_max_u10'],
        },
        
        # Alert status
        'alert': alert_info,
        
        # Metadata
        'lead_window': ssw_stats['lead_window'],
        'n_timesteps': ssw_stats['n_timesteps_in_window'],
        
        # ECMWF corroboration (URL only, no fragile API)
        'ecmwf_chart_url': ecmwf_url,
        
        # Definition reference
        'ssw_definition': 'Major SSW = zonal-mean zonal wind at 10 hPa, 60°N reverses to easterly (U < 0)',
    }
    
    # Save output
    output_file = OUTPUT_DIR / 'ssw_status.json'
    output_file.write_text(json.dumps(output, indent=2))
    logger.info(f"Saved: {output_file}")
    
    # Alert logging
    if alert_info['should_alert']:
        logger.warning(
            f"⚠️  SSW {alert_info['level']}: "
            f"{ssw_stats['ssw_probability']:.0f}% probability | "
            f"Current U10: {ssw_stats['current_u10']:.1f} m/s | "
            f"Vortex: {alert_info['vortex_state']}"
        )
    else:
        logger.info(
            f"SSW status: {alert_info['level']} | "
            f"{ssw_stats['ssw_probability']:.0f}% prob | "
            f"U10: {ssw_stats['current_u10']:.1f} m/s"
        )
    
    return output


def main():
    parser = argparse.ArgumentParser(
        description='SSW Monitor - GEFS ensemble-based sudden stratospheric warming probability'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Debug mode: inspect GEFS dataset structure and exit'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output JSON to stdout'
    )
    
    args = parser.parse_args()
    
    result = run_ssw_monitor(debug=args.debug)
    
    if args.json or args.debug:
        print(json.dumps(result, indent=2))
    
    # Exit code based on status
    if result.get('status') == 'error':
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
