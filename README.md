# WXD - Weather Ensemble Data Pipeline

Automated pipeline to fetch ensemble weather forecasts, generate AI commentary, and post to Bluesky.

**Live at:** [@wxd-london.bsky.social](https://bsky.app/profile/wxd-london.bsky.social)

**Charts:** [odgriff79.github.io/WXD](https://odgriff79.github.io/WXD/)

## Architecture

```
Open-Meteo/DWD APIs → Oracle VM (cron) → Claude CLI (commentary) → Bluesky (posts)
                                       → GitHub Pages (charts)
```

## Trackers

| Tracker | Model | Members | Source | Schedule (UTC) | Status |
|---------|-------|---------|--------|----------------|--------|
| A | GFS + ECM + AIFS + GEM | 31+51+51+21 | Open-Meteo | 08:30, 20:30 | LIVE |
| B | ICON-EU-EPS | 40 | DWD GRIB | 04:30, 16:30 | LIVE |
| C | MOGREPS-G | 18 | AWS S3 | TBD | Planned |
| D | UKMO Global | 1 (deterministic) | Open-Meteo | 05:00, 17:00 | LIVE |

Each tracker has its own subfolder, schedule, and Bluesky posts prefixed with model name (e.g., "ICON:", "UKMO:").

## Features

- **AI Commentary** - Claude CLI generates weather analysis from ensemble data
- **Trend Persistence** - Tracks consecutive runs with same cold/warm signal
- **Percentile Framing** - Reports ensemble agreement level and spread
- **Timing Uncertainty** - Analyzes cold window duration and confidence
- **Multi-model Alerts** - Cold/warm/divergence/swing alerts posted as thread replies
- **Dark Theme Charts** - Matplotlib charts with ensemble spread visualization

## Data

- **Variable:** 850hPa temperature (London: 51.5074, -0.1278)
- **Horizon:** 14 days (Tracker A), 5 days (ICON/UKMO)
- **Retention:** 7-day rolling cleanup

## Quick Start

```bash
# On VM
cd ~/wxd && source venv/bin/activate && source ~/.wxd_env

# Manual post (Tracker A)
python post_bluesky.py --dry-run

# Manual post (ICON)
python trackers/icon/post.py --dry-run

# Manual post (UKMO)
python trackers/ukmo/post.py --dry-run
```

## Remote Preview

Send commands via ntfy.sh:
```bash
curl -d "preview" ntfy.sh/wxd-cmd    # Quick preview with current data
curl -d "fresh" ntfy.sh/wxd-cmd      # Fetch new data, then preview
```

## Project Structure

```
wxd/
├── fetch.py              # Main 4-model data fetch
├── post_bluesky.py       # Main tracker posting
├── daily_summary.py      # Met Office narrative + WXD comparison
├── sync_charts.sh        # Push charts to GitHub Pages
├── trackers/
│   ├── shared/
│   │   └── analysis.py   # Common analysis functions
│   ├── icon/
│   │   ├── fetch.py      # DWD GRIB fetcher
│   │   └── post.py       # ICON posting
│   ├── ukmo/
│   │   ├── fetch.py      # Open-Meteo fetcher
│   │   └── post.py       # UKMO posting
│   └── mogreps/          # Future
└── docs/
    └── index.html        # GitHub Pages chart gallery
```

## Requirements

```
atproto        # Bluesky API
matplotlib     # Chart generation
requests       # API calls
eccodes        # GRIB handling (ICON)
netCDF4        # Grid file handling (ICON)
```

## Links

- [Bluesky Profile](https://bsky.app/profile/wxd-london.bsky.social)
- [Chart Gallery](https://odgriff79.github.io/WXD/)
- [CHANGELOG](CHANGELOG.md)
