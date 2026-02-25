# WXD Operations Cheatsheet

Quick reference for ntfy commands, cron schedules, and common operations.

## Status Dashboard

**URL:** http://YOUR_VM_IP:8080

Shows: Cron jobs, model runs, tracker status, recent feedback.

## ntfy Alerts (Automatic)

Cron jobs send push notifications on failure via ntfy.sh:
- **Alert channel:** Set `NTFY_CHANNEL=wxd-alerts` in `~/.wxd_env`
- **Subscribe:** Open `https://ntfy.sh/wxd-alerts` or use ntfy app
- Alerts include failure reason (e.g., "WXD CRON FAILED: git push failed")

## ntfy Commands (from Windows)

```powershell
# Send notification
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'your message'"
```

### Available Triggers

All commands run from **wxd-direct** (X stream) since cutover 2026-02-22.

| Trigger | Description |
|---------|-------------|
| `preview` | Main 4-model ensemble preview (X stream, existing data) |
| `fresh` | Main ensemble - fetch new data + preview |
| `icon` | ICON-EU-EPS preview (X stream) |
| `icon-fresh` | ICON - fetch new data + preview |
| `ukmo` | UKMO Global preview (X stream) |
| `ukmo-fresh` | UKMO - fetch new data + preview |
| `mogreps` | MOGREPS-G preview (X stream) |
| `mogreps-fresh` | MOGREPS - fetch new data + preview |
| `summary` | Daily Met Office summary preview |
| `engagement` | Engagement post preview |
| `cross` | Cross-tracker comparison - not yet ported |
| `cross-post` | Cross-tracker comparison - not yet ported |
| `ssw` | SSW Monitor - current probability % and status |
| `check` | Reply listener dry-run (check for new replies) |
| `respond` | Reply listener live (check + respond, gated behind LIVE_MODE) |
| `status` | Quick system status |
| `clear-feedback` | Clear feedback queue |
| `compare` | Run comparison capture |

```powershell
# Tracker A
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'preview'"
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'fresh'"

# ICON
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'icon'"
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'icon-fresh'"

# UKMO
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'ukmo'"
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'ukmo-fresh'"

# MOGREPS
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'mogreps'"
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'mogreps-fresh'"

# Daily Summary
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'summary'"

# Engagement
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'engagement'"

# Cross-Tracker (compare all 7 models)
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'cross'"
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'cross-post'"

# SSW Monitor (Sudden Stratospheric Warming)
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'ssw'"
```

## VM Cron Schedule

View current cron:
```bash
crontab -l
```

Edit cron:
```bash
crontab -e
```

### Current Schedule (all times UTC) — X stream (post-cutover 2026-02-22)

#### Forecast Trackers

| Time (UTC) | Task | Description |
|------------|------|-------------|
| 08:45, 20:45 | Main (X stream) | 4-model ensemble (GEFS/IFS-ENS/AIFS-ENS/GEPS) |
| 05:25, 10:15, 17:25, 22:15 | ICON (X stream) | DWD ICON-EU-EPS (40 members) |
| 03:15, 09:15, 15:15, 21:40 | MOGREPS (X stream) | Met Office ensemble (18 members) |
| 07:15, 19:40 | UKMO (X stream) | Met Office deterministic |
| 09:35 | Daily Summary | Met Office 5-day narrative + WXD comparison |

#### Weekly/Automated Posts

| Time (UTC) | Task | Description |
|------------|------|-------------|
| Sun 14:05 | Weekly Recap | Auto-generated weekly summary |
| Sun 12:05 | Community Request | Ask followers for topic suggestions |
| Tue 12:05 | Educational Post | Weather topic based on collected questions |
| Fri 12:05 | Educational Post | Weather topic (context-aware selection) |

#### Stratospheric Monitoring

| Time (UTC) | Task | Description |
|------------|------|-------------|
| 01:45, 07:45, 13:45, 19:45 | SSW Monitor (X stream) | GEFS polar vortex check |

#### Maintenance

| Time (UTC) | Task | Description |
|------------|------|-------------|
| 10:15, 22:15 | Chart Sync | Push charts to GitHub Pages |

### Cron Format Reference
```
* * * * * command
│ │ │ │ │
│ │ │ │ └── Day of week (0-7, Sun=0 or 7)
│ │ │ └──── Month (1-12)
│ │ └────── Day of month (1-31)
│ └──────── Hour (0-23)
└────────── Minute (0-59)
```

### Example Cron Entries
```bash
# Every 6 hours at :30
30 4,10,16,22 * * * /path/to/script.py

# Twice daily at 05:00 and 17:00
0 5,17 * * * /path/to/script.py

# Sunday and Wednesday at 18:00
0 18 * * 0,3 /path/to/script.py
```

## Reply System

All reply commands run from **wxd-direct** since cutover 2026-02-22.

