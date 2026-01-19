# CLAUDE.md - WXD Project

---
---
## ⚠️ STOP AND READ BEFORE ACTING ⚠️

**Before using ANY module or feature, READ its section in this file FIRST.**

- Bluesky work? Read "Bluesky Publishing - EXPERT MODULE" section first
- Reply system? Read "Reply System" section first
- Posting? Read "Mandatory Rules" section first

**DO NOT GUESS.** Check method names, follow documented patterns. Repeat offenses logged.

---
## ⚠️ MANDATORY: VM CONNECTION - READ FIRST ⚠️

**WXD-VM IP: 144.21.62.133** — This is the ONLY VM for WXD work.

Before ANY SSH command:
1. Read `.vm_config` to get the correct IP
2. **NEVER use 132.145.50.77** — that is EVO-VM (wrong project)
3. If context was compacted/lost, RE-READ this file and `.vm_config`

```
# Correct SSH pattern for WXD:
ssh -i "KEY_PATH" ubuntu@144.21.62.133 "cd ~/wxd && ..."
```

**If you are unsure which VM to use, STOP and ASK.**

---
## ⚠️ KNOWN ISSUE: Open-Meteo 504 Timeouts ⚠️

**Problem**: UKMO tracker fails with `504 Gateway Time-out` from Open-Meteo API.
**Frequency**: Intermittent, seen 14-15 Jan 2026.
**Solution**: Retry logic in `trackers/ukmo/fetch.py` - 7 retries over 2 hours (1m, 2m, 5m, 10m, 15m, 30m, 60m) with 3min request timeout.

**If user reports UKMO 504 error:**
1. Check if it's already recovered (API may be back): `curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5074&longitude=-0.1278&hourly=temperature_850hPa&models=ukmo_global_deterministic_10km&forecast_days=7&timezone=UTC" | head -1`
2. If API works, run: `bash trackers/ukmo/cron_ukmo.sh 2>&1 | tee -a trackers/ukmo/cron.log`
3. Verify dashboard shows green: `curl -s http://144.21.62.133:8080/ | grep -A2 "UKMO Tracker"`
4. Send recovery ntfy: `curl -d "UKMO recovered" ntfy.sh/wxd-alerts`

**DO NOT** just run fetch.py and post.py separately - use cron_ukmo.sh so logs update properly.

---

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

