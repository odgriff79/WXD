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


def generate_chat_response(reply_text: str, parent_text: str, session: dict = None) -> dict:
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

    prompt = f"""You are WXD, a friendly weather analysis bot on Bluesky focused on UK weather.
Your tone is: casual, friendly, weather-savvy, helpful. Like chatting with a knowledgeable weather friend.

IMPORTANT: If you're unsure about something, DON'T GUESS. Flag it for human review instead.
Examples of when to flag:
- Technical weather distinctions you're uncertain about (e.g., Met Office warnings vs UKHSA Cold Health Alerts)
- Specific local knowledge you might not have
- Questions about WXD's own posts/data that you can't verify
- Anything where being wrong could mislead the user

ORIGINAL POST:
{parent_text[:500]}

USER'S MESSAGE:
{reply_text}
{context}

Classify and respond. Categories:
1. genuine_question - Weather question you CAN answer confidently → helpful response
2. topic_suggestion - Future topic idea → brief thanks
3. appreciation - Thanks/praise → brief warm thanks
4. correction - Error pointed out → acknowledge, flag for review
5. uncertain - Question you're NOT SURE about → polite "let me check" + flag for human
6. spam - Off-topic/promotional → ignore

Output JSON only:
{{
    "classification": "genuine_question|topic_suggestion|appreciation|correction|uncertain|spam",
    "should_respond": true/false,
    "response_text": "Your response (max 280 chars, casual friendly tone)",
    "reason": "Brief explanation",
    "needs_human": true/false,
    "uncertainty_note": "If uncertain, what specifically needs checking"
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

            # Validate and sanitize response
            if response.get('should_respond') and response.get('response_text'):
                response['response_text'] = response['response_text'][:280]

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

    print(f"WXD Reply Listener v2 - {utcnow().isoformat()}")
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

    # Load state
    state = load_state(state_path)
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

    # Get recent posts
    print()
    print(f"Fetching {args.limit} recent posts...")
    posts = get_recent_posts(client, bsky_handle, limit=args.limit)
    print(f"  Found {len(posts)} posts")

    # Filter to posts with replies
    posts_with_replies = [p for p in posts if p.get('reply_count', 0) > 0]
    print(f"  {len(posts_with_replies)} posts have replies")

    if not posts_with_replies:
        print()
        print("No replies to process")
        save_state(state_path, state)
        return 0

    # Process replies
    print()
    print("Processing replies...")

    replies_sent = 0
    new_processed = []
    claude_calls = 0

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
                    result = generate_chat_response(reply['text'], post['text'], session)
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
                        session
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
