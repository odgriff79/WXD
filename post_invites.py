#!/usr/bin/env python3
"""
One-time script to post invite messages to test users.
Run with --post to actually send, otherwise dry-run.

Uses TextBuilder for proper mention facets (clickable @mentions).
"""

import os
import sys
from pathlib import Path

try:
    from atproto import Client, client_utils, models as atproto_models
except ImportError:
    print("ERROR: atproto not installed")
    sys.exit(1)


# Test users to invite - handle and message content
# First message uses TextBuilder for mention, rest are plain text
TESTERS = {
    "steve": {
        "handle": "winchesterweather.bsky.social",
        "messages": [
            # First message built with TextBuilder (mention at start)
            None,  # Placeholder - built dynamically with TextBuilder
            "How it works: reply to any of my weather posts with the word 'chat' somewhere in your reply. The system will pick it up and start a conversation.",
            "We're monitoring replies to see how it handles real weather questions. Let me know if anything seems weird or off!",
        ],
        "first_template": "Hey {mention} - Testing an automated reply system for WXD posts - uses Claude AI to handle conversations. Fancy being a guinea pig?",
    },
    "sarah": {
        "handle": "sarahhants.bsky.social",
        "messages": [
            None,  # Placeholder - built dynamically with TextBuilder
            "How it works: reply to this message AND another post of your choice from me with the word 'chat' somewhere in your reply. Want to make sure it picks up triggers across different threads.",
            "We're monitoring replies to see how it handles real conversation - your cold health alert question is exactly the type of query we want it to handle well! Let me know if anything seems weird.",
        ],
        "first_template": "Hey {mention} - Testing an automated reply system for my weather posts - uses Claude AI to handle conversations. Fancy being a guinea pig?",
    },
}


def resolve_handle_to_did(client: Client, handle: str) -> str:
    """Resolve a handle to a DID."""
    try:
        response = client.app.bsky.actor.get_profile({'actor': handle})
        return response.did
    except Exception as e:
        print(f"  ERROR resolving {handle}: {e}")
        return None


def build_first_message(template: str, handle: str, did: str):
    """Build first message with proper mention facet using TextBuilder."""
    # Template has {mention} placeholder
    # Split around it to build with TextBuilder
    parts = template.split("{mention}")

    tb = client_utils.TextBuilder()
    tb.text(parts[0])  # "Hey "
    tb.mention(f"@{handle}", did)  # Proper mention facet
    if len(parts) > 1:
        tb.text(parts[1])  # Rest of message

    return tb


def post_thread(client: Client, tester_config: dict, dry_run: bool = True) -> bool:
    """Post a thread of messages with proper mention in first post."""
    handle = tester_config["handle"]
    messages = tester_config["messages"]
    first_template = tester_config["first_template"]

    # Resolve handle to DID for mention
    print(f"  Resolving @{handle}...")
    did = resolve_handle_to_did(client, handle)
    if not did:
        print(f"  ERROR: Could not resolve handle")
        return False
    print(f"  DID: {did}")

    # Build first message with proper mention
    first_msg = build_first_message(first_template, handle, did)

    if dry_run:
        print("DRY RUN - would post:")
        print(f"  [1/{len(messages)}] {first_msg.build_text()[:60]}...")
        for i, msg in enumerate(messages[1:], start=2):
            print(f"  [{i}/{len(messages)}] {msg[:60]}...")
        return True

    try:
        # Post first message (with TextBuilder for mention)
        print(f"  Posting message 1/{len(messages)}...")
        response = client.send_post(first_msg)
        root_uri = response.uri
        root_cid = response.cid
        parent_uri = root_uri
        parent_cid = root_cid

        # Post replies (plain text, no mentions needed)
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
        import traceback
        traceback.print_exc()
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
        post_thread(client, TESTERS["steve"], dry_run)
        print()

    if post_sarah:
        print("Sarah invite thread:")
        post_thread(client, TESTERS["sarah"], dry_run)
        print()

    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
