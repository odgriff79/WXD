# CLAUDE.md - WXD Project

**Read this file at the start of every session.**

## Project Summary

Weather ensemble data pipeline. The VM fetches raw JSON from Open-Meteo and pushes to GitHub. That's it.

**Your role (Claude Code on VM)**: Infrastructure maintenance only.

**NOT your role**: Weather analysis, data interpretation, statistics. That happens in Claude.ai browser.

## VM Setup

- **User**: ubuntu
- **Project dir**: ~/wxd
- **Venv**: ~/wxd/venv
- **Cron**: Scheduled fetch + push

## Commands

```bash
# Activate environment
cd ~/wxd && source venv/bin/activate

# Manual fetch
python fetch.py

# Commit and push
git add data/*.json && git commit -m "Update $(date -u +%Y-%m-%d_%H%MZ)" && git push
```

## Cron Job

Runs automatically. Check with:
```bash
crontab -l
```

## Troubleshooting

1. **Fetch fails**: Check Open-Meteo status, network connectivity
2. **Push fails**: Verify SSH key, git remote config
3. **Data stale**: Check cron logs in syslog

## DO NOT

- Add analysis code
- Parse or process the JSON
- Create summary files
- Interpret weather data

The raw JSON goes to GitHub. Claude.ai does everything else.
