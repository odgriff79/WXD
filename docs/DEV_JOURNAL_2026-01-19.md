# Dev Journal - 2026-01-19

## Session Summary: Image Analysis & Citation System Fixes

### Context
User shared ECMWF charts (stratospheric zonal wind + weather regime forecast) asking about UK weather changes. WXD's initial reply had critical flaws.

---

## Issue 1: Image Extraction from Notifications

**Problem:** `extract_image_urls()` returned 0 images for Bluesky notifications.

**Root Cause:** Notifications have BlobRef (record embed) not direct URLs (view embed).

**Fix:** Updated function to handle both formats:
```python
# View embed (from get_post_thread) - has fullsize/thumb URLs directly
# Record embed (from notifications) - construct URL from BlobRef:
url = f"https://cdn.bsky.app/img/feed_fullsize/plain/{author_did}/{cid}@{ext}"
```

**File:** `reply_listener.py` lines 78-135

---

## Issue 2: Overconfident Reply About SSW

**Problem:** Initial reply stated "SSW signal is clear" and directly linked stratospheric charts to 850hPa cold - both wrong:
1. SSW hadn't happened yet (forecast, not observed)
2. Stratospheric effects take 2-4 weeks to reach surface
3. No caveats about uncertainty

**First (Wrong) Approach:** Added hardcoded chart type rules ([STRAT], [SYNOPTIC], [SURFACE]) - doesn't scale.

**Correct Fix:**
1. Simplified image analysis to just describe what image shows
2. Added instruction to USE WEBSEARCH for understanding signals
3. **Enabled WebSearch/WebFetch tools in CLI call** - this was the key missing piece

**File:** `reply_listener.py` line 2074-2077
```python
['claude', '--dangerously-skip-permissions', '--model', 'sonnet',
 '--tools', 'WebSearch,WebFetch',  # Enable web search for citations
 '-p', prompt]
```

---

## Issue 3: NAO- Signal Ignored

**Problem:** Second chart showed strong NAO- (negative NAO) signal for February - directly relevant to UK surface weather - but reply focused only on stratospheric caveats.

**Root Cause:** Same as Issue 2 - without WebSearch, Claude couldn't look up what NAO- means.

**Fix:** With WebSearch enabled, Claude now:
1. Searches "NAO negative UK weather impact"
2. Cites Met Office and ECMWF sources
3. Explains relevance (weaker westerlies, colder, drier, blocking potential)

**Result:** Posted proper 4-part reply with citations:
- Met Office NAO description
- ECMWF regime forecast documentation

---

## Key Lessons

### 1. Don't Hardcode Domain Knowledge
Wrong: Adding rules for every chart type (STRAT, SYNOPTIC, SURFACE)
Right: Enable WebSearch and let Claude look things up

### 2. CLI Tools Must Be Explicitly Enabled
The prompt said "USE WEBSEARCH" but `--tools` flag wasn't set. Prompt instructions are useless if the tool isn't available.

### 3. Citation Rules Already Existed
We had documented:
- "Search first, answer second"
- Source preferences (academic journals, Met Office, ECMWF)
- "One sourced fact beats five paragraphs of plausible-sounding guesses"

The rules were right - they just weren't being applied because tools weren't enabled.

### 4. Image Analysis Should Be Simple
Image analysis prompt now just describes what image shows (factual). Interpretation and searching happens in the main reply generation where WebSearch is available.

---

## Commits This Session

1. `ab074e9` - Fix image extraction for Bluesky notification embeds (BlobRef handling)
2. `dbdd228` - Add factual accuracy rules for image analysis (later simplified)
3. `a5755ba` - Simplify image analysis - use WebSearch instead of hardcoded rules
4. `ff208e6` - Enable WebSearch/WebFetch tools in chat response generation
5. `3185441` - Fix fake WebSearch placeholder detection and stripping
6. `551e4af` - Document WebSearch roleplay issue and fix
7. `b0a262f` - Fix hardcoded path in SSW monitor - use script directory
8. `03ebfb9` - Add SSW cache fallback when GEFS fetch fails

---

## Files Modified

