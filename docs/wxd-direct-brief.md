# WXD Direct GRIB Access - Project Brief

**Version:** 1.0 (Reviewed & Approved)  
**Date:** 2025-12-30  
**Status:** Ready to implement

---

## Overview

Parallel proof-of-concept to fetch 850hPa temperature data for London directly from meteorological source agencies, bypassing Open-Meteo aggregator. Runs independently alongside current WXD system with no shared code, data, or dependencies.

---

## End Goal

Four models, all runs, direct from source:

| Model | Source | Runs/Day | Latency | Subset API | Grid Spacing |
|-------|--------|----------|---------|------------|--------------|
| GFS | NOAA NOMADS | 4 (00/06/12/18z) | ~2-4hr | Yes | 0.25° |
| IFS | ECMWF Open Data | 4 (00/06/12/18z) | ~2-9hr* | Yes (client) | ~0.1° |
| AIFS | ECMWF Open Data | 4 (verify cadence for aifs-single/aifs-ens) | Often faster than IFS | Yes (client) | ~0.1° |
| GEM | MSC Datamart | 00/12z confirmed; 06/18z under test | ~3-4hr | WCS subset available** | 15km |

*ECMWF 2025 Open Data Phase may have reduced latency to ~2hr for 0.25° products - verify during POC.

**MSC GeoMet WCS now supports bounding box subsetting - Phase 3 optimisation.

---

## Target Location

**London:** 51.5°N, 0.1°W, 850hPa temperature only.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Local (Windows)                                             │
│   VS Code + Claude Code extension (orchestrator)            │
│                         │                                   │
│                         ▼ SSH dispatch                      │
│   ssh -i key ubuntu@<NEW_VM_IP> "cd ~/wxd-direct && claude" │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ NEW Oracle VM (4 OCU / 24GB RAM)                            │
│                                                             │
│   ~/wxd-direct/              ← This project (isolated)      │
│   ├── src/                                                  │
│   │   ├── fetchers/          ← Per-source fetch logic       │
│   │   │   ├── gfs.py                                        │
│   │   │   ├── ecmwf.py       (IFS + AIFS)                   │
│   │   │   └── gem.py                                        │
│   │   ├── extract.py         ← GRIB → London point value    │
│   │   ├── compare.py         ← Side-by-side vs Open-Meteo   │
│   │   └── store.py           ← SQLite logging               │
│   ├── data/                  ← Temporary GRIB files         │
│   ├── db/                    ← comparison.db                │
│   ├── logs/                                                 │
│   ├── requirements.txt                                      │
│   └── CLAUDE.md                                             │
│                                                             │
│   NO CONTACT with:                                          │
│   - ~/Evo_mon                                               │
│   - ~/video-object-removal                                  │
│   - Any existing WXD code on other VM                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Isolation Rules

**MUST NOT:**
- Touch existing WXD codebase
- Share database with current system
- Use same cron jobs
- Import any existing WXD modules
- Post to Bluesky (POC phase)

**MUST:**
- Live in dedicated `~/wxd-direct/` directory
- Use own virtual environment
- Log to own database
- Be independently startable/stoppable

---

## Phased Approach

### Phase 1: GFS Only (POC)

**Goal:** Prove GRIB toolchain works on ARM, get one value comparable to Open-Meteo.

**Tasks:**
1. Set up VM with Python 3.11+, venv
2. Install `eccodes`, `cfgrib`, `xarray`, `requests`
3. Configure ARM library paths (see System Setup section)
4. Fetch GFS 12z 850hPa for London via NOMADS subset API
5. Extract single point value (document interpolation method used)
6. Fetch same timestamp from Open-Meteo
7. Log both to SQLite with full metadata
8. Compare - do they agree within tolerance?

**GFS Prime Meridian Gotcha:**
GFS uses 0-360° longitude. London (0.1°W) = 359.9°E. The NOMADS filter API may fail on boxes spanning the prime meridian.

