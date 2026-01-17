# SSW Monitor - GEFS Ensemble

Sudden Stratospheric Warming (SSW) probability monitor using GEFS 31-member ensemble.

## What it does

Monitors the polar vortex by tracking zonal-mean zonal wind at 10 hPa, 60°N. A major SSW occurs when this wind reverses from westerly to easterly (U < 0 m/s).

## Data Source

**GEFS** (Global Ensemble Forecast System) via NOAA NOMADS OPeNDAP:
- 31 ensemble members (30 perturbed + 1 control)
- Forecast range: 16 days
- Updates: 4x daily (00z, 06z, 12z, 18z)
- Data available ~6 hours after run time

## Files

| File | Purpose |
|------|---------|
| `ssw_monitor.py` | Main monitor script |
| `ssw_verify.py` | Connectivity/variable name verification |
| `ssw_status.json` | Latest status output |

## Usage

```bash
# Verify GEFS connectivity (run once to confirm setup)
python3 ssw_verify.py

# Run monitor with JSON output
python3 ssw_monitor.py --json

# Run with debug output
python3 ssw_monitor.py --debug
```

## Output (ssw_status.json)

```json
{
  "ssw_probability_pct": 3.2,
  "current_u10_60n_ms": 23.0,
  "alert": {
    "level": "NORMAL",
    "color": "green",
    "should_alert": false
  },
  "ensemble": {
    "n_members": 31,
    "n_reversals": 1
  }
}
```

## Alert Levels

| Level | Condition | Action |
|-------|-----------|--------|
| NORMAL | <10% probability | No post |
| WATCH | 10-24% probability | Consider posting |
| ALERT | 25-49% probability | Post update |
| STRONG | >=50% probability | Post + highlight |

## Resource Usage

- Network: ~5-10 MB per run (OPeNDAP subset)
- Memory: ~300-500 MB peak
- Time: ~22 seconds
- Disk: ~1 KB output

## Why GEFS only (no ECMWF)

ECMWF's 101-member ensemble would be better, but:
- OpenCharts API returns images only, not data
- Open Data Portal lacks 10 hPa level (stops at 50 hPa)
- CDS API has multi-week delay

GEFS provides real-time 10 hPa data via OPeNDAP with no registration required.

## GEFS Data Latency

| Run | Available (approx) |
|-----|-------------------|
| 00z | ~06:00 UTC |
| 06z | ~12:00 UTC |
| 12z | ~18:00 UTC |
| 18z | ~00:00 UTC |

## Cron Schedule (suggested)

Run twice daily after 12z and 00z data available:
```
# SSW monitor - 19:00 and 07:00 UTC
0 19 * * * cd /home/ubuntu/wxd && python3 ssw_monitor.py >> logs/ssw.log 2>&1
0 7 * * * cd /home/ubuntu/wxd && python3 ssw_monitor.py >> logs/ssw.log 2>&1
```
