# Changelog

All notable changes to WXD (Weather Ensemble Data Pipeline) documented here.

## [Unreleased]

## [2025-12-29] - Daily Summary Enhancements & ntfy Triggers

### Added
- **ntfy triggers for summary and engagement** - Can now preview daily summary and engagement posts via ntfy commands
- **Met Office long-range scraping** - daily_summary.py now fetches from long-range forecast page
- **Met Office warnings scraping** - Fetches day-by-day warning status from uk-warnings page
- **Standalone warnings post** - Active warnings now posted as separate post (not in thread) with:
  - Warning level (Yellow/Amber/Red)
  - Date range
  - Affected nations
  - Hazard types

### Fixed
- **Warnings post truncation** - Rewrote to be concise (<280 chars) with affected areas included
- **Navigation noise in scraping** - Added skip phrases to filter out menu/header text

### Known Issues
- **Engagement cron has --dry-run** - Needs removal to enable live Sunday/Wednesday posts

## [2025-12-29] - Period-Based Analysis & Commentary Improvements

### Added
- **Period-based analysis** - Forecasts now analyzed in three periods:
  - Short-term (0-72h): Days 1-3, highest confidence
  - Mid-range (72-144h): Days 4-6, medium confidence
  - Extended (144h+): Day 7+, lower confidence
- Commentary now covers full forecast range, not just first few days
- If pattern is uniform (cold/mild throughout), says that; if divergent, breaks down by period

### Changed
- **All trackers use Sonnet model** - Upgraded from haiku to sonnet for better commentary quality
- **Claude CLI syntax fixed** - Corrected '-p prompt' flag position (was causing 300s timeouts)
- **Prompt improvements** - All trackers now explicitly forbidden from dramatizing when analysis shows "no significant shift"
- **Chart overlays** - ICON and MOGREPS now show run-to-run progression (matching UKMO style)

### Fixed
- **Commentary contradiction** - Fixed issue where Claude wrote "signal weakening" when analysis said "no significant shift"
- **Input parameter** - Changed input=prompt to input=None since prompt now passed via -p flag


### TODO
- ~~**Anytime preview/testing mode** - Allow fresh data fetch for preview/testing without polluting or contaminating the production data files or history. Must ensure complete isolation from scheduled runs.~~ **DONE**
- **ICON/UKMO/MOGREPS commentary enhancement** - Need to port Tracker A's rich features: story-first prompts (no prefix), split/thread for longer posts (290 char), threshold warnings (-5°C/-8°C), 450 char for significant events. Currently have basic "ICON:" prefix style with 250 char single post.
- **Break down workflows into smaller tasks** - Current cron jobs run fetch + analysis + chart + Claude commentary + post as one heavy process. Causes memory issues and VM overload (load avg 20+). Need to split into smaller sequential steps or add delays between stages. MOGREPS S3 fetches + Claude CLI commentary together overwhelm the VM.

### Fixed
- **MOGREPS longitude bug** - Was using 0-360 convention (359.87°) but MOGREPS files use -180..180 convention. With `method='nearest'`, 359.87 snapped to 179.86° (Pacific Ocean) instead of London. Fix: use -0.1278° directly. Debug confirmed: correct selection now at -0.14°.
- **UKMO temps too warm** - Changed from `ukmo_seamless` to `ukmo_global_deterministic_10km`. Seamless model smoothed extremes (showed -6.9°C when actual was -8°C). Deterministic model now matches theweatheroutlook.com verification.

### Changed
- **MOGREPS cron timing** - Pushed to 03:00, 09:00, 15:00, 21:00 UTC (9 hours after each run). S3 files upload progressively - earlier times had insufficient forecast hours. **MONITOR:** Check if 9h delay allows full forecast range.
- **MOGREPS safeguards added** - (1) Minimum 4 forecast hours required before posting. (2) Abort if run-to-run shift exceeds 10°C (indicates comparing to corrupted historical data). **MONITOR:** These safeguards could block legitimate posts during extreme pattern changes - check cron.log if posts missing.

### Known Issues (Resolved)
- ~~**MOGREPS data completely wrong** - Chart showed inverted trend vs Meteociel reference. Root cause: longitude convention mismatch selecting Pacific instead of London.~~ **FIXED**

