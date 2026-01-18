#!/usr/bin/env python3
"""
WXD Bluesky Publishing Module
=============================

Expert-level Bluesky operations for all wxd projects. Handles the complexities
of the AT Protocol so you don't have to figure them out each time.

CRITICAL KNOWLEDGE:
------------------
1. URLs DO NOT auto-link in Bluesky - you MUST use facets (this module does it automatically)
2. Facets use BYTE positions, not character positions (UTF-8 matters!)
3. Bluesky has NO edit - you must delete and repost
4. Max post length is 300 characters
5. Threads need proper root/parent chain

QUICK START:
-----------
    from lib.bluesky import BlueskyClient

    client = BlueskyClient()  # Reads credentials from environment

    # Simple post (URLs auto-linked!)
    result = client.post("Check this: https://example.com")
    print(f"Posted: {result['url']}")

    # Thread
    results = client.post_thread(["Part 1", "Part 2", "Part 3"])

    # Delete
    client.delete(result['uri'])

    # List recent
    for p in client.get_recent_posts(10):
        print(p['text'][:50])

CREDENTIALS:
-----------
Set these environment variables (usually via ~/.wxd_env):
    export BSKY_HANDLE="your-handle.bsky.social"
    export BSKY_PASSWORD="your-app-password"

USAGE FROM OTHER PROJECTS:
-------------------------
    import sys
    sys.path.insert(0, '/home/ubuntu/wxd')
    from lib.bluesky import BlueskyClient

For full documentation see: ~/wxd/docs/BLUESKY_PUBLISHING.md
"""

import json
import os
import re
from pathlib import Path
from typing import Optional, Union
from datetime import datetime, timezone

try:
    from atproto import Client, models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False
    Client = None
    models = None


class BlueskyError(Exception):
    """Bluesky operation failed."""
    pass


def log_lesson(problem: str, root_cause: str, fix: str, prevention: str):
    """
    Append a new lesson to the lessons learned file.

    Call this when you encounter and fix a new issue.
    Future sessions will see it in the docs.

    Example:
        log_lesson(
            problem="Thread posts appeared disconnected",
            root_cause="Reply chain refs were wrong",
            fix="Fixed root/parent ref logic",
            prevention="Use post_thread() which handles chaining"
        )
    """
    from datetime import datetime
    from pathlib import Path

    lessons_file = Path("/home/ubuntu/wxd/docs/BLUESKY_PUBLISHING.md")
    if not lessons_file.exists():
        print("  Warning: Lessons file not found, skipping log")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    lesson_entry = f"""
---

### {today}: {problem[:50]}

**Problem:** {problem}

**Root cause:** {root_cause}

**Fix:** {fix}

**Prevention:** {prevention}
"""

    # Find the "## Implementation Status" marker and insert before it
    content = lessons_file.read_text()
    marker = "## Implementation Status"

    if marker in content:
        parts = content.split(marker)
        new_content = parts[0] + lesson_entry + "\n" + marker + parts[1]
        lessons_file.write_text(new_content)
        print(f"  Logged lesson: {problem[:40]}...")
    else:
        # Append to end if marker not found
        with open(lessons_file, 'a') as f:
            f.write(lesson_entry)
        print(f"  Logged lesson: {problem[:40]}...")


# =============================================================================
# RESEARCH TOPIC REGISTRATION
# Links posts to research topics for citation support in reply system
# =============================================================================

RESEARCH_INDEX_PATH = Path(__file__).parent.parent / "data" / "research_index.json"


