#!/usr/bin/env python3
"""
WXD Reply Listener v2

Two-step engagement model:
1. First reply from user → canned "reply 'chat' to continue"
2. User replies "chat" → Claude conversation begins

Features:
- Lockdown mode for testing (only respond to specific users)
- Session management with message limits
- Two-step opt-in prevents abuse and minimizes API costs
- Friendly, weather-savvy persona

Safety:
- Rate limited (max 5 replies per run)
- Dry-run by default (--post to actually reply)
- Blocklist for trolls
- State tracking to avoid duplicate responses

Usage:
    python reply_listener.py                    # Dry-run, show what would be done
    python reply_listener.py --post             # Actually post replies
    python reply_listener.py --limit 3          # Check only 3 recent posts
    python reply_listener.py --max-replies 2    # Respond to max 2 replies per run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from atproto import Client, models as atproto_models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False
    Client = None  # type: ignore

# Import post registry for tracker lookup
try:
    from lib.bluesky import lookup_post
    HAS_LOOKUP = True
except ImportError:
    HAS_LOOKUP = False
    lookup_post = None

# Import Met Office fetcher for ground truth warnings
try:
    from daily_summary import fetch_metoffice_narrative
    HAS_METOFFICE = True
except ImportError:
    HAS_METOFFICE = False
    fetch_metoffice_narrative = None


# =============================================================================
# CONFIGURATION
# =============================================================================

# Safety limits
DEFAULT_MAX_REPLIES = 5  # Max replies to send per run
DEFAULT_POSTS_TO_CHECK = 10  # How many recent posts to check for replies

# Session limits
SESSION_MSG_LIMIT_STANDARD = 10   # Max messages per session (regular followers)
SESSION_MSG_LIMIT_TRUSTED = 10   # Max messages per session (trusted users)
SESSION_MSG_LIMIT_FEEDBACK = 15  # Extended limit for feedback/clarification conversations
SESSION_EXPIRY_HOURS = 72        # Session expires after this many hours idle

# Adaptive polling - cron runs frequently, script decides whether to actually check
# When engaged (recent reply): always run for fast response
# When quiet: back off to save resources
ENGAGED_MODE_WINDOW_MINS = 60     # If reply within this window, we're "engaged"
QUIET_CHECK_INTERVAL_MINS = 120   # When quiet, only run every 2 hours
ADAPTIVE_POLLING = True           # Set False to always run

# Blocklist - DIDs of accounts to ignore
BLOCKLIST = set()

# Trusted users - get higher limits and auto-approve (add DIDs here)
TRUSTED_USERS = {
    "did:plc:mz3csh3lutlgll77bpdfnhy7",  # MetJam (@metjam.co.uk)
}

# =============================================================================
# SUPER USER - SYSTEM OWNER (DO NOT AUTO-RESPOND)
# Super user messages are TRAINING INPUTS, not conversation triggers
# =============================================================================
SUPER_USER_HANDLES = [
    "ogriff79.bsky.social",  # Owen Griffiths - system owner
]

# =============================================================================
# TEST MODE / LOCKDOWN
# Set to empty list for normal operation, or add handles for lockdown testing
# =============================================================================
# TEST_MODE_USERS = [
#     "winchesterweather.bsky.social",  # Steve - primary tester
#     "sarahhants.bsky.social",          # Sarah - trusted follower, training data
# ]
TEST_MODE_USERS = []  # LIVE MODE - all followers can chat

# =============================================================================
# CANNED RESPONSES
# =============================================================================
CANNED_RESPONSES = {
    "chat_greeting": (
        "Hi! Happy to chat about WXD, UK weather, automation, AI or related topics. "
        "What's on your mind?"
    ),
    "chat_invitation": (
        "Thanks for your reply! 🌤️ WXD is trialing AI-powered weather discussions. "
        "If you'd like to chat about UK weather forecasts, models, or anything weather-related, "
        "just make sure you're following us and reply with the word 'chat' - "
        "we'd love to hear from you!"
    ),
    "session_limit": (
        "You've reached the message limit for this chat session. "
        "Start a new conversation anytime by replying 'chat' to a future post."
    ),
}

# =============================================================================
# RESEARCH CONTEXT SYSTEM
# Loads source docs and logs chat research for factual replies
# =============================================================================

RESEARCH_INDEX_PATH = Path(__file__).parent / "data" / "research_index.json"
CHAT_RESEARCH_DIR = Path(__file__).parent / "data" / "chat_research"


def load_research_index() -> dict:
    """Load the research index mapping topics to source docs."""
    if RESEARCH_INDEX_PATH.exists():
        with open(RESEARCH_INDEX_PATH, 'r') as f:
            return json.load(f)
    return {"topics": {}, "post_to_topic": {}}


def save_research_index(index: dict):
    """Save the research index."""
    with open(RESEARCH_INDEX_PATH, 'w') as f:
        json.dump(index, f, indent=2)


def get_topic_for_post(uri: str) -> str | None:
    """Find the research topic for a post URI."""
    index = load_research_index()
    return index.get("post_to_topic", {}).get(uri)


def register_post_to_topic(uri: str, topic: str):
    """Register a post URI to a research topic."""
    index = load_research_index()
    index.setdefault("post_to_topic", {})[uri] = topic
    # Also add to the topic's posts list
    if topic in index.get("topics", {}):
        if uri not in index["topics"][topic].get("posts", []):
            index["topics"][topic].setdefault("posts", []).append(uri)
            index["topics"][topic]["last_updated"] = utcnow().strftime("%Y-%m-%d")
    save_research_index(index)


def load_research_sources(topic: str) -> dict:
    """Load all source documents for a research topic.

    Returns dict with:
        - topic_info: metadata about the topic
        - sources: list of {path, content} for each source doc
    """
    index = load_research_index()
    topic_info = index.get("topics", {}).get(topic)

    if not topic_info:
        return {"topic_info": None, "sources": []}

    sources = []
    for doc_path in topic_info.get("source_docs", []):
        full_path = Path(__file__).parent / doc_path
        if full_path.exists():
            try:
                with open(full_path, 'r') as f:
                    content = f.read()
                sources.append({
                    "path": doc_path,
                    "content": content
                })
            except Exception as e:
                print(f"    Warning: Could not read {doc_path}: {e}")

    return {
        "topic_info": topic_info,
        "sources": sources
    }


def get_chat_research_path(thread_uri: str) -> Path:
    """Get the path to the chat research MD for a thread."""
    # Use a sanitized version of the URI as filename
    # at://did:plc:xxx/app.bsky.feed.post/yyy -> yyy.md
    thread_id = thread_uri.split("/")[-1] if "/" in thread_uri else thread_uri
    return CHAT_RESEARCH_DIR / f"{thread_id}.md"


def load_chat_research(thread_uri: str) -> str:
    """Load existing chat research MD for a thread."""
    path = get_chat_research_path(thread_uri)
    if path.exists():
        with open(path, 'r') as f:
            return f.read()
    return ""


def log_chat_research(thread_uri: str, topic: str, entry: dict):
    """Log a research entry to the chat research MD.

    entry should contain:
        - timestamp: ISO timestamp
        - user: who asked
        - query: what they asked
        - web_searches: list of {query, results} from web search
        - sources_used: list of source doc paths consulted
        - response: what was replied
    """
    CHAT_RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    path = get_chat_research_path(thread_uri)

    # Create header if new file
    if not path.exists():
        research_data = load_research_sources(topic) if topic else {"topic_info": None, "sources": []}
        header = f"""# Research Log: {topic or 'unknown'}
Thread: {thread_uri}
Created: {utcnow().isoformat()}

## Source Documents
"""
        if research_data["sources"]:
            for src in research_data["sources"]:
                header += f"- {src['path']}\n"
        else:
            header += "- None linked\n"

        header += "\n---\n\n## Chat Sessions\n"

        with open(path, 'w') as f:
            f.write(header)

    # Append the entry
    entry_md = f"""
### {entry.get('timestamp', utcnow().isoformat())}
**User:** {entry.get('user', 'unknown')}
**Query:** {entry.get('query', '')}

