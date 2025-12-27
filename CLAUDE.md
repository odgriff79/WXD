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
[2025-12-27] Fetch at 07:30/19:30 UTC: optimal for capturing 00z/12z runs across all models
[2025-12-27] Latest symlinks: gfs_latest.json points to most recent fetch
```

## Model Schedule

| Model | Members | Runs | Delay | Best Capture |
|-------|---------|------|-------|--------------|
| GFS | 31 | 00z, 06z, 12z, 18z | ~3.5h | 07:30, 19:30 UTC |
| ECMWF IFS | 51 | 00z, 12z | ~7h | 07:30, 19:30 UTC |
| ECMWF AIFS | 51 | 00z, 12z | ~7h | 07:30, 19:30 UTC |
| GEM | 21 | 00z, 12z | ~4h | 07:30, 19:30 UTC |

## VM Setup

- **User**: ubuntu
- **Project dir**: ~/wxd
- **Venv**: ~/wxd/venv
- **Cron**: 07:30 and 19:30 UTC daily

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
30 7,19 * * * /home/ubuntu/wxd/cron_fetch.sh
```

Runs at 07:30 and 19:30 UTC to capture:
- 00z runs (available by ~07:00 for all models)
- 12z runs (available by ~19:00 for all models)

## Troubleshooting

1. **Fetch fails**: Check Open-Meteo status, network connectivity
2. **Push fails**: Verify SSH key, git remote config
3. **Data stale**: Check `cron.log`, verify crontab
4. **Old files not deleted**: Check cleanup logic in fetch.py

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