```
# Use single grid column to avoid wraparound issues
# This intentionally selects one column at ~0° longitude
leftlon=359&rightlon=360&toplat=52&bottomlat=51
```

**Success Criteria:** 
Values agree within 0.5K, OR discrepancy explained by:
- Interpolation method (nearest neighbour vs bilinear)
- Grid point selection differences
- Time interpolation
- Model orography differences

### Phase 2: Add ECMWF (IFS + AIFS)

**Goal:** Second source, test `ecmwf-opendata` client.

**Access:** Open access per ECMWF Real-time Catalogue policy (1 Oct 2025); client endpoint may still require configuration.

**Note on AIFS:** Often available sooner than IFS because ML inference time is seconds/minutes once initial conditions are set.

**Tasks:**
1. Integrate `ecmwf-opendata` client
2. Fetch IFS 12z 850hPa
3. Fetch AIFS 12z 850hPa (use `aifs-single` or `aifs-ens`)
4. Add to comparison database
5. Note any parameter/unit/coordinate quirks
6. Measure actual latency vs documented estimates

**Success:** Three models logging correctly.

### Phase 3: Add GEM

**Goal:** Fourth model, handle no-subset case (or test WCS alternative).

**Tasks:**
1. Download full 850hPa level GRIB from MSC Datamart
2. Extract London point locally
3. Clean up temp files
4. Add to comparison
5. Test 06/18z availability (may be unreliable)

**Phase 3b (Bandwidth Optimisation):**
Test MSC GeoMet WCS endpoint with bounding box subsetting:
```
SUBSET=long(-1,1),lat(51,52)
```
Returns NetCDF/GeoTIFF of tiny area instead of full GRIB.

**Success:** Four models logging, GEM quirks documented.

### Phase 4: Scheduler + All Runs

**Goal:** Automated fetching of all available runs.