```bash
cd ~/wxd-direct && source venv/bin/activate && source ~/.wxd_env

# Reply listener (dry-run - default)
python reply_listener.py --force

# Reply listener (live posting)
python reply_listener.py --force --post

# Clear feedback queue
python reply_listener.py --clear-feedback

# Show feedback summary
python reply_listener.py --feedback
```

### ntfy Reply Commands

| Trigger | Description |
|---------|-------------|
| `check` | Check replies NOW (dry-run) |
| `respond` | Check AND respond NOW (live, gated behind LIVE_MODE) |
| `clear-feedback` | Clear the feedback queue |

```powershell
# Check replies (dry-run)
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'check'"

# Respond to replies (live)
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'respond'"

# Clear feedback
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'clear-feedback'"
```

## Common VM Commands

Since cutover (2026-02-22), all posting runs from **wxd-direct** via X stream.

```bash
# Navigate to wxd-direct
cd ~/wxd-direct && source venv/bin/activate && source ~/.wxd_env

# X stream dry-run previews
python src/xstream/runner.py --tracker main --dry-run
python src/xstream/runner.py --tracker icon --dry-run
python src/xstream/runner.py --tracker ukmo --dry-run
python src/xstream/runner.py --tracker mogreps --dry-run
python src/xstream/runner.py --tracker ssw --dry-run

# Other dry-runs
python daily_summary.py --dry-run
python engagement/engagement_post.py --dry-run

# Fetch fresh data
python src/scheduler.py --force

# Check logs
tail -50 logs/xstream/cron.log
tail -50 logs/shadow/cron.log

# Check swap
free -h
```

## File Locations

Since cutover (2026-02-22), production runs from **wxd-direct**.

| Path | Description |
|------|-------------|
| `~/wxd-direct/` | Production project directory |
| `~/wxd/` | Legacy (archived, read-only) |
| `~/.wxd_env` | Environment variables (BSKY credentials) |
| `~/wxd-direct/shadow_data/main/` | Main tracker data and charts |
| `~/wxd-direct/shadow_data/icon/` | ICON data and charts |
| `~/wxd-direct/shadow_data/ukmo/` | UKMO data and charts |
| `~/wxd-direct/shadow_data/mogreps/` | MOGREPS data and charts |
| `~/wxd-direct/shadow_data/ssw/` | SSW monitor status and charts |
| `~/wxd-direct/src/xstream_configs/` | X stream YAML configs per tracker |
| `~/wxd-direct/data/post_registry.json` | Post registry for feedback tracing |

## SSW Monitor (Sudden Stratospheric Warming)

Monitors polar vortex for SSW events using GEFS 31-member ensemble.

### What it tracks
- Zonal-mean zonal wind at 10 hPa, 60°N
- Major SSW = wind reversal (westerly → easterly, U < 0 m/s)
- SSW can influence UK weather 2-4 weeks later (NAO-, blocking, cold)

### ntfy Command
```powershell
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'ssw'"
```

### Output Example
```
SSW STATUS
==============================
Probability: 3.2%
Alert: NORMAL
Current U10 @60N: 23.0 m/s
```

### Alert Levels
| Level | Probability | Meaning |
|-------|-------------|---------|
| NORMAL | < 10% | Vortex stable |
| WATCH | 10-30% | Elevated risk |
| WARNING | 30-50% | SSW likely developing |
| ALERT | > 50% | SSW imminent/occurring |

### Manual Commands
```bash
# Check SSW status (wxd-direct)
cd ~/wxd-direct && cat shadow_data/ssw/ssw_status.json

# SSW X stream dry-run
cd ~/wxd-direct && source venv/bin/activate && source ~/.wxd_env && python src/xstream/runner.py --tracker ssw --dry-run
```

## Troubleshooting

### Claude CLI timeout
- Check swap is enabled: `free -h`
- Ensure using sonnet model (not haiku)
- Verify syntax: `claude --dangerously-skip-permissions --model sonnet -p "prompt"`

### Bluesky posting fails
- Check credentials in `~/.wxd_env`
- Verify atproto is installed: `pip show atproto`

### Data not fetching
- Check internet: `curl -I https://google.com`
- Verify AWS access for MOGREPS/UKMO
- Check scheduler logs: `tail -50 ~/wxd-direct/logs/scheduler.log`

## Quick Status Check

```bash
# Check recent charts (wxd-direct)
ls -la ~/wxd-direct/shadow_data/*/data/chart_latest.png

# Check recent X stream outputs
ls -lt ~/wxd-direct/shadow_data/*/outputs/run_x_*.txt | head -10

# Check xstream cron log
tail -30 ~/wxd-direct/logs/xstream/cron.log

# Check post registry
jq '.posts[-5:]' ~/wxd-direct/data/post_registry.json
```
