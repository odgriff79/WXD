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

| Trigger | Description |
|---------|-------------|
| `preview` | Tracker A - quick preview (existing data) |
| `fresh` | Tracker A - fetch new data + preview |
| `icon` | ICON - quick preview |
| `icon-fresh` | ICON - fetch new data + preview |
| `ukmo` | UKMO - quick preview |
| `ukmo-fresh` | UKMO - fetch new data + preview |
| `mogreps` | MOGREPS - quick preview |
| `mogreps-fresh` | MOGREPS - fetch new data + preview |
| `summary` | Daily Met Office summary preview |
| `engagement` | Engagement post preview |
| `cross` | Cross-tracker comparison (all 7 models) preview |
| `cross-post` | Cross-tracker comparison - LIVE post |
| `ssw` | SSW Monitor - current probability % and status |
| `check` | Reply listener dry-run |
| `respond` | Reply listener live |
| `status` | Quick system status |
| `clear-feedback` | Clear dashboard feedback queue |

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

### Current Schedule (all times UTC)

#### Forecast Trackers

| Time (UTC) | Task | Description |
|------------|------|-------------|
| 08:30, 20:30 | Tracker A | 4-model ensemble (GFS/ECM/AIFS/GEM) |
| 04:00, 10:00, 16:00, 22:00 | ICON | German ensemble (40 members) |
| 03:00, 09:00, 15:00, 21:00 | MOGREPS | UK Met Office ensemble (18 members) |
| 07:00, 19:00 | UKMO | UK Met Office deterministic |
| 09:30 | Daily Summary | Met Office 5-day narrative + WXD comparison |

#### Weekly/Automated Posts

| Time (UTC) | Task | Description |
|------------|------|-------------|
| Sun 01:00 | Weekly Changelog | Auto-generated from git commits |
| Sun 12:00 | Community Request | Ask followers for topic suggestions |
| Mon 20:00 | Collect Questions | Harvest replies from Sunday post |
| Tue 12:00 | Educational Post | Weather topic based on collected questions |
| Fri 12:00 | Educational Post | Weather topic (context-aware selection) |

#### Stratospheric Monitoring

| Time (UTC) | Task | Description |
|------------|------|-------------|
| 05:30, 11:30, 17:30, 23:30 | SSW Monitor | GEFS 31-member ensemble polar vortex check |

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

```bash
# Reply listener (dry-run - default)
python reply_listener.py

# Reply listener (live posting)
python reply_listener.py --post

# Force run (bypass adaptive polling)
python reply_listener.py --post --force

# Clear feedback queue (dashboard cleanup)
python reply_listener.py --clear-feedback
```

### ntfy Reply Commands

| Trigger | Description |
|---------|-------------|
| `check` | Check replies NOW (dry-run) |
| `respond` | Check AND respond NOW (live) |

```powershell
# Check replies (dry-run)
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'check'"

# Respond to replies (live)
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'respond'"
```

## Common VM Commands

```bash
# Navigate to WXD
cd ~/wxd

# Activate environment
source venv/bin/activate
source ~/.wxd_env

# Pull latest code
git pull

# Manual runs (dry run)
python trackers/icon/post.py --dry-run
python trackers/ukmo/post.py --dry-run
python trackers/mogreps/post.py --dry-run
python post_bluesky.py --dry-run
python engagement/engagement_post.py --dry-run
python cross_tracker_synthesis.py          # Cross-tracker comparison

# Manual runs (live)
python trackers/icon/fetch.py && python trackers/icon/post.py
python trackers/ukmo/fetch.py && python trackers/ukmo/post.py
python trackers/mogreps/fetch.py && python trackers/mogreps/post.py

# Check logs
tail -f /var/log/syslog | grep CRON
journalctl -u cron -f

# Check swap
free -h
```

## File Locations

| Path | Description |
|------|-------------|
| `~/wxd/` | Main project directory |
| `~/.wxd_env` | Environment variables (BSKY credentials) |
| `~/wxd/trackers/icon/data/` | ICON data and charts |
| `~/wxd/trackers/ukmo/data/` | UKMO data and charts |
| `~/wxd/trackers/mogreps/data/` | MOGREPS data and charts |
| `~/wxd/engagement/data/` | Engagement state and Q&A |
| `~/wxd/ssw/` | SSW monitor scripts and status |

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
# Check SSW status
python ssw/ssw_monitor.py --json

# View current status file
cat ssw/ssw_status.json
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
- Verify AWS access for MOGREPS
- Check Open-Meteo API status

## Quick Status Check

```bash
# Check recent posts
ls -la ~/wxd/trackers/*/data/chart_latest.png

# Check history files
head -20 ~/wxd/trackers/icon/data/history.json

# Check engagement state
cat ~/wxd/engagement/data/engagement_state.json
```
