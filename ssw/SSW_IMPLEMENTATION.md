# SSW Monitor Implementation Plan

**Status: LIVE**

Last updated: 2026-01-17

Intro thread posted: https://bsky.app/profile/wxd-london.bsky.social/post/3mcninibyl62z

---

## Overview

Sudden Stratospheric Warming (SSW) probability monitor using GEFS 31-member ensemble data. Tracks zonal-mean zonal wind at 10 hPa, 60°N - when this reverses to easterly (U < 0), a major SSW event occurs.

SSW events can bring extended cold spells to the UK 2-4 weeks after the stratospheric reversal.

---

## Data Source

**GEFS via NOAA NOMADS OPeNDAP**
- 31 ensemble members (30 perturbed + 1 control)
- Forecast range: 16 days
- Runs: 4x daily (00z, 06z, 12z, 18z)
- Data latency: ~6 hours after run time
- Resource usage: ~10MB network, ~22 sec compute per fetch

**Why not ECMWF?**
- ECMWF has 101-member ensemble (better)
- OpenCharts API: Returns images only, no data endpoint found
- Open Data Portal: Lacks 10 hPa level (stops at 50 hPa)
- CDS API: Multi-week delay, not suitable for real-time monitoring

**ECMWF S2S Data - Future Investigation:**
- Simon Lee (@simonleewx.com) tip: https://apps.ecmwf.int/datasets/data/s2s-realtime-instantaneous-accum-ecmf/levtype=pl/type=cf/
- 48 hour delay (this is what powers his SSW site)
- Worth investigating for enhanced monitoring
- **Status**: To be explored for future enhancement

---

## Automation Schedule

**Fetch frequency:** 4x daily (all GEFS runs)
- After 00z: ~07:00 UTC
- After 06z: ~13:00 UTC
- After 12z: ~19:00 UTC
- After 18z: ~01:00 UTC

**Post frequency:** Max 1x per 24 hours

---

## Alert Thresholds

| Level | Probability | Meaning |
|-------|-------------|---------|
| NORMAL | <10% | No signal - silent |
| WATCH | 10-24% | Signal emerging |
| ALERT | 25-49% | Significant signal |
| STRONG | >=50% | High probability event |

---

## Posting Rules

### When to POST:

1. **Threshold reached**: Any run reaches ≥10% probability
2. **Level change**: NORMAL→WATCH, WATCH→ALERT, ALERT→STRONG (or reverse)
3. **Daily update while elevated**: If probability stays ≥10%, post daily update
4. **Signal subsided**: When probability drops back below 10% after being elevated - ONE "signal subsided" post

### When NOT to post:

- Daily "0% all clear" noise (no value)
- Multiple times per day (max 1 post per 24h)
- Single outlier run if other runs don't support (note in logs only)

### Run agreement context:

Each post includes context from other recent runs:
- "3 of 4 runs today elevated"
- "First run to reach threshold in 24h"
- "Supported by 00z (12%), 06z (15%)"

---

## Post Format

### WATCH (10-24%):
```
🌀 SSW Watch: GEFS shows X% of members with stratospheric wind reversal in 5-16 day window.

Vortex currently [state] (XX m/s). Monitoring.

(X of Y runs in last 24h also elevated)
```

### ALERT escalation:
```
🌀 SSW Alert ↑: X% (up from Y% yesterday). N/31 members showing reversal signal.

If verified, increased cold risk for UK in 2-4 weeks.
```

### STRONG (>=50%):
```
🌀 SSW Strong Signal: X% of GEFS members now showing reversal. Vortex weakening significantly.

[Claude AI commentary on implications and history]
```

### Signal subsided:
```
🌀 SSW signal subsided: Back below 10%. Vortex stable.
```

---

## Data Storage

### `ssw/history.json` - Rolling history (7+ days):
```json
{
  "runs": [
    {
      "timestamp": "2026-01-17T19:15:52Z",
      "cycle": "12z",
      "probability": 3.2,
      "n_reversals": 1,
      "n_members": 31,
      "current_u10": 23.0,
      "min_u10": -3.5,
      "level": "NORMAL"
    }
  ]
}
```

Extends automatically if signal active (keeps full event history).

### `ssw/state.json` - Posting state:
```json
{
  "elevated_runs": 0,
  "last_level": "NORMAL",
  "last_probability": 3.2,
  "signal_started": null,
  "subsided_posted": false,
  "last_post_time": null,
  "last_posted_commentary": null
}
```

### `ssw/ssw_status.json` - Latest run output (current)

---

## AI Commentary

When posting, Claude receives:
- Last 7 days of probability history
- Trend direction (emerging/strengthening/weakening/stable)
- Current vortex state
- Run agreement data
- Previous posted commentary (for narrative continuity)

Claude writes contextual commentary following WXD style:
- Factual, no hype
- Dates explicit
- Acknowledges uncertainty
- Notes model agreement/disagreement

---

## Dashboard Integration

Added to `status_web.py` CRON_JOBS:
```python
("SSW Monitor", "/home/ubuntu/wxd/logs/ssw.log", "19:00 UTC", r"SSW status|Saved|NORMAL|WATCH|ALERT", ["19:00"]),
```

---

## Files

| File | Purpose |
|------|---------|
| `ssw_monitor.py` | Main fetch + analysis + posting |
| `ssw_verify.py` | GEFS connectivity test |
| `ssw/history.json` | Rolling run history |
| `ssw/state.json` | Posting state tracking |
| `ssw/ssw_status.json` | Latest run output |
| `logs/ssw.log` | Cron log |

---

## One-off Introduction Post

**To be posted manually before automation goes live:**

```
New feature: SSW probability monitor 🌀

Now tracking Sudden Stratospheric Warming signals using GEFS 31-member ensemble. Posts only when probability reaches ≥10%.

SSW events can disrupt the polar vortex, often bringing extended cold spells to the UK 2-4 weeks later.

Current status: 3% (0/31 members showing reversal) - normal winter vortex.

(ECMWF's 101-member ensemble would give higher resolution, but their API doesn't expose 10 hPa data publicly. Exploring options.)
```

**Owner review required before posting.**

---

## TODO

- [x] Implement state tracking in ssw_monitor.py
- [x] Add --post flag with Bluesky integration
- [x] Add history.json management
- [x] Add Claude commentary generation
- [x] Add cron entries (4x fetch, 1x post window)
- [x] Owner review of intro post
- [x] Go live (2026-01-17)
- [x] Add latency probe for data availability tracking
- [ ] Investigate ECMWF S2S data (48h delay) per Simon Lee tip

---

## Risks / Notes

- GEFS only 31 members (ECMWF would be 101)
- SSW events are rare (1-2 per winter typically)
- Long lead time to UK impact (2-4 weeks) means signal may evolve
- False positives possible - threshold set at 10% to avoid noise
- NOMADS OPeNDAP occasionally slow/unavailable - retry logic in place