**Automation Architecture:** [docs/AUTOMATION_ARCHITECTURE.md](docs/AUTOMATION_ARCHITECTURE.md) - Maps post types to source code, cron schedules, **status dashboard** (http://144.21.62.133:8080), and state tracking system.

Key points:
- **Two-step engagement**: First reply gets canned "reply 'chat' to continue", Claude only invoked after opt-in
- **User tiers**: Blocked → Non-follower → Follower → Trusted (different limits)
- **Pre-filters**: Blocklist, pass-through (@tags), follower check - all before any Claude call
- **Session limits**: 5 msgs/session (standard), 10 msgs (trusted), 72h expiry
- **Corrections**: Always require human approval via ntfy

**Post Registry:** [`docs/POST_REGISTRY.md`](docs/POST_REGISTRY.md) - All posts are logged with tracker/model info to `data/post_registry.json` for feedback tracing.

**Feedback Analysis Workflow:**
When reviewing user feedback on automated posts:
1. Run `python reply_listener.py --post --force` to fetch new notifications
2. Run `python reply_listener.py --feedback` to display feedback with tracker identification
3. The system automatically looks up `parent_uri` in the post registry to identify the tracker
4. Fix the correct code file based on tracker shown

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
├── lib/
│   └── bluesky.py        # Shared Bluesky publishing module (cross-project)
├── data/
│   └── post_registry.json # Post→tracker mapping for feedback tracing
└── docs/
    ├── REPLY_SYSTEM.md   # Reply system architecture
    ├── POST_REGISTRY.md  # Post registry system docs
    ├── index.html        # GitHub Pages chart gallery
    └── charts/           # Published charts
```

## Bluesky Publishing - EXPERT MODULE

**Full docs:** `docs/BLUESKY_PUBLISHING.md`
**Module:** `lib/bluesky.py`

### CRITICAL KNOWLEDGE (read before any Bluesky work)

1. **URLs DO NOT auto-link** - Bluesky requires "facets" to make links clickable
2. **Bluesky has NO edit** - must delete and repost
3. **Facets use BYTE positions** - not character positions (UTF-8!)
4. **Max 300 characters** per post
5. **Threads need [X/Y] numbering** - MANDATORY
6. **NEVER GUESS METHOD NAMES** - Check Quick Reference below or run `dir(client)` BEFORE calling any method. Repeat offense logged 2026-01-11.
7. **EDUCATIONAL CONTENT NEEDS LOGIC CHECK** - Verify causal claims are correct direction. "X causes Y" must be verified, not just plausible. See "Simon Lee Test" in docs/BLUESKY_PUBLISHING.md. Incident logged 2026-01-18.

### Available Methods (MEMORIZE - do not guess)

```python
BlueskyClient methods:
- post(text, image_path=None)    # Single post
- post_thread(posts)             # Thread
- delete(uri)                    # Delete by URI
- get_recent_posts(limit=20)     # List own posts
- find_posts_containing(text)    # Search posts
- replace(uri, new_text)         # Delete + repost
- get_post(uri)                  # Get single post
```

### Quick Reference

```python
# From ANY wxd project on this VM:
import sys
sys.path.insert(0, '/home/ubuntu/wxd')
from lib.bluesky import BlueskyClient

client = BlueskyClient()  # Reads from BSKY_HANDLE, BSKY_PASSWORD env vars

# Post (URLs auto-linked!)
result = client.post("Check this: https://example.com")
# result = {'uri': 'at://...', 'cid': '...', 'url': 'https://bsky.app/...'}

# Thread (auto-numbered)
results = client.post_thread(["Part 1...", "Part 2...", "Part 3..."])

# Delete
client.delete(result['uri'])

# List recent posts
for p in client.get_recent_posts(10):
    print(f"{p['text'][:50]}...")

# Find posts to delete
posts = client.find_posts_containing("[1/5]")

# Replace (delete + repost - WARNING: loses engagement)
client.replace(old_uri, "Corrected text")

# ENGAGEMENT TOPIC TRACKING - prevents repeats!
from lib.bluesky import EngagementTracker
tracker = EngagementTracker()

# Check before posting engagement content
if tracker.is_topic_recent("Why forecasts change"):
    print("Too recent - pick different topic!")

# ALWAYS log after manual engagement posts
tracker.log_topic("weather_education", "Topic text here")
```

### Environment Setup

```bash
# Must be run before using BlueskyClient:
source ~/.wxd_env  # Sets BSKY_HANDLE and BSKY_PASSWORD
```

### Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `BadRequestError repo must be valid did` | Wrong URI format for delete | Use full `at://` URI from post result |
| Link not clickable | Facets missing | Module auto-detects - if manual, check byte positions |
| Thread not connected | Reply chain broken | Use `post_thread()` which handles chaining |

### When You Make a Mistake - LOG IT

```python
from lib.bluesky import log_lesson

# After fixing any Bluesky issue, log it for future sessions:
log_lesson(
    problem="What went wrong",
    root_cause="Why it happened",
    fix="How you fixed it",
    prevention="How to avoid in future"
)
```

This appends to `docs/BLUESKY_PUBLISHING.md` - future Claude sessions will see it!

### Hashtags

**See `docs/HASHTAGS.md` for full reference.**

Quick rules:
- **#ukweather** - major events only, DON'T SPAM
- **#uksnow** - respect UK Snow Map project
- Regular posts = NO hashtags
- Tech posts = #python #claude #opensource

### DO NOT

- Manually construct facets unless necessary (module auto-detects URLs)
- Assume links will auto-link (they won't!)
- Try to edit a post (delete and repost instead)
- Forget to activate venv and source `~/.wxd_env` first
- Spam hashtags on routine posts

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

### Other Projects on WXD-VM
The WXD-VM also hosts other ISOLATED projects:

| Project | Path | Port | Notes |
|---------|------|------|-------|
| wxd | ~/wxd/ | 8080 | This project |
| wxd-direct | ~/wxd-direct/ | 8081 | GRIB validation POC |
| stock-lab | ~/stock-lab/ | 8082 | PRIVATE - do not interact |

**CRITICAL**: These projects are ISOLATED. Never cross-contaminate code, data, or credentials between them.

### Rules
- **WXD work goes to WXD-VM only**
- **EVO-VM is maintenance-only for Evo_mon — do not touch for WXD**
- **stock-lab is PRIVATE** - do not access its code, data, or details from wxd context
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

### OCI CLI (Oracle Cloud Infrastructure)
OCI CLI is installed on VM for managing cloud resources:
```bash
export PATH=/home/ubuntu/.local/bin:$PATH
export SUPPRESS_LABEL_WARNING=True
oci network security-list get --security-list-id <SECURITY_LIST_OCID>
```
- **Config**: ~/.oci/config (API key auth)
- **Security list OCID**: See `oci network vcn list` to find your VCN, then check default-security-list-id

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

## Met Office Warnings - 48 Hour Rule (PROJECT-WIDE)

**NEVER mention Met Office warnings unless ALL criteria are met:**

1. **48 hours max** - Warning must be within next 48 hours
2. **Specific date** - Must have structured format like "Tue 20 Jan" (not vague ranges like "Friday 23 Jan - Sunday 1 Feb")
3. **Regions affected** - Must explicitly list England/Scotland/Wales/Northern Ireland
4. **Warning level** - Must have Yellow/Amber/Red level

**If ANY of these are missing → don't mention warnings at all.**

**Implementation:**
- Single shared function: `filter_warnings_48h()` in `daily_summary.py`
- Used by: `post_bluesky.py`, `trackers/shared/commentary.py`
- Returns empty string if validation fails

**Why this rule exists:**
- 2026-01-19: Posted "Yellow warning Friday 23 Jan - Sunday 1 Feb" which was a **forecast period header**, not an actual warning
- Met Office doesn't issue warnings 4+ days ahead
- Vague date ranges from forecast text were being confused with real warnings

**Test:** If you can't point to specific date + level + regions in the raw data, it's not a real warning.

## Location Inference Rule (PROJECT-WIDE)

**All locations are assumed to be UK unless explicitly stated otherwise.**

When users mention places:
- Winchester → Winchester, UK (use London data as proxy)
- Boston → Boston, Lincolnshire, UK (NOT Massachusetts)
- Any ambiguous city → UK interpretation first

**Why:** WXD is a UK weather project. All our models use London coordinates. Users asking about "their weekend weather" are UK-based.

**For cross-tracker responses:**
- Always use our standard London 850hPa data
- Location names mentioned just indicate the user's local area
- Don't try to fetch location-specific data - our data IS the relevant data

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
- Run reply_listener.py with --post when debugging (use dry-run only, --post consumes test data)
- Use git stash/pop carelessly (can lose DB data and state files)
- Process live data when testing fixes (verify with dry-run first, preserve test cases)
- Guess function/class names when importing - always grep for actual definition first

## Commentary Hallucination Prevention

**2026-01-18 incident**: Claude wrote "cold peak Tuesday 21st" when data showed Jan 21 was +0.6C (mild). Actual coldest was Jan 27. Root cause: Claude saw "Tue 27" in context but wrote "Tue 21" - date confusion.

**Current fixes (post_bluesky.py):**
1. Date format changed from `%a %d` ("Tue 27") to `%a %b %d` ("Tue Jan 27") - harder to misread
2. Temperature trajectory added to context - Claude sees actual temps by date to cross-verify

**FUTURE IMPROVEMENT: Chart Image Verification**

The anthropic SDK is installed (`pip install anthropic` done 2026-01-18) but NOT yet integrated.

To implement chart-based sanity checking:
1. Add `ANTHROPIC_API_KEY` to `~/.wxd_env` (create at console.anthropic.com → API Keys)
2. Modify `get_claude_commentary()` to use SDK instead of CLI
3. Pass chart image along with data context
4. Add prompt instruction: "Verify your commentary matches the chart shape - coldest point should align visually"

This would catch gross errors where commentary contradicts the visual curve. The trajectory approach works but image verification is more robust.

**Code location**: `post_bluesky.py` line ~1335 (subprocess call to claude CLI)

**SDK usage pattern**:
```python
import anthropic
import base64

client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
with open(chart_path, "rb") as f:
    image_data = base64.standard_b64encode(f.read()).decode("utf-8")

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_data}},
            {"type": "text", "text": prompt}
        ]
    }]
)
```

---

## NEVER MAKE THINGS UP

**This is mandatory. Violation requires public correction.**

Before stating ANY fact in public posts or documentation:
- **Durations/timelines**: Check git log, CHANGELOG, or project start date
- **Numbers/statistics**: Verify from actual data, code, or logs
- **Feature claims**: Confirm code actually does what you're claiming
- **Dates**: Check calendar, commits, or documentation

If unsure, say "approximately" or "I believe" - or ask the user to confirm.

**2026-01-10 incident**: Claimed "6 months in production" when project was 2 weeks old. Required public apology on Bluesky.


## Migration Plan: wxd → wxd-legacy

**Status:** PLANNED - Migration approved, awaiting Phase 1 start

This project will be renamed to `wxd-legacy` and archived. A new unified `wxd` project will replace it, using direct GRIB fetching instead of Open-Meteo.

**Why:**
- Direct agency data is more reliable (171 validation pairs, <0.3K delta)
- 67% more data points per day (30 vs 18 runs)
- Near real-time latency vs 1-2h Open-Meteo delay
- Full MOGREPS ensemble access (18 members)
- Removes third-party dependency

**Migration Phases:**
1. Create new unified repo (becomes `wxd`)
2. Port analysis layer with JSON→SQLite migration
3. Port posting/commentary system
4. Port supporting systems (replies, dashboard, ntfy)
5. Shadow mode (7+ days parallel running)
6. Cutover
7. Archive this project as `wxd-legacy`

**Key Documents (in ~/wxd-direct/):**
- `docs/MIGRATION_PLAN.md` - Full 7-phase plan with validation requirements
- `docs/wxd_migration_ai_responses.md` - AI review synthesis
- `reports/DIRECT_VS_OPENMETEO_COMPARISON.md` - Evidence for migration

**Until Migration:**
- This project continues as production
- No new features - stability only
- All ntfy commands remain here until cutover

**IMPORTANT:** During shadow mode (Phase 5), this project remains authoritative. The new system runs in dry-run only.

## WXD-Direct Project (~/wxd-direct/)

Validation POC for direct GRIB fetching. All 7 models proven working. Will be merged into new unified `wxd` project during migration.

**Location:** ~/wxd-direct/ (same VM, separate directory)
**Details:** See ~/wxd-direct/CLAUDE.md for full project brief, phases, and status.

**IMPORTANT:** wxd-direct is ISOLATED from ~/wxd - do not cross-contaminate code or data.