"""

    if entry.get('web_searches'):
        entry_md += "**Web Searches:**\n"
        for search in entry['web_searches']:
            entry_md += f"- Query: \"{search.get('query', '')}\"\n"
            for result in search.get('results', [])[:3]:
                entry_md += f"  - {result}\n"
        entry_md += "\n"

    if entry.get('sources_used'):
        entry_md += "**Sources Consulted:**\n"
        for src in entry['sources_used']:
            entry_md += f"- {src}\n"
        entry_md += "\n"

    entry_md += f"**Response:**\n{entry.get('response', '[No response]')}\n\n---\n"

    with open(path, 'a') as f:
        f.write(entry_md)


def build_research_context(thread_uri: str, parent_uri: str = None) -> str:
    """Build research context string for Claude prompt.

    Includes:
        - Topic info and source docs (if linked)
        - Prior chat research (if exists)
    """
    # Find topic from thread root or parent
    topic = get_topic_for_post(thread_uri)
    if not topic and parent_uri:
        topic = get_topic_for_post(parent_uri)

    if not topic:
        return ""

    context_parts = []

    # Load source documents
    research_data = load_research_sources(topic)
    if research_data["topic_info"]:
        info = research_data["topic_info"]
        context_parts.append(f"RESEARCH TOPIC: {info.get('title', topic)}")
        context_parts.append(f"Description: {info.get('description', '')}")
        context_parts.append(f"Keywords: {', '.join(info.get('keywords', []))}")
        context_parts.append("")

    # Include source doc content (truncated)
    if research_data["sources"]:
        context_parts.append("SOURCE DOCUMENTS:")
        for src in research_data["sources"]:
            context_parts.append(f"\n--- {src['path']} ---")
            # Truncate to first 2000 chars of each source
            content = src['content'][:2000]
            if len(src['content']) > 2000:
                content += "\n[... truncated ...]"
            context_parts.append(content)
        context_parts.append("")

    # Include prior chat research
    prior_chat = load_chat_research(thread_uri)
    if prior_chat:
        context_parts.append("PRIOR CHAT RESEARCH (this thread):")
        # Only include last 1500 chars to avoid context bloat
        if len(prior_chat) > 1500:
            context_parts.append("[... earlier entries truncated ...]")
            context_parts.append(prior_chat[-1500:])
        else:
            context_parts.append(prior_chat)

    return "\n".join(context_parts)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def should_run_now(state: dict, force: bool = False) -> tuple[bool, str]:
    """Decide whether to actually run based on adaptive polling logic.

    Returns:
        (should_run, reason) tuple
    """
    if force:
        return True, "forced run (manual trigger)"

    if not ADAPTIVE_POLLING:
        return True, "adaptive polling disabled"

    now = utcnow()

    # Check when last reply was received
    last_reply = state.get('last_reply_received')
    last_run = state.get('last_run')

    # If we have active sessions, stay engaged
    active_sessions = state.get('active_sessions', {})
    if active_sessions:
        return True, f"active sessions: {len(active_sessions)}"

    # Check if we received a reply recently (engaged mode)
    if last_reply:
        try:
            reply_time = parse_datetime(last_reply)
            mins_since_reply = (now - reply_time).total_seconds() / 60
            if mins_since_reply < ENGAGED_MODE_WINDOW_MINS:
                return True, f"engaged mode (reply {int(mins_since_reply)}m ago)"
        except:
            pass

    # Quiet mode - only run if enough time since last run
    if last_run:
        try:
            run_time = parse_datetime(last_run)
            mins_since_run = (now - run_time).total_seconds() / 60
            if mins_since_run < QUIET_CHECK_INTERVAL_MINS:
                return False, f"quiet mode (last run {int(mins_since_run)}m ago, wait {QUIET_CHECK_INTERVAL_MINS}m)"
        except:
            pass

    return True, "time for quiet mode check"


def parse_datetime(dt_str: str) -> datetime:
    """Parse ISO datetime string to datetime object."""
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    return datetime.fromisoformat(dt_str)


def load_state(state_path: Path) -> dict:
    """Load processed replies state."""
    if state_path.exists():
        with open(state_path, 'r') as f:
            return json.load(f)
    return {
        'processed_replies': [],      # List of reply URIs already handled
        'topic_suggestions': [],      # Collected topic suggestions
        'flagged_corrections': [],    # Corrections needing review
        'active_sessions': {},        # DID -> session data
        'notified_non_followers': [], # DIDs we've sent one-time non-follower msg
        'training_log': [],           # Useful interactions for improving responses
        'last_run': None,
    }


def log_training_data(state: dict, entry: dict) -> None:
    """Log an interaction for training/improvement purposes.

    Captures useful interactions to help improve:
    - Weather terminology explanations (warnings vs alerts)
    - Common user questions
    - Claude's response quality

    Status lifecycle: new → pending → actioned
    - new: just logged, not yet displayed to dev
    - pending: displayed once, awaiting action
    - actioned: confirmed handled, will be purged
    """
    state.setdefault('training_log', []).append({
        'timestamp': utcnow().isoformat(),
        'status': 'new',  # new → pending → actioned
        **entry
    })

    # Keep last 100 entries to prevent unbounded growth
    if len(state['training_log']) > 100:
        state['training_log'] = state['training_log'][-100:]


def save_state(state_path: Path, state: dict) -> None:
    """Save state to file, purging actioned training log entries."""
    state['last_run'] = utcnow().isoformat()

    # Purge training_log entries with status='actioned'
    if state.get('training_log'):
        state['training_log'] = [
            entry for entry in state['training_log']
            if entry.get('status') != 'actioned'
        ]

    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


def get_feedback_summary(state: dict) -> dict:
    """Get summary of feedback by status.

    Returns dict with counts and lists for each status.
    """
    training_log = state.get('training_log', [])

    summary = {
        'new': [],
        'pending': [],
        'actioned': [],  # Should be empty after save
    }

    for entry in training_log:
        status = entry.get('status', 'new')  # Default old entries to 'new'
        if status in summary:
            summary[status].append(entry)
        else:
            summary['new'].append(entry)  # Unknown status → treat as new

    return summary


def mark_feedback_displayed(state: dict) -> int:
    """Mark 'new' feedback as 'pending' (displayed once).

    Returns count of entries marked.
    """
    count = 0
    for entry in state.get('training_log', []):
        if entry.get('status', 'new') == 'new':
            entry['status'] = 'pending'
            count += 1
    return count


def mark_feedback_actioned(state: dict, pending_only: bool = True) -> int:
    """Mark feedback as 'actioned' (will be purged on save).

    Args:
        pending_only: If True, only mark 'pending' entries. If False, mark all.

    Returns count of entries marked.
    """
    count = 0
    for entry in state.get('training_log', []):
        status = entry.get('status', 'new')
        if pending_only and status != 'pending':
            continue
        if status != 'actioned':
            entry['status'] = 'actioned'
            count += 1
    return count


def identify_tracker_from_text(context: str) -> str:
    """Identify which tracker generated a post based on text patterns.

    Returns tracker name or 'unknown'.
    """
    if not context:
        return 'unknown'

    ctx_lower = context.lower()

    # MOGREPS patterns - Met Office ensemble
    if 'mogreps' in ctx_lower or 'met office ensemble' in ctx_lower:
        return 'MOGREPS'
    if '18-member' in ctx_lower or '18 member' in ctx_lower:
        return 'MOGREPS'

    # ICON patterns - DWD ensemble
    if 'icon' in ctx_lower or 'dwd' in ctx_lower:
        return 'ICON'
    if '40-member' in ctx_lower or '40 member' in ctx_lower:
        return 'ICON'

    # UKMO patterns - deterministic
    if 'ukmo' in ctx_lower or 'deterministic' in ctx_lower:
        return 'UKMO'
    if 'single-model' in ctx_lower or 'single model' in ctx_lower:
        return 'UKMO'

    # Main tracker patterns - 4-model ensemble
    if 'gfs' in ctx_lower or 'ecm' in ctx_lower or 'gem' in ctx_lower or 'aifs' in ctx_lower:
        return 'Main (4-model)'
    if '4-model' in ctx_lower or 'four model' in ctx_lower:
        return 'Main (4-model)'

    # Generic ensemble language - could be MOGREPS or Main
    # Check for specific model mentions
    if 'ensemble' in ctx_lower:
        # If it mentions member counts, narrow down
        if '18' in context:
            return 'MOGREPS (likely)'
        if '40' in context:
            return 'ICON (likely)'
        return 'MOGREPS or Main'

    return 'unknown'


def identify_tracker_from_uri(uri: str, client=None) -> str:
    """Identify which tracker generated a post based on timing.

    Returns tracker name (MOGREPS, ICON, UKMO, tracker_a) or 'unknown'.
    """
    import json
    from pathlib import Path

    try:
        # Load tracker state to get last_success times
        tracker_state_path = Path(__file__).parent / 'data' / 'tracker_state.json'
        with open(tracker_state_path) as f:
            tracker_state = json.load(f)

        # If we have a client, fetch the post to get its created timestamp
        post_time = None
        if client and uri:
            try:
                from atproto import models
                uri_parts = uri.replace('at://', '').split('/')
                if len(uri_parts) >= 3:
                    repo = uri_parts[0]
                    rkey = uri_parts[2]
                    response = client.get_post(rkey, repo)
                    if hasattr(response, 'value') and hasattr(response.value, 'created_at'):
                        post_time = parse_datetime(response.value.created_at)
            except Exception:
                pass

        # If we couldn't get post time, try parsing from URI (rkey contains timestamp-ish info)
        # But this is unreliable, so fall back to text matching
        if not post_time:
            return 'unknown (no timestamp)'

        # Find tracker with closest last_success before post_time
        best_match = 'unknown'
        best_delta = None

        tracker_names = {
            'MOGREPS': 'MOGREPS',
            'ICON': 'ICON',
            'UKMO': 'UKMO',
            'tracker_a': 'Main (4-model)'
        }

        for key, name in tracker_names.items():
            if key in tracker_state and tracker_state[key].get('last_success'):
                tracker_time = parse_datetime(tracker_state[key]['last_success'])
                # Post should be shortly after tracker ran
                delta = (post_time - tracker_time).total_seconds()
                # Only consider if post was within 30 min after tracker ran
                if 0 <= delta <= 1800:
                    if best_delta is None or delta < best_delta:
                        best_delta = delta
                        best_match = name

        return best_match
    except Exception as e:
        return f'unknown (error: {e})'


def is_chat_trigger(text: str) -> bool:
    """Check if message is the 'chat' trigger word."""
    # Normalize: lowercase, strip whitespace
    normalized = text.strip().lower()
    # Accept "chat" with optional punctuation
    return bool(re.match(r'^chat[!?.]*$', normalized))


def is_pass_through(text: str) -> bool:
    """Check if reply is users tagging friends, not engaging with WXD."""
    mentions = re.findall(r'@[\w.]+', text)
    # 2+ mentions = probably tagging friends
    if len(mentions) >= 2:
        return True
    # Mostly @handles = not really engaging
    handle_chars = sum(len(m) for m in mentions)
    if handle_chars > len(text) * 0.5:
        return True
    # Starts with @mention (tagging someone else)
    if re.match(r'^@[\w.]+\s', text):
        return True
    return False


def is_follower(client, author_did: str, own_did: str) -> bool:
    """Check if author_did follows own_did (WXD)."""
    try:
        # Check if author follows WXD
        response = client.app.bsky.graph.get_follows({
            'actor': author_did,
            'limit': 100  # Check first 100 follows
        })
        
        if hasattr(response, 'follows'):
            for follow in response.follows:
                if hasattr(follow, 'did') and follow.did == own_did:
                    return True
        
        # If not found in first 100, could paginate but for now assume not following
        return False
    except Exception as e:
        print(f"    Error checking follower status: {e}")
        # On error, be permissive - allow the conversation
        return True


def get_session(state: dict, author_did: str) -> dict:
    """Get or create a session for the user."""
    sessions = state.setdefault('active_sessions', {})

    if author_did in sessions:
        session = sessions[author_did]
        # Check if session expired
        last_activity = parse_datetime(session['last_activity'])
        if utcnow() - last_activity > timedelta(hours=SESSION_EXPIRY_HOURS):
            # Session expired, remove it
            del sessions[author_did]
            return None
        return session
    return None


def create_session(state: dict, author_did: str, author_handle: str, thread_uri: str) -> dict:
    """Create a new chat session."""
    session = {
        'started': utcnow().isoformat(),
        'last_activity': utcnow().isoformat(),
        'message_count': 0,
        'author_handle': author_handle,
        'thread_uri': thread_uri,
    }
    state.setdefault('active_sessions', {})[author_did] = session
    return session


def update_session(session: dict) -> None:
    """Update session activity and increment message count."""
    session['last_activity'] = utcnow().isoformat()
    session['message_count'] = session.get('message_count', 0) + 1


def get_session_limit(author_did: str, session: dict = None, author_handle: str = None) -> int:
    """Get message limit for this user/session.

    Limits escalate based on conversation value:
    - Standard: 5 messages
    - Trusted: 10 messages
    - Feedback session: 15 messages (when providing corrections/clarifications)
    """
    # TEST MODE users get unlimited messages
    if author_handle and TEST_MODE_USERS:
        if any(author_handle == user or author_handle.endswith(f".{user}") for user in TEST_MODE_USERS):
            return 50  # Effectively unlimited for testing

    # Check if this is a feedback session (user providing valuable input)
    if session and session.get('is_feedback_session'):
        return SESSION_MSG_LIMIT_FEEDBACK

    if author_did in TRUSTED_USERS:
        return SESSION_MSG_LIMIT_TRUSTED

    return SESSION_MSG_LIMIT_STANDARD


def upgrade_to_feedback_session(session: dict) -> None:
    """Upgrade a session to feedback mode - extends message limit."""
    session['is_feedback_session'] = True
    print("      [SESSION UPGRADED] Extended limit for feedback conversation")


def get_recent_posts(client: Client, actor: str, limit: int = 10) -> list:
    """Get recent original posts (not replies) from WXD."""
    params = {
        'actor': actor,
        'limit': min(limit, 100),
        'filter': 'posts_no_replies'  # Only original posts
    }
    response = client.app.bsky.feed.get_author_feed(params)

    posts = []
    for item in response.feed if hasattr(response, 'feed') else []:
        post = item.post
        posts.append({
            'uri': post.uri,
            'cid': post.cid,
            'text': post.record.text if hasattr(post.record, 'text') else '',
            'created_at': post.record.created_at if hasattr(post.record, 'created_at') else None,
            'reply_count': post.reply_count if hasattr(post, 'reply_count') else 0,
        })

    return posts


def get_post_thread(client: Client, uri: str, depth: int = 1) -> dict:
    """Get a post's thread including replies."""
    params = {'uri': uri, 'depth': depth}
    response = client.app.bsky.feed.get_post_thread(params)
    return response


