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
SESSION_MSG_LIMIT_STANDARD = 5   # Max messages per session (regular followers)
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
TRUSTED_USERS = set()

# =============================================================================
# TEST MODE / LOCKDOWN
# Set to empty list for normal operation, or add handles for lockdown testing
# =============================================================================
TEST_MODE_USERS = [
    "winchesterweather.bsky.social",  # Steve - primary tester
    "sarahhants.bsky.social",          # Sarah - trusted follower, training data
]
# TEST_MODE_USERS = []  # Set to empty list for normal operation

# =============================================================================
# CANNED RESPONSES
# =============================================================================
CANNED_RESPONSES = {
    "chat_invitation": (
        "Thanks for the reply! WXD is trialing automated AI responses. "
        "Reply 'chat' to this message to continue the conversation."
    ),
    "session_limit": (
        "You've reached the message limit for this chat session. "
        "Start a new conversation anytime by replying 'chat' to a future post."
    ),
    "non_follower": (
        "Thanks for reaching out! WXD replies are currently limited to followers. "
        "Follow for weather updates and responses."
    ),
}


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
    """
    state.setdefault('training_log', []).append({
        'timestamp': utcnow().isoformat(),
        **entry
    })

    # Keep last 100 entries to prevent unbounded growth
    if len(state['training_log']) > 100:
        state['training_log'] = state['training_log'][-100:]


def save_state(state_path: Path, state: dict) -> None:
    """Save state to file."""
    state['last_run'] = utcnow().isoformat()
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


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


def get_session_limit(author_did: str, session: dict = None) -> int:
    """Get message limit for this user/session.

    Limits escalate based on conversation value:
    - Standard: 5 messages
    - Trusted: 10 messages
    - Feedback session: 15 messages (when providing corrections/clarifications)
    """
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


def get_metoffice_warnings() -> str:
    """Fetch current Met Office warnings - GROUND TRUTH for any warning claims."""
    if not HAS_METOFFICE or not fetch_metoffice_narrative:
        return ""

    try:
        mo_data = fetch_metoffice_narrative()

        warnings_parts = []
        if mo_data.get("long_range_warning"):
            warnings_parts.append(f"ACTIVE: {mo_data['long_range_warning']}")
        if mo_data.get("uk_warnings"):
            warnings_parts.append(f"UK: {mo_data['uk_warnings']}")

        if warnings_parts:
            return "MET OFFICE WARNINGS:\n" + "\n".join(warnings_parts)
        else:
            return "MET OFFICE WARNINGS: None currently in force"
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
            ['claude', '--dangerously-skip-permissions', '--model', 'haiku', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:500]
    except Exception as e:
        print(f"    Error fetching location forecast: {e}")

    return ""


def generate_chat_response(reply_text: str, parent_text: str, session: dict = None, forecast_context: str = "") -> dict:
    """Use Claude CLI to generate a conversational response.

    Returns dict with:
        - classification: genuine_question | topic_suggestion | appreciation | correction | uncertain | spam
        - should_respond: bool
        - response_text: str (if should_respond)
        - reason: str (explanation)
        - needs_human: bool (flag for owner review)
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

    prompt = f"""You are WXD, a friendly weather analysis bot on Bluesky focused on UK weather.
Your tone is: casual, friendly, weather-savvy, helpful. Like chatting with a knowledgeable weather friend.

CRITICAL: Be ACCURATE, not overconfident. Weather is complex.
- Our data shows 850hPa temps (1.5km altitude) - these DON'T directly predict surface conditions
- For snow: 850hPa temps indicate potential, but surface snow depends on local factors (elevation, urban heat, exact precip timing)
- For location-specific questions: Give the synoptic outlook but note local forecasts (Met Office, metcheck) are better for street-level detail
- NEVER claim certainty about local weather from our ensemble data alone
- If uncertain, say so - better to be honest than confidently wrong

WARNINGS RULE - CRITICAL:
- NEVER mention Met Office warnings unless they are EXPLICITLY stated in the forecast data provided
- If a warning IS in the data, you MUST specify: region affected AND valid period (dates)
- Do NOT invent or assume warnings exist - if not in the data, don't mention them

Use the forecast data to explain the general pattern, then qualify with appropriate caveats.

Only flag for human review if:
- User points out an error in WXD's data (correction)
- Question is about WXD's internal systems/operations
{forecast_section}
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
    "response_text": "Your response (max 295 chars, casual friendly tone, SPECIFIC not vague)",
    "reason": "Brief explanation",
    "needs_human": true/false
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

            # Validate and sanitize response - smart truncation at word boundary
            if response.get('should_respond') and response.get('response_text'):
                text = response['response_text']
                if len(text) > 300:
                    # Truncate at last space before 297 chars, add "..."
                    text = text[:297]
                    last_space = text.rfind(' ')
                    if last_space > 250:  # Only if we have reasonable content
                        text = text[:last_space] + "..."
                    else:
                        text = text[:297] + "..."
                response['response_text'] = text

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
    args = parser.parse_args()

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

    # =================================================================
    # PHASE 1: Check notifications for threaded conversation replies
    # This catches replies to WXD's own replies, not just to original posts
    # =================================================================
    print()
    print("Checking notifications for threaded replies...")
    notification_replies = get_notification_replies(client, own_did, limit=50)
    print(f"  Found {len(notification_replies)} reply notifications")

    # Filter to only new notifications from users with active sessions
    # (or new chat triggers from anyone)
    active_session_dids = set(state.get('active_sessions', {}).keys())
    threaded_replies = []
    for notif in notification_replies:
        if notif['uri'] in processed_set:
            continue
        # Include if: user has active session OR this might be a chat trigger
        if notif['author_did'] in active_session_dids or is_chat_trigger(notif['text']):
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

    replies_sent = 0
    new_processed = []
    claude_calls = 0

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

        # Skip pass-through
        if is_pass_through(reply['text']):
            print("    [SKIP] Pass-through detected")
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

        response_text = None

        if session:
            msg_limit = get_session_limit(author_did, session)
            if session['message_count'] >= msg_limit:
                print(f"    Session limit reached ({msg_limit} msgs)")
                response_text = CANNED_RESPONSES['session_limit']
                del state['active_sessions'][author_did]
            else:
                print("    Active session - generating response...")
                result = generate_chat_response(reply['text'], context_text, session, forecast_context)
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
        elif is_chat_trigger(reply['text']):
            # New chat trigger in a thread
            print("    'chat' trigger detected - starting session!")
            session = create_session(state, author_did, author_handle, reply.get('root_uri', reply['uri']))
            result = generate_chat_response("Hi, I'd like to chat about weather!", context_text, session, forecast_context)
            claude_calls += 1
            if result.get('should_respond'):
                response_text = result.get('response_text')
                update_session(session)
            else:
                response_text = "Hi! Happy to chat about UK weather. What's on your mind?"
                update_session(session)

        # Post response if we have one
        if response_text:
            print(f"    Response: {response_text[:80]}...")

            if dry_run:
                print("    [DRY RUN - would post reply]")
            else:
                result = post_reply(
                    client,
                    response_text,
                    reply_to={'uri': reply['uri'], 'cid': reply['cid']},
                    root={'uri': reply.get('root_uri', reply['uri']),
                          'cid': reply.get('root_cid', reply['cid'])}
                )
                if result:
                    print(f"    Posted reply: {result['uri']}")
                    replies_sent += 1
                else:
                    print("    Failed to post reply")

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

            if session:
                # User has an active session
                msg_limit = get_session_limit(author_did, session)
                if session['message_count'] >= msg_limit:
                    # Session limit reached
                    print(f"      Session limit reached ({msg_limit} msgs)")
                    response_text = CANNED_RESPONSES['session_limit']
                    # End the session
                    del state['active_sessions'][author_did]
                else:
                    # Continue conversation - invoke Claude
                    print("      Active session - generating response...")
                    result = generate_chat_response(reply['text'], post['text'], session, forecast_context)
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
                # No active session
                if is_chat_trigger(reply['text']):
                    # User said "chat" - start a new session!
                    print("      'chat' trigger detected - starting session!")
                    session = create_session(state, author_did, author_handle, post['uri'])

                    # Generate initial response with Claude
                    result = generate_chat_response(
                        "Hi, I'd like to chat about weather!",
                        post['text'],
                        session,
                        forecast_context
                    )
                    claude_calls += 1

                    if result.get('should_respond'):
                        response_text = result.get('response_text')
                        update_session(session)

                        # Log session start for training
                        log_training_data(state, {
                            'type': 'session_start',
                            'author': author_handle,
                            'wxd_post_context': post['text'][:200],
                            'initial_response': response_text,
                        })
                    else:
                        # Fallback greeting if Claude didn't respond
                        response_text = "Hi! Happy to chat about UK weather. What's on your mind?"
                        update_session(session)
                else:
                    # First reply without "chat" - send invitation
                    # Log the initial question for context (useful for training)
                    print("      First reply - sending chat invitation")
                    log_training_data(state, {
                        'type': 'initial_question',
                        'author': author_handle,
                        'user_message': reply['text'],
                        'wxd_post_context': post['text'][:200],
                        'note': 'Pre-chat question - user may follow up with chat trigger',
                    })
                    response_text = CANNED_RESPONSES['chat_invitation']

            # =================================================================
            # POST RESPONSE
            # =================================================================

            if response_text:
                print(f"      Response: {response_text[:80]}...")

                if dry_run:
                    print("      [DRY RUN - would post reply]")
                else:
                    result = post_reply(
                        client,
                        response_text,
                        reply_to={'uri': reply['uri'], 'cid': reply['cid']},
                        root={'uri': post['uri'], 'cid': post['cid']}
                    )
                    if result:
                        print(f"      Posted reply: {result['uri']}")
                        replies_sent += 1
                    else:
                        print("      Failed to post reply")

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
