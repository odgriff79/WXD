#!/usr/bin/env python3
"""
SSW Monitor - First Run Verification Script

Run this ONCE on your Oracle VM to:
1. Verify GEFS OPeNDAP directory listing
2. Check exact variable/coordinate names
3. Confirm the monitor will work

Usage:
    python3 ssw_verify.py
"""
import sys
from datetime import datetime, timezone

def check_requests():
    """Check if requests is available."""
    try:
        import requests
        return True
    except ImportError:
        print("❌ requests not installed. Run: pip install requests --break-system-packages")
        return False


def check_xarray():
    """Check if xarray + netcdf4 are available."""
    try:
        import xarray as xr
        import netCDF4
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Run: pip install xarray netCDF4 --break-system-packages")
        return False


def list_gefs_directory():
    """List available GEFS datasets in today's OPeNDAP directory."""
    import requests
    
    d = datetime.now(timezone.utc).strftime("%Y%m%d")
    url = f"https://nomads.ncep.noaa.gov/dods/gefs/gefs{d}/"
    
    print(f"\n{'='*60}")
    print(f"Step 1: Checking GEFS OPeNDAP directory")
    print(f"URL: {url}")
    print(f"{'='*60}\n")
    
    try:
        resp = requests.get(url, timeout=30)
        print(f"Status: {resp.status_code}")
        
        if resp.status_code == 200:
            # Parse the HTML listing for dataset names
            content = resp.text
            
            # Look for dataset links (they typically end in _00z, _06z, etc.)
            import re
            datasets = re.findall(r'gefs_[a-z0-9_]+_\d{2}z', content)
            datasets = sorted(set(datasets))
            
            if datasets:
                print(f"\n✅ Found {len(datasets)} datasets:")
                for ds in datasets:
                    print(f"   - {ds}")
                return datasets
            else:
                print("⚠️  Could not parse dataset names from listing")
                print(f"Raw content preview:\n{content[:1500]}")
                return []
        else:
            print(f"❌ Failed to access directory: {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return []


def inspect_gefs_dataset(dataset_name: str = None):
    """Inspect a specific GEFS dataset structure."""
    import xarray as xr
    
    d = datetime.now(timezone.utc).strftime("%Y%m%d")
    
    # Default to common dataset name if not specified
    if dataset_name is None:
        dataset_name = "gefs_pgrb2ap5_00z"
    
    url = f"https://nomads.ncep.noaa.gov/dods/gefs/gefs{d}/{dataset_name}"
    
    print(f"\n{'='*60}")
    print(f"Step 2: Inspecting dataset structure")
    print(f"URL: {url}")
    print(f"{'='*60}\n")
    
    try:
        print("Opening dataset (this may take 30-60 seconds)...")
        ds = xr.open_dataset(url)
        
        print("\n✅ Dataset opened successfully!\n")
        
        # Dimensions
        print("DIMENSIONS:")
        for dim, size in ds.dims.items():
            print(f"   {dim}: {size}")
        
        # Coordinates
        print("\nCOORDINATES:")
        for name, coord in ds.coords.items():
            print(f"   {name}: shape={coord.shape}, dtype={coord.dtype}")
            vals = coord.values
            if len(vals) <= 8:
                print(f"      values: {vals}")
            else:
                print(f"      first 4: {vals[:4]}")
                print(f"      last 4:  {vals[-4:]}")
        
        # Data variables (just names, there are usually hundreds)
        print(f"\nDATA VARIABLES ({len(ds.data_vars)} total):")
        
        # Find U-wind variable
        ugrd_candidates = ['ugrdprs', 'ugrd', 'u', 'uwnd']
        found_ugrd = None
        for var in ugrd_candidates:
            if var in ds.data_vars:
                found_ugrd = var
                break
        
        if found_ugrd:
            print(f"\n   ✅ U-wind variable found: '{found_ugrd}'")
            uvar = ds[found_ugrd]
            print(f"      dims: {uvar.dims}")
            print(f"      shape: {uvar.shape}")
        else:
            print(f"\n   ⚠️  No U-wind variable found in {ugrd_candidates}")
            print("      Available variables starting with 'u':")
            for var in sorted(ds.data_vars):
                if var.startswith('u'):
                    print(f"         - {var}")
        
        # Summary for config
        print(f"\n{'='*60}")
        print("CONFIGURATION SUMMARY")
        print(f"{'='*60}")
        
        # Detect likely names
        ens_dim = None
        for c in ['ens', 'member', 'ensemble']:
            if c in ds.dims:
                ens_dim = c
                break
        
        lev_coord = None
        for c in ['lev', 'isobaric', 'level']:
            if c in ds.coords:
                lev_coord = c
                break
        
        lat_coord = None
        for c in ['lat', 'latitude']:
            if c in ds.coords:
                lat_coord = c
                break
        
        print(f"   Ensemble dim: {ens_dim or 'NOT FOUND'}")
        print(f"   Level coord:  {lev_coord or 'NOT FOUND'}")
        print(f"   Lat coord:    {lat_coord or 'NOT FOUND'}")
        print(f"   U-wind var:   {found_ugrd or 'NOT FOUND'}")
        
        if lev_coord:
            lev_vals = ds[lev_coord].values
            if 10 in lev_vals:
                print(f"   10 hPa level: ✅ Available")
            elif 1000 in lev_vals:
                print(f"   10 hPa level: ✅ Available (as 1000 Pa)")
            else:
                print(f"   10 hPa level: ⚠️  Check levels: {lev_vals[:10]}...")
        
        ds.close()
        
        print(f"\n{'='*60}")
        print("✅ Verification complete! The ssw_monitor.py should work.")
        print(f"{'='*60}\n")
        
        return True
        
    except Exception as e:
        print(f"❌ Error opening dataset: {e}")
        return False


def main():
    print("\n" + "="*60)
    print("SSW Monitor - First Run Verification")
    print("="*60)
    
    # Check dependencies
    print("\nChecking dependencies...")
    if not check_requests():
        sys.exit(1)
    if not check_xarray():
        sys.exit(1)
    print("✅ Dependencies OK\n")
    
    # List available datasets
    datasets = list_gefs_directory()
    
    if not datasets:
        print("\n⚠️  Could not list datasets. Trying default name anyway...")
    
    # Find the best dataset to inspect
    # Prefer: gefs_pgrb2ap5_00z (0.5 deg, all members, pressure levels)
    preferred = ['gefs_pgrb2ap5_00z', 'gefs_pgrb2ap5_12z', 'gefs_pgrb2sp25_00z']
    
    dataset_to_check = None
    for pref in preferred:
        if pref in datasets:
            dataset_to_check = pref
            break
    
    if dataset_to_check is None and datasets:
        # Pick the first one that looks like pressure gribs
        for ds in datasets:
            if 'pgrb' in ds:
                dataset_to_check = ds
                break
    
    if dataset_to_check is None:
        dataset_to_check = "gefs_pgrb2ap5_00z"  # Default guess
    
    print(f"\nWill inspect: {dataset_to_check}")
    
    # Inspect the dataset
    success = inspect_gefs_dataset(dataset_to_check)
    
    if success:
        print("\nNext steps:")
        print("1. Copy ssw_monitor.py to your Oracle VM")
        print("2. Run: python3 ssw_monitor.py --debug")
        print("3. If that works, set up cron (see crontab example)")
        print("4. Output will be in /home/owen/wxd/ssw/ssw_status.json")
    else:
        print("\n⚠️  Verification failed. Check the errors above.")
        print("You may need to adjust variable names in ssw_monitor.py")
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