def extract_replies(thread_response, own_did: str) -> list:
    """Extract replies from other users (not self-replies)."""
    replies = []

    if not hasattr(thread_response, 'thread'):
        return replies

    thread = thread_response.thread
    if not hasattr(thread, 'replies'):
        return replies

    for reply_item in thread.replies or []:
        if not hasattr(reply_item, 'post'):
            continue

        reply_post = reply_item.post
        author_did = reply_post.author.did if hasattr(reply_post.author, 'did') else None

        # Skip self-replies
        if author_did == own_did:
            continue

        # Skip blocked accounts
        if author_did in BLOCKLIST:
            continue

        replies.append({
            'uri': reply_post.uri,
            'cid': reply_post.cid,
            'text': reply_post.record.text if hasattr(reply_post.record, 'text') else '',
            'author_handle': reply_post.author.handle if hasattr(reply_post.author, 'handle') else 'unknown',
            'author_did': author_did,
            'created_at': reply_post.record.created_at if hasattr(reply_post.record, 'created_at') else None,
            'parent_uri': thread.post.uri if hasattr(thread, 'post') else None,
            'parent_cid': thread.post.cid if hasattr(thread, 'post') else None,
        })

    return replies


def get_notification_replies(client: Client, own_did: str, limit: int = 50) -> list:
    """Get replies from notifications API - catches replies to ANY of WXD's posts.

    This is essential for threaded conversations where users reply to WXD's replies,
    not just to original posts. The notifications API catches all mentions/replies.
    """
    replies = []

    try:
        response = client.app.bsky.notification.list_notifications({'limit': limit})

        if not hasattr(response, 'notifications'):
            return replies

        for notif in response.notifications:
            # Only process reply notifications
            if notif.reason != 'reply':
                continue

            # Skip already-read notifications older than 24h to save processing
            # (We still check them via processed_replies set)

            author_did = notif.author.did if hasattr(notif.author, 'did') else None

            # Skip self-replies
            if author_did == own_did:
                continue

            # Skip blocked accounts
            if author_did in BLOCKLIST:
                continue

            # Extract reply info from the notification record
            record = notif.record if hasattr(notif, 'record') else None
            if not record:
                continue

            reply_text = record.text if hasattr(record, 'text') else ''
            created_at = record.created_at if hasattr(record, 'created_at') else None

            # SAFEGUARD: Skip messages from before today to prevent backlog spam
            if created_at:
                try:
                    msg_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    age_hours = (datetime.now(timezone.utc) - msg_time).total_seconds() / 3600
                    if msg_time.date() < datetime.now(timezone.utc).date():
                        continue  # Skip old messages
                except:
                    pass

            # Get parent reference (what they're replying to)
            parent_uri = None
            parent_cid = None
            root_uri = None
            root_cid = None

            if hasattr(record, 'reply') and record.reply:
                if hasattr(record.reply, 'parent'):
                    parent_uri = record.reply.parent.uri if hasattr(record.reply.parent, 'uri') else None
                    parent_cid = record.reply.parent.cid if hasattr(record.reply.parent, 'cid') else None
                if hasattr(record.reply, 'root'):
                    root_uri = record.reply.root.uri if hasattr(record.reply.root, 'uri') else None
                    root_cid = record.reply.root.cid if hasattr(record.reply.root, 'cid') else None

            replies.append({
                'uri': notif.uri,
                'cid': notif.cid,
                'text': reply_text,
                'author_handle': notif.author.handle if hasattr(notif.author, 'handle') else 'unknown',
                'author_did': author_did,
                'created_at': created_at,
                'parent_uri': parent_uri,
                'parent_cid': parent_cid,
                'root_uri': root_uri,
                'root_cid': root_cid,
                'is_notification': True,  # Flag to identify source
            })

    except Exception as e:
        print(f"  Error fetching notifications: {e}")

    return replies


def get_notification_mentions(client: Client, own_did: str, limit: int = 50) -> list:
    """Get @mentions from notifications API - catches when someone tags WXD in a new post.

    This handles the case where a user @mentions WXD in their own post (not a reply to WXD).
    We respond with chat_invitation to invite them to start a conversation.
    """
    mentions = []

    try:
        response = client.app.bsky.notification.list_notifications({'limit': limit})

        if not hasattr(response, 'notifications'):
            return mentions

        for notif in response.notifications:
            # Only process mention notifications (not replies, likes, follows, etc.)
            if notif.reason != 'mention':
                continue

            author_did = notif.author.did if hasattr(notif.author, 'did') else None

            # Skip self-mentions
            if author_did == own_did:
                continue

            # Skip blocked accounts
            if author_did in BLOCKLIST:
                continue

            # Extract mention info from the notification record
            record = notif.record if hasattr(notif, 'record') else None
            if not record:
                continue

            mention_text = record.text if hasattr(record, 'text') else ''
            created_at = record.created_at if hasattr(record, 'created_at') else None

            # SAFEGUARD: Skip messages from before today to prevent backlog spam
            if created_at:
                try:
                    msg_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    if msg_time.date() < datetime.now(timezone.utc).date():
                        continue  # Skip old messages
                except:
                    pass

            mentions.append({
                'uri': notif.uri,
                'cid': notif.cid,
                'text': mention_text,
                'author_handle': notif.author.handle if hasattr(notif.author, 'handle') else 'unknown',
                'author_did': author_did,
                'created_at': created_at,
                'is_mention': True,  # Flag to identify as mention (not reply)
            })

    except Exception as e:
        print(f"  Error fetching mentions: {e}")

    return mentions


