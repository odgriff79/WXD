# CLAUDE.md - WXD Project

**Read this file at the start of every session.**

## Project Summary

Weather ensemble data pipeline with automated Bluesky posting. Multiple trackers fetch data from different sources, generate AI commentary via Claude CLI, and post to Bluesky.

**Live:** [@wxd-london.bsky.social](https://bsky.app/profile/wxd-london.bsky.social)
**Charts:** [odgriff79.github.io/WXD](https://odgriff79.github.io/WXD/)

## Trackers

| Tracker | Model | Schedule (UTC) | Files |
|---------|-------|----------------|-------|
| A (Main) | GFS+ECM+AIFS+GEM | 08:30, 20:30 | `fetch.py`, `post_bluesky.py` |
| B | ICON-EU-EPS (40 members) | 04:30, 16:30 | `trackers/icon/` |
| C | MOGREPS-G (18 members) | TBD | `trackers/mogreps/` (planned) |
| D | UKMO Global (deterministic) | 05:00, 17:00 | `trackers/ukmo/` |

## Key Files

```
wxd/
├── fetch.py              # Main 4-model data fetch
├── post_bluesky.py       # Main tracker posting (Tracker A)
├── daily_summary.py      # Met Office narrative thread
├── sync_charts.sh        # Push charts to GitHub Pages
├── trackers/
│   ├── shared/
│   │   ├── __init__.py
│   │   └── analysis.py   # Common analysis functions (trend, percentile, timing)
│   ├── icon/
│   │   ├── fetch.py      # DWD GRIB fetcher
│   │   ├── post.py       # ICON posting
│   │   └── cron_icon.sh
│   └── ukmo/
│       ├── fetch.py      # Open-Meteo fetcher
│       ├── post.py       # UKMO posting
│       └── cron_ukmo.sh
└── docs/
    ├── index.html        # GitHub Pages chart gallery
    └── charts/           # Published charts
```

## Shared Analysis Module

`trackers/shared/analysis.py` provides common functions for all trackers:
- `run_full_analysis()` - Main pipeline returning all analysis + context string
- Trend persistence tracking
- Percentile framing (ensemble agreement)
- Timing uncertainty analysis
- Run-on-run shift detection

## VM Setup

- **User**: ubuntu
- **Project dir**: ~/wxd
- **Venv**: ~/wxd/venv
- **Env file**: ~/.wxd_env (Bluesky credentials)

## Commands

```bash
# Activate environment
cd ~/wxd && source venv/bin/activate && source ~/.wxd_env

# Manual runs (dry-run first!)
python post_bluesky.py --dry-run              # Tracker A
python trackers/icon/post.py --dry-run        # ICON
python trackers/ukmo/post.py --dry-run        # UKMO

# Check cron
crontab -l

# View logs
tail -100 cron.log

# Sync charts to GitHub Pages
./sync_charts.sh
```

## Remote Preview (ntfy.sh)

```bash
curl -d "preview" ntfy.sh/YOUR_CHANNEL    # Quick preview
curl -d "fresh" ntfy.sh/YOUR_CHANNEL      # Fresh fetch + preview
curl -d "icon" ntfy.sh/YOUR_CHANNEL       # ICON preview
curl -d "ukmo" ntfy.sh/YOUR_CHANNEL       # UKMO preview
```

## Remote Orchestration

**Check `.vm_config` for VM IP and SSH key path (gitignored).**

```bash
# Example from VS Code
ssh -i "$SSH_KEY" ubuntu@$VM_IP "cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && python post_bluesky.py --dry-run"
```

## Critical Notes

1. **GitHub username is `odgriff79`** - NOT ogrisel
2. **Claude CLI has no `--max-tokens` flag** - Don't add it, causes silent failures
3. **Always `--dry-run` first** before live posts
4. **Update CHANGELOG.md** after any code changes
5. **MANDATORY: Thread numbering** - ALL multi-post Bluesky threads MUST include `[X/Y]` at the start of each message (e.g., `[1/4]`, `[2/4]`). No exceptions.

## Troubleshooting

| Issue | Check |
|-------|-------|
| Post shows fallback text only | Claude CLI failing - check stderr |
| Chart not updating on GitHub Pages | Run `./sync_charts.sh` |
| Cron not running | `crontab -l`, check permissions on .sh files |
| ICON fetch fails | DWD servers, eccodes installation |

## SECURITY - READ CAREFULLY

**NEVER include in any file committed to git:**
- SSH key paths or filenames (e.g., `ssh-key-*.key`)
- VM IP addresses
- ntfy channel names (use `YOUR_CHANNEL` placeholder)
- Any file paths containing usernames or personal directories
- Bluesky credentials or API keys
- Any personally identifiable information

**Before creating/editing public files:**
1. Check if the file will be committed to git
2. Replace all sensitive values with placeholders like `YOUR_VM_IP`, `YOUR_CHANNEL`, `PATH_TO_KEY`
3. Review the content for any personal paths or credentials

**If you accidentally commit sensitive info:**
- The git history retains it even after deletion
- Rotating the exposed secret (e.g., change ntfy channel) is safer than history rewrite

## Background Tasks (Check at session start)

**Oracle A1 Grabber** - Started 2024-12-30
- Script: `~/grab_a1_instance.sh` on VM
- Log: `/home/ubuntu/grab_a1.log`
- Purpose: Grab Oracle A1.Flex free tier (4 OCPU, 24GB RAM, uk-london-1)
- PAYG upgrade initiated 2024-12-30 (improves capacity access)
- Budget alert: £1/month safety limit set
- Check status: Send `oracle` to ntfy.sh/wxd-cmd
- On success: Alerts wxd-alerts with instance IP
- **Migration plan**: See `MIGRATION_PLAN.md` for full setup checklist
- Remove this section once instance is acquired and migrated

## DO NOT

- Add `--max-tokens` to Claude CLI calls (doesn't exist)
- Use `ogrisel` anywhere (wrong username)
- Post without `--dry-run` testing first
- Commit credentials or `.vm_config`
- Include SSH key paths, VM IPs, or ntfy channels in committed files
- Create cheatsheets or docs with real infrastructure details in public repos
- Post multi-message threads without `[X/Y]` numbering on EVERY message