**Tasks:**
1. Cron jobs for each source timed to typical availability
2. Retry logic for transient failures
3. Stale data detection
4. Log actual availability times (measure, don't assume)

**Success:** Hands-off operation for 7 days.

### Phase 5: Evaluation

**Goal:** Decide whether to migrate, integrate, or abandon.

**Questions to answer:**
- Does direct access solve the 13°C offset mystery?
- Is latency meaningfully better?
- Is maintenance burden acceptable?
- Any reliability issues encountered?

---

## System Setup (Ubuntu ARM)

### Dependencies

```
# requirements.txt
cfgrib>=0.9.10
eccodes>=1.5.0
xarray>=2023.0.0
ecmwf-opendata>=0.3.0
requests>=2.28.0
numpy>=1.24.0
```

### System Packages

```bash
sudo apt install libeccodes-dev libeccodes-tools
```

### ARM-Specific Environment Variables

Add to `~/.bashrc`:

```bash
# eccodes definition path (required on ARM)
export ECCODES_DEFINITION_PATH=/usr/share/eccodes/definitions

# Library path if pip eccodes fails to find shared library
export LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu:$LD_LIBRARY_PATH
```

### Performance Note

For single-point extraction on ARM, the full xarray/cfgrib stack may be sluggish. Consider using low-level `codes_grib_new_from_file` patterns in `src/extract.py` for maximum speed. Test both approaches in Phase 1.

---

## Data Sources - Technical Details

### GFS (NOAA NOMADS)

```
Base URL: https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl

London request (avoiding prime meridian issue):
?file=gfs.t12z.pgrb2.0p25.f000
&var_TMP=on
&lev_850_mb=on
&subregion=
&toplat=52&bottomlat=51&leftlon=359&rightlon=360
&dir=%2Fgfs.YYYYMMDD%2F12%2Fatmos

# Note: leftlon=359&rightlon=360 intentionally selects single grid column
# at ~0° longitude to avoid CGI wraparound issues at prime meridian
```

- NOAA usage policy: 120 hits/min per IP across listed sites
- No auth required
- Returns tiny GRIB2 file
- Grid spacing: 0.25°

### ECMWF (IFS + AIFS)

```python
from ecmwf.opendata import Client
client = Client()
client.retrieve(
    model="ifs",  # or "aifs-single" / "aifs-ens"
    type="fc",
    param="t",
    levtype="pl",
    level=850,
    area=[52, -1, 51, 1],  # N/W/S/E
    target="ifs_850.grib"
)
```

**Model identifiers:**
- `ifs` - Physics-driven deterministic
- `aifs-single` - AI deterministic
- `aifs-ens` - AI ensemble

**Access:** Open access per ECMWF Real-time Catalogue policy (1 Oct 2025). Client endpoint may still require configuration.

**Latency:** 
- Historical: ~6-9hr post-run
- 2025 Open Data Phase: May be ~2hr for 0.25° products (verify)
- AIFS often available before IFS (faster inference)

**Grid spacing:** ~0.1°

### GEM (MSC Datamart)

**Option A: Full GRIB Download**
```
Base URL: https://dd.weather.gc.ca/model_gem_global/15km/grib2/lat_lon/
Path: HH/CMC_glb_TMP_ISBL_850_latlon.15x.15_YYYYMMDDHH_P000.grib2
```

- No subsetting - download full level (~10-50MB)
- Extract point locally, delete temp file
- 00/12z confirmed; 06/18z under test (POC verifies)
- Grid spacing: 15km

**Option B: WCS Subsetting (Phase 3b)**
```
MSC GeoMet WCS endpoint with:
SUBSET=long(-1,1),lat(51,52)
```
Returns NetCDF/GeoTIFF of tiny bounding box - drastically reduces bandwidth.

---

## Database Schema

```sql
CREATE TABLE comparisons (
    id INTEGER PRIMARY KEY,
    fetched_at TEXT,           -- When we fetched
    model TEXT,                -- gfs/ifs/aifs-single/aifs-ens/gem/openmeteo
    run_time TEXT,             -- Model run (e.g., 2025-12-30T12:00Z)
    forecast_hour INTEGER,     -- Hours ahead (valid_time - run_time)
    valid_time TEXT,           -- Forecast valid time
    temp_850_k REAL,           -- Value in Kelvin
    lat REAL,                  -- Actual grid point used
    lon REAL,                  -- Canonical -180..180 (ALWAYS)
    interp_method TEXT,        -- nearest/bilinear
    grid_spacing TEXT,         -- e.g., "0.25deg", "15km"
    elevation_model REAL,      -- Model orography at point (metres)
    source_url TEXT,           -- Where we got it
    raw_value REAL,            -- Before any conversion
    data_quality TEXT,         -- OK/INTERPOLATED/MISSING_FIELD/DELAYED
    notes TEXT                 -- Quirks, errors
);

CREATE INDEX idx_model_valid ON comparisons(model, valid_time);
CREATE INDEX idx_run_time ON comparisons(run_time);
```

---

## Comparison Metadata (for 13°C debugging)

Log these for each fetch to diagnose discrepancies:

| Field | Purpose |
|-------|---------|
| Actual lat/lon used | Grid point vs requested |
| Interpolation method | Nearest vs bilinear |
| Grid spacing | Model resolution differences |
| Model orography | Elevation at grid point |
| Valid time (UTC) | Exact timestamp match |
| data_quality flag | Track anomalies |
| GRIB message metadata | Any quirks in encoding |

**Note on 850hPa and orography:**
850hPa is a constant pressure surface, not constant altitude. If a model has very different surface elevation for London (due to grid smoothing over Thames Valley), vertical interpolation to 850hPa can occasionally be affected if terrain is close to that pressure level.

---

## Estimated Resource Usage

| Phase | CPU | Memory | Disk | Bandwidth/day |
|-------|-----|--------|------|---------------|
| POC (GFS only) | Minimal | ~200MB | ~100MB | ~1MB |
| Full (4 models, no WCS) | Low | ~500MB | ~500MB working | ~200MB |
| Full (4 models, with WCS) | Low | ~500MB | ~200MB working | ~50MB |

Well within 4 OCU / 24GB capacity.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| eccodes on ARM | Set `ECCODES_DEFINITION_PATH` and `LD_LIBRARY_PATH` explicitly |
| ECMWF latency | 6-9hr historical; measure actual 2025 availability |
| GEM 06/18z | May not exist reliably; document, don't depend |
| Prime meridian | GFS filter API quirk; use 359-360 not -1 to 1 |
| Interpolation mismatch | Open-Meteo likely uses bilinear; document method used |
| Longitude storage | Always store -180..180; convert 359.9→-0.1 on ingest |
| xarray performance | Test low-level eccodes API as alternative |
| Scope creep | This is POC: no Bluesky, no charts, no fancy UI |

---

## Success Criteria

### POC Complete (Phase 1):
- [ ] GFS value agrees with Open-Meteo within tolerance, OR discrepancy fully explained
- [ ] GRIB toolchain proven on ARM
- [ ] Interpolation method documented
- [ ] Coordinate conversion working correctly

### Full System (Phase 4):
- [ ] 4 models logging reliably for 7 days
- [ ] Actual availability times measured (not assumed)
- [ ] Clear comparison data to evaluate vs Open-Meteo
- [ ] Decision documented: migrate, integrate, or abandon

---

## CLAUDE.md (for project directory)

```markdown
# WXD Direct GRIB Access

## Purpose
Proof-of-concept for fetching 850hPa temperature directly from 
meteorological agencies (GFS, IFS, AIFS, GEM) instead of Open-Meteo.

## Isolation
This project is COMPLETELY SEPARATE from:
- Existing WXD system
- Evo_mon  
- video-object-removal
- Any other projects on any VM

Do not import, reference, or modify anything outside ~/wxd-direct/

## Location
London: 51.5°N, 0.1°W

## Coordinate Conventions (CRITICAL)

| Source | Longitude Convention | London Value |
|--------|---------------------|--------------|
| GFS | 0 to 360 | 359.9°E |
| ECMWF | -180 to 180 | -0.1°E |
| GEM | Verify | TBD |
| **Storage** | **-180 to 180** | **-0.1** |

**RULE:** Always store canonical lon in -180..180 in DB; convert only at fetch time.
Never store 359.9 - always convert to -0.1 immediately on ingest.

## Temperature Units
- GRIB standard: Kelvin
- Always store as Kelvin, convert for display only

## Interpolation
Document whether using nearest neighbour or bilinear for each source.
This affects comparison validity with Open-Meteo.

## Grid Spacing Reference
- GFS: 0.25° (~28km)
- IFS/AIFS: ~0.1° (~11km)  
- GEM: 15km

## ARM/eccodes Setup
```bash
export ECCODES_DEFINITION_PATH=/usr/share/eccodes/definitions
export LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu:$LD_LIBRARY_PATH
```

## Working Directory
All temp files in ~/wxd-direct/data/, clean up after extraction.

## Model Identifiers
- GFS: N/A (URL-based)
- ECMWF IFS: `model="ifs"`
- ECMWF AIFS: `model="aifs-single"` or `model="aifs-ens"`
- GEM: N/A (file path based)

## Data Quality Flags
Use in database:
- `OK` - Normal fetch
- `INTERPOLATED` - Value was interpolated (not direct grid point)
- `MISSING_FIELD` - Expected field not in GRIB
- `DELAYED` - Fetched later than expected availability
```

---

## Next Actions

1. Provision new Oracle VM (4 OCU / 24GB RAM)
2. SSH key setup
3. Bootstrap `~/wxd-direct/` directory structure
4. Install system packages and Python environment
5. Begin Phase 1: GFS single fetch test

---

## Review Status

| Reviewer | Status | Date |
|----------|--------|------|
| GPT-4 | ✅ Approved | 2025-12-30 |
| Gemini | ✅ Approved | 2025-12-30 |

**Verdict:** Technically sound, scientifically defensible, architecturally clean, ready to implement.
