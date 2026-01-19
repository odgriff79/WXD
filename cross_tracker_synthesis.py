#!/usr/bin/env python3
"""
WXD Cross-Tracker Synthesis

Generates a synthesis post comparing all tracked models.
Triggered manually via ntfy for significant weather events.

Usage:
    python cross_tracker_synthesis.py              # Dry-run
    python cross_tracker_synthesis.py --post       # Actually post
    python cross_tracker_synthesis.py --preview    # Show what would be posted
"""

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent

# Try imports
try:
    from atproto import Client, models as atproto_models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False

try:
    from lib.cross_tracker import (
        load_all_models,
        find_agreement_and_divergence,
        build_comparison_context,
        get_data_age,
    )
    HAS_CROSS_TRACKER = True
except ImportError:
    HAS_CROSS_TRACKER = False
    print("ERROR: lib/cross_tracker.py not found")
    exit(1)

try:
    from lib.bluesky import register_post
    HAS_REGISTRY = True
except ImportError:
    HAS_REGISTRY = False
    register_post = None


def utcnow():
    return datetime.now(timezone.utc)


def generate_synthesis_commentary(context: str, analysis: dict) -> str:
    """Use Claude to generate synthesis commentary."""

    # Build prompt
    prompt = f"""You are WXD, a weather analysis bot. Write a cross-tracker synthesis post comparing what all the models we track are showing.

TODAY IS: {utcnow().strftime('%A %d %B %Y')} (UTC)

DATA FROM ALL TRACKERS:
{context}

ANALYSIS SUMMARY:
- Coldest model: {analysis.get('coldest_model', 'N/A').upper()} at {analysis.get('coldest_temp', 0):.1f}C
- Warmest model: {analysis.get('warmest_model', 'N/A').upper()} at {analysis.get('warmest_temp', 0):.1f}C
- Temperature spread: {analysis.get('temp_spread', 0):.1f}C across models
- Timing agreement: {'Yes - all models agree' if analysis.get('date_agreement') else 'No - models differ on timing'}

WRITE A SYNTHESIS POST (max 800 chars, will be split into thread):

STYLE:
- This is a MANUAL post for significant events - make it count
- Lead with the headline: what's the main story across all models?
- Highlight agreement: "All 7 models now pointing to cold spell late January"
- Highlight divergence: "ICON shows earlier cold (-5C Sat 25th), GFS holds off until Mon 27th"
- Note data freshness if relevant (e.g., "UKMO freshest at 30min old")
- Be specific with dates and temperatures
- NO emoji, NO sensationalism
- Factual, measured tone

FORMAT:
- Start DIRECTLY with the story - no preamble, no "Here's a synthesis", no meta-commentary
- Can mention specific model names when highlighting differences
- End with what to watch for in upcoming model runs
- Output ONLY the post text - nothing else. No questions, no "would you like", no explanations.

Post text (output ONLY this, nothing else):"""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout.strip()
            # Strip markdown formatting (Bluesky doesn't support it)
            import re
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold** -> bold
            text = re.sub(r'\*([^*]+)\*', r'\1', text)       # *italic* -> italic
            text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)  # Remove --- lines
            text = re.sub(r'\n{3,}', '\n\n', text)  # Collapse multiple newlines
            return text.strip()

    except Exception as e:
        print(f"Claude error: {e}")

    # Fallback
    return f"Cross-tracker synthesis: {analysis.get('coldest_model', 'N/A').upper()} coldest at {analysis.get('coldest_temp', 0):.1f}C, {analysis.get('warmest_model', 'N/A').upper()} mildest at {analysis.get('warmest_temp', 0):.1f}C. Spread: {analysis.get('temp_spread', 0):.1f}C across models."


