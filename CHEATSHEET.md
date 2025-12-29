# WXD Operations Cheatsheet

Quick reference for ntfy commands, cron schedules, and common operations.

## ntfy Commands (from Windows)

```powershell
# Send notification
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/wxd-cmd' -Body 'your message'"

# Common triggers
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/wxd-cmd' -Body 'preview'"
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/wxd-cmd' -Body 'fetch_icon'"
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/wxd-cmd' -Body 'fetch_ukmo'"
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/wxd-cmd' -Body 'fetch_mogreps'"
```

## SSH to VM

```bash
ssh -i "C:\Users\o_gri\OneDrive\Documents\ssh-key-2025-12-12.key" ubuntu@132.145.50.77
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

| Time (UTC) | Task | Description |
|------------|------|-------------|
| 04:30 | Tracker A | 4-model ensemble (GFS/ECM/AIFS/GEM) |
| 10:30 | Tracker A | 4-model ensemble |
| 16:30 | Tracker A | 4-model ensemble |
| 22:30 | Tracker A | 4-model ensemble |
| 05:00 | ICON fetch + post | German ensemble (40 members) |
| 17:00 | ICON fetch + post | German ensemble |
| 05:30 | UKMO fetch + post | UK Met Office deterministic |
| 17:30 | UKMO fetch + post | UK Met Office deterministic |
| 06:00 | MOGREPS fetch + post | UK Met Office ensemble (18 members) |
| 18:00 | MOGREPS fetch + post | UK Met Office ensemble |
| 08:00 | Daily summary | Met Office 5-day outlook |
| 18:00 Sun/Wed | Engagement post | Educational/community posts |

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
