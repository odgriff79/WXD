# WXD Automation Architecture

Quick reference for debugging automated posts based on user feedback.

## Automated Post Types & Source Code

### 1. Main 4-Model Ensemble Posts (GFS/GEM/ECM/IFS)
- **Schedule:** 08:30, 20:30 UTC
- **Cron:** cron_fetch.sh
- **Files:**
  - fetch.py - Fetches data from Open-Meteo
  - post_bluesky.py - Generates commentary and posts
  - data/history_compact.json - Stored run history
- **Key functions in post_bluesky.py:**
  - analyze_run_diff() - Compares runs by matching timestamps
  - check_cold_threshold() - Detects cold signals
  - calculate_signal_strength() - Returns high_confidence/strong/emerging
  - generate_claude_commentary() - Calls Claude CLI for post text

### 2. ICON Tracker Posts
- **Schedule:** 04:00, 10:00, 16:00, 22:00 UTC
- **Files:**
  - trackers/icon/fetch.py - Fetches ICON data
  - trackers/icon/post.py - Generates and posts
  - trackers/icon/data/history.json - Run history
  - trackers/shared/analysis.py - Shared analysis
  - trackers/shared/commentary.py - Shared Claude prompt

### 3. MOGREPS Tracker Posts
- **Schedule:** 03:00, 09:00, 15:00, 21:00 UTC
- **Files:**
  - trackers/mogreps/fetch.py
  - trackers/mogreps/post.py
  - trackers/mogreps/data/history.json

### 4. UKMO Tracker Posts
- **Schedule:** 07:00, 19:00 UTC
- **Files:**
  - trackers/ukmo/fetch.py
  - trackers/ukmo/post.py
  - trackers/ukmo/data/history.json

### 5. Daily Summary Posts
- **Schedule:** 09:30 UTC
- **Files:** daily_summary.py, cron_daily_summary.sh

### 6. Reply Listener (Chat Responses)
- **Schedule:** Every 15 minutes
- **Files:**
  - reply_listener.py - Processes replies, manages chat sessions
  - data/reply_listener_state.json - Session state

### 7. Engagement Posts
- **Schedule:** Sun 12:00 (community), Tue/Fri 12:00 (educational)
- **Files:** engagement/engagement_post.py

---

## Shared Modules

### trackers/shared/analysis.py
- analyze_run_diff_ensemble() - Run comparison (matches by timestamp)
- check_cold_threshold_ensemble() - Cold detection
- calculate_signal_strength() - Confidence levels
- update_trend_persistence() - Consecutive run tracking

### trackers/shared/commentary.py
- generate_commentary() - Claude CLI prompt with LANGUAGE guidance
- split_for_posting() - Thread splitting
- post_thread_to_bluesky() - Bluesky API posting

---

## Debugging Guide

| User Feedback | Check This File |
|---------------|-----------------|
| False shift claims | shared/analysis.py - analyze_run_diff_ensemble() |
| Sensational language | shared/commentary.py - LANGUAGE section in prompt |
| Wrong confidence level | shared/analysis.py - calculate_signal_strength() |
| Reply not sent | reply_listener.py - session management |
| Chat limit reached | reply_listener.py - get_session_limit() |
| Main ensemble issues | post_bluesky.py - prompt sections |

---

## Language Guidelines

**Use:** highly likely, well-supported, notable, marked, significant

**Avoid:** locked, dramatic, slammed, plunged, major shift