## [2025-12-28] - Shared Analysis Module & Enhanced Trackers

### Code Audit (Claude Web)
Full codebase audit completed - **all calculations verified correct**:
- Data retrieval: All 4 models (GFS, ECM, AIFS, GEM) fetching correctly from Open-Meteo
- Statistical calculations: Mean/min/max/spread computed correctly
- Chart generation: Axes labeled, units correct, ensemble spread rendered properly
- Alert logic: Threshold checks, hysteresis, and multi-model detection all correct
- Minor notes: ICON `get_run_label()` has unreachable 06z/18z branches (harmless)

### Fixed
- **MOGREPS 4x daily** - Updated `get_latest_run()` to target all 4 runs (00z, 06z, 12z, 18z), not just 00z/12z
- **MOGREPS fallback** - Added `get_fallback_run()` to try previous run if target unavailable on S3
- **MOGREPS delay** - Corrected delay from 4h to 6h based on actual S3 availability testing

### Added
- **Shared analysis module** (`trackers/shared/analysis.py`) - Common analysis functions across all trackers:
  - Trend persistence tracking (consecutive runs with same signal)
  - Percentile framing (ensemble spread at coldest point, agreement level)
  - Timing uncertainty analysis (cold window duration, confidence level)
  - Run-on-run shift detection (shared between ensemble and deterministic models)
  - Full analysis pipeline function for easy integration

- **Enriched Claude CLI context** - All trackers now pass comprehensive analysis to Claude:
  - Shift information with direction and date
  - Cold signal with ensemble min/max
  - Trend persistence (e.g., "Cold persisting for 3 runs")
  - Spread analysis (e.g., "High agreement, 4C spread")
  - Timing window (e.g., "Cold spell spans ~3 days")

### Changed
- **ICON tracker** - Now uses shared analysis module with percentile framing
- **MOGREPS tracker** - Now uses shared analysis module with percentile framing
- **UKMO tracker** - Now uses shared analysis module (deterministic, no percentile framing)

### Fixed
- **Claude CLI calls** - Removed invalid `--max-tokens` flag from all trackers (ICON, MOGREPS, UKMO, daily_summary). This flag doesn't exist in Claude CLI and was causing silent failures with fallback text only.

### Technical
- Added `sys.path.insert()` to each tracker for shared module imports
- Separate trend state files per tracker (`trend_state.json`)
- Analysis functions return both individual results and formatted context string
- GitHub Pages at `odgriff79.github.io/WXD/` with chart gallery
- `sync_charts.sh` script copies tracker charts to `docs/charts/` and pushes to GitHub

### Added
- **Local VM config file** - `.vm_config` (gitignored) stores VM IP and SSH key path for remote orchestration
- **Reply threading for alerts** - Cold/warm/divergence/swing alerts now post as replies to main post, creating a tidy thread instead of separate posts
- **Percentile framing** - Counts % of ensemble members below threshold (e.g., "35% of GFS members below -5°C by Jan 2")
- **Bimodal detection** - Detects when ensemble splits into distinct cold/mild clusters (e.g., "GFS split: 40% cold vs 60% mild")
- **Trend persistence tracking** - Tracks consecutive runs with same signal, notes strengthening/weakening (e.g., "Cold signal run #4, strengthening")
- **Timing uncertainty** - Reports spread when models agree on event but disagree on timing (e.g., "Cold arrives ~Jan 2 ±1.5 days")
- All new analysis passed to Claude CLI as context for richer AI commentary
- **Chart watermark** - "wxd-london.bsky.social | Free to use with attribution" in bottom-right
- **Public chart URL** - chart_latest.png now pushed to GitHub for embedding

### Changed
- `post_to_bluesky()` now returns post reference (uri/cid) to enable threading
- Claude CLI prompt enhanced with structured ANALYSIS CONTEXT section
- **IFS → ECM** - Chart legend AND post text now shows "ECM" instead of "ECMWF IFS" for better UK weather community recognition
- **Chart title simplified** - Shows "(00z run)" or "(12z run)" without fetch timestamp
- **cron_fetch.sh** - Now commits and pushes chart_latest.png after Bluesky post