def register_research_topic(topic: str, post_uris: list, sources: list = None):
    """
    Register post URIs to a research topic for reply context system.

    Args:
        topic: Topic ID (e.g., "model_bias_blocking")
        post_uris: List of AT URIs to register
        sources: Optional list of source doc paths (creates/updates topic if provided)
    """
    # Load existing index
    if RESEARCH_INDEX_PATH.exists():
        with open(RESEARCH_INDEX_PATH, 'r') as f:
            index = json.load(f)
    else:
        index = {"topics": {}, "post_to_topic": {}}

    # Create topic if it doesn't exist and sources provided
    if topic not in index.get("topics", {}) and sources:
        index.setdefault("topics", {})[topic] = {
            "title": topic.replace("_", " ").title(),
            "description": "",
            "source_docs": sources,
            "keywords": [],
            "posts": [],
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d")
        }
    elif sources and topic in index.get("topics", {}):
        # Update sources if provided and topic exists
        existing_sources = index["topics"][topic].get("source_docs", [])
        for src in sources:
            if src not in existing_sources:
                existing_sources.append(src)
        index["topics"][topic]["source_docs"] = existing_sources
        index["topics"][topic]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Register post URIs
    for uri in post_uris:
        index.setdefault("post_to_topic", {})[uri] = topic
        if topic in index.get("topics", {}):
            if uri not in index["topics"][topic].get("posts", []):
                index["topics"][topic].setdefault("posts", []).append(uri)

    # Save
    with open(RESEARCH_INDEX_PATH, 'w') as f:
        json.dump(index, f, indent=2)

    print(f"  Registered {len(post_uris)} posts to research topic '{topic}'")


