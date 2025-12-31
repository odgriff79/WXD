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

## Reply System

Automated reply handling with cost controls and abuse prevention. **Full architecture: [`docs/REPLY_SYSTEM.md`](docs/REPLY_SYSTEM.md)**

Key points:
- **Two-step engagement**: First reply gets canned "reply 'chat' to continue", Claude only invoked after opt-in
- **User tiers**: Blocked → Non-follower → Follower → Trusted (different limits)
- **Pre-filters**: Blocklist, pass-through (@tags), follower check - all before any Claude call
- **Session limits**: 5 msgs/session (standard), 10 msgs (trusted), 72h expiry
- **Corrections**: Always require human approval via ntfy

Scripts:
- `reply_listener.py` - Main processor (cron every 4h)
- `fetch_own_posts.py` - Post history for audit

## Key Files

```
wxd/
├── fetch.py              # Main 4-model data fetch
├── post_bluesky.py       # Main tracker posting (Tracker A)
├── daily_summary.py      # Met Office narrative thread
├── reply_listener.py     # Reply monitoring & response
├── fetch_own_posts.py    # Post history fetcher
├── sync_charts.sh        # Push charts to GitHub Pages
├── trackers/
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── analysis.py   # Common analysis functions
│   │   └── commentary.py # Shared Claude commentary generation
│   ├── icon/
│   │   ├── fetch.py      # DWD GRIB fetcher
│   │   ├── post.py       # ICON posting
│   │   └── cron_icon.sh
│   ├── mogreps/
│   │   ├── fetch.py      # Met Office S3 fetcher
│   │   ├── post.py       # MOGREPS posting
│   │   └── cron_mogreps.sh
│   └── ukmo/
│       ├── fetch.py      # Open-Meteo fetcher
│       ├── post.py       # UKMO posting
│       └── cron_ukmo.sh
├── engagement/
│   └── engagement_post.py # Community engagement posts
└── docs/
    ├── REPLY_SYSTEM.md   # Reply system architecture
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

## VM Environment Separation — CRITICAL

Two VMs exist. They are completely separate. **Never cross-contaminate.**

| Name | Purpose | Hostname | Status |
|------|---------|----------|--------|
| **WXD-VM** | All WXD work | wxd-arm-vm | **ACTIVE** - all development here |
| **EVO-VM** | Evo_mon only | evohome-monitor | Maintenance only - DO NOT USE for WXD |

### Rules
- **WXD work goes to WXD-VM only**
- **EVO-VM is maintenance-only for Evo_mon — do not touch for WXD**
- Before any remote operation: **STOP → CONFIRM target VM by name → CHECK `.vm_config` → proceed**
- If uncertain, **ASK**

### Connection Details
Stored in `.vm_config` (gitignored). **Never hardcode IPs or keys.**

### WXD-VM Details
- **Hardware**: Oracle ARM A1.Flex (4 OCPU, 24GB RAM)
- **User**: ubuntu
- **Project dir**: ~/wxd
- **Venv**: ~/wxd/venv
- **Env file**: ~/.wxd_env (Bluesky credentials)
- **Migrated**: 2025-12-30

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
# Tracker A (main ensemble)
curl -d "preview" ntfy.sh/YOUR_CHANNEL    # Quick preview (stale data)
curl -d "fresh" ntfy.sh/YOUR_CHANNEL      # Fresh fetch + preview

# Other trackers
curl -d "icon" ntfy.sh/YOUR_CHANNEL       # ICON preview
curl -d "icon-fresh" ntfy.sh/YOUR_CHANNEL # ICON fresh + preview
curl -d "ukmo" ntfy.sh/YOUR_CHANNEL       # UKMO preview
curl -d "ukmo-fresh" ntfy.sh/YOUR_CHANNEL # UKMO fresh + preview
curl -d "mogreps" ntfy.sh/YOUR_CHANNEL    # MOGREPS preview
curl -d "mogreps-fresh" ntfy.sh/YOUR_CHANNEL  # MOGREPS fresh + preview

# Daily/engagement
curl -d "summary" ntfy.sh/YOUR_CHANNEL    # Met Office summary preview
curl -d "engagement" ntfy.sh/YOUR_CHANNEL # Engagement post preview

# Reply system
curl -d "check" ntfy.sh/YOUR_CHANNEL      # Check replies NOW (dry-run)
curl -d "respond" ntfy.sh/YOUR_CHANNEL    # Check AND respond NOW (live)

# Utility
curl -d "status" ntfy.sh/YOUR_CHANNEL     # Quick system status
curl -d "oracle" ntfy.sh/YOUR_CHANNEL     # Check A1 grabber status
```

## Cron Schedule (UTC)

| Job | Time | Script |
|-----|------|--------|
| Tracker A | 08:30, 20:30 | `cron_fetch.sh` |
| ICON | 04:00, 10:00, 16:00, 22:00 | `trackers/icon/cron_icon.sh` |
| MOGREPS | 03:00, 09:00, 15:00, 21:00 | `trackers/mogreps/cron_mogreps.sh` |
| UKMO | 07:00, 19:00 | `trackers/ukmo/cron_ukmo.sh` |
| Daily Summary | 09:30 | `cron_daily_summary.sh` |
| Chart Sync | 10:15, 22:15 | `sync_charts.sh` |
| Reply Listener | */15 min | `reply_listener.py --post` |
| Engagement (Sun) | 12:00 | `engagement_post.py --community-request` |
| Engagement (Tue/Fri) | 12:00 | `engagement_post.py` |

**Reply Listener Adaptive Polling:**
- Cron runs every 15 min
- If reply received in last 60 min (engaged mode): runs
- If no recent activity (quiet mode): only runs every 2h
- Use `--force` to bypass adaptive polling

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

## DO NOT

- Add `--max-tokens` to Claude CLI calls (doesn't exist)
- Use `ogrisel` anywhere (wrong username)
- Post without `--dry-run` testing first
- Commit credentials or `.vm_config`
- Include SSH key paths, VM IPs, or ntfy channels in committed files
- Create cheatsheets or docs with real infrastructure details in public repos
- Post multi-message threads without `[X/Y]` numbering on EVERY message
