# WXD-Direct Phase 8: Evaluation Plan

## Context
WXD-Direct fetches 850hPa temperature directly from meteorological agency GRIB/NetCDF files instead of Open-Meteo API. Goal: verify data quality before potential production use.

**Location:** London (51.5N, 0.1W)
**Variable:** 850hPa temperature (T850)
**Models implemented:** GFS, IFS, AIFS, GEM, MOGREPS, UKMO, ICON

## Current Data (2025-12-31)

| Model | Temp (K) | Temp (C) | Run Time | Valid Time |
|-------|----------|----------|----------|------------|
| GFS | 268.12 | -5.03 | 2025-12-31 00z | 2025-12-31 00z |
| IFS | 268.50 | -4.65 | 2025-12-31 00z | 2025-12-31 00z |
| GEM | 268.22 | -4.93 | 2025-12-31 00z | 2025-12-31 00z |
| UKMO | 268.25 | -4.90 | 2025-12-31 00z | 2025-12-31 00z |
| ICON | 268.39 | -4.76 | 2025-12-31 00z | 2025-12-31 00z |
| AIFS | 271.34 | -1.81 | 2025-12-31 06z | 2025-12-31 06z |
| MOGREPS | 273.93 | +0.78 | **None** | **None** |

## Identified Problems

### CRITICAL: MOGREPS missing metadata
- `run_time` and `valid_time` are NULL
- Without this, we cannot compare to other models
- Temperature is 6K warmer than main cluster - impossible to diagnose without timing info

### CONCERN: AIFS 3K warmer than cluster
- AIFS shows -1.8C vs -4.5 to -5C for others
- BUT: AIFS valid_time is 06z, others are 00z
- This MIGHT be legitimate (warmer later in day)
- OR: extraction bug in AIFS fetcher

### QUESTION: Are we comparing apples to apples?
- Different valid times across models
- Need to ensure all comparisons use SAME forecast target time

## Proposed Evaluation Steps

### Step 1: Fix MOGREPS Metadata
- Debug mogreps.py to extract and store run_time/valid_time
- Verify we're reading correct NetCDF attributes
- Re-run fetch and confirm metadata populated

### Step 2: Standardize Valid Times
- All models should be compared for SAME valid time (e.g., 2025-12-31 12:00 UTC)
- Fetch T+0 analysis from each model for fair comparison
- Document which model runs map to which valid times

### Step 3: Cross-Reference with Open-Meteo
For same location/time, compare:
- WXD-Direct GFS vs Open-Meteo GFS
- WXD-Direct IFS vs Open-Meteo IFS
Should match within 0.5K for same grid point

### Step 4: Verify Pressure Level
- Confirm all fetchers select 850hPa (not 925hPa or 700hPa)
- MOGREPS uses Pascals (85000) - verify conversion
- ICON uses level index - verify correct level

### Step 5: Verify Coordinate Extraction
- London target: 51.5N, 0.1W (-0.1 longitude)
- Check each fetcher's coordinate handling:
  - GFS uses 0-360 longitude (should query 359.9)
  - Others use -180 to 180 (should query -0.1)
- Log actual grid point used for each extraction

### Step 6: Compare with Observations
- Find London radiosonde data (if available)
- Or use Heathrow METAR + lapse rate estimate
- Provides independent ground truth

## Success Criteria

1. All models show `run_time` and `valid_time` populated
2. For same valid time, all models within 3K of each other
3. WXD-Direct matches Open-Meteo within 0.5K for same model
4. No systematic bias identified

## Questions for External Review

1. Is 3K spread between models acceptable for 850hPa T?
2. Is comparing T+0 analysis the right approach, or should we compare longer forecasts?
3. What's the expected accuracy of interpolating to a point from 0.25deg grid?
4. Should MOGREPS (ensemble mean of 18 members) be warmer than deterministic models?
5. Is AIFS expected to differ significantly from IFS for same valid time?

## Risks

- **False confidence**: If we only compare models to each other, systematic errors could go undetected
- **Timing errors**: If valid times don't match, differences are meaningless
- **Interpolation errors**: Point extraction from coarse grids adds uncertainty

## Decision Point

After evaluation, decide:
- A) WXD-Direct is accurate enough to replace Open-Meteo
- B) WXD-Direct needs fixes before production use
- C) Keep Open-Meteo, WXD-Direct for research only