class BlueskyClient:
    """
    Expert Bluesky client with auto-faceting and proper error handling.

    This class handles the complexities of the AT Protocol:
    - Auto-detects URLs, mentions, hashtags and creates facets
    - Proper byte-position calculations for UTF-8
    - Thread chaining with correct root/parent references
    - Clean delete/replace operations

    Example:
        client = BlueskyClient()
        result = client.post("Hello https://example.com!")
        # The URL is automatically made clickable
    """

    def __init__(self, handle: str = None, password: str = None):
        """
        Initialize client with credentials.

        Args:
            handle: Bluesky handle (default: from BSKY_HANDLE env var)
            password: App password (default: from BSKY_PASSWORD env var)

        Raises:
            BlueskyError: If atproto not installed or credentials missing
        """
        if not HAS_ATPROTO:
            raise BlueskyError("atproto not installed. Run: pip install atproto")

        self.handle = handle or os.environ.get('BSKY_HANDLE')
        self.password = password or os.environ.get('BSKY_PASSWORD')

        if not self.handle or not self.password:
            raise BlueskyError(
                "Credentials not found. Set BSKY_HANDLE and BSKY_PASSWORD env vars, "
                "or pass handle/password to constructor."
            )

        self._client = None
        self._did = None

    def __getattr__(self, name):
        """Catch incorrect method names and show available methods."""
        available = ['post', 'post_thread', 'delete', 'get_recent_posts',
                     'find_posts_containing', 'replace', 'get_post']
        raise AttributeError(
            f"BlueskyClient has no method '{name}'.\n"
            f"Available methods: {', '.join(available)}\n"
            f"READ CLAUDE.md BEFORE GUESSING METHOD NAMES."
        )

    def _ensure_logged_in(self):
        """Login if not already logged in."""
        if self._client is None:
            self._client = Client()
            profile = self._client.login(self.handle, self.password)
            self._did = profile.did

    def _detect_facets(self, text: str) -> list:
        """
        Auto-detect URLs, mentions, and hashtags in text.

        IMPORTANT: Bluesky uses BYTE positions, not character positions.
        This is critical for non-ASCII text (emojis, accented chars).

        Args:
            text: Post text to scan

        Returns:
            List of facet objects ready for the API
        """
        facets = []
        text_bytes = text.encode('utf-8')

        # URL pattern
        url_pattern = r'https?://[^\s<>\[\]()"\',]+[^\s<>\[\]()"\',.]'
        for match in re.finditer(url_pattern, text):
            url = match.group()
            # Calculate byte positions
            start_char = match.start()
            end_char = match.end()
            byte_start = len(text[:start_char].encode('utf-8'))
            byte_end = len(text[:end_char].encode('utf-8'))

            facets.append(models.AppBskyRichtextFacet.Main(
                index=models.AppBskyRichtextFacet.ByteSlice(
                    byte_start=byte_start,
                    byte_end=byte_end
                ),
                features=[models.AppBskyRichtextFacet.Link(uri=url)]
            ))

        # Mention pattern (@handle.domain.tld)
        mention_pattern = r'@([a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'
        for match in re.finditer(mention_pattern, text):
            handle = match.group()[1:]  # Remove @
            start_char = match.start()
            end_char = match.end()
            byte_start = len(text[:start_char].encode('utf-8'))
            byte_end = len(text[:end_char].encode('utf-8'))

            # Resolve handle to DID (required for mentions)
            try:
                self._ensure_logged_in()
                profile = self._client.get_profile(handle)
                did = profile.did

                facets.append(models.AppBskyRichtextFacet.Main(
                    index=models.AppBskyRichtextFacet.ByteSlice(
                        byte_start=byte_start,
                        byte_end=byte_end
                    ),
                    features=[models.AppBskyRichtextFacet.Mention(did=did)]
                ))
            except Exception:
                # Skip invalid mentions
                pass

        # Hashtag pattern
        hashtag_pattern = r'#[a-zA-Z][a-zA-Z0-9_]*'
        for match in re.finditer(hashtag_pattern, text):
            tag = match.group()[1:]  # Remove #
            start_char = match.start()
            end_char = match.end()
            byte_start = len(text[:start_char].encode('utf-8'))
            byte_end = len(text[:end_char].encode('utf-8'))

            facets.append(models.AppBskyRichtextFacet.Main(
                index=models.AppBskyRichtextFacet.ByteSlice(
                    byte_start=byte_start,
                    byte_end=byte_end
                ),
                features=[models.AppBskyRichtextFacet.Tag(tag=tag)]
            ))

        return facets

    def _make_post_url(self, uri: str) -> str:
        """Convert AT URI to web URL."""
        # at://did:plc:xxx/app.bsky.feed.post/yyy -> https://bsky.app/profile/handle/post/yyy
        parts = uri.split('/')
        rkey = parts[-1]
        return f"https://bsky.app/profile/{self.handle}/post/{rkey}"

    def _validate_post(self, text: str) -> list:
        """
        Run learned validation checks before posting.

        Returns list of warnings (empty if all good).
        These checks encode lessons learned from past mistakes.
        """
        warnings = []

        # LESSON 2026-01-10: Check for URLs that won't be auto-linked
        # if manual facets provided but URL pattern found
        url_pattern = r'https?://[^\s]+'
        urls_in_text = re.findall(url_pattern, text)

        # LESSON 2026-01-10: Thread numbering required for multi-post
        # (handled by post_thread, but warn if someone tries manual)

        # Check for common engagement topic patterns that might be repeats
        engagement_keywords = ['why do', 'what is', 'how do', 'explained']
        if any(kw in text.lower() for kw in engagement_keywords):
            warnings.append(
                "REMINDER: This looks like engagement content. "
                "Did you check EngagementTracker.is_topic_recent()?"
            )

        return warnings

    def post(self, text: str, facets: list = None, images: list = None,
             reply_to: str = None, auto_facets: bool = True,
             skip_warnings: bool = False,
             tracker: str = None, model: str = None) -> dict:
        """
        Post to Bluesky with automatic facet detection.

        URLs in your text are AUTOMATICALLY made clickable unless you
        set auto_facets=False.

        Args:
            text: Post text (max 300 characters)
            facets: Manual facets (overrides auto-detection if provided)
            images: List of image file paths (not yet implemented)
            reply_to: URI of post to reply to
            auto_facets: Auto-detect URLs/mentions/hashtags (default True)
            skip_warnings: Skip validation warnings (default False)
            tracker: Tracker name for post registry (e.g., 'ssw')
            model: Model name for post registry

        Returns:
            dict with keys:
                - uri: AT Protocol URI (at://did:plc:.../app.bsky.feed.post/...)
                - cid: Content ID
                - url: Web URL (https://bsky.app/profile/.../post/...)

        Raises:
            BlueskyError: If post fails
            ValueError: If text > 300 characters

        Example:
            result = client.post("Check this: https://example.com")
            print(f"Posted: {result['url']}")
        """
        if len(text) > 300:
            raise ValueError(f"Post too long ({len(text)} chars, max 300)")

        # Run learned validation checks
        if not skip_warnings:
            warnings = self._validate_post(text)
            for w in warnings:
                print(f"  WARNING: {w}")

        self._ensure_logged_in()

        # Auto-detect facets if not provided
        if facets is None and auto_facets:
            facets = self._detect_facets(text)

        # Build reply reference if replying
        reply_ref = None
        if reply_to:
            # Get the post we're replying to
            try:
                thread = self._client.get_post_thread(reply_to)
                parent_post = thread.thread.post

                # For replies, we need both parent and root
                parent_ref = models.create_strong_ref(parent_post)

                # Find the root (might be the parent itself or further up)
                root_post = parent_post
                if hasattr(thread.thread, 'parent') and thread.thread.parent:
                    # Walk up to find root
                    current = thread.thread
                    while hasattr(current, 'parent') and current.parent:
                        current = current.parent
                    if hasattr(current, 'post'):
                        root_post = current.post

                root_ref = models.create_strong_ref(root_post)

                reply_ref = models.AppBskyFeedPost.ReplyRef(
                    parent=parent_ref,
                    root=root_ref
                )
            except Exception as e:
                raise BlueskyError(f"Failed to get reply target: {e}")

        try:
            if facets:
                response = self._client.send_post(text=text, facets=facets, reply_to=reply_ref)
            else:
                response = self._client.send_post(text=text, reply_to=reply_ref)

            # Register post for feedback tracing (default to 'manual' if no tracker specified)
            register_post(
                uri=response.uri,
                tracker=tracker or 'manual',
                model=model,
                text_preview=text[:100]
            )

            return {
                'uri': response.uri,
                'cid': response.cid,
                'url': self._make_post_url(response.uri)
            }
        except Exception as e:
            raise BlueskyError(f"Post failed: {e}")

    def post_thread(self, posts: list, auto_number: bool = True,
                    auto_facets: bool = True,
                    tracker: str = None, model: str = None,
                    topic: str = None, sources: list = None) -> list:
        """
        Post a thread with proper reply chaining.

        Automatically adds [1/N], [2/N] etc. numbering to each post.

        Args:
            posts: List of post texts
            auto_number: Add [X/Y] thread numbering (default True)
            auto_facets: Auto-detect URLs/mentions/hashtags (default True)
            tracker: Tracker name for post registry (e.g., 'weekly')
            model: Model name for post registry
            topic: Research topic to link this thread to (for reply context system)
            sources: List of source doc paths for this topic (creates topic if needed)

        Returns:
            List of result dicts (same format as post())

        Example:
            # Basic thread
            results = client.post_thread([
                "This is the start...",
                "The middle of my thread...",
                "And the conclusion!"
            ])
            print(f"Thread: {results[0]['url']}")

            # Thread with research topic (for citation support in replies)
            results = client.post_thread(
                posts,
                topic="model_bias_blocking",
                sources=["incoming/research.md"]
            )
        """
        if not posts:
            raise ValueError("No posts provided")

        # Add thread numbering
        total = len(posts)
        if auto_number and total > 1:
            numbered = []
            for i, text in enumerate(posts):
                indicator = f"[{i+1}/{total}] "
                max_len = 300 - len(indicator)
                if len(text) > max_len:
                    text = text[:max_len - 3].rstrip() + "..."
                numbered.append(indicator + text)
            posts = numbered

        self._ensure_logged_in()

        results = []
        root_ref = None
        parent_ref = None

        for i, text in enumerate(posts):
            # Detect facets for this post
            facets = self._detect_facets(text) if auto_facets else None

            # Build reply reference for thread continuation
            reply_ref = None
            if parent_ref:
                reply_ref = models.AppBskyFeedPost.ReplyRef(
                    parent=parent_ref,
                    root=root_ref
                )

            try:
                if facets:
                    response = self._client.send_post(text=text, facets=facets, reply_to=reply_ref)
                else:
                    response = self._client.send_post(text=text, reply_to=reply_ref)

                result = {
                    'uri': response.uri,
                    'cid': response.cid,
                    'url': self._make_post_url(response.uri)
                }
                results.append(result)

                # Register post for feedback tracing (default to 'manual' if no tracker specified)
                register_post(
                    uri=response.uri,
                    tracker=tracker or 'manual',
                    model=model,
                    text_preview=text[:100]
                )

                # Update refs for next post
                current_ref = models.ComAtprotoRepoStrongRef.Main(
                    uri=response.uri, cid=response.cid
                )
                if root_ref is None:
                    root_ref = current_ref
                parent_ref = current_ref

            except Exception as e:
                raise BlueskyError(f"Thread post {i+1} failed: {e}")

        # Register to research topic if specified
        if topic and results:
            try:
                register_research_topic(
                    topic=topic,
                    post_uris=[r['uri'] for r in results],
                    sources=sources
                )
            except Exception as e:
                print(f"Warning: Could not register research topic: {e}")

        return results

    def delete(self, uri: str) -> bool:
        """
        Delete a post by its URI.

        Args:
            uri: AT Protocol URI (at://did:plc:.../app.bsky.feed.post/...)
                 Get this from post()['uri'] or get_recent_posts()

        Returns:
            True if deleted successfully

        Raises:
            BlueskyError: If delete fails

        Example:
            client.delete("at://did:plc:abc123/app.bsky.feed.post/xyz789")
        """
        self._ensure_logged_in()

        try:
            self._client.delete_post(uri)
            return True
        except Exception as e:
            raise BlueskyError(f"Delete failed: {e}")

    def get_recent_posts(self, limit: int = 20) -> list:
        """
        Get recent posts from the account.

        Args:
            limit: Max posts to return (default 20, max 100)

        Returns:
            List of dicts with keys:
                - uri: AT Protocol URI
                - cid: Content ID
                - url: Web URL
                - text: Post text
                - created_at: ISO timestamp
                - like_count: Number of likes
                - reply_count: Number of replies
                - repost_count: Number of reposts
                - is_reply: True if this is a reply

        Example:
            for post in client.get_recent_posts(10):
                print(f"{post['created_at']}: {post['text'][:50]}...")
        """
        self._ensure_logged_in()

        try:
            feed = self._client.get_author_feed(self._did, limit=min(limit, 100))

            results = []
            for item in feed.feed:
                post = item.post
                record = post.record

                results.append({
                    'uri': post.uri,
                    'cid': post.cid,
                    'url': self._make_post_url(post.uri),
                    'text': record.text if hasattr(record, 'text') else '',
                    'created_at': record.created_at if hasattr(record, 'created_at') else None,
                    'like_count': getattr(post, 'like_count', 0),
                    'reply_count': getattr(post, 'reply_count', 0),
                    'repost_count': getattr(post, 'repost_count', 0),
                    'is_reply': hasattr(record, 'reply') and record.reply is not None
                })

            return results
        except Exception as e:
            raise BlueskyError(f"Failed to get posts: {e}")

    def get_post(self, uri: str) -> dict:
        """
        Get a specific post by URI.

        Args:
            uri: AT Protocol URI

        Returns:
            dict with post details (same format as get_recent_posts items)
        """
        self._ensure_logged_in()

        try:
            thread = self._client.get_post_thread(uri)
            post = thread.thread.post
            record = post.record

            return {
                'uri': post.uri,
                'cid': post.cid,
                'url': self._make_post_url(post.uri),
                'text': record.text if hasattr(record, 'text') else '',
                'created_at': record.created_at if hasattr(record, 'created_at') else None,
                'like_count': getattr(post, 'like_count', 0),
                'reply_count': getattr(post, 'reply_count', 0),
                'repost_count': getattr(post, 'repost_count', 0),
            }
        except Exception as e:
            raise BlueskyError(f"Failed to get post: {e}")

    def replace(self, uri: str, new_text: str, **kwargs) -> dict:
        """
        Replace a post (delete and repost).

        WARNING: This loses all engagement (likes, replies, reposts).
        Bluesky does not support editing posts.

        Args:
            uri: URI of post to replace
            new_text: New post text
            **kwargs: Additional args passed to post()

        Returns:
            dict with new post details

        Example:
            new = client.replace(old_uri, "Corrected text")
        """
        self.delete(uri)
        return self.post(new_text, **kwargs)

    def find_posts_containing(self, search_text: str, limit: int = 50) -> list:
        """
        Find recent posts containing specific text.

        Useful for finding posts to delete/replace.

        Args:
            search_text: Text to search for (case-insensitive)
            limit: Max posts to search through

        Returns:
            List of matching posts

        Example:
            posts = client.find_posts_containing("[1/5]")
            for p in posts:
                print(p['text'][:50])
        """
        all_posts = self.get_recent_posts(limit)
        search_lower = search_text.lower()
        return [p for p in all_posts if search_lower in p['text'].lower()]