### Investigated
- **Previous Runs API** - Not suitable for backfill (no 850hPa data, no ensemble members)
- **ICON & UKMO expansion** - Initial investigation found deterministic-only via Open-Meteo Forecast API
- **Open-Meteo ICON 850hPa** - Returns NULL for `temperature_850hPa` on ICON ensemble despite API docs claiming support. Works fine for GFS/ECMWF. Likely data availability/ingestion issue on their side.

### Multi-Tracker Architecture
Separating models into independent trackers rather than mixing into one ensemble:
- **Tracker A** - Main 4-model ensemble (GFS, ECM, AIFS, GEM) via Open-Meteo - 2x daily (08:30, 20:30 UTC) ✅ LIVE
- **Tracker B** - ICON-EU-EPS (40 members) via DWD GRIB - 2x daily (04:30, 16:30 UTC for 00z/12z runs) ✅ LIVE
- **Tracker C** - MOGREPS-G (18 members) via AWS S3 NetCDF - future (bucket: `met-office-global-ensemble-model-data`)
- **Tracker D** - UKMO Global Deterministic (~10km) via Open-Meteo - 2x daily (05:00, 17:00 UTC) ✅ LIVE

Each tracker: own subfolder (`trackers/icon/`), own schedule, own cron, own Bluesky posts prefixed with model name.