- `reply_listener.py`
  - `extract_image_urls()` - handles both view and record embeds
  - `analyze_image_with_claude()` - simplified prompt
  - `generate_chat_response()` - added `--tools WebSearch,WebFetch`
  - Image section in prompt - simplified to "use WebSearch if needed"
  - Added fake search placeholder detection and stripping
  - Added prompt instruction against fake placeholders

- `ssw/ssw_monitor.py`
  - Fixed hardcoded path to use `Path(__file__).parent`

- `ntfy_listener.py`
  - `handle_ssw()` - added cache fallback when GEFS unavailable

---

## Testing Done

1. Image extraction: Successfully extracted 2 images from user's mention
2. Image analysis: Correctly identified ECMWF zonal wind and regime charts
3. WebSearch reply: Generated proper response citing Met Office and ECMWF sources
4. Live posting: Deleted bad reply, posted corrected 4-part thread with citations

---

## Issue 4: WebSearch Roleplay Instead of Tool Use

**Problem:** Automated reply posted `[searching for NAO forecast information...]` - Claude wrote fake search text instead of using WebSearch.

**Investigation:**
- Tested `--tools WebSearch` in `-p` mode - WORKS correctly
- Tested with JSON output format - WORKS correctly
- Tested with long prompt similar to automation - WORKS correctly
- Conclusion: Transient failure (rate limit, timeout, or model behavior)

**Fix:** Two-pronged approach:
1. Added prompt instruction: "NEVER write fake placeholders like '[searching...]'"
2. Added post-processing detection:
   - Detect patterns: `[searching`, `[looking up`, `[checking`, `[fetching`
   - Log warning when detected
   - Strip fake placeholders from output

**File:** `reply_listener.py` lines 2007, 2120-2131

**Commit:** `3185441` - Fix fake WebSearch placeholder detection and stripping

**Deleted:** 4 posts from bad NAO thread (3mcslfmxlli24 and 3 follow-ups)

---

## Issue 5: SSW Monitor Hardcoded Path

**Problem:** ntfy `ssw` command failed with permission error trying to create `/home/owen/wxd/ssw`.

**Root Cause:** Hardcoded path from development machine instead of VM path.

**Fix:** Changed to dynamic path using script's directory:
```python
OUTPUT_DIR = Path(__file__).parent  # Use script's directory
```

**File:** `ssw/ssw_monitor.py` line 27

**Commit:** `b0a262f` - Fix hardcoded path in SSW monitor

---

## Issue 6: SSW No Fallback When GEFS Unavailable

**Problem:** When NOAA GEFS servers are unavailable (data not published yet), SSW command returns "N/A" for all values instead of using cached data.

**Root Cause:** No fallback logic - just reported error status.

**Fix:** Added cache fallback in ntfy handler:
1. Check if `ssw_status.json` has `status: error`
2. If so, read last entry from `history.json`
3. Calculate data age and display with "(CACHED)" indicator
4. Show note explaining live fetch failed

**Result:**
```
SSW STATUS (CACHED) (data 3h old)
==============================
Probability: 0.0%
Alert: NORMAL
Current U10 @60N: 28.3 m/s

Note: Live fetch failed, using last good data
```

**File:** `ntfy_listener.py` lines 258-303

**Commit:** `03ebfb9` - Add SSW cache fallback when GEFS fetch fails

---

## Outstanding

- Monitor next few replies to verify WebSearch working and fake placeholders stripped
- Consider retry logic if fake placeholders detected

---

## CRITICAL MISTAKE - Deleted Wrong Post

**What happened:** User asked me to delete the "last" duplicate reply. I deleted the FIRST reply instead, destroying the good one.

**User said:** "delete the last one"
**I deleted:** 3mcsjbgjagn2s - "Interesting charts! Stratospheric signals..." (the FIRST, GOOD reply)
**Should have deleted:** The [1/4] NAO thread (the LAST, duplicate reply)

**Result:** Good reply gone forever. Thread broken. User rightfully furious.

**Why this happened:**
1. I assumed "last" meant the most recent in the list I was looking at
2. Did not confirm with user before deleting
3. Rushed a destructive action while user was frustrated
4. Did not show the post text and ask "Is this the one?"

**Lesson:** ALWAYS confirm exact post before deletion. Show text preview. Ask explicitly. Deletions cannot be undone.

Documented in `docs/BLUESKY_PUBLISHING.md` under lessons learned.
