#!/usr/bin/env python3
"""
WXD Reply Listener

Monitors replies to WXD posts and responds intelligently using Claude CLI.

Classification:
- genuine_question → respond with helpful answer
- topic_suggestion → log for engagement posts
- appreciation → brief thanks
- correction → flag for review
- spam/irrelevant → ignore

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
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from atproto import Client, models as atproto_models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False


# Safety limits
DEFAULT_MAX_REPLIES = 5  # Max replies to send per run
DEFAULT_POSTS_TO_CHECK = 10  # How many recent posts to check for replies

# Blocklist - DIDs of accounts to ignore (add trolls here)
BLOCKLIST = set()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_state(state_path: Path) -> dict:
    """Load processed replies state."""
    if state_path.exists():
        with open(state_path, 'r') as f:
            return json.load(f)
    return {
        'processed_replies': [],  # List of reply URIs already handled
        'topic_suggestions': [],  # Collected topic suggestions
        'flagged_corrections': [],  # Corrections needing review
        'last_run': None,
    }


def save_state(state_path: Path, state: dict) -> None:
    """Save state to file."""
    state['last_run'] = utcnow().isoformat()
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


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


def classify_reply(reply_text: str, parent_text: str) -> dict:
    """Use Claude CLI to classify a reply and generate response if needed.

    Returns dict with:
        - classification: genuine_question | topic_suggestion | appreciation | correction | spam
        - should_respond: bool
        - response_text: str (if should_respond)
        - reason: str (explanation)
    """
    prompt = f"""You are WXD, a weather analysis bot on Bluesky. Analyze this reply to one of your posts.

YOUR POST:
{parent_text[:500]}

REPLY FROM USER:
{reply_text}

Classify this reply and decide if/how to respond. Categories:
1. genuine_question - User asking about weather, forecasts, or your analysis → respond helpfully
2. topic_suggestion - User suggesting a topic for future posts → log it, brief thanks
3. appreciation - User thanking or praising → brief thanks
4. correction - User pointing out an error → flag for review, acknowledge
5. spam - Off-topic, promotional, trolling → ignore

Output JSON only:
{{
    "classification": "genuine_question|topic_suggestion|appreciation|correction|spam",
    "should_respond": true/false,
    "response_text": "Your response (max 280 chars, plain text, no emojis unless replying to emojis)",
    "reason": "Brief explanation of classification"
}}"""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0 and result.stdout.strip():
            # Parse JSON response
            output = result.stdout.strip()
            # Handle potential markdown code blocks
            if '```json' in output:
                output = output.split('```json')[1].split('```')[0]
            elif '```' in output:
                output = output.split('```')[1].split('```')[0]

            response = json.loads(output.strip())

            # Validate and sanitize response
            if response.get('should_respond') and response.get('response_text'):
                # Truncate response if needed
                response['response_text'] = response['response_text'][:280]

            return response

    except subprocess.TimeoutExpired:
        print("    Claude CLI timeout")
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}")
    except Exception as e:
        print(f"    Classification error: {e}")

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
        # Build reply reference
        parent_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
            uri=reply_to['uri'],
            cid=reply_to['cid']
        )

        # If no root specified, use reply_to as root
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
    parser = argparse.ArgumentParser(description='WXD Reply Listener')
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

    print(f"WXD Reply Listener - {utcnow().isoformat()}")
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

            reply_preview = reply['text'][:60] + "..." if len(reply['text']) > 60 else reply['text']
            print(f"\n    Reply from @{reply['author_handle']}:")
            print(f"      {reply_preview}")

            # Classify reply
            print("      Classifying...")
            classification = classify_reply(reply['text'], post['text'])

            print(f"      Classification: {classification.get('classification', 'unknown')}")
            print(f"      Reason: {classification.get('reason', 'N/A')}")

            # Handle based on classification
            if classification.get('should_respond'):
                response_text = classification.get('response_text', '')
                print(f"      Response: {response_text[:80]}...")

                if dry_run:
                    print("      [DRY RUN - would post reply]")
                else:
                    # Post the reply
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

            # Track topic suggestions
            if classification.get('classification') == 'topic_suggestion':
                state.setdefault('topic_suggestions', []).append({
                    'text': reply['text'],
                    'author': reply['author_handle'],
                    'date': utcnow().isoformat(),
                })

            # Track corrections for review
            if classification.get('classification') == 'correction':
                state.setdefault('flagged_corrections', []).append({
                    'text': reply['text'],
                    'author': reply['author_handle'],
                    'parent_uri': post['uri'],
                    'date': utcnow().isoformat(),
                })

            # Mark as processed
            new_processed.append(reply['uri'])

    # Update state
    state['processed_replies'] = list(processed_set | set(new_processed))

    # Keep only last 1000 processed URIs to prevent unbounded growth
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
    if dry_run:
        print(f"  Replies that would be sent: {replies_sent}")
    else:
        print(f"  Replies sent: {replies_sent}")

    if state.get('topic_suggestions'):
        print(f"  Topic suggestions logged: {len(state['topic_suggestions'])}")
    if state.get('flagged_corrections'):
        print(f"  Corrections flagged: {len(state['flagged_corrections'])}")

    print("=" * 50)

    return 0


if __name__ == "__main__":
    exit(main())
