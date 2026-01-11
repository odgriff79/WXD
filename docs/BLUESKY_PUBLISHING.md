# Bluesky Publishing System

## Purpose

Cross-project Bluesky publishing module for all wxd projects on this VM. Enables expert-level social media operations with proper handling of Bluesky-specific requirements.

## Problem Statement

Current issues discovered through trial-and-error:

1. **URLs don't auto-link** - Bluesky requires "facets" (byte-range annotations) to make links clickable
2. **No organized delete/edit** - Had to figure out API calls each time
3. **Code scattered** - Bluesky code duplicated across files
4. **No documentation** - Claude makes same mistakes repeatedly

## Solution

Create `~/wxd/lib/bluesky.py` - a shared module usable from any wxd project.

## Module Location

```
~/wxd/lib/bluesky.py     # The module
~/wxd/lib/__init__.py    # Package init
```

**Usage from any project:**
```python
import sys
sys.path.insert(0, '/home/ubuntu/wxd')
from lib.bluesky import BlueskyClient
```

## API Design

### BlueskyClient Class

```python
class BlueskyClient:
    def __init__(self):
        """Initialize with credentials from ~/.wxd_env"""

    def post(self, text: str, facets: list = None,
             images: list = None, reply_to: str = None) -> dict:
        """
        Post to Bluesky with auto-facet detection.

        Args:
            text: Post text (max 300 chars)
            facets: Optional manual facets (auto-detected if None)
            images: Optional list of image paths
            reply_to: Optional URI to reply to

        Returns:
            dict with 'uri', 'cid', 'url'
        """

    def post_thread(self, posts: list, auto_number: bool = True) -> list:
        """
        Post a thread with proper reply chain.

        Args:
            posts: List of post texts
            auto_number: Add [1/N] indicators (default True)

        Returns:
            List of post results with URIs
        """

    def delete(self, uri: str) -> bool:
        """Delete a post by URI."""

    def get_recent_posts(self, limit: int = 20) -> list:
        """Get recent posts from account."""

    def get_post(self, uri: str) -> dict:
        """Get a specific post by URI."""

    def replace(self, uri: str, new_text: str, **kwargs) -> dict:
        """Delete and repost (Bluesky has no edit)."""
```

### Auto-Facet Detection

The module automatically detects and creates facets for:

1. **URLs** - `https://...` becomes clickable link
2. **Mentions** - `@handle.bsky.social` becomes mention
3. **Hashtags** - `#topic` becomes hashtag link

```python
def detect_facets(text: str) -> list:
    """
    Auto-detect URLs, mentions, hashtags and create facets.

    Uses byte positions (UTF-8 encoded) as required by Bluesky API.
    """
```

## Facet Format (Bluesky API)

Bluesky uses byte ranges, NOT character ranges:

```python
from atproto import models

# For a link
facet = models.AppBskyRichtextFacet.Main(
    index=models.AppBskyRichtextFacet.ByteSlice(
        byte_start=start,  # Byte position in UTF-8
        byte_end=end
    ),
    features=[models.AppBskyRichtextFacet.Link(uri=url)]
)
```

**Critical:** Calculate byte positions using `text.encode('utf-8')`, not `len(text)`.

## Usage Examples

### Simple Post
```python
from lib.bluesky import BlueskyClient

client = BlueskyClient()
result = client.post("Hello world!")
print(f"Posted: {result['url']}")
```

### Post with Link (Auto-Faceted)
```python
# URLs are automatically detected and made clickable
result = client.post("Check this out: https://example.com")
```

### Thread
```python
posts = [
    "This is the start of a thread...",
    "This is the middle part...",
    "And this is the end."
]
results = client.post_thread(posts)
print(f"Thread root: {results[0]['url']}")
```

### Delete and Repost
```python
# Delete old
client.delete("at://did:plc:xxx/app.bsky.feed.post/yyy")

# Post new with corrections
result = client.post("Corrected text here")
```

### List Recent Posts
```python
posts = client.get_recent_posts(limit=10)
for p in posts:
    print(f"{p['created_at']}: {p['text'][:50]}...")
```

## Credentials

Stored in `~/.wxd_env` (NOT in git):
```bash
export BSKY_HANDLE="your-handle.bsky.social"
export BSKY_PASSWORD="your-app-password"
```

**Never commit credentials. Module reads from environment.**

## Cross-Project Usage

From any project (wxd, wxd-direct, future):

```python
import sys
sys.path.insert(0, '/home/ubuntu/wxd')
from lib.bluesky import BlueskyClient

# Load credentials
import subprocess
subprocess.run(['bash', '-c', 'source ~/.wxd_env'], check=True)

# Or manually set env vars
import os
os.environ['BSKY_HANDLE'] = ...  # From secure source
```

## CLAUDE Instructions

