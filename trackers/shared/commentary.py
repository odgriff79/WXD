#!/usr/bin/env python3
"""
WXD Shared Commentary Module

Common commentary generation for all trackers:
- Story-first Claude prompts (no prefixes)
- Dynamic character limits (450 for significant events)
- Thread splitting with sentence boundaries
- Thread numbering [X/Y]
- Bluesky posting with threading support
"""

import subprocess
from typing import List, Tuple, Optional

# Try to import atproto for Bluesky
try:
    from atproto import Client, models as atproto_models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False

# Thresholds for determining significance
COLD_THRESHOLD = -5
EXTREME_COLD = -8


def is_significant_event(cold_info: dict, trend_analysis: dict) -> bool:
    """Determine if this is a significant weather event warranting longer posts.

    Significant if:
    - Extreme cold (<-8C)
    - Cold persisting 3+ runs
    - Any cold signal present
    """
    if not cold_info:
        return False

    temp = cold_info.get('temp')
    if temp is not None and temp <= EXTREME_COLD:
        return True

    if trend_analysis and trend_analysis.get('cold_persistence', 0) >= 3:
        return True

    # Any cold signal is worth more space
    if temp is not None and temp < COLD_THRESHOLD:
        return True

    return False


def split_for_posting(text: str, max_chars: int = 290) -> List[str]:
    """Split text into posts, breaking at sentence boundaries.

    Args:
        text: Full text to split
        max_chars: Maximum characters per post (default 290 to leave room for [X/Y])

    Returns:
        List of post texts
    """
    if len(text) <= max_chars:
        return [text]

    posts = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            posts.append(remaining)
            break

        # Find last sentence break within limit
        chunk = remaining[:max_chars]
        last_period = chunk.rfind('. ')

        if last_period > max_chars // 2:
            posts.append(remaining[:last_period + 1].strip())
            remaining = remaining[last_period + 2:].strip()
        else:
            # No good break point - break at space
            last_space = chunk.rfind(' ')
            if last_space > 0:
                posts.append(remaining[:last_space].strip() + "...")
                remaining = remaining[last_space + 1:].strip()
            else:
                posts.append(chunk + "...")
                remaining = remaining[max_chars:].strip()

    return posts


def add_thread_numbers(posts: List[str]) -> List[str]:
    """Add [X/Y] numbering to start of each post.

    Only adds if >1 post. Truncates content if needed to fit.
    """
    if len(posts) <= 1:
        return posts

    total = len(posts)
    result = []

    for i, post in enumerate(posts):
        indicator = f"[{i+1}/{total}] "
        max_content = 300 - len(indicator)

        # Truncate if needed (mandatory numbering)
        if len(post) > max_content:
            post = post[:max_content - 3].rstrip() + "..."

        result.append(indicator + post)

    return result


def generate_commentary(
    model_name: str,
    full_context: str,
    cold_info: dict,
    trend_analysis: dict,
    run_diff: dict = None,
    is_ensemble: bool = True
) -> Tuple[str, bool]:
    """Generate Claude CLI commentary with story-first prompt.

    Args:
        model_name: Display name (e.g., "ICON", "UKMO", "MOGREPS")
        full_context: Analysis context string from run_full_analysis
        cold_info: Cold threshold check result
        trend_analysis: Trend persistence result
        run_diff: Run-on-run shift result
        is_ensemble: Whether this is an ensemble model

    Returns:
        Tuple of (commentary_text, is_fallback)
    """
    # Determine if significant event (more chars allowed)
    significant = is_significant_event(cold_info, trend_analysis)
    max_chars = 450 if significant else 290

    # Build story-first prompt
    model_desc = f"{model_name} ensemble" if is_ensemble else f"{model_name} model"
    member_info = " (40 members)" if model_name == "ICON" else " (18 members)" if model_name == "MOGREPS" else ""

    prompt = f"""You are WXD, a weather ensemble analysis bot. Write commentary on this {model_desc}{member_info} 850hPa temperature data for London.

Write a Bluesky post (max {max_chars} chars). This post will be followed by any relevant alerts as thread replies.

STYLE:
- NO PREFIX - don't start with "{model_name}:" or "London 850hPa..." or similar. Just start talking.
- Lead with the STORY: what's happening, what's changing, what it means
- Commentary first, not data dump - avoid leading with specific temperatures
- Example good: "Cold air arriving for New Year as {model_name} now shows a significant drop."
- Example bad: "{model_name} shows -7.2C..." or "London temps..." (wastes characters)
- Mention model agreement/disagreement and what changed since last run
- Can mention ONE key temperature to anchor the story

SIGNAL AND TIMING FRAMEWORK:
- SIGNAL tells you event confidence: "locked" = certain it's happening, "strong" = very likely, "emerging" = developing
- TIMING tells you the date window and spread (e.g., "Jan 3-5, +/-2 days")
- NEVER say "confidence low" when SIGNAL is "locked" - the event IS happening, only timing varies
- When signal is locked/strong, lead with certainty: "Cold locked in for next week" not "Cold possible"
- Use the TIMING window as a range: "coldest period Jan 3-5" not "coldest on Jan 4"
- If models agree on event but differ on exact day, that's NORMAL for 5+ day forecasts - not low confidence

CLARITY ON TIMEFRAMES:
- If PERIODS shows uniform pattern (cold/mild throughout), say that
- If PERIODS shows divergent pattern, mention short-term vs mid/extended outlook
- Mention ensemble spread if relevant (high agreement vs wide spread)

ANALYSIS:
{full_context}

FORMAT: Plain text, no emojis, use C for temps. Start immediately with the story."""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            input=None,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0 and result.stdout.strip():
            # Clean up any accidental prefix Claude might add
            text = result.stdout.strip()
            prefixes_to_remove = [f"{model_name}:", f"{model_name.lower()}:", "London 850hPa:"]
            for prefix in prefixes_to_remove:
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
            return text[:max_chars], False

    except Exception as e:
        print(f"  Claude CLI error: {e}")

    # Fallback - still story-first style
    if cold_info:
        temp = cold_info.get('temp', '?')
        date = cold_info.get('date', 'soon')
        return f"Cold signal in {model_name} data - ensemble mean reaches {temp}C around {date}. More details in the analysis below.", True
    elif run_diff:
        shift = abs(run_diff.get('shift', 0))
        direction = run_diff.get('direction', 'changed')
        return f"Latest {model_name} run has shifted {shift}C {direction} since the previous update.", True
    else:
        return f"No significant changes in the latest {model_name} run.", True


