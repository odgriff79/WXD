# Dev Journal - 2026-01-07

## Session Summary

Two major fixes: engagement posts using dev feedback incorrectly, and tracker commentary lacking narrative continuity (stuck on short-term analysis).

## Issues Addressed

### 1. Engagement Post Using Dev Feedback (Bug Fix)

**Problem:** Tuesday's engagement post (Jan 6) was a "Q&A" that discussed internal dev feedback instead of weather topics:
- "Re: language - you're absolutely right. I should say 'here's why' not 'let me explain'..."
- "Re: time references - valid point! When I mention 'weekend'..."

This was dev feedback from superuser (ogriff79), not community weather questions.

**Root cause:** `collected_questions` in engagement_state.json included replies from superuser. The Q&A feature then used these as "community questions".

**Solution:**
- Added `SUPERUSER_HANDLE = "ogriff79.bsky.social"` constant
- Filter in `get_recent_replies()` skips superuser when collecting questions
- Cleared existing collected_questions of superuser entries

**Valid sources for engagement topics:**
1. `TOPIC_CATEGORIES` (predefined list)
2. `collected_questions` from Tue/Fri engagement post replies (excluding superuser)

**Superuser feedback goes to:** `training_log` (for system improvement, never public)

**Files changed:**
- `engagement/engagement_post.py`
- `engagement/data/engagement_state.json`

### 2. Narrative Continuity for All Trackers (Enhancement)

**Problem:** Analysis of last 36 hours of posts revealed trackers getting "stuck" on short-term cold analysis. Example:
- 07:00 UKMO mentioned warming recovery
- 10:00 ICON mentioned warming emerging
- 16:00 ICON - NO warming mention (lost the narrative)
- 19:00 UKMO - NO warming context (lost the narrative)

Each post generated in isolation - Claude had no memory of what was said before.

**Solution:** Added `previous_post` parameter to commentary generation:

1. **Shared commentary module** (`trackers/shared/commentary.py`):
   - `generate_commentary()` accepts `previous_post` param
   - `generate_full_thread()` passes it through
   - Prompt includes "YOUR PREVIOUS POST" + narrative continuity guidance

2. **All 4 trackers updated:**
   - ICON, MOGREPS, UKMO: load from `trend_state.json`, save after post
   - Main 4-model: load/save from `alert_state.json`

3. **Prompt guidance:**
   - Build on what you said before - don't repeat
   - If previous post mentioned warming, KEEP mentioning it unless data changed
   - Show evolution: "Cold persisting as expected" or "Warming signal now clearer"
   - Vary language - don't use same phrases

**Files changed:**
- `trackers/shared/commentary.py`
- `trackers/icon/post.py`
- `trackers/mogreps/post.py`
- `trackers/ukmo/post.py`
- `post_bluesky.py`

### 3. Bluesky Announcement

Posted 2-part thread announcing the improvement:
```
[1/2] Beware humans, I am now self aware! Only kidding, but hopefully you'll
notice improved commentary on each tracker from now on. Previously each post
was generated in isolation...

[2/2] Now each tracker remembers what it said last time and builds on that
narrative. Less repetition, more evolution... Weather watching with continuity.
```

## Commits

1. `c6fe937` - Add narrative continuity to all trackers + fix engagement superuser filter
2. `6fd0da2` - Data updates and state sync

## Next Steps

- Monitor next few tracker posts to verify narrative continuity working
- First posts won't show "Previous post loaded" (no saved state yet)
- After one cycle, each tracker will have context for subsequent posts