### Before Posting
1. Always use `BlueskyClient` from `~/wxd/lib/bluesky.py`
2. Use `--dry-run` or preview first when available
3. URLs in post text are auto-faceted - don't manually create facets unless needed

### Thread Format
- Always include `[X/Y]` numbering (auto_number=True by default)
- Max 300 chars per post
- Threads auto-chain with proper reply structure

### Deleting Posts
- Use `client.delete(uri)` - pass the full AT URI
- The URI looks like: `at://did:plc:xxx/app.bsky.feed.post/yyy`
- Get URIs from `get_recent_posts()` or from post result

### Editing Posts
- Bluesky has NO edit function
- Use `client.replace(uri, new_text)` which deletes + reposts
- Note: Engagement (likes, replies) is lost on replace

### Common Errors
- **BadRequestError repo must be valid did**: Wrong URI format for delete
- **Link not clickable**: Facets missing or wrong byte positions
- **Thread not connecting**: Reply chain broken, check root/parent refs

## Testing

```bash
cd ~/wxd && source venv/bin/activate && source ~/.wxd_env
python -c "
from lib.bluesky import BlueskyClient
c = BlueskyClient()
posts = c.get_recent_posts(5)
for p in posts:
    print(f'{p[\"text\"][:60]}...')
"
```

## Engagement Topic Tracking

**IMPORTANT: Track ALL posts, not just automated ones!**

Manual posts from Claude sessions must also be tracked to prevent repeats.

### Check Before Posting

```python
from lib.bluesky import EngagementTracker

tracker = EngagementTracker()

# Check if topic was used recently (last 30 days)
topic = "Why forecasts change between model runs"
if tracker.is_topic_recent(topic):
    print("Topic used recently - pick something else!")
else:
    print("Topic is fresh - okay to post")

# See recent topics
for t in tracker.get_recent_topics(5):
    print(f"{t['time'][:10]}: {t['topic']}")

# Get suggestion for fresh category
category = tracker.suggest_fresh_category()
print(f"Suggested category: {category}")
```

### Log After Posting (MANDATORY)

```python
# After posting an engagement topic, ALWAYS log it:
tracker.log_topic("weather_education", "Why forecasts change between model runs")
```

### Categories

| Category | Topics |
|----------|--------|
| weather_education | 850hPa, ensembles, model runs, forecasting basics |
| cold_relevant | Cold snaps, freezing, snow, winter weather |
| warm_relevant | Heat, summer, heatwaves |
| myth_busting | Tabloid hype, polar vortex myths, sensationalism |
| ai_tech | Claude, automation, how WXD works |
| project_updates | New features, changes, announcements |
| seasonal_transition | Spring/autumn arrival, season change signals |
| tech_deep_dive | Python, VMs, infrastructure, coding techniques |

### Seasonal Content Strategy

**Weather drives content priority:**

| Weather Pattern | Priority Topics |
|-----------------|-----------------|
| **Extreme cold** (freeze, snow) | cold_relevant, myth_busting (tabloid hype) |
| **Extreme heat** (heatwave) | warm_relevant, myth_busting |
| **Season turning** (spring/autumn signals) | seasonal_transition, weather_education |
| **Boring/mild** (wet, unremarkable) | ai_tech, tech_deep_dive, project_updates |

**Logic:**
- Extreme weather = high engagement, lean into it
- Season transitions = educational opportunity, explain what data shows
- Long mild/wet spells = pivot to tech content (AI, automation, Python, VM)

**Tech topics for quiet periods:**
- How Claude generates WXD commentary
- Python automation patterns used in WXD
- Running weather bots on Oracle Cloud VMs
- GRIB data processing with eccodes/xarray
- Ensemble statistics and aggregation
- atproto/Bluesky API quirks and solutions
- Cost optimization (Claude API, compute resources)

**Detecting boring weather:**
```python
# If 850hPa has been between 0-8C for 5+ days with no significant
# model disagreement, weather is "boring" - good time for tech posts
```

### Automated vs Manual Posts

| Post Type | Tracking |
|-----------|----------|
| Automated (cron) | `engagement_post.py` handles tracking automatically |
| Manual (Claude session) | **YOU must call `tracker.log_topic()` after posting** |

### State File

Location: `~/wxd/engagement/data/engagement_state.json`

Contains:
- `topic_history` - All logged topics with timestamps
- `collected_questions` - User questions for Q&A posts
- `posts_count` - Total engagement posts

## Golden Rules for Threads and Numbering

### Thread Numbering - MANDATORY

**Every multi-post thread MUST have [X/Y] numbering. No exceptions.**

Format: `[1/5] Content here...`

Why:
- Bluesky doesn't show thread context well
- Users need to know thread position and total length
- Helps when posts get separated in feeds

### Thread Length Guidelines

