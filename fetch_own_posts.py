#!/usr/bin/env python3
"""
WXD Post History Fetcher

Fetches WXD's own post history from Bluesky using the getAuthorFeed API.
Uses cursor pagination to retrieve all posts.

Usage:
    python fetch_own_posts.py                      # Fetch all posts, save to data/post_history.json
    python fetch_own_posts.py --limit 50           # Fetch only 50 most recent posts
    python fetch_own_posts.py --dry-run            # Preview what would be fetched (no save)
    python fetch_own_posts.py --stats              # Show statistics only

Filtering (post-fetch):
    python fetch_own_posts.py --since 2025-12-30   # Only posts since date
    python fetch_own_posts.py --until 2025-12-31   # Only posts until date
    python fetch_own_posts.py --search "cold"      # Find posts containing text
    python fetch_own_posts.py --originals          # Exclude replies
    python fetch_own_posts.py --with-images        # Only posts with images

Combined example (audit cron job):
    python fetch_own_posts.py --since 2025-12-31T09:00 --until 2025-12-31T10:00 --dry-run
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from atproto import Client
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fetch_author_feed(client: Client, actor: str, limit: int = None, cursor: str = None,
                       filter_type: str = None) -> dict:
    """Fetch posts from an author's feed with pagination.

    Args:
        client: Authenticated atproto Client
        actor: Handle or DID of the author
        limit: Max posts per request (max 100)
        cursor: Pagination cursor from previous request
        filter_type: API filter - 'posts_no_replies', 'posts_with_media',
                     'posts_and_author_threads', or None for all

    Returns:
        dict with 'feed' (list of posts) and 'cursor' (for next page)
    """
    params = {'actor': actor}
    if limit:
        params['limit'] = min(limit, 100)  # API max is 100
    if cursor:
        params['cursor'] = cursor
    if filter_type:
        params['filter'] = filter_type

    response = client.app.bsky.feed.get_author_feed(params)
    return response


def extract_post_data(feed_item: dict) -> dict:
    """Extract relevant data from a feed item."""
    post = feed_item.post
    record = post.record

    # Parse created_at timestamp
    created_at = record.created_at if hasattr(record, 'created_at') else None

    # Get text content
    text = record.text if hasattr(record, 'text') else ''

    # Check for images
    has_image = False
    image_count = 0
    if hasattr(post, 'embed') and post.embed:
        embed_type = getattr(post.embed, '$type', '') or str(type(post.embed))
        if 'images' in embed_type.lower() or hasattr(post.embed, 'images'):
            has_image = True
            if hasattr(post.embed, 'images'):
                image_count = len(post.embed.images) if post.embed.images else 0

    # Check if it's a reply
    is_reply = hasattr(record, 'reply') and record.reply is not None
    reply_to = None
    if is_reply and hasattr(record.reply, 'parent'):
        reply_to = record.reply.parent.uri if hasattr(record.reply.parent, 'uri') else None

    # Engagement metrics
    like_count = post.like_count if hasattr(post, 'like_count') else 0
    repost_count = post.repost_count if hasattr(post, 'repost_count') else 0
    reply_count = post.reply_count if hasattr(post, 'reply_count') else 0

    return {
        'uri': post.uri,
        'cid': post.cid,
        'created_at': created_at,
        'text': text,
        'text_length': len(text),
        'has_image': has_image,
        'image_count': image_count,
        'is_reply': is_reply,
        'reply_to': reply_to,
        'like_count': like_count,
        'repost_count': repost_count,
        'reply_count': reply_count,
    }


def parse_datetime(dt_str: str) -> datetime:
    """Parse flexible datetime string to datetime object."""
    if not dt_str:
        return None

    # Try various formats
    formats = [
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M',
        '%Y-%m-%d',
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    raise ValueError(f"Could not parse datetime: {dt_str}")


def filter_posts(posts: list, since: str = None, until: str = None,
                 search: str = None) -> list:
    """Filter posts by date range and/or text search (client-side).

    Args:
        posts: List of post dicts
        since: Include only posts after this datetime
        until: Include only posts before this datetime
        search: Include only posts containing this text (case-insensitive)

    Returns:
        Filtered list of posts
    """
    result = posts

    if since:
        since_dt = parse_datetime(since)
        result = [p for p in result if p.get('created_at') and
                  parse_datetime(p['created_at'][:19]) >= since_dt]

    if until:
        until_dt = parse_datetime(until)
        result = [p for p in result if p.get('created_at') and
                  parse_datetime(p['created_at'][:19]) <= until_dt]

    if search:
        pattern = re.compile(re.escape(search), re.IGNORECASE)
        result = [p for p in result if pattern.search(p.get('text', ''))]

    return result


def fetch_all_posts(client: Client, actor: str, max_posts: int = None,
                    filter_type: str = None) -> list:
    """Fetch all posts from an author with pagination.

    Args:
        client: Authenticated atproto Client
        actor: Handle or DID
        max_posts: Maximum posts to fetch (None = all)
        filter_type: API filter (posts_no_replies, posts_with_media, etc)

    Returns:
        List of post data dicts
    """
    all_posts = []
    cursor = None
    page = 1

    while True:
        # Calculate batch size
        if max_posts:
            remaining = max_posts - len(all_posts)
            if remaining <= 0:
                break
            batch_size = min(100, remaining)
        else:
            batch_size = 100

        print(f"  Fetching page {page}...")
        response = fetch_author_feed(client, actor, limit=batch_size, cursor=cursor,
                                     filter_type=filter_type)

        feed = response.feed if hasattr(response, 'feed') else []
        if not feed:
            break

        for item in feed:
            post_data = extract_post_data(item)
            all_posts.append(post_data)

            if max_posts and len(all_posts) >= max_posts:
                break

        print(f"    Got {len(feed)} posts (total: {len(all_posts)})")

        # Check for next page
        cursor = response.cursor if hasattr(response, 'cursor') else None
        if not cursor:
            break

        if max_posts and len(all_posts) >= max_posts:
            break

        page += 1

    return all_posts


def calculate_stats(posts: list) -> dict:
    """Calculate statistics from post history."""
    if not posts:
        return {'total': 0}

    total = len(posts)
    with_images = sum(1 for p in posts if p.get('has_image'))
    replies = sum(1 for p in posts if p.get('is_reply'))
    original = total - replies

    total_likes = sum(p.get('like_count', 0) for p in posts)
    total_reposts = sum(p.get('repost_count', 0) for p in posts)
    total_replies = sum(p.get('reply_count', 0) for p in posts)

    # Date range
    dates = [p.get('created_at') for p in posts if p.get('created_at')]
    oldest = min(dates) if dates else None
    newest = max(dates) if dates else None

    # Average text length
    text_lengths = [p.get('text_length', 0) for p in posts]
    avg_length = sum(text_lengths) / len(text_lengths) if text_lengths else 0

    return {
        'total': total,
        'original_posts': original,
        'replies': replies,
        'with_images': with_images,
        'total_likes': total_likes,
        'total_reposts': total_reposts,
        'total_replies_received': total_replies,
        'avg_text_length': round(avg_length, 1),
        'oldest_post': oldest,
        'newest_post': newest,
    }


def main():
    parser = argparse.ArgumentParser(
        description='WXD Post History Fetcher',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
API Filters (server-side, efficient):
  --originals         Only original posts (no replies)
  --with-images       Only posts with media

Client Filters (post-fetch):
  --since DATE        Posts after DATE (2025-12-30 or 2025-12-30T09:00)
  --until DATE        Posts before DATE
  --search TEXT       Posts containing TEXT (case-insensitive)

Examples:
  # Find all cold-related posts
  python fetch_own_posts.py --search "cold" --dry-run

  # Audit posts from a specific cron window
  python fetch_own_posts.py --since 2025-12-31T09:00 --until 2025-12-31T10:00 --dry-run

  # Get only posts with charts
  python fetch_own_posts.py --with-images --stats
        """
    )
    parser.add_argument('--limit', '-l', type=int, help='Max posts to fetch (default: all)')
    parser.add_argument('--dry-run', '-n', action='store_true', help='Preview without saving')
    parser.add_argument('--stats', '-s', action='store_true', help='Show statistics only')
    parser.add_argument('--output', '-o', type=str, help='Output file path')

    # API filters (server-side)
    parser.add_argument('--originals', action='store_true', help='Exclude replies (API filter)')
    parser.add_argument('--with-images', action='store_true', help='Only posts with images (API filter)')

    # Client filters (post-fetch)
    parser.add_argument('--since', type=str, help='Posts after this date (YYYY-MM-DD or YYYY-MM-DDTHH:MM)')
    parser.add_argument('--until', type=str, help='Posts before this date')
    parser.add_argument('--search', type=str, help='Filter posts containing this text')

    args = parser.parse_args()

    if not HAS_ATPROTO:
        print("ERROR: atproto library not installed")
        print("Run: pip install atproto")
        return 1

    # Check credentials
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    if not bsky_handle or not bsky_password:
        print("ERROR: BSKY_HANDLE and BSKY_PASSWORD must be set")
        print("Source ~/.wxd_env first")
        return 1

    # Setup paths
    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)

    output_path = Path(args.output) if args.output else data_dir / "post_history.json"

    print(f"WXD Post History Fetcher - {utcnow().isoformat()}")
    print(f"Account: {bsky_handle}")
    if args.limit:
        print(f"Limit: {args.limit} posts")
    if args.dry_run:
        print("DRY RUN - will not save")

    # Determine API filter
    filter_type = None
    if args.originals:
        filter_type = 'posts_no_replies'
        print("API Filter: originals only (no replies)")
    elif args.with_images:
        filter_type = 'posts_with_media'
        print("API Filter: posts with media only")

    # Show client filters
    if args.since:
        print(f"Client Filter: since {args.since}")
    if args.until:
        print(f"Client Filter: until {args.until}")
    if args.search:
        print(f"Client Filter: search '{args.search}'")

    print()

    # Authenticate
    print("Authenticating with Bluesky...")
    try:
        client = Client()
        client.login(bsky_handle, bsky_password)
        print("  Authenticated successfully")
    except Exception as e:
        print(f"ERROR: Authentication failed: {e}")
        return 1

    # Fetch posts
    print()
    print("Fetching posts...")
    try:
        posts = fetch_all_posts(client, bsky_handle, max_posts=args.limit,
                                filter_type=filter_type)
    except Exception as e:
        print(f"ERROR: Failed to fetch posts: {e}")
        return 1

    print()
    print(f"Fetched {len(posts)} posts from API")

    # Apply client-side filters
    if args.since or args.until or args.search:
        posts = filter_posts(posts, since=args.since, until=args.until, search=args.search)
        print(f"After filtering: {len(posts)} posts")

    # Calculate statistics
    stats = calculate_stats(posts)

    print()
    print("Statistics:")
    print(f"  Total posts: {stats['total']}")
    print(f"  Original posts: {stats['original_posts']}")
    print(f"  Replies: {stats['replies']}")
    print(f"  Posts with images: {stats['with_images']}")
    print(f"  Total likes: {stats['total_likes']}")
    print(f"  Total reposts: {stats['total_reposts']}")
    print(f"  Total replies received: {stats['total_replies_received']}")
    print(f"  Avg text length: {stats['avg_text_length']} chars")
    if stats.get('oldest_post'):
        print(f"  Date range: {stats['oldest_post'][:10]} to {stats['newest_post'][:10]}")

    if args.stats:
        # Stats only mode - don't save
        return 0

    # Prepare output data
    output_data = {
        'fetched_at': utcnow().isoformat(),
        'account': bsky_handle,
        'stats': stats,
        'posts': posts,
    }

    # Save or preview
    if args.dry_run:
        print()
        print("=" * 50)
        print("PREVIEW - Most recent 5 posts:")
        print("=" * 50)
        for p in posts[:5]:
            print(f"\n[{p['created_at'][:19] if p['created_at'] else 'unknown'}]")
            text_preview = p['text'][:100] + "..." if len(p['text']) > 100 else p['text']
            print(f"  {text_preview}")
            print(f"  Likes: {p['like_count']} | Reposts: {p['repost_count']} | Replies: {p['reply_count']}")
    else:
        print()
        print(f"Saving to {output_path}...")
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        print(f"  Saved {len(posts)} posts")

    print()
    print("Complete")
    return 0


if __name__ == "__main__":
    exit(main())
