# WXD - Weather Ensemble Data Pipeline

Automated pipeline to fetch ensemble weather forecasts for trend comparison and model verification.

## Architecture

```
Open-Meteo API → Oracle VM (cron 07:30/19:30 UTC) → GitHub (timestamped JSON) → Claude.ai (analysis)
```

**VM Role**: Dumb data pipe. Fetch JSON, timestamp, commit, push. No analysis.

**Claude.ai Role**: Reads JSON from GitHub, performs all interpretation live in chat.

## Data Structure

### Timestamped Files (for trend comparison)
```
data/gfs_2025-12-27_0730Z.json      # GFS fetch at 07:30 UTC
data/gfs_2025-12-27_1930Z.json      # GFS fetch at 19:30 UTC
data/ecmwf_2025-12-27_0730Z.json    # ECMWF fetch at 07:30 UTC
...
```

### Latest Symlinks (for quick access)
```
data/gfs_latest.json    → gfs_2025-12-27_1930Z.json
data/ecmwf_latest.json  → ecmwf_2025-12-27_1930Z.json
data/gem_latest.json    → gem_2025-12-27_1930Z.json
```

## Models

| Model | Members | Runs | Typical Delay | Best Fetch Time |
|-------|---------|------|---------------|-----------------|
| GFS (GEFS) | 31 | 00z, 06z, 12z, 18z | ~3.5h | 07:30, 19:30 UTC |
| ECMWF IFS | 51 | 00z, 12z | ~7h | 07:30, 19:30 UTC |
| GEM (GEPS) | 21 | 00z, 12z | ~4h | 07:30, 19:30 UTC |

## Data Content

Each JSON contains:
- **14-day forecast** for 850hPa temperature
- **3 days of past model data** (for run-to-run comparison)
- **All ensemble members** (control + perturbed)
- **Metadata** including fetch time, likely model run, location

Variable: `temperature_850hPa` at London (51.5074, -0.1278)

## Retention

- Files kept for **7 days** (rolling)
- Older files automatically deleted by cleanup
- ~2 fetches/day × 3 models × 7 days = ~42 files max

## Usage

```bash
# Manual fetch
cd ~/wxd && source venv/bin/activate
python fetch.py

# Data is auto-fetched by VM cron at 07:30 and 19:30 UTC
```

## For Claude.ai Analysis

Latest data always available at:
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/gfs_latest.json
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/ecmwf_latest.json
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/gem_latest.json

For historical comparison, browse timestamped files in `data/` directory.

## Analysis Use Cases

1. **Run-to-run trend**: Compare today's 00z vs yesterday's 00z - is forecast shifting warmer/cooler?
2. **Model agreement**: Do GFS/ECMWF/GEM agree on T+120h temperature?
3. **Ensemble spread**: Is spread narrowing (confidence) or widening (uncertainty)?
4. **Outlier detection**: Any ensemble members showing extreme values?
