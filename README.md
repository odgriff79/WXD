# WXD - Weather Ensemble Data Pipeline

Automated pipeline to fetch ensemble weather forecasts and store as raw JSON.

## Architecture

```
Open-Meteo API → Oracle VM (cron fetch) → GitHub (raw JSON) → Claude.ai (analysis)
```

**VM Role**: Dumb data pipe. Fetch JSON, commit, push. No analysis.

**Claude.ai Role**: Reads raw JSON from GitHub, performs all interpretation live in chat.

## Data

- `data/gfs_ensemble.json` - GFS 31-member ensemble
- `data/ecmwf_ensemble.json` - ECMWF IFS 51-member ensemble
- `data/gem_ensemble.json` - GEM 21-member ensemble

Variable: 850hPa temperature for London (51.5074, -0.1278)

## Usage

```bash
# Manual fetch
python fetch.py

# Data is auto-fetched by VM cron job
```

## For Claude.ai Analysis

Raw JSON available at:
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/gfs_ensemble.json
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/ecmwf_ensemble.json
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/gem_ensemble.json