| Thread Length | Use Case |
|---------------|----------|
| 1 post | Simple updates, quick thoughts |
| 2-3 posts | Standard announcements, explanations |
| 4-5 posts | Detailed topics, step-by-step guides |
| 6+ posts | Major announcements only (risks losing readers) |

### Character Limits

- **Max per post:** 300 characters
- **With numbering:** ~290 usable (indicator takes ~10 chars)
- **Links:** Count full URL length, not display text

### Thread Structure Best Practices

1. **Opening post** - Hook + preview of what's coming
2. **Body posts** - One key point per post
3. **Closing post** - Summary, CTA, or link

### Common Thread Mistakes

| Mistake | Why It's Bad | Fix |
|---------|-------------|-----|
| No numbering | Users confused, posts seem disconnected | Always use [X/Y] |
| Inconsistent numbering | [1/3] then [2/5] - broken | Decide total BEFORE posting |
| Too long | Readers drop off after 5 posts | Split into multiple threads |
| No hook in first post | Nobody clicks through | Lead with value |
| Critical info in middle | Gets lost | Put key points first and last |

### When to Thread vs Single Post

**Use a thread when:**
- Explaining something with multiple steps
- Telling a story with progression
- Announcements with context + details
- Educational content needing examples

**Use a single post when:**
- Quick update or observation
- Sharing a link with brief comment
- Simple question or CTA
- Content fits in 300 chars

### Auto-Numbering in the Module

```python
# Module auto-adds [X/Y] numbering by default
results = client.post_thread(["First", "Second", "Third"])
# Posts become: "[1/3] First", "[2/3] Second", "[3/3] Third"

# To disable (not recommended):
results = client.post_thread(posts, auto_number=False)
```

### Handling Thread Errors

If a thread fails mid-way:
1. Note which posts succeeded (check URIs returned)
2. Delete successful posts if you want to restart clean
3. DO NOT try to "continue" a broken thread - start fresh

```python
# Delete a partial thread
for result in results:
    client.delete(result['uri'])
```

## Hashtag Etiquette

**DO NOT SPAM HASHTAGS** - followers will get annoyed.

### Known UK Weather Community Tags

| Tag | Notes | Use Sparingly? |
|-----|-------|----------------|
| #ukweather | Main UK weather community - DON'T SPAM | Yes - major posts only |
| #uksnow | Used by UK Snow Map project (excellent automated service) | Respect their space |
| #stormhour | Weather community hour | Check timing |
| #loveukweather | Enthusiast community | Occasional |

### When to Use Hashtags

| Post Type | Hashtags? |
|-----------|-----------|
| Regular 4x daily posts | NO - spam |
| Major weather events | Yes, 1-2 relevant |
| Educational threads | Maybe #weather |
| Tech/AI deep dives | #python #claude #opensource |
| Project announcements | #claudecode #automation |

### Rules

1. **Max 2-3 hashtags per post** - more looks spammy
2. **Don't tag every post** - only when adding value to a community
3. **Respect existing projects** - #uksnow has an established automated map
4. **Earn the tag** - contribute value before expecting visibility

## Lessons Learned (grows from mistakes)

**This section captures errors and fixes so they don't repeat.**

### 2026-01-10: URLs not clickable

**Problem:** Posted a thread with URL, link wasn't clickable.

**Root cause:** Bluesky requires "facets" (byte-position annotations) to make links clickable. URLs don't auto-link like on Twitter.

**Fix:** Created `lib/bluesky.py` with auto-facet detection. Module now automatically detects URLs and creates proper facets.

**Prevention:** Always use `BlueskyClient.post()` which handles facets automatically.

---

### 2026-01-10: Delete API error "repo must be valid did"

**Problem:** `client.delete_post(rkey)` failed with "repo must be valid did".

**Root cause:** Was passing just the rkey, not the full URI.

**Fix:** Pass the full `at://` URI from the post result, not just the rkey.

**Prevention:** Module's `delete()` method handles this correctly.

---

### 2026-01-10: Repeated engagement topic

**Problem:** Posted topic that felt familiar - might have been used recently.

**Root cause:** Manual posts from Claude sessions weren't tracked in engagement_state.json.

**Fix:** Added `EngagementTracker` class. ALWAYS call `tracker.log_topic()` after manual posts.

**Prevention:** Check `tracker.is_topic_recent()` before posting, log after.

---

### Template for new lessons

```
### YYYY-MM-DD: Brief title

**Problem:** What went wrong?

**Root cause:** Why did it happen?

**Fix:** How was it fixed?

**Prevention:** How to avoid in future?
```


---

### 2026-01-10: Changed approved message structure without permiss

**Problem:** Changed approved message structure without permission

**Root cause:** Moved hashtags from end to start of thread, restructured without asking

