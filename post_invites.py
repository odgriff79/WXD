#!/usr/bin/env python3
"""
One-time script to post invite messages to test users.
Run with --post to actually send, otherwise dry-run.
"""

import os
import sys
from pathlib import Path

try:
    from atproto import Client
except ImportError:
    print("ERROR: atproto not installed")
    sys.exit(1)

# Invite messages
STEVE_MESSAGES = [
    "Hey @winchesterweather.bsky.social! Testing an automated reply system for WXD posts - uses Claude AI to handle conversations. Fancy being a guinea pig?",
    "How it works: reply to any of my weather posts with the word 'chat' somewhere in your reply. The system will pick it up and start a conversation.",
    "We're monitoring replies to see how it handles real weather questions. Let me know if anything seems weird or off!",
]

SARAH_MESSAGES = [
    "Hey @sarahhants.bsky.social! Testing an automated reply system for my weather posts - uses Claude AI to handle conversations. Fancy being a guinea pig?",
    "How it works: reply to this message AND another post of your choice from me with the word 'chat' somewhere in your reply. Want to make sure it picks up triggers across different threads.",
    "We're monitoring replies to see how it handles real conversation - your cold health alert question is exactly the type of query we want it to handle well! Let me know if anything seems weird.",
]


def post_thread(client: Client, messages: list, dry_run: bool = True) -> bool:
    """Post a thread of messages."""
    from atproto import models as atproto_models

    if dry_run:
        print("DRY RUN - would post:")
        for i, msg in enumerate(messages):
            print(f"  [{i+1}/{len(messages)}] {msg[:60]}...")
        return True

    try:
        # Post first message
        print(f"  Posting message 1/{len(messages)}...")
        response = client.send_post(text=messages[0])
        root_uri = response.uri
        root_cid = response.cid
        parent_uri = root_uri
        parent_cid = root_cid

        # Post replies
        for i, msg in enumerate(messages[1:], start=2):
            print(f"  Posting message {i}/{len(messages)}...")

            parent_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
                uri=parent_uri,
                cid=parent_cid
            )
            root_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
                uri=root_uri,
                cid=root_cid
            )
            reply_ref = atproto_models.AppBskyFeedPost.ReplyRef(
                parent=parent_ref,
                root=root_ref
            )

            response = client.send_post(text=msg, reply_to=reply_ref)
            parent_uri = response.uri
            parent_cid = response.cid

        print("  Thread posted successfully!")
        return True

    except Exception as e:
        print(f"  Error: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Post invite messages to testers')
    parser.add_argument('--post', action='store_true', help='Actually post (default: dry-run)')
    parser.add_argument('--steve', action='store_true', help='Post to Steve only')
    parser.add_argument('--sarah', action='store_true', help='Post to Sarah only')
    args = parser.parse_args()

    dry_run = not args.post

    # Check credentials
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    if not bsky_handle or not bsky_password:
        print("ERROR: BSKY_HANDLE and BSKY_PASSWORD must be set")
        return 1

    print(f"Post Invites - {'DRY RUN' if dry_run else 'LIVE MODE'}")
    print()

    # Authenticate
    print("Authenticating...")
    client = Client()
    client.login(bsky_handle, bsky_password)
    print(f"  Logged in as {bsky_handle}")
    print()

    # Determine who to post to
    post_steve = args.steve or (not args.steve and not args.sarah)
    post_sarah = args.sarah or (not args.steve and not args.sarah)

    if post_steve:
        print("Steve invite thread:")
        post_thread(client, STEVE_MESSAGES, dry_run)
        print()

    if post_sarah:
        print("Sarah invite thread:")
        post_thread(client, SARAH_MESSAGES, dry_run)
        print()

    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
