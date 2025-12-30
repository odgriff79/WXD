#!/usr/bin/env python3
"""
WXD Reply Digest System

Collects replies/mentions from followers only (DoS protection).
Logs to digest file for manual review or ntfy summary.

Usage:
    python reply_digest.py              # Collect and save digest
    python reply_digest.py --summary    # Show recent digest summary
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from atproto import Client
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_followers(client, handle: str) -> set:
    """Get set of follower DIDs for the account."""
    followers = set()
    cursor = None

    try:
        # Get actor DID first
        profile = client.app.bsky.actor.get_profile({'actor': handle})
        actor_did = profile.did

        # Paginate through followers
        while True:
            params = {'actor': actor_did, 'limit': 100}
            if cursor:
                params['cursor'] = cursor

            result = client.app.bsky.graph.get_followers(params)

            for follower in result.followers:
                followers.add(follower.did)

            if not result.cursor:
                break
            cursor = result.cursor

            # Safety limit
            if len(followers) > 5000:
                break

    except Exception as e:
        print(f"  Error fetching followers: {e}")

    return followers


def collect_replies(handle: str, password: str, since_hours: int = 48) -> list:
    """Collect replies/mentions from followers only."""
    if not HAS_ATPROTO or not handle or not password:
        print("  Bluesky credentials not available")
        return []

    try:
        client = Client()
        client.login(handle, password)

        print("  Fetching followers list...")
        followers = get_followers(client, handle)
        print(f"  Found {len(followers)} followers")

        print("  Fetching notifications...")
        notifications = client.app.bsky.notification.list_notifications()

        replies = []
        cutoff = utcnow() - timedelta(hours=since_hours)
        skipped_non_follower = 0

        for notif in notifications.notifications:
            # Only process replies and mentions
            if notif.reason not in ['reply', 'mention']:
                continue

            # Parse timestamp
            try:
                notif_time = datetime.fromisoformat(
                    notif.indexed_at.replace('Z', '+00:00')
                )
                if notif_time < cutoff:
                    continue
            except:
                continue

            # Check if author is a follower (DoS protection)
            author_did = notif.author.did
            if author_did not in followers:
                skipped_non_follower += 1
                continue

            # Get post text
            text = ""
            if hasattr(notif, 'record') and hasattr(notif.record, 'text'):
                text = notif.record.text

            replies.append({
                "author": notif.author.handle,
                "author_name": getattr(notif.author, 'display_name', notif.author.handle),
                "text": text[:500],  # Limit text length
                "time": notif.indexed_at,
                "type": notif.reason,
                "uri": notif.uri
            })

        print(f"  Collected {len(replies)} replies from followers")
        print(f"  Skipped {skipped_non_follower} from non-followers")

        return replies

    except Exception as e:
        print(f"  Error collecting replies: {e}")
        return []


def save_digest(replies: list, digest_path: Path) -> None:
    """Save replies to digest file."""
    # Load existing digest
    existing = []
    if digest_path.exists():
        try:
            with open(digest_path, 'r') as f:
                existing = json.load(f)
        except:
            existing = []

    # Add new replies (avoid duplicates by URI)
    existing_uris = {r.get('uri') for r in existing}
    new_replies = [r for r in replies if r.get('uri') not in existing_uris]

    # Combine and keep last 100
    combined = new_replies + existing
    combined = combined[:100]

    # Save
    with open(digest_path, 'w') as f:
        json.dump(combined, f, indent=2)

    print(f"  Saved {len(new_replies)} new replies to digest")


def get_summary(digest_path: Path, limit: int = 10) -> str:
    """Get summary of recent replies for ntfy."""
    if not digest_path.exists():
        return "No replies collected yet."

    try:
        with open(digest_path, 'r') as f:
            replies = json.load(f)
    except:
        return "Error reading digest."

    if not replies:
        return "No replies in digest."

    lines = [f"REPLY DIGEST ({len(replies)} total)\n"]

    for r in replies[:limit]:
        author = r.get('author', 'unknown')
        text = r.get('text', '')[:100]
        rtype = r.get('type', 'reply')
        lines.append(f"@{author} ({rtype}): {text}...")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='WXD Reply Digest')
    parser.add_argument('--summary', '-s', action='store_true',
                       help='Show digest summary')
    parser.add_argument('--hours', type=int, default=48,
                       help='Hours to look back (default 48)')
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    digest_path = script_dir / "data" / "reply_digest.json"
    digest_path.parent.mkdir(exist_ok=True)

    # Credentials
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    print(f"WXD Reply Digest - {utcnow().isoformat()}")

    if args.summary:
        print(get_summary(digest_path))
        return 0

    # Collect replies
    print(f"Collecting replies from last {args.hours} hours...")
    replies = collect_replies(bsky_handle, bsky_password, args.hours)

    if replies:
        save_digest(replies, digest_path)

    # Show summary
    print("\n" + get_summary(digest_path, limit=5))

    return 0


if __name__ == "__main__":
    exit(main())