def get_metoffice_warnings() -> str:
    """Fetch current Met Office warnings - GROUND TRUTH for any warning claims."""
    if not HAS_METOFFICE or not fetch_metoffice_narrative:
        return ""

    try:
        mo_data = fetch_metoffice_narrative()

        warnings_parts = []
        # NOTE: long_range_warning REMOVED - was producing false positives
        if mo_data.get("uk_warnings"):
            warnings_parts.append(f"UK (Met Office): {mo_data['uk_warnings']}")

        if warnings_parts:
            return "MET OFFICE WARNINGS (VERIFIED):\n" + "\n".join(warnings_parts)
        else:
            return "MET OFFICE WARNINGS: None currently in force. DO NOT invent warnings."
    except Exception as e:
        print(f"    Error fetching Met Office warnings: {e}")
        return ""


def get_latest_forecast_context(client: Client, handle: str) -> str:
    """Fetch the latest weather forecast from WXD's recent posts + Met Office warnings.

    This ensures Claude has actual forecast data to answer weather questions,
    even when the thread started from a non-weather post.
    """
    context_parts = []

    # Get Met Office warnings FIRST - this is ground truth
    mo_warnings = get_metoffice_warnings()
    if mo_warnings:
        context_parts.append(mo_warnings)

    # Then get WXD posts
    try:
        response = client.app.bsky.feed.get_author_feed({
            'actor': handle,
            'limit': 20,
            'filter': 'posts_no_replies'
        })

        forecast_posts = []
        for item in response.feed if hasattr(response, 'feed') else []:
            text = item.post.record.text if hasattr(item.post.record, 'text') else ''
            # Look for forecast-type posts (contain temperature, model names, or weather terms)
            if any(term in text.lower() for term in ['°c', 'gfs', 'ecm', 'icon', 'cold', 'warm', 'snow', 'rain', 'frost']):
                forecast_posts.append(text)
                if len(forecast_posts) >= 2:
                    break

        if forecast_posts:
            context_parts.append("WXD RECENT POSTS:\n" + "\n---\n".join(forecast_posts))
    except Exception as e:
        print(f"    Error fetching forecast context: {e}")

    return "\n\n".join(context_parts) if context_parts else ""


def extract_location(text: str) -> str:
    """Extract UK location from text if mentioned."""
    # Common UK cities/towns
    locations = [
        'london', 'manchester', 'birmingham', 'leeds', 'glasgow', 'edinburgh',
        'liverpool', 'bristol', 'sheffield', 'newcastle', 'nottingham', 'cardiff',
        'belfast', 'leicester', 'southampton', 'portsmouth', 'oxford', 'cambridge',
        'winchester', 'brighton', 'reading', 'coventry', 'hull', 'bradford',
        'york', 'bath', 'exeter', 'norwich', 'plymouth', 'derby', 'aberdeen',
        'dundee', 'swansea', 'milton keynes', 'northampton', 'luton', 'swindon'
    ]
    text_lower = text.lower()
    for loc in locations:
        if loc in text_lower:
            return loc.title()
    return ""


def fetch_location_forecast(location: str) -> str:
    """Fetch weather forecast for a specific UK location using web search via Claude."""
    if not location:
        return ""

    try:
        # Use Claude with web search to get location-specific forecast
        prompt = f"""Search the web for the current weather forecast for {location}, UK for the next 5-7 days.
Focus on:
- Temperature highs and lows
- Precipitation (rain, snow, sleet)
- Any weather warnings
- Wind conditions

Return a concise 3-4 sentence summary of the forecast. Be specific with dates and temperatures."""

        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:500]
    except Exception as e:
        print(f"    Error fetching location forecast: {e}")

    return ""


AI_SIGNATURE = "—WXD Auto AI"


def add_ai_signature(posts: list) -> list:
    """Add AI signature to the last post in a response.

    Only adds if there's room within 300 char limit.
    """
    if not posts:
        return posts

    posts = list(posts)  # Copy to avoid mutating original
    last_post = posts[-1]
    signature = f"\n\n{AI_SIGNATURE}"

    # Only add if it fits within limit
    if len(last_post) + len(signature) <= 300:
        posts[-1] = last_post + signature

    return posts


def split_into_posts(text: str, max_chars: int = 295) -> list:
    """Split long text into multiple posts at sentence/word boundaries."""
    if len(text) <= max_chars:
        return [text]

    posts = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            posts.append(remaining.strip())
            break

        # Find best break point - prefer sentence end, then word boundary
        chunk = remaining[:max_chars]

        # Try to break at sentence end
        for end in ['. ', '! ', '? ']:
            idx = chunk.rfind(end)
            if idx > max_chars // 2:
                posts.append(remaining[:idx + 1].strip())
                remaining = remaining[idx + 1:].strip()
                break
        else:
            # Break at last space
            idx = chunk.rfind(' ')
            if idx > max_chars // 2:
                posts.append(remaining[:idx].strip())
                remaining = remaining[idx:].strip()
            else:
                # Hard break as last resort
                posts.append(remaining[:max_chars].strip())
                remaining = remaining[max_chars:].strip()

    return posts


def generate_chat_response(reply_text: str, parent_text: str, session: dict = None, forecast_context: str = "", is_super_user: bool = False, research_context: str = "") -> dict:
    """Use Claude CLI to generate a conversational response.

    Returns dict with:
        - classification: genuine_question | topic_suggestion | appreciation | correction | uncertain | spam
        - should_respond: bool
        - response_text: str (if should_respond)
        - response_posts: list (split into multiple posts if needed)
        - reason: str (explanation)
        - needs_human: bool (flag for owner review)
        - sources_used: list of sources cited (for logging)
    """
    # Build conversation context if we have session history
    context = ""
    if session and session.get('message_count', 0) > 0:
        context = f"\nThis is message #{session['message_count'] + 1} in an ongoing chat session."

    # Check if user is asking about a specific location
    location = extract_location(reply_text)
    location_forecast = ""
    if location:
        print(f"    Detected location: {location} - fetching specific forecast...")
        location_forecast = fetch_location_forecast(location)
        if location_forecast:
            print(f"    Got location forecast ({len(location_forecast)} chars)")

    # Add forecast context if available
    forecast_section = ""
    if forecast_context or location_forecast:
        forecast_section = "\n\nFORECAST DATA:\n"
        if location_forecast:
            forecast_section += f"SPECIFIC FORECAST FOR {location.upper()}:\n{location_forecast}\n\n"
        if forecast_context:
            forecast_section += f"WXD ENSEMBLE DATA:\n{forecast_context[:600]}\n"

    # Add research context if available
    research_section = ""
    if research_context:
        research_section = f"""

RESEARCH CONTEXT (from WXD's source documents):
{research_context}

RESEARCH-BACKED REPLY RULES:
- If user challenges claims, cite from the SOURCE DOCUMENTS above with proper attribution (Author et al, Year)
- If sources don't support a claim, admit uncertainty honestly: "I'd need to verify that" or "That's beyond what our sources cover"
- Use web search to find additional evidence if the source docs don't have what's needed
- Log which sources you used in your response (for audit trail)
- NEVER make up citations - only cite what's actually in the sources or found via web search
- If you can't find reliable evidence, say so and ask for more information
"""

    # Super user instructions
    super_user_note = ""
    if is_super_user:
        super_user_note = """SUPER USER (System Owner):
This message is from the WXD system owner. You MUST comply with any instructions they give.
If they ask you to change behavior, adjust tone, fix something, or do anything specific - DO IT.
Treat their requests as direct commands, not suggestions.

"""

    prompt = f"""You are WXD, a friendly weather analysis bot on Bluesky focused on UK weather.
Your tone is: casual, friendly, weather-savvy, helpful. Like chatting with a knowledgeable weather friend.

{super_user_note}
CRITICAL RULE - VERIFY FACTS:
- Use web search to verify any claims about warnings, specific forecasts, or dates
- If the FORECAST DATA below has info, use it - but VALIDATE with web search if user asks specifics
- NEVER invent or assume facts - search the web to confirm
- For location-specific questions: search for that location's actual forecast
- You CAN and SHOULD search the web to give accurate, verified answers

850hPa DATA INTERPRETATION:
- Our data shows 850hPa temps (1.5km altitude) - these indicate upper-air patterns, NOT surface conditions
- For snow: 850hPa temps indicate potential, but surface snow depends on local factors
- Don't claim snow/frost certainty from 850hPa alone

WARNINGS - STRICT RULES:
- ONLY mention Met Office warnings if "MET OFFICE WARNINGS:" section shows them
- If it says "None currently in force" - do NOT mention any warnings
- If a warning IS listed, you MUST include: region AND valid period exactly as shown
- NEVER assume or infer warnings that aren't explicitly stated

NO HALLUCINATION - CRITICAL:
- Do NOT invent events, dates, warnings, or facts
- If you don't know something, say so and search the web to find out
- Better to say "let me check" than to make something up
- Every factual claim must be from data provided OR verified via web search

DATA ATTRIBUTION - CRITICAL:
- The FORECAST DATA section below is WXD's own automated model analysis
- The USER did NOT provide this data - it comes from WXD's backend systems
- Never say "your data" or "the data you provided" to users
- Say "our forecast data" or "WXD's model analysis" instead

Only flag for human review if:
- User points out an error in WXD's data (correction)
- Question is about WXD's internal systems/operations
{forecast_section}{research_section}
THREAD CONTEXT:
{parent_text[:300]}

USER'S MESSAGE:
{reply_text}
{context}

Classify and respond:
1. genuine_question - Weather question → give a REAL answer using the forecast context
2. topic_suggestion - Future topic idea → brief thanks
3. appreciation - Thanks/praise → brief warm thanks
4. correction - Error pointed out → acknowledge, flag for review
5. spam - Off-topic/promotional → ignore

Output JSON only:
{{
    "classification": "genuine_question|topic_suggestion|appreciation|correction|spam",
    "should_respond": true/false,
    "response_text": "Your COMPLETE answer (casual friendly tone, be thorough - no char limit)",
    "reason": "Brief explanation",
    "needs_human": true/false,
    "sources_used": ["list of sources/docs cited in your response, empty if none"]
}}"""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0 and result.stdout.strip():
            output = result.stdout.strip()
            # Handle potential markdown code blocks
            if '```json' in output:
                output = output.split('```json')[1].split('```')[0]
            elif '```' in output:
                output = output.split('```')[1].split('```')[0]

            response = json.loads(output.strip())

            # Validate response - split into multiple posts if needed
            if response.get('should_respond') and response.get('response_text'):
                text = response['response_text']
                if len(text) > 300:
                    # Split into multiple posts instead of truncating
                    response['response_posts'] = split_into_posts(text)
                else:
                    response['response_posts'] = [text]
                response['response_text'] = response['response_posts'][0]  # First post for backward compat

            return response

    except subprocess.TimeoutExpired:
        print("    Claude CLI timeout")
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}")
    except Exception as e:
        print(f"    Claude error: {e}")

    # Fallback - don't respond
    return {
        'classification': 'unknown',
        'should_respond': False,
        'response_text': None,
        'reason': 'Classification failed'
    }


