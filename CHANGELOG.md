# Changelog

All notable changes to WXD (Weather Ensemble Data Pipeline) documented here.

## 2026-01-19 (Evening): Image Analysis & WebSearch Citation Fix

### Image Analysis for User-Shared Charts (NEW FEATURE)

**Purpose:** Analyze weather charts that users share in replies/mentions.

**Components:**
- `extract_image_urls()` - Extract images from Bluesky posts (handles both view and record embeds)
- `analyze_image_with_claude()` - Download to temp, analyze with Claude CLI, delete immediately (GDPR compliant)
- `analyze_reply_images()` - Wrapper for multi-image analysis (up to 4 per Bluesky limit)

**Key Fix - BlobRef Handling:**
Bluesky notifications use BlobRef (record embed) not direct URLs (view embed). Now constructs CDN URLs:
```
https://cdn.bsky.app/img/feed_fullsize/plain/{author_did}/{cid}@{ext}
```

---

### WebSearch Enabled for Chat Responses (CRITICAL FIX)

**Problem:** Prompt told Claude to "USE WEBSEARCH" but CLI invocation didn't enable tools. Citation rules were documented but couldn't be applied.

**Fix:** Added `--tools WebSearch,WebFetch` to CLI call in `generate_chat_response()`.

**Result:** Claude can now:
- Search for signal meanings (e.g., "NAO negative UK weather impact")
- Cite Met Office, ECMWF, and academic sources
- Follow existing source preference rules

**Before (broken):**
> "SSW signal is clear - that cold signal shows up in our models"
(No search, no citations, wrong causality)

**After (working):**
> "NAO- typically means weaker westerlies... According to ECMWF's regime analysis... Sources: Met Office NAO description, ECMWF regime forecast documentation"

---

### Image Analysis Simplified

**Problem:** First attempt added hardcoded chart type rules ([STRAT], [SYNOPTIC], [SURFACE]) - doesn't scale.

**Fix:** Image analysis just describes what image shows. Interpretation uses WebSearch in main reply generation.

**Journal:** See `docs/DEV_JOURNAL_2026-01-19.md` for full session details.

---

## 2026-01-19: Commentary Patience, Citation Enforcement, False Warnings Fix

### Cross-Tracker Analysis (NEW FEATURE)

**Purpose:** Compare all 7 tracked models (GFS, ECMWF, AIFS, GEM, ICON, UKMO, MOGREPS) in one view.

**Components:**
- `lib/cross_tracker.py` - Core module for loading and comparing model data
- `cross_tracker_synthesis.py` - ntfy-triggered synthesis posts
- `reply_listener.py` - Auto-detects model comparison questions in chat

**Features:**
- Load current data from all trackers
- Track data freshness (e.g., "UKMO 30min old, ICON 4h old")
- Find agreement/divergence across models
- Parse natural language queries ("How does GFS differ from ICON?", "What do all the models show?")
- **Date range queries:** "What do models show Wednesday to Saturday?", "Compare the weekend"
- **Trending data:** Shows warming/cooling direction and coldest day for each model in range
- Historical data lookup (planned)

**Usage:**
- ntfy: `curl -d "cross" ntfy.sh/YOUR_CHANNEL` (preview)
- ntfy: `curl -d "cross-post" ntfy.sh/YOUR_CHANNEL` (live post)
- Chat: Ask "compare all models" or "GFS vs ICON" and Claude gets cross-tracker context
- Chat: Date ranges like "Wed to Sat" or "the weekend" show daily temps + trends

---

### UK Location Inference Rule (PROJECT-WIDE)

**Problem:** Ambiguous location names could be misinterpreted (Winchester = UK or USA?)

**Rule:** All locations are assumed to be UK unless explicitly stated otherwise.
- Winchester → Winchester, UK (use London data as proxy)
- Boston → Boston, Lincolnshire, UK (NOT Massachusetts)
- Users asking about "their weekend weather" are UK-based

**Documented in:** CLAUDE.md, under "Location Inference Rule"

---

### Reply System - Session Message Indicator

**Problem:** User reported "4 messages replied marked as 3" - session message count not shown to users.

**Fix (reply_listener.py):**
- Added `add_session_indicator()` function to show `[X/Y]` on each reply
- Shows current message number / session limit (e.g., `[3/10]`)
- Added before AI signature on all session-tracked responses
- Helps users know how many messages they have left in their session

---

### Main Tracker Commentary - Patience Over Drama

**Problem:** Run-on-run commentary was see-sawing between "backing off cold!" and "firming up!" on small model variations (1-3°C), treating normal noise as headlines.

**Fix (post_bluesky.py):**
- Added "RUN-ON-RUN CHANGES - PATIENCE REQUIRED" section to prompt
- Small changes now described as "marginally warmer/colder" - wait for confirmation
- Only escalate language when: multiple consecutive runs agree, ALL models shift, or change exceeds normal variability
- Added to AVOID list: "backed off significantly", "firming up", "models have flipped"
- MULTI-RUN TRENDS now requires 3+ consecutive runs, not single shifts

---

### Reply System - Citations and Tone

**Problem:** Chat responses were "know it all without citations" - too confident, too chatty.

