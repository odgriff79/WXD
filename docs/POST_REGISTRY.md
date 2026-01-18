# Post Registry System

Tracks which tracker/model generated each Bluesky post for feedback tracing.

## Problem Solved

When dev feedback arrives on a post, we need to identify which tracker generated it to fix the correct code. Previously this required manual tracing via timestamps or guessing from post text.

## Solution

All posting paths now register posts to `data/post_registry.json` with:
- `uri` - Bluesky AT Protocol URI
- `tracker` - Source tracker name
- `model` - Model name (if applicable)
- `text_preview` - First 100 chars for verification
- `timestamp` - When posted

## Registry File

```
data/post_registry.json
```

Keeps last 500 posts (auto-pruned).

## Trackers Registered

| Tracker | Code Location | Registry Name |
|---------|---------------|---------------|
| Main (4-model) | `post_bluesky.py` | `Main` |
| MOGREPS | `trackers/mogreps/post.py` | `MOGREPS` |
| ICON | `trackers/icon/post.py` | `ICON` |
| UKMO | `trackers/ukmo/post.py` | `UKMO` |
| Daily Summary | `daily_summary.py` | `daily_summary` |
| Met Warnings | `daily_summary.py` | `met_warnings` |
| Engagement | `engagement/engagement_post.py` | `engagement` |
| SSW Monitor | `ssw_monitor.py` | `ssw` |
| Weekly Recap | `post_bluesky.py --weekly` | `weekly` |
| Changelog | `post_bluesky.py --changelog` | `changelog` |

## API

### Register a post (automatic)

All trackers call this automatically after posting:

```python
from lib.bluesky import register_post

register_post(
    uri="at://did:plc:.../app.bsky.feed.post/...",
    tracker="MOGREPS",
    model="mogreps-g",
    text_preview="[1/2] Progressive cooling..."
)
```

### Look up a post

```python
from lib.bluesky import lookup_post

info = lookup_post("at://did:plc:.../app.bsky.feed.post/...")
if info:
    print(f"Tracker: {info['tracker']}")
    print(f"Model: {info['model']}")
    print(f"Posted: {info['timestamp']}")
```

## Feedback Workflow

When `reply_listener.py --feedback` runs:

1. Feedback entries now include `parent_uri` (the post being replied to)
2. Display code calls `lookup_post(parent_uri)` to get tracker name
3. If not in registry (old posts), falls back to text pattern matching

## Adding New Posting Paths

When adding new automated posts:

1. Import: `from lib.bluesky import register_post`
2. After successful post, call:
   ```python
   register_post(
       uri=response.uri,
       tracker='your_tracker_name',
       model='model_name_or_none',
       text_preview=text[:100]
   )
   ```

Or if using shared functions:
- `post_thread_to_bluesky()` - pass `tracker=` and `model=` params
- `BlueskyClient.post()` - pass `tracker=` and `model=` params
- `BlueskyClient.post_thread()` - pass `tracker=` and `model=` params
