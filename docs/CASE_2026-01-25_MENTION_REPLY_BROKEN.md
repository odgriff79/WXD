# CASE: Mention Reply System Broken - 2026-01-25

**Status:** URGENT - NEEDS FIXING
**Severity:** HIGH - Live system producing bad responses
**Date:** 2026-01-25

## Summary

The @mention reply system was working correctly, then broken by well-intentioned but harmful changes during a debugging session. Responses are now:
- Too long (multi-post when should be single)
- Ignoring citation rules
- Making unsourced causal claims about meteorology
- Using dramatic language ("classic", "aligns with", "dramatic")
- Confusing SSW (forecast) with existing blocking (current pattern)

## What Was Working (Git 656a356)

Simple, direct prompt for mentions:

```python
mention_prompt = f"""You are WXD, a weather bot. Someone @mentioned you on Bluesky.

THEIR MESSAGE: {mention['text']}{quoted_context}{mention_forecast}

RESPOND WITH ONE SHORT POST (max 280 chars). Rules:
- You have been given the CORRECT model data above - USE IT to answer
- If the data shows specific temps/dates, quote them accurately
- If they're asking about a model you DON'T have data for above, say "I don't have [model] data to hand"
- DO NOT substitute one model's data for another - that's misleading
- Be helpful but concise - factual over chatty
- DO NOT waffle - one concise message only

Output ONLY the reply text, nothing else."""

result = subprocess.run(
    ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', mention_prompt],
    capture_output=True, text=True, timeout=30
)
```

Key characteristics:
- ONE short post (max 280 chars)
- Direct subprocess call
- Simple focused rules
- No complex JSON parsing

## What Broke It

Changes made during 2026-01-25 session:

### 1. Switched to `generate_chat_response()` (BAD)

Mention handling now calls `generate_chat_response()` which has a **154-line prompt**. Claude ignores rules buried in long prompts.

Location: `reply_listener.py` lines 3078-3117

```python
# Current broken code
result = generate_chat_response(
    reply_text=mention['text'],
    parent_text=context_text,
    session=None,
    forecast_context=forecast_ctx,
    is_super_user=is_mention_super,
    research_context="",
    image_context=image_context,
    parent_uri=mention.get('parent_uri', '')
)
```

### 2. Added Citation Rules That Get Ignored

Added to `generate_chat_response()` prompt (lines 2375-2518):
- "CITATION REQUIREMENT - THIS IS NOT OPTIONAL"
- "CRITICAL RULE - NO UNSOURCED METEOROLOGY CLAIMS"
- "STRICT EVIDENCE-BASED RESPONSES - NO EXCEPTIONS"
- "FINAL REMINDER - BEFORE YOU RESPOND"

These rules ARE in the code but Claude ignores them because:
- Prompt is too long (~154 lines)
- Critical rules buried in middle
- Too many competing instructions

### 3. Multi-Post Responses

System now returns multiple posts with thread numbering when ONE short post was expected:
- Truncation added: "if len(response_posts) > 2: response_posts = response_posts[:2]"
- But even 2 posts is wrong - should be 1

## Good Changes to Keep

These fixes from the session ARE correct and should be preserved:

### 1. `extract_image_urls()` - recordWithMedia fix
```python
# Now handles images in embed.media.images (recordWithMedia type)
if hasattr(embed, 'media') and hasattr(embed.media, 'images'):
    image_list = embed.media.images
```

### 2. `get_notification_mentions()` - parent context capture
```python
# Now captures parent_uri, root_uri, images
'parent_uri': parent_uri,  # Post this mention is replying to
'root_uri': root_uri,      # Root of thread
'images': mention_images,  # Images attached to mention
```

### 3. Parent post fetching in main()
```python
# Fetches parent post when mention is a reply
if mention.get('parent_uri'):
    parent_posts = client.app.bsky.feed.get_posts({'uris': [mention['parent_uri']]})
    # Extract text and images from parent
```

### 4. Image analysis from parent post
```python
# Analyzes images from parent if mention has none
images_to_analyze = mention.get('images', []) or parent_images
```

## The Fix Required

1. **Revert mention handling to simple prompt** - NOT `generate_chat_response()`
2. **Keep parent context additions** - parent_uri capture, parent fetching, image extraction
3. **Keep recordWithMedia fix** - in `extract_image_urls()`
4. **Simple prompt with image/parent context added**:

```python
mention_prompt = f"""You are WXD, a weather bot. Someone @mentioned you on Bluesky.

THEIR MESSAGE: {mention['text']}{parent_context}{quoted_context}{image_context}{mention_forecast}

RESPOND WITH ONE SHORT POST (max 280 chars). Rules:
- Use the data/images above to answer accurately
- Quote specific values from charts/data when available
- If asked about a model you don't have data for, say so
- Be concise and factual
- DO NOT make causal claims about meteorology without citation

Output ONLY the reply text, nothing else."""
```

5. **For citations**: Use `--tools WebSearch,WebFetch` flag when calling Claude CLI (documented in DEV_JOURNAL_2026-01-19.md as working approach)

## Evidence

### User Feedback During Session
- "no thread number as per our fucking rules"
- "very vague on details and truncated replies"
- "citations, no bs, don't confuse existing block with SSW that hasn't happened yet"
- "your knowledge is actually assumptions not scientific or academic citations"
- "mandatory rule you can not make specific rules for a reply's content that would be fucking nuts"

### Log Output Showing Problem
```
Response (2 post(s)): [1/2] The ECMWF sub-seasonal charts you've shared ...
Posted 2 post(s): [1/2] The ECMWF sub-seasonal charts you've shared ...
```
Should be ONE post, not two.

### Specific Bad Behavior
Bot said things like:
- "This aligns with..." (causal claim, no source)
- "Classic SSW signature" (dramatic language, no citation)
- Conflated SSW forecast (future) with current blocking pattern (present)

## Files Affected

| File | Lines | What Changed |
|------|-------|--------------|
| `reply_listener.py` | 117-135 | `extract_image_urls()` - KEEP |
| `reply_listener.py` | 1261-1285 | `get_notification_mentions()` - KEEP |
| `reply_listener.py` | 2375-2518 | `generate_chat_response()` prompt - REVIEW |
| `reply_listener.py` | 3021-3144 | Mention handling in main() - REVERT TO SIMPLE |

## References

- DEV_JOURNAL_2026-01-19.md - Documents working configuration
- Git commit 656a356 - Last known working mention prompt
- UNIFIED_REPLY_REFACTOR.md - Documents today's (broken) refactor

## Action Items

- [ ] Revert mention handling to simple prompt (lines 3078-3144)
- [ ] Keep parent/image context additions
- [ ] Keep recordWithMedia fix
- [ ] Test with dry-run before live
- [ ] Verify single-post responses
- [ ] Verify citations work via --tools flag
