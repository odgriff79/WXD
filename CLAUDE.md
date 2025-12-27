# CLAUDE.md - WXD Project

**Read this file at the start of every session.**

## Project Summary

Weather ensemble data pipeline for trend comparison and model verification.
VM fetches timestamped JSON from Open-Meteo, pushes to GitHub. Claude.ai does all analysis.

**Your role (Claude Code on VM)**: Infrastructure maintenance only.

**NOT your role**: Weather analysis, data interpretation, statistics. That happens in Claude.ai browser.

## Key Design Decisions

```
[2025-12-27] Timestamped files for history: gfs_2025-12-27_0730Z.json format
[2025-12-27] 7-day rolling retention: auto-cleanup of old files
[2025-12-27] past_days=3 in API: includes previous model runs for trend comparison
[2025-12-27] Fetch at 09:00/21:00 UTC: optimal for capturing 00z/12z runs (ECMWF ready by 08:00/20:00)
[2025-12-27] Latest symlinks: gfs_latest.json points to most recent fetch
```

## Model Schedule

| Model | Members | Runs | Delay | Best Capture |
|-------|---------|------|-------|--------------|
| GFS | 31 | 00z, 06z, 12z, 18z | ~3.5h | 09:00, 21:00 UTC |
| ECMWF IFS | 51 | 00z, 12z | ~8h | 09:00, 21:00 UTC |
| ECMWF AIFS | 51 | 00z, 12z | ~8h | 09:00, 21:00 UTC |
| GEM | 21 | 00z, 12z | ~4h | 09:00, 21:00 UTC |

## VM Setup

- **User**: ubuntu
- **Project dir**: ~/wxd
- **Venv**: ~/wxd/venv
- **Cron**: 09:00 and 21:00 UTC daily (after ECMWF dissemination)

## Data Structure

```
data/
├── gfs_2025-12-27_0730Z.json         # Timestamped fetch
├── gfs_2025-12-27_1930Z.json
├── gfs_latest.json                   # Copy of most recent
├── ecmwf_ifs_2025-12-27_0730Z.json
├── ecmwf_ifs_latest.json
├── ecmwf_aifs_2025-12-27_0730Z.json
├── ecmwf_aifs_latest.json
├── gem_2025-12-27_0730Z.json
└── gem_latest.json
```

## Commands

```bash
# Activate environment
cd ~/wxd && source venv/bin/activate

# Manual fetch (creates timestamped files, updates latest symlinks, cleans old)
python fetch.py

# Check cron
crontab -l

# View recent fetches
ls -la data/*.json | head -20

# Check logs
tail -50 cron.log
```

## Cron Job

```
0 9,21 * * * /home/ubuntu/wxd/cron_fetch.sh
```

Runs at 09:00 and 21:00 UTC to capture:
- 00z runs (ECMWF available ~08:00, +1h buffer)
- 12z runs (ECMWF available ~20:00, +1h buffer)

## Bluesky Automation

Posts are made automatically after each fetch if credentials are configured.

**Setup:**
```bash
# Copy template and edit with your credentials
cp ~/.wxd_env.template ~/.wxd_env
nano ~/.wxd_env

# Add your Bluesky handle and app password:
# export BSKY_HANDLE="your.handle.bsky.social"
# export BSKY_PASSWORD="your-app-password"

# Test manually
cd ~/wxd && source venv/bin/activate
python post_bluesky.py
```

**How it works:**
1. Reads history_compact.json
2. Pipes to Claude CLI for AI commentary (max 300 chars)
3. Generates matplotlib chart (dark theme)
4. Posts text + image to Bluesky

**Get app password:** https://bsky.app/settings/app-passwords

## Troubleshooting

1. **Fetch fails**: Check Open-Meteo status, network connectivity
2. **Push fails**: Verify SSH key, git remote config
3. **Data stale**: Check `cron.log`, verify crontab
4. **Old files not deleted**: Check cleanup logic in fetch.py
5. **Bluesky post fails**: Check credentials in ~/.wxd_env, check cron.log

## DO NOT

- Add analysis code
- Parse or process the JSON
- Create summary files
- Interpret weather data

The raw JSON goes to GitHub. Claude.ai does everything else.

## Remote Orchestration

This project can be managed via VS Code Claude dispatching to VM Claude:

```bash
ssh -i "path/to/key" ubuntu@<VM_IP> "cd ~/wxd && claude -p 'your task here'"
```

Same pattern as video-object-removal project.