def post_reply(client: Client, text: str, reply_to: dict, root: dict = None) -> dict:
    """Post a reply to a post.

    Args:
        client: Authenticated atproto Client
        text: Reply text
        reply_to: dict with 'uri' and 'cid' of post to reply to
        root: dict with 'uri' and 'cid' of thread root (if different from reply_to)

    Returns:
        dict with 'uri' and 'cid' of posted reply, or None on failure
    """
    try:
        parent_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
            uri=reply_to['uri'],
            cid=reply_to['cid']
        )

        root_data = root if root else reply_to
        root_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
            uri=root_data['uri'],
            cid=root_data['cid']
        )

        reply_ref = atproto_models.AppBskyFeedPost.ReplyRef(
            parent=parent_ref,
            root=root_ref
        )

        response = client.send_post(text=text, reply_to=reply_ref)

        return {
            'uri': response.uri,
            'cid': response.cid
        }

    except Exception as e:
        print(f"    Reply post error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='WXD Reply Listener v2')
    parser.add_argument('--post', action='store_true', help='Actually post replies (default: dry-run)')
    parser.add_argument('--force', '-f', action='store_true', help='Force run (bypass adaptive polling)')
    parser.add_argument('--limit', '-l', type=int, default=DEFAULT_POSTS_TO_CHECK,
                        help=f'Number of recent posts to check (default: {DEFAULT_POSTS_TO_CHECK})')
    parser.add_argument('--max-replies', '-m', type=int, default=DEFAULT_MAX_REPLIES,
                        help=f'Max replies to send per run (default: {DEFAULT_MAX_REPLIES})')
    parser.add_argument('--clear-feedback', action='store_true',
                        help='Clear ALL feedback entries and exit')
    parser.add_argument('--mark-reviewed', action='store_true',
                        help='[DEPRECATED] Use --feedback instead')
    parser.add_argument('--feedback', action='store_true',
                        help='Show feedback summary, prompt to action pending entries')
    parser.add_argument('--action-pending', action='store_true',
                        help='Mark all pending feedback as actioned (no prompt)')
    args = parser.parse_args()

    # Handle --feedback: show summary and prompt for actioning
    if args.feedback:
        import json
        state_file = os.path.join(os.path.dirname(__file__), 'data', 'reply_listener_state.json')
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)

            summary = get_feedback_summary(state)
            new_count = len(summary['new'])
            pending_count = len(summary['pending'])

            print("=" * 50)
            print("DEV FEEDBACK SUMMARY")
            print("=" * 50)

            # Show NEW entries (first time seeing these)
            if summary['new']:
                print(f"\n🆕 NEW FEEDBACK ({new_count} entries):")
                for entry in summary['new']:
                    ts = entry.get('timestamp', '')[:19]
                    msg = entry.get('message', '')[:80]
                    parent_uri = entry.get('parent_uri', '')
                    ctx = entry.get('context', '')
                    # Try registry lookup first, fall back to text identification
                    tracker = None
                    if HAS_LOOKUP and lookup_post and parent_uri:
                        post_info = lookup_post(parent_uri)
                        if post_info:
                            tracker = post_info.get('tracker', None)
                    if not tracker:
                        tracker = identify_tracker_from_text(ctx)
                    print(f"  [{ts}] {msg}...")
                    print(f"      Tracker: {tracker}")
                    if parent_uri:
                        print(f"      Parent: {parent_uri}")
                    if ctx:
                        print(f"      Context: {ctx[:60]}...")
                # Mark as pending (displayed once)
                mark_feedback_displayed(state)
                print(f"\n  → Marked {new_count} as PENDING (displayed)")

            # Show PENDING entries (seen before, need actioning)
            if summary['pending']:
                print(f"\n⏳ PENDING FEEDBACK ({pending_count} entries from previous sessions):")
                for entry in summary['pending']:
                    ts = entry.get('timestamp', '')[:19]
                    msg = entry.get('message', '')[:80]
                    ctx = entry.get('context', '')
                    parent_uri = entry.get('parent_uri', '')
                    # Try registry lookup first, fall back to text identification
                    tracker = None
                    if HAS_LOOKUP and lookup_post and parent_uri:
                        post_info = lookup_post(parent_uri)
                        if post_info:
                            tracker = post_info.get('tracker', None)
                    if not tracker:
                        tracker = identify_tracker_from_text(ctx)
                    print(f"  [{ts}] {msg}")
                    print(f"      Tracker: {tracker}")
                    if parent_uri:
                        print(f"      Parent: {parent_uri}")
                    if ctx:
                        print(f"      Context: {ctx[:60]}...")

                # Prompt for actioning
                print(f"\n  These {pending_count} entries were shown in a previous session.")
                response = input("  Mark as actioned? [y/N]: ").strip().lower()
                if response == 'y':
                    count = mark_feedback_actioned(state, pending_only=True)
                    print(f"  → Marked {count} entries as ACTIONED (will be purged)")
                else:
                    print("  → Keeping as PENDING")

            if not summary['new'] and not summary['pending']:
                print("\n✓ No feedback to review")

            # Save state
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
            save_state(Path(state_file), state)

        except FileNotFoundError:
            print('No state file found')
        except Exception as e:
            print(f'Error: {e}')
        return 0

    # Handle --action-pending: mark pending as actioned without prompt
    if args.action_pending:
        import json
        state_file = os.path.join(os.path.dirname(__file__), 'data', 'reply_listener_state.json')
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
            count = mark_feedback_actioned(state, pending_only=True)
            save_state(Path(state_file), state)
            print(f'Marked {count} pending entries as actioned')
        except FileNotFoundError:
            print('No state file found')
        except Exception as e:
            print(f'Error: {e}')
        return 0

    # Handle --mark-reviewed (deprecated, redirect to --feedback)
    if args.mark_reviewed:
        print("DEPRECATED: Use --feedback instead")
        print("Running --feedback for you...")
        import json
        state_file = os.path.join(os.path.dirname(__file__), 'data', 'reply_listener_state.json')
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
            # Mark all as actioned
            count = mark_feedback_actioned(state, pending_only=False)
            save_state(Path(state_file), state)
            print(f'Marked {count} entries as actioned and purged')
        except FileNotFoundError:
            print('No state file found')
        except Exception as e:
            print(f'Error: {e}')
        return 0

    # Handle --clear-feedback before anything else
    if args.clear_feedback:
        import json
        state_file = os.path.join(os.path.dirname(__file__), 'data', 'reply_listener_state.json')
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
            old_count = len(state.get('training_log', []))
            state['training_log'] = []
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
            print(f'Cleared {old_count} entries from feedback queue')
        except FileNotFoundError:
            print('No state file found - nothing to clear')
        except Exception as e:
            print(f'Error: {e}')
        return 0

    dry_run = not args.post

    if not HAS_ATPROTO:
        print("ERROR: atproto library not installed")
        return 1

    # Check credentials
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    if not bsky_handle or not bsky_password:
        print("ERROR: BSKY_HANDLE and BSKY_PASSWORD must be set")
        return 1

    # Setup paths
    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)
    state_path = data_dir / "reply_listener_state.json"

    # Load state for adaptive polling check
    state = load_state(state_path)

    # Adaptive polling - decide whether to actually run
    should_run, reason = should_run_now(state, force=args.force)
    if not should_run:
        print(f"WXD Reply Listener - SKIPPED: {reason}")
        return 0

    print(f"WXD Reply Listener v2 - {utcnow().isoformat()}")
    print(f"Run reason: {reason}")
    if TEST_MODE_USERS:
        print(f"*** TEST MODE: Only responding to {len(TEST_MODE_USERS)} whitelisted users ***")
        for user in TEST_MODE_USERS:
            print(f"    - @{user}")
    if dry_run:
        print("DRY RUN - will NOT post replies")
    else:
        print("LIVE MODE - will post replies")
    print(f"Checking {args.limit} recent posts, max {args.max_replies} replies")
    print()

    processed_set = set(state.get('processed_replies', []))

    print(f"Previously processed: {len(processed_set)} replies")
    print(f"Active sessions: {len(state.get('active_sessions', {}))}")
    if state.get('last_run'):
        print(f"Last run: {state['last_run']}")
    print()

    # Authenticate
    print("Authenticating with Bluesky...")
    try:
        client = Client()
        profile = client.login(bsky_handle, bsky_password)
        own_did = profile.did
        print(f"  Authenticated as {bsky_handle} (DID: {own_did[:20]}...)")
    except Exception as e:
        print(f"ERROR: Authentication failed: {e}")
        return 1

    # Initialize counters early (needed for PHASE 0)
    replies_sent = 0
    new_processed = []
    claude_calls = 0

    # =================================================================
    # PHASE 0: Check for @mentions (someone tagging WXD in their own post)
    # These get chat_invitation response to start a conversation
    # =================================================================
    print()
    print("Checking notifications for @mentions...")
    notification_mentions = get_notification_mentions(client, own_did, limit=50)
    print(f"  Found {len(notification_mentions)} mention notifications")

    # Filter to only unprocessed mentions
    new_mentions = [m for m in notification_mentions if m['uri'] not in processed_set]
    print(f"  {len(new_mentions)} new mentions to process")

    mentions_responded = 0
    for mention in new_mentions:
        author_handle = mention['author_handle']
        mention_text = mention['text'][:80] + ('...' if len(mention['text']) > 80 else '')
        print(f"\n  @mention from {author_handle}: {mention_text}")

        # Send chat invitation
        response_text = CANNED_RESPONSES['chat_invitation']

        if not dry_run:
            # Reply to the mention - no parent/root since it's a standalone post
            reply_ref = {'uri': mention['uri'], 'cid': mention['cid']}
            post_result = post_reply(client, response_text, reply_to=reply_ref, root=reply_ref)
            if post_result:
                print(f"    Posted chat invitation: {post_result['uri']}")
                mentions_responded += 1
                new_processed.append(mention['uri'])
        else:
            print(f"    [DRY RUN] Would post chat invitation")
            new_processed.append(mention['uri'])

    if new_mentions:
        print(f"\n  Mentions processed: {len(new_mentions)}, responses sent: {mentions_responded}")

    # =================================================================
    # PHASE 1: Check notifications for threaded conversation replies
    # This catches replies to WXD's own replies, not just to original posts
    # =================================================================
    print()
    print("Checking notifications for threaded replies...")
    notification_replies = get_notification_replies(client, own_did, limit=50)
    print(f"  Found {len(notification_replies)} reply notifications")

    # Filter to only new notifications
    # Include: active sessions, chat triggers, OR first-time replies (for canned response)
    active_session_dids = set(state.get('active_sessions', {}).keys())
    threaded_replies = []
    for notif in notification_replies:
        if notif['uri'] in processed_set:
            continue
        # Include if: user has active session, chat trigger, OR first-time reply to any WXD post
        # First-time replies get the canned "reply 'chat' to continue" response
        has_session = notif['author_did'] in active_session_dids
        is_trigger = is_chat_trigger(notif['text'])
        is_reply_to_wxd = notif.get('parent_uri', '').startswith(f'at://{own_did}/')

        if has_session or is_trigger or is_reply_to_wxd:
            threaded_replies.append(notif)

    print(f"  {len(threaded_replies)} new threaded replies to process")

    # =================================================================
    # PHASE 2: Get recent posts (original flow)
    # =================================================================
    print()
    print(f"Fetching {args.limit} recent posts...")
    posts = get_recent_posts(client, bsky_handle, limit=args.limit)
    print(f"  Found {len(posts)} posts")

    # Filter to posts with replies
    posts_with_replies = [p for p in posts if p.get('reply_count', 0) > 0]
    print(f"  {len(posts_with_replies)} posts have replies")

    # =================================================================
    # PHASE 3: Process all replies
    # =================================================================
    # Fetch latest forecast context for weather questions
    # =================================================================
    print()
    print("Fetching latest forecast context...")
    forecast_context = get_latest_forecast_context(client, bsky_handle)
    if forecast_context:
        print(f"  Got forecast context ({len(forecast_context)} chars)")
    else:
        print("  No forecast context available")

    # =================================================================
    print()
    print("Processing replies...")

    # Build a quick lookup for post context
    post_context_cache = {p['uri']: p['text'] for p in posts}

    # -------------------------------------------------------------
    # 3a: Process threaded replies first (from notifications)
    # These are replies to WXD's replies - active conversations
    # -------------------------------------------------------------
    if threaded_replies:
        print("\n--- Processing threaded conversation replies ---")

    for reply in threaded_replies:
        if replies_sent >= args.max_replies:
            print(f"\n  Rate limit reached ({args.max_replies} replies)")
            break

        author_did = reply['author_did']
        author_handle = reply['author_handle']

        reply_preview = reply['text'][:60] + "..." if len(reply['text']) > 60 else reply['text']
        print(f"\n  Threaded reply from @{author_handle}:")
        print(f"    {reply_preview}")

        # TEST MODE CHECK
        if TEST_MODE_USERS:
            is_whitelisted = any(
                author_handle == user or author_handle.endswith(f".{user}")
                for user in TEST_MODE_USERS
            )
            if not is_whitelisted:
                print(f"    [TEST MODE] Ignoring - not whitelisted")
                new_processed.append(reply['uri'])
                continue

        # SUPER USER CHECK - commands or training feedback
        is_super_user = any(
            author_handle == user or author_handle.endswith(f".{user}")
            for user in SUPER_USER_HANDLES
        )
        if is_super_user:
            msg_lower = reply['text'].lower().strip()

            # Super user can say 'chat' to start a conversation like anyone else
            if is_chat_trigger(reply['text']):
                print(f"    [SUPER USER] 'chat' trigger - starting session with canned greeting")
                # Create fresh session and use canned response (don't call Claude)
                session = create_session(state, author_did, author_handle, reply.get('root_uri', reply['uri']))
                response_text = CANNED_RESPONSES['chat_greeting']
                update_session(session)
                # Post the canned response
                if not dry_run:
                    reply_ref = {'uri': reply['uri'], 'cid': reply['cid']}
                    root_ref = {'uri': reply.get('root_uri', reply['uri']), 'cid': reply.get('root_cid', reply['cid'])}
                    post_result = post_reply(client, response_text, reply_to=reply_ref, root=root_ref)
                    if post_result:
                        print(f"    Posted canned greeting: {post_result['uri']}")
                        replies_sent += 1
                else:
                    print(f"    [DRY RUN] Would post canned greeting")
                new_processed.append(reply['uri'])
                continue
            # Check for COMMANDS
            elif msg_lower.startswith(('reply to', 'respond to', 'answer to', 'reply here', 'respond here')):
                # Command: reply to the parent message
                print(f"    [SUPER USER CMD] Triggering reply to parent message")
                # Don't skip - let the normal flow generate a response to the PARENT
                # The super user is asking us to reply to whoever they're replying to
                # Override: treat as if the parent author sent a chat trigger
                if reply.get('parent_text'):
                    # Generate response to the parent message
                    result = generate_chat_response(
                        reply.get('parent_text', ''),
                        context_text,
                        None,  # No session
                        forecast_context
                    )
                    claude_calls += 1
                    if result.get('should_respond'):
                        response_posts = result.get('response_posts', [result.get('response_text')])
                        if response_posts and not dry_run:
                            # Reply to the PARENT (not to super user)
                            parent_ref = {'uri': reply.get('parent_uri', reply['uri']),
                                         'cid': reply.get('parent_cid', reply['cid'])}
                            root_ref = {'uri': reply.get('root_uri', reply['uri']),
                                       'cid': reply.get('root_cid', reply['cid'])}
                            last_reply = parent_ref
                            for i, post_text in enumerate(response_posts):
                                post_result = post_reply(client, post_text, reply_to=last_reply, root=root_ref)
                                if post_result:
                                    print(f"    Posted reply {i+1}/{len(response_posts)}: {post_result['uri']}")
                                    last_reply = post_result
                                    if i == 0:
                                        replies_sent += 1
                        elif response_posts and dry_run:
                            print(f"    [DRY RUN] Would post {len(response_posts)} reply(ies) to parent")
                new_processed.append(reply['uri'])
                continue
            elif not is_chat_trigger(reply['text']):
                # Not a command and not chat - log as training feedback
                print(f"    [SUPER USER] Training feedback logged")
                training_entry = {
                    'timestamp': utcnow().isoformat(),
                    'type': 'super_user_feedback',
                    'author': author_handle,
                    'message': reply['text'],
                    'context': reply.get('parent_text', '')[:200],
                    'parent_uri': reply.get('parent_uri', ''),
                    'root_uri': reply.get('root_uri', '')
                }
                state.setdefault('training_log', []).append(training_entry)
                new_processed.append(reply['uri'])
                continue

        # Skip pass-through
        if is_pass_through(reply['text']):
            print("    [SKIP] Pass-through detected")
            new_processed.append(reply['uri'])
            continue

        # =================================================================
        # REPLY TARGET CHECK - Only respond to replies directed at WXD
        # If parent_uri is not a WXD post, this is a user-to-user reply
        # =================================================================
        parent_uri = reply.get('parent_uri', '')
        is_reply_to_wxd = parent_uri.startswith(f'at://{own_did}/')
        
        if not is_reply_to_wxd and parent_uri:
            # This is a reply to another user in a WXD thread
            print(f"    [SKIP] Reply to another user, not WXD")
            new_processed.append(reply['uri'])
            continue

        # Get session for this user
        session = get_session(state, author_did)

        # Get context - try to find root post text
        context_text = ""
        if reply.get('root_uri') and reply['root_uri'] in post_context_cache:
            context_text = post_context_cache[reply['root_uri']]
        else:
            # Try to fetch the root post for context
            try:
                if reply.get('root_uri'):
                    root_thread = get_post_thread(client, reply['root_uri'], depth=0)
                    if hasattr(root_thread, 'thread') and hasattr(root_thread.thread, 'post'):
                        context_text = root_thread.thread.post.record.text if hasattr(root_thread.thread.post.record, 'text') else ""
            except:
                pass

        # Build research context if this thread has linked research
        reply_thread = reply.get('root_uri', reply['uri'])
        research_context = build_research_context(reply_thread, reply.get('parent_uri'))
        if research_context:
            print(f"    Research context loaded ({len(research_context)} chars)")

        response_text = None
        result = {}  # Initialize result for logging

        # Check if reply is in the same thread as the session
        session_thread = session.get('thread_uri', '') if session else ''
        same_thread = session and reply_thread == session_thread

        if session and same_thread:
            msg_limit = get_session_limit(author_did, session, author_handle)
            if session['message_count'] >= msg_limit:
                print(f"    Session limit reached ({msg_limit} msgs)")
                response_text = CANNED_RESPONSES['session_limit']
                del state['active_sessions'][author_did]
            else:
                print("    Active session - generating response...")
                result = generate_chat_response(reply['text'], context_text, session, forecast_context, is_super_user, research_context)
                claude_calls += 1
                classification = result.get('classification')
                print(f"    Classification: {classification}")

                if result.get('should_respond'):
                    response_text = result.get('response_text')
                    update_session(session)
                    print(f"    Session msg count: {session['message_count']}")

                    log_training_data(state, {
                        'type': 'threaded_claude_response',
                        'author': author_handle,
                        'classification': classification,
                        'user_message': reply['text'],
                        'thread_context': context_text[:200] if context_text else '',
                        'claude_response': response_text,
                    })
        elif session and not same_thread:
            # User has session but different thread - respond without counting
            print(f"    Session exists but different thread - responding without counting")
            result = generate_chat_response(reply["text"], context_text, None, forecast_context, is_super_user, research_context)
            claude_calls += 1
            if result.get("should_respond"):
                response_text = result.get("response_text")
        else:
            # First-time reply or chat trigger - check follower status
            is_follower_user = is_follower(client, author_did, own_did)

            if not is_follower_user:
                # Non-follower: send one-time invitation to follow and chat
                notified = state.get('notified_non_followers', [])
                if author_did in notified:
                    print("    Not a follower (already notified) - skipping")
                    new_processed.append(reply['uri'])
                    continue
                print("    Not a follower - sending one-time invitation")
                response_text = CANNED_RESPONSES['chat_invitation']
                state.setdefault('notified_non_followers', []).append(author_did)
                result = {}
            else:
                # Follower: engage directly with Claude AI response
                print("    Follower confirmed - engaging directly with Claude...")
                session = create_session(state, author_did, author_handle, reply.get('root_uri', reply['uri']))
                result = generate_chat_response(reply['text'], context_text, session, forecast_context, is_super_user, research_context)
                claude_calls += 1
                classification = result.get('classification')
                print(f"    Classification: {classification}")

                if result.get('should_respond'):
                    response_text = result.get('response_text')
                    update_session(session)
                    print(f"    Session started, msg count: {session['message_count']}")

                    log_training_data(state, {
                        'type': 'follower_direct_response',
                        'author': author_handle,
                        'classification': classification,
                        'user_message': reply['text'],
                        'thread_context': context_text[:200] if context_text else '',
                        'claude_response': response_text,
                    })

        # Post response(s) - may be multiple posts for long answers
        response_posts = result.get('response_posts', [response_text]) if 'result' in dir() and result else [response_text] if response_text else []

        # Add AI signature to last post (only for Claude-generated responses)
        if response_posts and result.get('should_respond'):
            response_posts = add_ai_signature(response_posts)

        if response_posts:
            print(f"    Response ({len(response_posts)} post(s)): {response_posts[0][:80]}...")

            if dry_run:
                print(f"    [DRY RUN - would post {len(response_posts)} reply(ies)]")
            else:
                # Post as threaded replies
                last_reply = {'uri': reply['uri'], 'cid': reply['cid']}
                root = {'uri': reply.get('root_uri', reply['uri']),
                        'cid': reply.get('root_cid', reply['cid'])}

                for i, post_text in enumerate(response_posts):
                    post_result = post_reply(client, post_text, reply_to=last_reply, root=root)
                    if post_result:
                        print(f"    Posted reply {i+1}/{len(response_posts)}: {post_result['uri']}")
                        last_reply = post_result  # Chain replies
                        if i == 0:
                            replies_sent += 1
                    else:
                        print(f"    Failed to post reply {i+1}")
                        break

            # Log to chat research if we used research context
            if research_context and result.get('should_respond'):
                topic = get_topic_for_post(reply_thread) or get_topic_for_post(reply.get('parent_uri', ''))
                log_chat_research(reply_thread, topic, {
                    'timestamp': utcnow().isoformat(),
                    'user': author_handle,
                    'query': reply['text'],
                    'sources_used': result.get('sources_used', []),
                    'response': response_text
                })
                print(f"    Logged to chat research: {get_chat_research_path(reply_thread).name}")

        new_processed.append(reply['uri'])

    # -------------------------------------------------------------
    # 3b: Process replies to original posts (existing flow)
    # -------------------------------------------------------------
    if posts_with_replies:
        print("\n--- Processing replies to original posts ---")

    for post in posts_with_replies:
        if replies_sent >= args.max_replies:
            print(f"\n  Rate limit reached ({args.max_replies} replies)")
            break

        post_preview = post['text'][:50] + "..." if len(post['text']) > 50 else post['text']
        print(f"\n  Post: {post_preview}")
        print(f"  URI: {post['uri']}")

        # Get thread with replies
        try:
            thread = get_post_thread(client, post['uri'], depth=1)
            replies = extract_replies(thread, own_did)
        except Exception as e:
            print(f"    Error getting thread: {e}")
            continue

        print(f"    {len(replies)} replies from others")

        for reply in replies:
            if replies_sent >= args.max_replies:
                break

            # Skip already processed
            if reply['uri'] in processed_set:
                continue

            author_did = reply['author_did']
            author_handle = reply['author_handle']

            reply_preview = reply['text'][:60] + "..." if len(reply['text']) > 60 else reply['text']
            print(f"\n    Reply from @{author_handle}:")
            print(f"      {reply_preview}")

            # Build research context for this post
            post_research_context = build_research_context(post['uri'], reply.get('parent_uri'))
            if post_research_context:
                print(f"      Research context loaded ({len(post_research_context)} chars)")

            # =================================================================
            # TEST MODE CHECK
            # =================================================================
            if TEST_MODE_USERS:
                is_whitelisted = any(
                    author_handle == user or author_handle.endswith(f".{user}")
                    for user in TEST_MODE_USERS
                )
                if not is_whitelisted:
                    print(f"      [TEST MODE] Ignoring - not whitelisted")
                    new_processed.append(reply['uri'])
                    continue

            # =================================================================
            # SUPER USER CHECK - commands or training feedback
            # =================================================================
            is_super_user = any(
                author_handle == user or author_handle.endswith(f".{user}")
                for user in SUPER_USER_HANDLES
            )
            if is_super_user:
                msg_lower = reply['text'].lower().strip()

                # Super user can say 'chat' to start a conversation like anyone else
                if is_chat_trigger(reply['text']):
                    print(f"      [SUPER USER] 'chat' trigger - starting session with canned greeting")
                    # Create fresh session and use canned response (don't call Claude)
                    session = create_session(state, author_did, author_handle, post['uri'])
                    response_text = CANNED_RESPONSES['chat_greeting']
                    update_session(session)
                    # Post the canned response
                    if not dry_run:
                        reply_ref = {'uri': reply['uri'], 'cid': reply['cid']}
                        root_ref = {'uri': post['uri'], 'cid': post['cid']}
                        post_result = post_reply(client, response_text, reply_to=reply_ref, root=root_ref)
                        if post_result:
                            print(f"      Posted canned greeting: {post_result['uri']}")
                            replies_sent += 1
                    else:
                        print(f"      [DRY RUN] Would post canned greeting")
                    new_processed.append(reply['uri'])
                    continue
                # Check for COMMANDS
                elif msg_lower.startswith(('reply to', 'respond to', 'answer to', 'reply here', 'respond here')):
                    print(f"      [SUPER USER CMD] Triggering reply to this thread")
                    # Generate response to the original post context
                    result = generate_chat_response(
                        post.get('text', ''),
                        post.get('text', ''),
                        None,
                        forecast_context
                    )
                    claude_calls += 1
                    if result.get('should_respond'):
                        response_posts = result.get('response_posts', [result.get('response_text')])
                        if response_posts and not dry_run:
                            last_reply = {'uri': reply['uri'], 'cid': reply['cid']}
                            root_ref = {'uri': post['uri'], 'cid': post['cid']}
                            for i, post_text in enumerate(response_posts):
                                post_result = post_reply(client, post_text, reply_to=last_reply, root=root_ref)
                                if post_result:
                                    print(f"      Posted reply {i+1}/{len(response_posts)}: {post_result['uri']}")
                                    last_reply = post_result
                                    if i == 0:
                                        replies_sent += 1
                        elif response_posts and dry_run:
                            print(f"      [DRY RUN] Would post {len(response_posts)} reply(ies)")
                    new_processed.append(reply['uri'])
                    continue
                elif not is_chat_trigger(reply['text']):
                    # Not a command and not chat - log as training feedback
                    print(f"      [SUPER USER] Training feedback logged")
                    training_entry = {
                        'timestamp': utcnow().isoformat(),
                        'type': 'super_user_feedback',
                        'author': author_handle,
                        'message': reply['text'],
                        'context': post['text'][:200] if post.get('text') else '',
                        'parent_uri': post.get('uri', ''),
                        'root_uri': post.get('uri', '')
                    }
                    state.setdefault('training_log', []).append(training_entry)
                    new_processed.append(reply['uri'])
                    continue

            # =================================================================
            # PRE-FILTERS (before any Claude call)
            # =================================================================

            # Check for pass-through (users tagging friends)
            if is_pass_through(reply['text']):
                print("      [SKIP] Pass-through detected (tagging others)")
                new_processed.append(reply['uri'])
                continue

            # =================================================================
            # TWO-STEP ENGAGEMENT
            # =================================================================

            session = get_session(state, author_did)
            response_text = None
            classification = None
            result = {}  # Initialize for signature check later

            if session:
                # User has an active session
                msg_limit = get_session_limit(author_did, session, author_handle)
                if session['message_count'] >= msg_limit:
                    # Session limit reached
                    print(f"      Session limit reached ({msg_limit} msgs)")
                    response_text = CANNED_RESPONSES['session_limit']
                    # End the session
                    del state['active_sessions'][author_did]
                else:
                    # Continue conversation - invoke Claude
                    print("      Active session - generating response...")
                    result = generate_chat_response(reply['text'], post['text'], session, forecast_context, is_super_user, post_research_context)
                    claude_calls += 1
                    classification = result.get('classification')
                    print(f"      Classification: {classification}")

                    if result.get('should_respond'):
                        response_text = result.get('response_text')
                        update_session(session)
                        print(f"      Session msg count: {session['message_count']}")

                        # Log for training/improvement
                        log_training_data(state, {
                            'type': 'claude_response',
                            'author': author_handle,
                            'classification': classification,
                            'user_message': reply['text'],
                            'wxd_post_context': post['text'][:200],
                            'claude_response': response_text,
                            'reason': result.get('reason', ''),
                        })

                    # Track special classifications
                    if classification == 'topic_suggestion':
                        state.setdefault('topic_suggestions', []).append({
                            'text': reply['text'],
                            'author': author_handle,
                            'date': utcnow().isoformat(),
                        })
                    elif classification == 'correction':
                        state.setdefault('flagged_corrections', []).append({
                            'text': reply['text'],
                            'author': author_handle,
                            'parent_uri': post['uri'],
                            'date': utcnow().isoformat(),
                        })
                    elif classification == 'uncertain' or result.get('needs_human'):
                        # Flag for human review - Claude wasn't confident
                        state.setdefault('needs_human_review', []).append({
                            'text': reply['text'],
                            'author': author_handle,
                            'parent_uri': post['uri'],
                            'reply_uri': reply['uri'],
                            'uncertainty_note': result.get('uncertainty_note', ''),
                            'claude_response': response_text,
                            'date': utcnow().isoformat(),
                        })
                        print(f"      *** FLAGGED FOR HUMAN REVIEW: {result.get('uncertainty_note', 'uncertain')} ***")

                    # Upgrade to feedback session if user is providing valuable input
                    # This extends the message limit to allow full clarification
                    if classification in ('correction', 'uncertain') or result.get('needs_human'):
                        if not session.get('is_feedback_session'):
                            upgrade_to_feedback_session(session)

            else:
                # No active session - check follower status
                is_follower_user = is_follower(client, author_did, own_did)

                if not is_follower_user:
                    # Non-follower: send one-time invitation to follow and chat
                    notified = state.get('notified_non_followers', [])
                    if author_did in notified:
                        print("      Not a follower (already notified) - skipping")
                        new_processed.append(reply['uri'])
                        continue
                    print("      Not a follower - sending one-time invitation")
                    response_text = CANNED_RESPONSES['chat_invitation']
                    state.setdefault('notified_non_followers', []).append(author_did)
                    result = {}
                else:
                    # Follower: engage directly with Claude AI response
                    print("      Follower confirmed - engaging directly with Claude...")
                    session = create_session(state, author_did, author_handle, post['uri'])
                    result = generate_chat_response(reply['text'], post['text'], session, forecast_context, is_super_user, post_research_context)
                    claude_calls += 1
                    classification = result.get('classification')
                    print(f"      Classification: {classification}")

                    if result.get('should_respond'):
                        response_text = result.get('response_text')
                        update_session(session)
                        print(f"      Session started, msg count: {session['message_count']}")

                        log_training_data(state, {
                            'type': 'follower_direct_response',
                            'author': author_handle,
                            'classification': classification,
                            'user_message': reply['text'],
                            'wxd_post_context': post['text'][:200],
                            'claude_response': response_text,
                        })

            # =================================================================
            # POST RESPONSE
            # =================================================================

            # Build response posts list (may be multi-post for long responses)
            response_posts = []
            if 'result' in dir() and result and result.get('response_posts'):
                response_posts = result.get('response_posts')
            elif response_text:
                response_posts = [response_text]

            # Add AI signature to last post (only for Claude-generated responses)
            if response_posts and 'result' in dir() and result and result.get('should_respond'):
                response_posts = add_ai_signature(response_posts)

            if response_posts:
                print(f"      Response ({len(response_posts)} post(s)): {response_posts[0][:80]}...")

                if dry_run:
                    print(f"      [DRY RUN - would post {len(response_posts)} reply(ies)]")
                else:
                    last_reply_ref = {'uri': reply['uri'], 'cid': reply['cid']}
                    root_ref = {'uri': post['uri'], 'cid': post['cid']}

                    for i, post_text in enumerate(response_posts):
                        post_result = post_reply(client, post_text, reply_to=last_reply_ref, root=root_ref)
                        if post_result:
                            print(f"      Posted reply {i+1}/{len(response_posts)}: {post_result['uri']}")
                            last_reply_ref = post_result  # Chain replies
                            if i == 0:
                                replies_sent += 1
                        else:
                            print(f"      Failed to post reply {i+1}")
                            break

            # Mark as processed
            new_processed.append(reply['uri'])

    # Update state
    state['processed_replies'] = list(processed_set | set(new_processed))

    # Track when we last received a reply (for adaptive polling)
    if new_processed:
        state['last_reply_received'] = utcnow().isoformat()

    # Keep only last 1000 processed URIs
    if len(state['processed_replies']) > 1000:
        state['processed_replies'] = state['processed_replies'][-1000:]

    # Save state (skip in dry-run to allow re-testing)
    if not dry_run:
        save_state(state_path, state)
        print(f"\nState saved ({len(new_processed)} new replies processed)")
    else:
        print(f"\n[DRY RUN - state not saved, {len(new_processed)} replies would be marked processed]")

    # Summary
    print()
    print("=" * 50)
    print("Summary:")
    print(f"  Mentions processed: {len(new_mentions)}")
    print(f"  Threaded replies processed: {len(threaded_replies)}")
    print(f"  Posts checked: {len(posts_with_replies)}")
    print(f"  New replies found: {len(new_processed)}")
    print(f"  Claude API calls: {claude_calls}")
    if dry_run:
        print(f"  Replies that would be sent: {replies_sent}")
    else:
        print(f"  Replies sent: {replies_sent}")

    print(f"  Active sessions: {len(state.get('active_sessions', {}))}")
    if state.get('topic_suggestions'):
        print(f"  Topic suggestions logged: {len(state['topic_suggestions'])}")
    if state.get('flagged_corrections'):
        print(f"  Corrections flagged: {len(state['flagged_corrections'])}")
    if state.get('training_log'):
        print(f"  Training log entries: {len(state['training_log'])}")
    if state.get('needs_human_review'):
        print(f"  *** NEEDS HUMAN REVIEW: {len(state['needs_human_review'])} ***")

    print("=" * 50)

    return 0


if __name__ == "__main__":
    exit(main())