def split_into_posts(text: str, max_chars: int = 290) -> list:
    """Split text into posts at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    posts = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            posts.append(remaining.strip())
            break

        chunk = remaining[:max_chars]

        # Find sentence break
        for end in ['. ', '! ', '? ']:
            idx = chunk.rfind(end)
            if idx > max_chars // 2:
                posts.append(remaining[:idx + 1].strip())
                remaining = remaining[idx + 2:].strip()
                break
        else:
            # No sentence break - find word boundary
            idx = chunk.rfind(' ')
            if idx > max_chars // 2:
                posts.append(remaining[:idx].strip())
                remaining = remaining[idx + 1:].strip()
            else:
                posts.append(remaining[:max_chars].strip())
                remaining = remaining[max_chars:].strip()

    return posts


def add_thread_numbers(posts: list) -> list:
    """Add [X/Y] numbering to posts."""
    if len(posts) <= 1:
        return posts

    total = len(posts)
    result = []
    for i, post in enumerate(posts):
        indicator = f"[{i+1}/{total}] "
        max_content = 300 - len(indicator)
        if len(post) > max_content:
            post = post[:max_content - 3].rstrip() + "..."
        result.append(indicator + post)

    return result


def post_thread(posts: list, client, dry_run: bool = True) -> bool:
    """Post thread to Bluesky."""
    if dry_run:
        return True

    try:
        root = None
        parent = None

        for i, text in enumerate(posts):
            text = text.strip()[:300]

            reply_ref = None
            if parent:
                parent_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
                    uri=parent['uri'], cid=parent['cid']
                )
                root_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
                    uri=root['uri'], cid=root['cid']
                )
                reply_ref = atproto_models.AppBskyFeedPost.ReplyRef(
                    parent=parent_ref, root=root_ref
                )

            response = client.send_post(text=text, reply_to=reply_ref)
            print(f"  Posted {i+1}/{len(posts)}: {response.uri}")

            # Register post
            if HAS_REGISTRY and register_post:
                register_post(
                    uri=response.uri,
                    tracker='cross_tracker',
                    model='synthesis',
                    text_preview=text[:100]
                )

            if root is None:
                root = {'uri': response.uri, 'cid': response.cid}
            parent = {'uri': response.uri, 'cid': response.cid}

        return True

    except Exception as e:
        print(f"Bluesky error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='WXD Cross-Tracker Synthesis')
    parser.add_argument('--post', action='store_true', help='Actually post (default is dry-run)')
    parser.add_argument('--preview', action='store_true', help='Show detailed preview')
    args = parser.parse_args()

    dry_run = not args.post

    print(f"WXD Cross-Tracker Synthesis - {utcnow().isoformat()}")
    if dry_run:
        print("DRY RUN MODE - will NOT post\n")
    else:
        print("LIVE MODE - will post to Bluesky\n")

    # Load all tracker data
    print("Loading all tracker data...")
    models_data = load_all_models()
    print(f"  Loaded {len(models_data)} models: {', '.join(models_data.keys())}")

    if not models_data:
        print("ERROR: No model data available")
        return 1

    # Build context
    print("\nBuilding comparison context...")
    context = build_comparison_context(['all'])
    print(f"  Context: {len(context)} chars")

    # Analyze
    print("\nAnalyzing agreement/divergence...")
    analysis = find_agreement_and_divergence(models_data)
    print(f"  Coldest: {analysis.get('coldest_model', 'N/A').upper()} at {analysis.get('coldest_temp', 0):.1f}C")
    print(f"  Warmest: {analysis.get('warmest_model', 'N/A').upper()} at {analysis.get('warmest_temp', 0):.1f}C")
    print(f"  Spread: {analysis.get('temp_spread', 0):.1f}C")

    # Generate commentary
    print("\nGenerating Claude commentary...")
    commentary = generate_synthesis_commentary(context, analysis)
    print(f"  Generated {len(commentary)} chars")

    # Split into posts
    posts = split_into_posts(commentary)
    posts = add_thread_numbers(posts)
    print(f"  Split into {len(posts)} post(s)")

    # Preview
    print("\n" + "=" * 50)
    print("PREVIEW:")
    print("=" * 50)
    for i, post in enumerate(posts):
        print(f"\n--- Post {i+1}/{len(posts)} ({len(post)} chars) ---")
        print(post)
    print("\n" + "=" * 50)

    if dry_run:
        print("\n[DRY RUN] Would post the above thread")
        return 0

    # Post
    print("\nPosting to Bluesky...")
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    if not bsky_handle or not bsky_password:
        print("ERROR: BSKY_HANDLE and BSKY_PASSWORD must be set")
        return 1

    client = Client()
    client.login(bsky_handle, bsky_password)
    print(f"  Authenticated as {bsky_handle}")

    if post_thread(posts, client, dry_run=False):
        print("\nSynthesis thread posted successfully!")
        return 0
    else:
        print("\nFailed to post synthesis thread")
        return 1


if __name__ == '__main__':
    exit(main())