**Tracker B implementation:**
- Uses ICON-EU-EPS (European domain) not ICON-EPS (global) - smaller files
- Only 00z and 12z runs have pressure-level 850hPa data (06z/18z only have model-level)
- Forecast range: 0-120h (5 days) at 12-hourly intervals
- Uses Python eccodes for point extraction (not wgrib2/CLI - those don't support unstructured grids)
- Files: `trackers/icon/fetch.py`, `trackers/icon/post.py`, `trackers/icon/cron_icon.sh`
- ntfy commands: `icon` (quick preview), `icon-fresh` (fetch new data)

### ICON 850hPa Data Solution
Open-Meteo doesn't provide ICON 850hPa, but DWD Open Data does via GRIB:

**Source:** `https://opendata.dwd.de/weather/nwp/icon-eu-eps/grib/[HH]/t/`
- Files: `icon-eu-eps_europe_icosahedral_pressure-level_YYYYMMDDHH_FFF_850_t.grib2.bz2`
- Each file ~10MB compressed, contains all 40 ensemble members for one forecast hour
- Only 00z and 12z runs have pressure-level data (06z/18z have model-level only)

**Grid handling:**
ICON uses unstructured icosahedral grid (164984 cells). CLI tools (`grib_ls -l`, `grib_get_data -l`, `cdo remapnn`) don't work because:
- eccodes CLI doesn't support nearest-neighbor on unstructured grids
- CDO needs grid definition files and has ecCodes packing errors

**Solution: Python eccodes + grid file**
1. Download DWD grid file `icon_grid_0037_R03B07_N02.nc` once (~55MB, cached)
2. Load cell center coordinates (clat/clon in radians)
3. Find nearest cell index to London (index 113327 at 51.46°N, 0.00°E)
4. For each GRIB: read values at that index using `codes_get_values()`

**Data flow per run:**
- 11 files (0h to 120h at 12-hourly) × 10MB = ~110MB download
- Processed sequentially, only one file in memory at a time
- Final output: ~50KB JSON with 40-member ensemble stats

**Requirements:** `pip install eccodes netCDF4` (Python bindings, not CLI)

### Future Work
Open-Meteo Ensemble API supports more models (but 850hPa availability varies):
- **ICON EPS Seamless** - 40 members (850hPa: use DWD GRIB instead)
- **BOM ACCESS-GE** - 18 members (independent Australian global ensemble)
- **UKMO MOGREPS-G** - 18 members (UK Met Office global ensemble)
- **UKMO MOGREPS-UK** - 3 members (UK high-res ensemble)

**Implementation notes:**
- Use `https://ensemble-api.open-meteo.com/v1/ensemble` (not forecast API) for ensembles
- UKMO deterministic (forecast API) has 4-hour delay due to Met Office licensing
- Horizon mismatch between models - may need to clip to shared max or allow early endings
- UKMO MOGREPS ensembles are separate from UKMO deterministic feed
- Consider UKMO deterministic as "benchmark line" alongside ensemble spread
- For any model where Open-Meteo lacks 850hPa, fall back to native GRIB + wgrib2

## [2025-12-28] - Multi-model Alerts & Remote Preview

### Added
- **Multi-model cold alerts** - Now reports ALL models crossing -5°C threshold, not just coldest (e.g., "ECM -7.2°C, AIFS -7.0°C, GFS -6.9°C, GEM -5.8°C")
- **Percentile threshold alerts** - Triggers when >80% of ensemble members cross cold threshold on any date
- **Dry-run mode** - `--dry-run` flag previews analysis without posting to Bluesky
- **Isolated fresh preview** - `fetch.py --preview` + `post_bluesky.py --preview` for anytime testing without contaminating production data
- **ntfy remote commands** - Two commands via `ntfy.sh/wxd-cmd`:
  - `preview`: Quick preview using current/stale data
  - `fresh`: Fetch new data first (isolated), then preview - no contamination of production files
- **ntfy_listener.py** - Python-based listener for remote preview commands
- **wxd-ntfy.service** - systemd service for persistent ntfy listener
- **Multi-post support** - Significant events can span multiple threaded posts (up to 550 chars, split at sentence boundaries)
- **Explicit cold ranking** - Analysis context now shows "COLD RANKING (coldest first)" so Claude doesn't misread JSON
- **Data provenance logging** - Prints fetched timestamp, run label (00z/12z), and first data timestamp for audit

### Fixed
- **Threading bug** - atproto requires proper model classes (`ComAtprotoRepoStrongRef.Main`, `AppBskyFeedPost.ReplyRef`) not plain dicts
- **Percentile alert wording** - Now says "below -5°C" instead of "below cold"
- **Chart title** - Now includes date (e.g., "28 Dec 00z") not just run time

### Changed
- **Cron schedule** - Changed from 09:00/21:00 UTC to 08:30/20:30 UTC for better model availability
- **Claude prompt overhaul**:
  - NO PREFIX rule - Don't waste characters on "London 850hPa temperatures:"
  - Commentary-first style - Lead with story/analysis, not data dump
  - Plain language - No jargon ("conviction", "regime", "synoptic")
  - No markdown - Bluesky is plain text only
  - Factual tone - Not tabloid headlines

## [2025-12-27] - Initial Bluesky Automation

### Added
- **Bluesky posting** via atproto library
- **Claude CLI integration** for AI-generated weather commentary
- **Matplotlib chart generation** (dark theme, 850hPa ensemble forecast)
- **Run-to-run shift detection** - Flags models that moved >2°C since last run
- **Confidence indicator** - High/medium/low based on model agreement and spread
- **Cold/warm threshold alerts** with hysteresis (must persist 2 runs)
- **Model divergence alerts** - When models disagree by >6°C
- **Rapid swing alerts** - When >8°C change expected in 48h
- **ntfy.sh push notifications** for API failures
- **Weekly git changelog** posted to Bluesky (Sundays 01:00 UTC)
- **Chart run labels** - Shows "00z run" or "12z run" in chart title
- **Fallback posting** when Claude CLI unavailable

### Infrastructure
- Cron schedule: 09:00 and 21:00 UTC (captures 00z/12z runs)
- Bluesky credentials via ~/.wxd_env
- alert_state.json for hysteresis tracking (gitignored)

## [2025-12-27] - Data Pipeline Setup

### Added
- **fetch.py** - Fetches 4-model ensemble data from Open-Meteo
- **Timestamped files** - gfs_2025-12-27_0900Z.json format
- **7-day rolling retention** - Auto-cleanup of old files
- **Latest symlinks** - gfs_latest.json always points to newest
- **Summary generation** - Ensemble stats (mean/min/max/spread)
- **History tracking** - Rolling 6-run history in history.json
- **Compact history** - 12-hourly data for Claude Web analysis

### Models
- GFS Ensemble (31 members)
- ECMWF IFS Ensemble (51 members)
- ECMWF AIFS Ensemble (51 members, AI-based)
- GEM Ensemble (21 members)

### Configuration
- 14-day forecast horizon
- 3 past days for run-to-run comparison
- 850hPa temperature variable
- London coordinates (51.5074, -0.1278)