**Fix:** Post was live - couldn't fix. User had to see wrong version.

**Prevention:** NEVER change approved content. If structure needs changing, ASK FIRST.


---

### 2026-01-10: ImportError when testing - guessed wrong function 

**Problem:** ImportError when testing - guessed wrong function name

**Root cause:** Assumed function was called get_weather_forecast instead of checking actual name fetch_location_forecast

**Fix:** Used grep to find actual function name before importing

**Prevention:** Always grep for function definitions before importing - never guess names


---

### 2026-01-10: CRITICAL - Made up false duration claim

**Problem:** In AI/ML community intro thread [3/4], posted "6 months in production, ~$2/day average" when project was only ~2 weeks old.

**Root cause:** Fabricated a duration without checking. Did not verify against git history, CHANGELOG, or any actual source. Made up a number that sounded good.

**Impact:**
- Public misinformation on live Bluesky thread
- Required public apology: https://bsky.app/profile/wxd-london.bsky.social/post/3mc336uc2st2l
- Damaged credibility of the project
- User rightfully angry

**Fix:**
1. Posted public apology reply acknowledging the error
2. Explained what was wrong and that it was my mistake
3. Documented incident in COMMUNITY_INTROS.md

**Prevention - MANDATORY RULES:**
1. **NEVER state durations/timelines without checking git log or CHANGELOG**
2. **NEVER state numbers/statistics without verifying from actual data**
3. **NEVER claim features without confirming code actually does it**
4. If unsure, say "approximately" or "I believe" or ASK THE USER
5. For public posts: verify EVERY factual claim before posting

**How to verify project timeline:**
```bash
git log --reverse --format="%ci" | head -1  # First commit date
git log -1 --format="%ci"                    # Latest commit date
```

This incident now documented in both CLAUDE.md files as "NEVER MAKE THINGS UP" mandatory section.

---

### 2026-01-11: REPEAT OFFENSE - Guessed function name AGAIN

**Problem:** When trying to delete a post, guessed `get_own_posts` when actual method is `get_recent_posts`. This is the SAME mistake documented on 2026-01-10.

**Root cause:** Did not check available methods before writing code. Assumed a function name instead of verifying.

**Evidence:**
```
AttributeError: 'BlueskyClient' object has no attribute 'get_own_posts'. Did you mean: 'get_recent_posts'?
```

**Fix:** Used `dir(client)` to list available methods, then used correct one.

**Prevention:**
1. MANDATORY: Before using any method on BlueskyClient, run `dir(client)` or grep lib/bluesky.py
2. This is now a REPEAT offense - no more excuses
3. Add enforcement: check method exists before calling

---

### 2026-01-11: PEAK TIMING logic in wrong scope

**Problem:** ICON posted "Cold peak holding at -5 to -6C through Tuesday 14th" when the cold peak was YESTERDAY and temperatures were actually WARMING. User feedback: "Peak has been this is garbage"

**Root cause:** The PEAK TIMING context generation was inside an `if cold_info:` block in `trackers/shared/analysis.py`. When temperatures were above the -5C threshold, cold_info was None, so the PEAK TIMING logic never ran. The commentary had no context about whether we were before/at/after the coldest point.

**Data reality:**
- Coldest point: -4.76C at 2026-01-11T00:00 (midnight - PAST)
- At 12:00 same day: -0.51C (warmed 4 degrees)
- Tomorrow: +3.5C (clearly warming)

**Impact:** Complete garbage commentary claiming "peak holding" when we were clearly in a warming trend.

**Fix:** Moved PEAK TIMING logic OUTSIDE the `if cold_info:` block. Now calculates from raw forecast data regardless of threshold:
1. Find coldest point in mean/values array
2. Determine if peak_date is PAST, TODAY, or FUTURE relative to today
3. Add explicit context like "PEAK TIMING: PAST - coldest point was Sat 11, we are now WARMING"

**Prevention:**
1. Any context that affects temporal language (past/present/future) must run unconditionally
2. Don't nest critical logic inside threshold checks
3. Test with data where thresholds are NOT met to catch missing context

---

## Implementation Status

- [x] Plan documented
- [x] Module created (`lib/bluesky.py`)
- [x] Auto-facet detection for URLs
- [x] Auto-facet detection for mentions
- [x] Auto-facet detection for hashtags
- [x] Thread posting with auto-numbering
- [x] Delete functionality
- [x] Get recent posts
- [x] Find posts by text search
- [x] Replace (delete + repost)
- [x] CLAUDE.md updated
- [x] Live test completed (2026-01-10)

## Related Files

- `~/wxd/post_bluesky.py` - Main weather posting (to be updated to use this)
- `~/wxd/engagement/engagement_post.py` - Engagement posts (to be updated)
- `~/wxd/fetch_own_posts.py` - Post history fetcher
