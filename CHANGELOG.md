# Changelog

All notable changes to WXD (Weather Ensemble Data Pipeline) documented here.

## [Unreleased]

### Added
- **Reply threading for alerts** - Cold/warm/divergence/swing alerts now post as replies to main post, creating a tidy thread instead of separate posts
- **Percentile framing** - Counts % of ensemble members below threshold (e.g., "35% of GFS members below -5°C by Jan 2")
- **Bimodal detection** - Detects when ensemble splits into distinct cold/mild clusters (e.g., "GFS split: 40% cold vs 60% mild")
- **Trend persistence tracking** - Tracks consecutive runs with same signal, notes strengthening/weakening (e.g., "Cold signal run #4, strengthening")
- **Timing uncertainty** - Reports spread when models agree on event but disagree on timing (e.g., "Cold arrives ~Jan 2 ±1.5 days")
- All new analysis passed to Claude CLI as context for richer AI commentary

### Changed
- `post_to_bluesky()` now returns post reference (uri/cid) to enable threading
- Claude CLI prompt enhanced with structured ANALYSIS CONTEXT section

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