class EngagementTracker:
    """
    Track engagement topics to prevent repeats.

    Uses ~/wxd/engagement/data/engagement_state.json for persistence.
    Works alongside the automated engagement_post.py system.

    Example:
        tracker = EngagementTracker()

        # Check if topic was used recently (last 30 days default)
        if tracker.is_topic_recent("Why forecasts change"):
            print("Too soon to repeat this topic!")

        # Log a topic after posting
        tracker.log_topic("weather_education", "Why forecasts change")

        # Get topic history
        for t in tracker.get_recent_topics(5):
            print(f"{t['time']}: {t['topic']}")
    """

    STATE_FILE = "/home/ubuntu/wxd/engagement/data/engagement_state.json"

    def __init__(self):
        self._state = None

    def _load_state(self) -> dict:
        """Load state from file."""
        import json
        from pathlib import Path

        state_path = Path(self.STATE_FILE)
        if state_path.exists():
            try:
                with open(state_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "topic_history": [],
            "posts_count": 0
        }

    def _save_state(self, state: dict):
        """Save state to file."""
        import json
        from pathlib import Path

        state_path = Path(self.STATE_FILE)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, 'w') as f:
            json.dump(state, f, indent=2)

    def get_recent_topics(self, limit: int = 10) -> list:
        """Get recent topic history."""
        state = self._load_state()
        return state.get("topic_history", [])[-limit:]

    def is_topic_recent(self, topic: str, days: int = 30) -> bool:
        """
        Check if a topic (or similar) was used recently.

        Uses fuzzy matching - checks if topic words appear in recent topics.

        Args:
            topic: Topic to check
            days: Look back this many days (default 30)

        Returns:
            True if topic appears to have been used recently
        """
        from datetime import datetime, timezone, timedelta

        state = self._load_state()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        topic_words = set(topic.lower().split())

        for entry in state.get("topic_history", []):
            try:
                entry_time = datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))
                if entry_time < cutoff:
                    continue

                # Check for significant word overlap
                entry_words = set(entry["topic"].lower().split())
                overlap = topic_words & entry_words
                # If more than 50% of words match, consider it similar
                if len(overlap) > len(topic_words) * 0.5:
                    return True
            except Exception:
                continue

        return False

    def log_topic(self, category: str, topic: str):
        """
        Log a topic after posting.

        Args:
            category: Topic category (e.g., "weather_education", "cold_relevant")
            topic: The topic text
        """
        from datetime import datetime, timezone

        state = self._load_state()

        if "topic_history" not in state:
            state["topic_history"] = []

        state["topic_history"].append({
            "category": category,
            "topic": topic,
            "time": datetime.now(timezone.utc).isoformat()
        })

        # Keep last 100 topics
        state["topic_history"] = state["topic_history"][-100:]
        state["posts_count"] = state.get("posts_count", 0) + 1

        self._save_state(state)

    def suggest_fresh_category(self) -> str:
        """
        Suggest a category that hasn't been used recently.

        Returns:
            Category name least recently used
        """
        state = self._load_state()
        history = state.get("topic_history", [])

        # Count recent category usage
        from collections import Counter
        recent_categories = Counter(
            entry.get("category", "unknown")
            for entry in history[-10:]
        )

        all_categories = [
            "weather_education",
            "cold_relevant",
            "warm_relevant",
            "myth_busting",
            "ai_tech",
            "project_updates"
        ]

        # Return least used
        for cat in all_categories:
            if cat not in recent_categories:
                return cat

        # Return least frequent
        return min(all_categories, key=lambda c: recent_categories.get(c, 0))


