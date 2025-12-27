# WXD - Weather Ensemble Data Pipeline

Automated pipeline to fetch ensemble weather forecasts for trend comparison and model verification.

## Architecture

```
Open-Meteo API → Oracle VM (cron 09:00/21:00 UTC) → GitHub (timestamped JSON) → Claude.ai (analysis)
```

**VM Role**: Dumb data pipe. Fetch JSON, timestamp, commit, push. No analysis.

**Claude.ai Role**: Reads JSON from GitHub, performs all interpretation live in chat.

## Data Structure

### Timestamped Files (for trend comparison)
```
data/gfs_2025-12-27_0900Z.json      # GFS fetch at 09:00 UTC
data/gfs_2025-12-27_2100Z.json      # GFS fetch at 21:00 UTC
data/ecmwf_ifs_2025-12-27_0900Z.json    # ECMWF IFS fetch at 09:00 UTC
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
| GFS (GEFS) | 31 | 00z, 06z, 12z, 18z | ~3.5h | 09:00, 21:00 UTC |
| ECMWF IFS | 51 | 00z, 12z | ~8h | 09:00, 21:00 UTC |
| ECMWF AIFS | 51 | 00z, 12z | ~8h | 09:00, 21:00 UTC |
| GEM (GEPS) | 21 | 00z, 12z | ~4h | 09:00, 21:00 UTC |

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

# Data is auto-fetched by VM cron at 09:00 and 21:00 UTC
```

## For Claude.ai Analysis

Latest data always available at:
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/gfs_latest.json
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/ecmwf_ifs_latest.json
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/ecmwf_aifs_latest.json
- https://raw.githubusercontent.com/odgriff79/WXD/main/data/gem_latest.json

For historical comparison, browse timestamped files in `data/` directory.

## Analysis Use Cases

1. **Run-to-run trend**: Compare today's 00z vs yesterday's 00z - is forecast shifting warmer/cooler?
2. **Model agreement**: Do GFS/ECMWF/GEM agree on T+120h temperature?
3. **Ensemble spread**: Is spread narrowing (confidence) or widening (uncertainty)?
4. **Outlier detection**: Any ensemble members showing extreme values?