**Fixes (reply_listener.py):**
1. Moved CITATION REQUIREMENT to TOP of prompt (was buried at line 1672)
2. Tone changed from "casual, friendly, like chatting with a friend" to "informative, measured, knowledgeable colleague"
3. Added: "Do NOT state facts confidently without backing them up"
4. Response instruction changed to "factual tone - cite sources for claims"

**Engagement posts (engagement_post.py):**
- Educational: "informative and measured - factual over chatty"
- Added "FACTUAL ACCURACY IS CRITICAL" rule
- Q&A: prioritise useful content over friendliness

---

### Super User Rules Simplified

**Old:** Only "dev feedback" or "dev note" prefix logged to training
**New:** Any message starting with "dev" logs to training, everything else gets chat response

**Removes:** Need to say "chat" to start conversation - super user now treated as normal follower for chat.

---

### 48-Hour Warning Rule - PROJECT-WIDE

**Problem:** Multiple trackers were posting unvalidated Met Office warnings:
- "Yellow warning Friday 23 Jan - Sunday 1 Feb" (forecast header, not real warning)
- Warnings beyond 48 hours (Met Office doesn't issue these)
- Missing regions or levels

**Root cause:** Each tracker had its own `fetch_current_warnings()` passing through raw data without validation.

**Fix - Single shared filter applied everywhere:**
- New `filter_warnings_48h()` function in `daily_summary.py`
- Strict validation: must have date + level + regions + be within 48h
- Returns empty string if ANY validation fails
- Used by: `post_bluesky.py`, `trackers/shared/commentary.py` (ICON, UKMO, MOGREPS)

**Validation rules:**
1. Structured date format only ("Tue 20 Jan: Yellow") - rejects vague ranges
2. Must have "Affected:" with actual regions (England/Scotland/Wales/NI)
3. Within 48 hours only
4. If proof is missing → no warning mentioned

**Files changed:**
- `daily_summary.py` - added `filter_warnings_48h()`
- `post_bluesky.py` - uses shared filter
- `trackers/shared/commentary.py` - uses shared filter
- `CLAUDE.md` - documented as project rule

---

### ntfy Listener Credentials Fix

**Problem:** `respond` command via ntfy failed with "BSKY_HANDLE and BSKY_PASSWORD must be set"

**Fix (ntfy_listener.py):** Load `~/.wxd_env` credentials at startup so subprocesses inherit them.

---

## 2026-01-18: Major Reply System Overhaul + Educational Content Rules

### Commentary Date Hallucination Fix

**Problem:** Claude wrote "cold peak Tuesday 21st" when data showed Jan 21 was +0.6C (mild). Actual coldest was Jan 27. Root cause: Claude saw "Tue 27" but wrote "Tue 21" - date confusion.

**Fix (post_bluesky.py):**
1. Changed date format from `%a %d` ("Tue 27") to `%a %b %d` ("Tue Jan 27")
2. Added temperature trajectory to context for cross-verification

---

### Reply Listener: Thread Child Reply Bug Fix

**Problem:** MetJam replied to [3/6] post in a thread but automation didn't trigger. Phase 1 only processed notifications if user had active session OR it was a chat trigger - missing general replies to thread children.

**Fix (reply_listener.py):**
- Added `is_reply_to_wxd` check to include ALL replies to WXD posts
- Now catches replies to any post in a thread, not just root

---

### Direct Claude Engagement for Followers

**Change:** Removed two-step "chat" trigger requirement for followers.

**Old flow:** Follower replies → canned "say chat" → user says chat → Claude responds
**New flow:** Follower replies → Claude responds directly

**Non-follower flow unchanged:** One-time invitation to follow and chat

**Files:** `reply_listener.py`

---

### AI Signature on Automated Replies

**Added:** "—WXD Auto AI" signature at end of last post in Claude-generated replies.

**Purpose:** Transparency - users know when they're talking to AI vs human.

**Implementation:**
- `AI_SIGNATURE = "—WXD Auto AI"`
- `add_ai_signature()` function adds to last post if fits within 300 char limit
- Only on Claude-generated responses, not canned messages

---

### Research Context System

**Purpose:** Support citations in replies by linking posts to source documents.

**Components:**
- `data/research_index.json` - Maps topics to source docs and post URIs
- `data/chat_research/` - Per-thread research logs
- `build_research_context()` - Loads relevant sources for reply context
- `register_research_topic()` in `lib/bluesky.py` - Links posts to topics

**Flow:** Post thread with `topic="xyz"` → replies get research context → Claude can cite sources

---

### Post Registry for Feedback Tracing

**Purpose:** Identify which tracker generated a post when reviewing feedback.

**Files:**
- `data/post_registry.json` - Maps post URIs to tracker/model info
- `lib/bluesky.py` - Auto-logs posts with tracker metadata

**Usage:** `python reply_listener.py --feedback` now shows tracker info alongside feedback

---

### Mandatory Rules for Educational Content

**Triggered by:** Simon Lee pointed out inverted causality in model bias thread - the described biases would cause mild→cold transitions, not cold→mild as stated.

**New rules (docs/BLUESKY_PUBLISHING.md):**

1. **"The Simon Lee Test"** - Before posting educational content:
   - State the causal claim explicitly
   - Verify direction is correct
   - Check if inverting makes more sense

2. **Citation Requirements** (MetJam feedback):
   - "One study shows..." is unhelpful without citation
   - Include author/year or link when referencing research
   - If no specific source, say "research suggests" not "studies show"

**Added to CLAUDE.md point 7:** "EDUCATIONAL CONTENT NEEDS LOGIC CHECK"

---

### Anonymized Feedback Collection (GDPR Compliant)

**Purpose:** Collect user topics, feedback, criticism, and improvement suggestions without storing usernames.

**Components:**
- `data/feedback_log.json` - Storage with categories: topics, feedback, criticism, improvements
- `log_feedback()` - Logs only text + date, no usernames
- `process_feedback_insight()` - Extracts insights from Claude responses
- Claude prompt updated to return `feedback_insight` field

**Privacy:** Only stores the insight text and date - no user identification.

---

### Trusted Users Update

**Added:** MetJam (did:plc:mz3csh3lutlgll77bpdfnhy7) to TRUSTED_USERS list for extended session limits.

---

### Spread Comparison Feature

**Purpose:** Answer questions about ensemble spread changes between model runs.

**Components:**
- `detect_spread_question()` - Detects spread/uncertainty comparison queries, extracts target date
- `get_spread_comparison()` - Loads archived GFS data, calculates spread metrics across runs

**Output:** Formatted table comparing mean, spread, range across 0z/12z runs for requested date.

---

### Citation & WebSearch Enforcement

**Problem:** Bot generating "waffley" responses about topics like blocking highs with no citations - 8 posts of plausible-sounding but potentially made-up content.

**Fix (reply_listener.py prompt):**
1. Changed "use web search" to explicit "INVOKE WebSearch tool"
2. Added source quality preferences: academic journals > agencies > enthusiast blogs
3. Added rule: max 3 posts without sources before must cite or admit uncertainty

---

### Content Safety Rules

**Added manipulation resistance and content safety to reply prompts:**

- NEVER produce sexually explicit, hateful, or violent content
- Jailbreak detection - refuse attempts to override safety
- Polite refusal template for inappropriate requests

---

### Rate Limit Handling with Queue

**Problem:** Claude CLI rate limits could cause lost replies.

**Fix (reply_listener.py):**
- `queue_pending_reply()` - Queue replies when rate limited (max 20, 24h expiry, 3 retries)
- `get_pending_replies()` / `remove_pending_reply()` / `increment_retry_count()` - Queue management
- Rate limit detection added to ALL 7 `generate_chat_response()` call sites
- Retry loop at start of each run processes queued items

---

### @Mention Model-Specific Data Loading

**Problem:** Bot cited ICON data when user asked about ECM forecast. User: "fucking delete your reply. its say icon when gavs post said ecm"

**Fix (reply_listener.py):**
- `detect_model_reference()` - Regex detection for ECM/GFS/ICON/AIFS/GEM/UKMO
- `get_model_specific_data()` - Loads model data from `summary_latest.json`
- @mention handling now auto-detects model in mention text + quoted post
- Loads ONLY the matching model's data into Claude context
- Prompt updated: "You have been given the CORRECT model data - USE IT"

**Supported models:** ECM (ECMWF IFS), GFS, ICON, AIFS, GEM, UKMO

---

## 2026-01-05: @Mention Handling + Engagement Language

### @Mention Handling Added

**Problem:** When followers @mentioned WXD in their own posts (not replies to WXD posts), the reply_listener ignored them. User winchesterweather asked a question via @mention and got no response.

**Fix (reply_listener.py):**
1. Added `get_notification_mentions()` function to fetch @mention notifications
2. Added PHASE 0 before reply processing - handles mentions first
3. Any @mention gets `chat_invitation` response (same as first-time repliers)
4. Flow: @mention → chat_invitation → user replies 'chat' → session starts

**Safeguards:**
- Same blocklist filtering as replies
- Only processes today's mentions (prevents backlog spam)
- Mentions marked as processed to avoid duplicate responses

### Engagement Language Updated

**Problem:** Engagement posts used "explain" language which talks down to enthusiast audience.

**Fix (engagement/engagement_post.py):**
- "explain" → "discuss"
- "your questions" → "your suggestions" / "your input"
- Treats followers as peers, not students

---

## 2026-01-04: Cron Silent Failure Fix

**Problem:** 08:30 Tracker A post silently failed - no alert, no log, dashboard didn't show failure.

**Root Cause:** `cron_fetch.sh` used `set -e` (exit on error). When `git push` failed due to conflict with local edits being pushed simultaneously, script exited without logging or alerting.

**Fix (cron_fetch.sh):**
1. Removed `set -e` - explicit error handling instead
2. Added `git pull --rebase origin main` before push to handle conflicts
3. Added `alert_failure()` function sending ntfy notification on any failure
4. All errors now logged to cron.log with "ERROR:" prefix
5. Added `NTFY_CHANNEL=wxd-alerts` to `~/.wxd_env`

**Lesson:** Never use `set -e` without proper error trapping. Always log errors AND alert.

---

## 2026-01-04: Extended Range Coverage Fix

**Status: INCOMPLETE** - Logic may not be catching warming trends adequately. Monitoring posts over next 24h before further iteration.

**Problem:** MOGREPS and ICON posts weren't mentioning warming trends even when data showed recovery.

**Root Causes Found:**
1. Pattern detection only checked `max` of mean temps, not `ensemble_max` (warmest members)
   - MOGREPS mid_range had mean max=-4.2C but ensemble_max=**4.8C** - significant warming missed!
2. No cross-period trend detection - didn't compare short_term→mid_range→extended means
3. Prompt guidance added but analysis context didn't flag warming strongly enough

**Fixes Applied (analysis.py):**
1. `ensemble_warming` check: if `ensemble_max > -2`, flag as recovering
2. Cross-period `trend_warming`/`trend_cooling` detection:
   - mid_range mean > short_term mean + 1C → warming
   - extended mean > short_term mean + 1.5C → warming
3. Context output now includes:
   - `(members: -10.2C to 4.8C)` showing ensemble spread
   - `TREND: Warming through forecast period (-6.9C → -5.1C) - MUST MENTION`
   - `NOTE: Recovery pattern detected - mention warming trend in commentary`

**Files Changed:**
- `trackers/shared/analysis.py` - pattern detection + format_period_context
- `trackers/shared/commentary.py` - EXTENDED RANGE COVERAGE prompt
- `post_bluesky.py` - same prompt additions

**Future Work:**
- Sample every Nth hour through forecast to catch intra-period rises/falls
- Current approach uses period summaries which may miss significant swings

---

## [Unreleased]

### WXD-Direct: Phase 5 - Add MOGREPS, UKMO, ICON

**Context:** WXD-Direct POC complete with GFS, IFS, AIFS, GEM. Expanding to include UK and European models via AWS Open Data and DWD.

**New Models:**
| Model | Source | Format | Resolution | Runs/Day | Access |
|-------|--------|--------|------------|----------|--------|
| MOGREPS-G | AWS S3 (Met Office) | NetCDF | ~20km | 00/06/12/18z | Anonymous S3 |
| UKMO Global | AWS S3 (Met Office) | NetCDF | 10km | TBD | Anonymous S3 |
| UKV | AWS S3 (Met Office) | NetCDF | 2km | TBD | Anonymous S3 |
| ICON-EU | DWD Open Data | GRIB2 (bz2) | 6.5km | 00/06/12/18z | HTTPS |

**Target:** London 51.5°N, 0.1°W, 850hPa temperature.

**Tasks:**
- [ ] Task 1: MOGREPS-G Fetcher (`~/wxd-direct/src/fetchers/mogreps.py`)
  - boto3 anonymous S3 access to `s3://met-office-global-ensemble-model-data/`
  - Extract 850hPa temp for London from NetCDF via xarray
  - Handle ensemble members (mean or control)
- [ ] Task 2: UKMO Deterministic Fetcher (`~/wxd-direct/src/fetchers/ukmo.py`)
  - Global: `s3://met-office-atmospheric-model-data/`
  - UKV: Separate bucket (verify)
- [ ] Task 3: ICON-EU Fetcher (`~/wxd-direct/src/fetchers/icon.py`)
  - HTTPS from `https://opendata.dwd.de/weather/nwp/icon-eu/grib/`
  - bz2 stream decompression
  - cfgrib for GRIB2 extraction
- [ ] Task 4: Update scheduler.py with new models
- [ ] Task 5: Update availability_probe.py for new models
- [ ] Task 6: Verify AWS bucket access and document file patterns
- [ ] Task 7: Check dependencies (boto3, xarray, cfgrib)

**Technical Notes:**
- NetCDF (Met Office) via xarray, GRIB2 (DWD) via cfgrib
- ICON files are bz2 compressed
- Verify longitude conventions per source (0-360 vs -180..180)
- MOGREPS ensemble: extract control run or compute mean

## [2025-12-31] - Reply System v2 Implementation

### Added
- **Reply listener v2** - Full two-step engagement model implemented:
  - First reply gets canned "reply 'chat' to continue"
  - Claude only invoked after explicit "chat" opt-in
  - Test mode/lockdown for whitelisted users only
- **Adaptive polling** - Smart cron scheduling:
  - Cron runs every 15 min
  - Engaged mode (reply within 60min): always runs
  - Quiet mode: only runs every 2h
  - `--force` flag bypasses adaptive logic
- **ntfy triggers for replies**:
  - `check`: Check replies now (dry-run)
  - `respond`: Check and respond now (live)
- **Training data logging** - Captures interactions for improving responses:
  - `initial_question`: Pre-chat questions
  - `session_start`: Chat session beginnings
  - `claude_response`: Generated responses
- **Uncertainty handling** - Claude flags instead of guessing:
  - New `uncertain` classification
  - `needs_human` flag for owner review
  - Logged to `needs_human_review` state
- **Dynamic session limits** - Extends for valuable conversations:
  - Standard: 5 messages
  - Trusted: 10 messages
  - Feedback session: 15 messages (auto-upgrades on corrections/uncertainty)
- **Proper Bluesky mentions** - Using TextBuilder for clickable @mention facets
- **post_invites.py** - Script for posting invite threads to test users

### Changed
- Reply listener cron: 4h → 15min (with adaptive polling)
- Updated CLAUDE.md with full ntfy command reference and cron schedule
- Updated REPLY_SYSTEM.md with implementation details

### Fixed
- @mentions in posts now use proper facets (resolve handle to DID, use TextBuilder)

## [2025-12-30] - Engagement System Overhaul & Oracle A1 Grabber

### Added
- **Oracle A1 instance grabber** - Automated script to grab ARM instance when capacity available
  - OCI CLI installed and configured on VM
  - Cycles through all 3 London availability domains every 60 seconds
  - Target: 2 OCPUs, 12GB RAM, 145GB disk, Ubuntu 24.04 ARM
  - ntfy alert on success, uses Windows SSH key for direct access
- **ntfy trigger `oracle`** - Check grabber status anytime
- **Context-aware topic selection** - Reads summary_latest.json for cold/warm signals, weights categories accordingly
- **Seasonal awareness** - Detects winter/summer/shoulder seasons, excludes irrelevant topics
- **New topic categories**:
  - `cold_relevant` (9 topics): 850hPa, model convergence, jet stream, Polar Vortex, Gulf Stream
  - `warm_relevant` (9 topics): Heatwaves, urban heat, dewpoint, thunderstorms
  - `myth_busting` (8 topics): Snow depth charts, weather bombs, tabloid hype debunking
- **Community request mode** - Sunday posts asking followers for topic suggestions
- **Thread indicators** - Posts now show [1/3] [2/3] [3/3] so users know more content follows
- **Question collection** - Monday cron harvests replies for Tuesday Q&A posts

### Changed
- **New engagement schedule**: Sun 12:00 (community request), Mon 20:00 (collect replies), Tue/Fri 12:00 (posts)
- **Removed --dry-run** from engagement cron - posts now go live

### Fixed
- **AI preamble leak** - Stricter prompt rules prevent "Let me create..." appearing in posts
- **Weather context parsing** - Fixed to match actual summary_latest.json structure

## [2025-12-29] - Daily Summary Enhancements & ntfy Triggers

### Added
- **ntfy triggers for summary and engagement** - Can now preview daily summary and engagement posts via ntfy commands
- **Met Office long-range scraping** - daily_summary.py now fetches from long-range forecast page
- **Met Office warnings scraping** - Fetches day-by-day warning status from uk-warnings page
- **Standalone warnings post** - Active warnings now posted as separate post (not in thread) with:
  - Warning level (Yellow/Amber/Red)
  - Date range
  - Affected nations
  - Hazard types

### Fixed
- **Warnings post truncation** - Rewrote to be concise (<280 chars) with affected areas included
- **Navigation noise in scraping** - Added skip phrases to filter out menu/header text

### Known Issues
- **Engagement cron has --dry-run** - Needs removal to enable live Sunday/Wednesday posts

## [2025-12-29] - Period-Based Analysis & Commentary Improvements

### Added
- **Period-based analysis** - Forecasts now analyzed in three periods:
  - Short-term (0-72h): Days 1-3, highest confidence
  - Mid-range (72-144h): Days 4-6, medium confidence
  - Extended (144h+): Day 7+, lower confidence
- Commentary now covers full forecast range, not just first few days
- If pattern is uniform (cold/mild throughout), says that; if divergent, breaks down by period

### Changed
- **All trackers use Sonnet model** - Upgraded from haiku to sonnet for better commentary quality
- **Claude CLI syntax fixed** - Corrected '-p prompt' flag position (was causing 300s timeouts)
- **Prompt improvements** - All trackers now explicitly forbidden from dramatizing when analysis shows "no significant shift"
- **Chart overlays** - ICON and MOGREPS now show run-to-run progression (matching UKMO style)

### Fixed
- **Commentary contradiction** - Fixed issue where Claude wrote "signal weakening" when analysis said "no significant shift"
- **Input parameter** - Changed input=prompt to input=None since prompt now passed via -p flag


### TODO
- ~~**Anytime preview/testing mode** - Allow fresh data fetch for preview/testing without polluting or contaminating the production data files or history. Must ensure complete isolation from scheduled runs.~~ **DONE**
- ~~**ICON/UKMO/MOGREPS commentary enhancement** - Need to port Tracker A's rich features: story-first prompts (no prefix), split/thread for longer posts (290 char), threshold warnings (-5°C/-8°C), 450 char for significant events. Currently have basic "ICON:" prefix style with 250 char single post.~~ **DONE - shared commentary module (trackers/shared/commentary.py)**
- ~~**Break down workflows into smaller tasks** - Current cron jobs run fetch + analysis + chart + Claude commentary + post as one heavy process. Causes memory issues and VM overload (load avg 20+). Need to split into smaller sequential steps or add delays between stages. MOGREPS S3 fetches + Claude CLI commentary together overwhelm the VM.~~ **RESOLVED - migrated to Oracle A1.Flex (4 OCPU, 24GB RAM)**
- ~~**Fetch own posts history** - Use `app.bsky.feed.getAuthorFeed` API with cursor pagination to retrieve WXD's own post history. Useful for audit, analytics, duplicate detection, and backfilling local records. Requires authenticated session with app password (already available in .wxd_env).~~ **DONE - fetch_own_posts.py**
- ~~**Reply listener system** - Monitor replies to WXD posts and respond intelligently:
  - Fetch replies via `app.bsky.feed.getPostThread`
  - Evaluate each reply with Claude CLI: genuine question → respond, spam → ignore, topic suggestion → log for engagement posts, appreciation → brief thanks, correction → flag for review
  - State tracking for processed replies
  - Safety: rate limit (max 5 replies/run), dry-run default, blocklist for trolls
  - Cron: every 4 hours~~ **DONE - reply_listener.py**
- **Reply system v2 implementation** - Full architecture documented in [`docs/REPLY_SYSTEM.md`](docs/REPLY_SYSTEM.md):
  - Two-step engagement model (canned "reply 'chat' to continue", Claude only after opt-in)
  - User tiers: Blocked → Non-follower → Follower → Trusted
  - Pre-filters: blocklist, pass-through (@tags), follower check
  - Session limits: 5 msgs (standard), 10 msgs (trusted), 72h expiry
  - ntfy approval for corrections and questions
  - Usage tracking and daily limits
  - **Status**: Architecture designed, implementation pending

- **Reply system monitoring TODOs** (review after launch):
  - [ ] Review 72h session expiry based on engagement patterns
  - [ ] Set final daily Claude limits after observing usage
  - [ ] Review per-user limits monthly
  - [ ] Monitor for abuse patterns

### Fixed
- **MOGREPS longitude bug** - Was using 0-360 convention (359.87°) but MOGREPS files use -180..180 convention. With `method='nearest'`, 359.87 snapped to 179.86° (Pacific Ocean) instead of London. Fix: use -0.1278° directly. Debug confirmed: correct selection now at -0.14°.
- **UKMO temps too warm** - Changed from `ukmo_seamless` to `ukmo_global_deterministic_10km`. Seamless model smoothed extremes (showed -6.9°C when actual was -8°C). Deterministic model now matches theweatheroutlook.com verification.

### Changed
- **MOGREPS cron timing** - Pushed to 03:00, 09:00, 15:00, 21:00 UTC (9 hours after each run). S3 files upload progressively - earlier times had insufficient forecast hours. **MONITOR:** Check if 9h delay allows full forecast range.
- **MOGREPS safeguards added** - (1) Minimum 4 forecast hours required before posting. (2) Abort if run-to-run shift exceeds 10°C (indicates comparing to corrupted historical data). **MONITOR:** These safeguards could block legitimate posts during extreme pattern changes - check cron.log if posts missing.

### Known Issues (Resolved)
- ~~**MOGREPS data completely wrong** - Chart showed inverted trend vs Meteociel reference. Root cause: longitude convention mismatch selecting Pacific instead of London.~~ **FIXED**

## [2025-12-28] - Shared Analysis Module & Enhanced Trackers

### Code Audit (Claude Web)
Full codebase audit completed - **all calculations verified correct**:
- Data retrieval: All 4 models (GFS, ECM, AIFS, GEM) fetching correctly from Open-Meteo
- Statistical calculations: Mean/min/max/spread computed correctly
- Chart generation: Axes labeled, units correct, ensemble spread rendered properly
- Alert logic: Threshold checks, hysteresis, and multi-model detection all correct
- Minor notes: ICON `get_run_label()` has unreachable 06z/18z branches (harmless)

### Fixed
- **MOGREPS 4x daily** - Updated `get_latest_run()` to target all 4 runs (00z, 06z, 12z, 18z), not just 00z/12z
- **MOGREPS fallback** - Added `get_fallback_run()` to try previous run if target unavailable on S3
- **MOGREPS delay** - Corrected delay from 4h to 6h based on actual S3 availability testing

### Added
- **Shared analysis module** (`trackers/shared/analysis.py`) - Common analysis functions across all trackers:
  - Trend persistence tracking (consecutive runs with same signal)
  - Percentile framing (ensemble spread at coldest point, agreement level)
  - Timing uncertainty analysis (cold window duration, confidence level)
  - Run-on-run shift detection (shared between ensemble and deterministic models)
  - Full analysis pipeline function for easy integration

- **Enriched Claude CLI context** - All trackers now pass comprehensive analysis to Claude:
  - Shift information with direction and date
  - Cold signal with ensemble min/max
  - Trend persistence (e.g., "Cold persisting for 3 runs")
  - Spread analysis (e.g., "High agreement, 4C spread")
  - Timing window (e.g., "Cold spell spans ~3 days")

### Changed
- **ICON tracker** - Now uses shared analysis module with percentile framing
- **MOGREPS tracker** - Now uses shared analysis module with percentile framing
- **UKMO tracker** - Now uses shared analysis module (deterministic, no percentile framing)

### Fixed
- **Claude CLI calls** - Removed invalid `--max-tokens` flag from all trackers (ICON, MOGREPS, UKMO, daily_summary). This flag doesn't exist in Claude CLI and was causing silent failures with fallback text only.

### Technical
- Added `sys.path.insert()` to each tracker for shared module imports
- Separate trend state files per tracker (`trend_state.json`)
- Analysis functions return both individual results and formatted context string
- GitHub Pages at `odgriff79.github.io/WXD/` with chart gallery
- `sync_charts.sh` script copies tracker charts to `docs/charts/` and pushes to GitHub

### Added
- **Local VM config file** - `.vm_config` (gitignored) stores VM IP and SSH key path for remote orchestration
- **Reply threading for alerts** - Cold/warm/divergence/swing alerts now post as replies to main post, creating a tidy thread instead of separate posts
- **Percentile framing** - Counts % of ensemble members below threshold (e.g., "35% of GFS members below -5°C by Jan 2")
- **Bimodal detection** - Detects when ensemble splits into distinct cold/mild clusters (e.g., "GFS split: 40% cold vs 60% mild")
- **Trend persistence tracking** - Tracks consecutive runs with same signal, notes strengthening/weakening (e.g., "Cold signal run #4, strengthening")
- **Timing uncertainty** - Reports spread when models agree on event but disagree on timing (e.g., "Cold arrives ~Jan 2 ±1.5 days")
- All new analysis passed to Claude CLI as context for richer AI commentary
- **Chart watermark** - "wxd-london.bsky.social | Free to use with attribution" in bottom-right
- **Public chart URL** - chart_latest.png now pushed to GitHub for embedding

### Changed
- `post_to_bluesky()` now returns post reference (uri/cid) to enable threading
- Claude CLI prompt enhanced with structured ANALYSIS CONTEXT section
- **IFS → ECM** - Chart legend AND post text now shows "ECM" instead of "ECMWF IFS" for better UK weather community recognition
- **Chart title simplified** - Shows "(00z run)" or "(12z run)" without fetch timestamp
- **cron_fetch.sh** - Now commits and pushes chart_latest.png after Bluesky post

### Investigated
- **Previous Runs API** - Not suitable for backfill (no 850hPa data, no ensemble members)
- **ICON & UKMO expansion** - Initial investigation found deterministic-only via Open-Meteo Forecast API
- **Open-Meteo ICON 850hPa** - Returns NULL for `temperature_850hPa` on ICON ensemble despite API docs claiming support. Works fine for GFS/ECMWF. Likely data availability/ingestion issue on their side.

### Multi-Tracker Architecture
Separating models into independent trackers rather than mixing into one ensemble:
- **Tracker A** - Main 4-model ensemble (GFS, ECM, AIFS, GEM) via Open-Meteo - 2x daily (08:30, 20:30 UTC) ✅ LIVE
- **Tracker B** - ICON-EU-EPS (40 members) via DWD GRIB - 2x daily (04:30, 16:30 UTC for 00z/12z runs) ✅ LIVE
- **Tracker C** - MOGREPS-G (18 members) via AWS S3 NetCDF - future (bucket: `met-office-global-ensemble-model-data`)
- **Tracker D** - UKMO Global Deterministic (~10km) via Open-Meteo - 2x daily (05:00, 17:00 UTC) ✅ LIVE

Each tracker: own subfolder (`trackers/icon/`), own schedule, own cron, own Bluesky posts prefixed with model name.

**Tracker B implementation:**
- Uses ICON-EU-EPS (European domain) not ICON-EPS (global) - smaller files
- Only 00z and 12z runs have pressure-level 850hPa data (06z/18z only have model-level)
- Forecast range: 0-120h (5 days) at 12-hourly intervals
- Uses Python eccodes for point extraction (not wgrib2/CLI - those don't support unstructured grids)
- Files: `trackers/icon/fetch.py`, `trackers/icon/post.py`, `trackers/icon/cron_icon.sh`
- ntfy commands: `icon` (quick preview), `icon-fresh` (fetch new data)

### ICON 850hPa Data Solution
Open-Meteo doesn't provide ICON 850hPa, but DWD Open Data does via GRIB:

**Source:** `https://opendata.dwd.de/weather/nwp/icon-eu-eps/grib/[HH]/t/`
- Files: `icon-eu-eps_europe_icosahedral_pressure-level_YYYYMMDDHH_FFF_850_t.grib2.bz2`
- Each file ~10MB compressed, contains all 40 ensemble members for one forecast hour
- Only 00z and 12z runs have pressure-level data (06z/18z have model-level only)

**Grid handling:**
ICON uses unstructured icosahedral grid (164984 cells). CLI tools (`grib_ls -l`, `grib_get_data -l`, `cdo remapnn`) don't work because:
- eccodes CLI doesn't support nearest-neighbor on unstructured grids
- CDO needs grid definition files and has ecCodes packing errors

**Solution: Python eccodes + grid file**
1. Download DWD grid file `icon_grid_0037_R03B07_N02.nc` once (~55MB, cached)
2. Load cell center coordinates (clat/clon in radians)
3. Find nearest cell index to London (index 113327 at 51.46°N, 0.00°E)
4. For each GRIB: read values at that index using `codes_get_values()`

**Data flow per run:**
- 11 files (0h to 120h at 12-hourly) × 10MB = ~110MB download
- Processed sequentially, only one file in memory at a time
- Final output: ~50KB JSON with 40-member ensemble stats

**Requirements:** `pip install eccodes netCDF4` (Python bindings, not CLI)

### Future Work
Open-Meteo Ensemble API supports more models (but 850hPa availability varies):
- **ICON EPS Seamless** - 40 members (850hPa: use DWD GRIB instead)
- **BOM ACCESS-GE** - 18 members (independent Australian global ensemble)
- **UKMO MOGREPS-G** - 18 members (UK Met Office global ensemble)
- **UKMO MOGREPS-UK** - 3 members (UK high-res ensemble)

**Implementation notes:**
- Use `https://ensemble-api.open-meteo.com/v1/ensemble` (not forecast API) for ensembles
- UKMO deterministic (forecast API) has 4-hour delay due to Met Office licensing
- Horizon mismatch between models - may need to clip to shared max or allow early endings
- UKMO MOGREPS ensembles are separate from UKMO deterministic feed
- Consider UKMO deterministic as "benchmark line" alongside ensemble spread
- For any model where Open-Meteo lacks 850hPa, fall back to native GRIB + wgrib2

## [2025-12-28] - Multi-model Alerts & Remote Preview

### Added
- **Multi-model cold alerts** - Now reports ALL models crossing -5°C threshold, not just coldest (e.g., "ECM -7.2°C, AIFS -7.0°C, GFS -6.9°C, GEM -5.8°C")
- **Percentile threshold alerts** - Triggers when >80% of ensemble members cross cold threshold on any date
- **Dry-run mode** - `--dry-run` flag previews analysis without posting to Bluesky
- **Isolated fresh preview** - `fetch.py --preview` + `post_bluesky.py --preview` for anytime testing without contaminating production data
- **ntfy remote commands** - Two commands via `ntfy.sh/wxd-cmd`:
  - `preview`: Quick preview using current/stale data
  - `fresh`: Fetch new data first (isolated), then preview - no contamination of production files
- **ntfy_listener.py** - Python-based listener for remote preview commands
- **wxd-ntfy.service** - systemd service for persistent ntfy listener
- **Multi-post support** - Significant events can span multiple threaded posts (up to 550 chars, split at sentence boundaries)
- **Explicit cold ranking** - Analysis context now shows "COLD RANKING (coldest first)" so Claude doesn't misread JSON
- **Data provenance logging** - Prints fetched timestamp, run label (00z/12z), and first data timestamp for audit

### Fixed
- **Threading bug** - atproto requires proper model classes (`ComAtprotoRepoStrongRef.Main`, `AppBskyFeedPost.ReplyRef`) not plain dicts
- **Percentile alert wording** - Now says "below -5°C" instead of "below cold"
- **Chart title** - Now includes date (e.g., "28 Dec 00z") not just run time

### Changed
- **Cron schedule** - Changed from 09:00/21:00 UTC to 08:30/20:30 UTC for better model availability
- **Claude prompt overhaul**:
  - NO PREFIX rule - Don't waste characters on "London 850hPa temperatures:"
  - Commentary-first style - Lead with story/analysis, not data dump
  - Plain language - No jargon ("conviction", "regime", "synoptic")
  - No markdown - Bluesky is plain text only
  - Factual tone - Not tabloid headlines

## [2025-12-27] - Initial Bluesky Automation

### Added
- **Bluesky posting** via atproto library
- **Claude CLI integration** for AI-generated weather commentary
- **Matplotlib chart generation** (dark theme, 850hPa ensemble forecast)
- **Run-to-run shift detection** - Flags models that moved >2°C since last run
- **Confidence indicator** - High/medium/low based on model agreement and spread
- **Cold/warm threshold alerts** with hysteresis (must persist 2 runs)
- **Model divergence alerts** - When models disagree by >6°C
- **Rapid swing alerts** - When >8°C change expected in 48h
- **ntfy.sh push notifications** for API failures
- **Weekly git changelog** posted to Bluesky (Sundays 01:00 UTC)
- **Chart run labels** - Shows "00z run" or "12z run" in chart title
- **Fallback posting** when Claude CLI unavailable

### Infrastructure
- Cron schedule: 09:00 and 21:00 UTC (captures 00z/12z runs)
- Bluesky credentials via ~/.wxd_env
- alert_state.json for hysteresis tracking (gitignored)

## [2025-12-27] - Data Pipeline Setup

### Added
- **fetch.py** - Fetches 4-model ensemble data from Open-Meteo
- **Timestamped files** - gfs_2025-12-27_0900Z.json format
- **7-day rolling retention** - Auto-cleanup of old files
- **Latest symlinks** - gfs_latest.json always points to newest
- **Summary generation** - Ensemble stats (mean/min/max/spread)
- **History tracking** - Rolling 6-run history in history.json
- **Compact history** - 12-hourly data for Claude Web analysis

### Models
- GFS Ensemble (31 members)
- ECMWF IFS Ensemble (51 members)
- ECMWF AIFS Ensemble (51 members, AI-based)
- GEM Ensemble (21 members)

### Configuration
- 14-day forecast horizon
- 3 past days for run-to-run comparison
- 850hPa temperature variable
- London coordinates (51.5074, -0.1278)