# =============================================================================
# POST REGISTRY - Track which tracker/model created each post
# =============================================================================

_POST_REGISTRY_PATH = Path(__file__).parent.parent / 'data' / 'post_registry.json'


def register_post(uri: str, tracker: str, model: str = None, text_preview: str = None) -> None:
    """Register a post with its source tracker/model for later lookup.

    Args:
        uri: The at:// URI of the post
        tracker: Tracker name (e.g., 'MOGREPS', 'ICON', 'UKMO', 'Main')
        model: Model name (e.g., 'mogreps-g', 'icon-eu-eps', 'ukmo-global')
        text_preview: First ~100 chars of post text for verification
    """
    try:
        if _POST_REGISTRY_PATH.exists():
            with open(_POST_REGISTRY_PATH) as f:
                registry = json.load(f)
        else:
            registry = {'posts': []}

        entry = {
            'uri': uri,
            'tracker': tracker,
            'model': model,
            'text_preview': (text_preview or '')[:100],
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        registry['posts'].append(entry)

        # Keep last 500 posts to avoid unbounded growth
        if len(registry['posts']) > 500:
            registry['posts'] = registry['posts'][-500:]

        with open(_POST_REGISTRY_PATH, 'w') as f:
            json.dump(registry, f, indent=2)
    except Exception as e:
        # Don't fail posting if registry fails
        print(f"Warning: Could not register post: {e}")


def lookup_post(uri: str) -> dict:
    """Look up which tracker/model created a post.

    Args:
        uri: The at:// URI to look up

    Returns:
        Dict with 'tracker', 'model', 'text_preview', 'timestamp' or None if not found
    """
    try:
        if not _POST_REGISTRY_PATH.exists():
            return None

        with open(_POST_REGISTRY_PATH) as f:
            registry = json.load(f)

        for entry in registry.get('posts', []):
            if entry.get('uri') == uri:
                return entry
        return None
    except Exception:
        return None


def help():
    """Print help information."""
    print(__doc__)


# Quick test when run directly
if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--help':
        help()
        sys.exit(0)

    print("Bluesky Publishing Module")
    print("=" * 40)
    print()
    print("Testing connection...")

    try:
        client = BlueskyClient()
        posts = client.get_recent_posts(3)
        print(f"Connected as @{client.handle}")
        print(f"\nRecent posts:")
        for p in posts:
            text = p['text'].replace('\n', ' ')[:60]
            print(f"  - {text}...")
        print()
        print("Module working correctly!")
    except BlueskyError as e:
        print(f"Error: {e}")
        sys.exit(1)