def post_thread_to_bluesky(
    posts: List[str],
    image_path: str = None,
    handle: str = None,
    password: str = None,
    alt_text: str = "850hPa temperature forecast chart"
) -> bool:
    """Post a thread to Bluesky with optional image on first post.

    Args:
        posts: List of post texts (already numbered with [X/Y])
        image_path: Optional path to chart image
        handle: Bluesky handle
        password: App password
        alt_text: Alt text for image

    Returns:
        True if successful
    """
    if not HAS_ATPROTO or not handle or not password:
        return False

    try:
        from pathlib import Path

        client = Client()
        client.login(handle, password)

        root = None
        parent = None

        for i, text in enumerate(posts):
            text = text.strip()[:300]  # Ensure within limit

            # Build reply reference if threading
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

            # Attach image to first post only
            if i == 0 and image_path:
                img_path = Path(image_path)
                if img_path.exists():
                    with open(img_path, 'rb') as f:
                        img_data = f.read()
                    upload = client.upload_blob(img_data)
                    embed = atproto_models.AppBskyEmbedImages.Main(
                        images=[atproto_models.AppBskyEmbedImages.Image(
                            alt=alt_text,
                            image=upload.blob
                        )]
                    )
                    response = client.send_post(text=text, embed=embed, reply_to=reply_ref)
                else:
                    response = client.send_post(text=text, reply_to=reply_ref)
            else:
                response = client.send_post(text=text, reply_to=reply_ref)

            print(f"  Posted {i+1}/{len(posts)}")

            if root is None:
                root = {'uri': response.uri, 'cid': response.cid}
            parent = {'uri': response.uri, 'cid': response.cid}

        return True

    except Exception as e:
        print(f"  Bluesky error: {e}")
        return False


def build_alert_posts(
    model_name: str,
    cold_info: dict,
    percentile_analysis: dict = None,
    trend_analysis: dict = None
) -> List[str]:
    """Build alert posts for significant events.

    Returns list of alert post texts (without numbering - caller adds that).
    """
    alerts = []

    # Cold alert
    if cold_info:
        temp = cold_info.get('temp', '?')
        date = cold_info.get('date', '?')
        extreme = cold_info.get('extreme', False)

        if extreme:
            alerts.append(f"Extreme cold signal: {model_name} ensemble mean drops to {temp}C around {date}. This is below the -8C threshold for notable cold.")
        elif temp is not None and temp < COLD_THRESHOLD:
            alerts.append(f"Cold alert: {model_name} shows {temp}C around {date}, crossing the -5C threshold.")

    # Ensemble agreement alert (for ensemble models)
    if percentile_analysis and percentile_analysis.get('agreement_level'):
        level = percentile_analysis['agreement_level']
        spread = percentile_analysis.get('spread_at_coldest', '?')

        if level == 'high' and cold_info:
            alerts.append(f"High ensemble agreement: Members tightly clustered with only {spread}C spread at the coldest point. Strong confidence in this forecast.")
        elif level == 'low':
            alerts.append(f"Wide ensemble spread: {spread}C range at coldest point indicates higher uncertainty. Expect adjustments in coming runs.")

    # Persistence alert
    if trend_analysis and trend_analysis.get('cold_persistence', 0) >= 3:
        runs = trend_analysis['cold_persistence']
        alerts.append(f"Signal persistence: Cold signal now showing for {runs} consecutive runs, indicating stable pattern.")

    return alerts


def generate_full_thread(
    model_name: str,
    full_context: str,
    cold_info: dict,
    trend_analysis: dict,
    percentile_analysis: dict = None,
    run_diff: dict = None,
    is_ensemble: bool = True
) -> Tuple[List[str], bool]:
    """Generate complete thread with main post and alerts.

    Returns:
        Tuple of (list of numbered posts, is_fallback)
    """
    # Generate main commentary
    main_text, is_fallback = generate_commentary(
        model_name, full_context, cold_info, trend_analysis, run_diff, is_ensemble
    )

    # Split main text if needed
    main_posts = split_for_posting(main_text)

    # Build alert posts
    alerts = build_alert_posts(model_name, cold_info, percentile_analysis, trend_analysis)

    # Combine all posts
    all_posts = main_posts + alerts

    # Add thread numbering
    numbered_posts = add_thread_numbers(all_posts)

    return numbered_posts, is_fallback
