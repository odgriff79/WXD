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
from datetime import datetime, timezone
from typing import List, Tuple, Optional
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Try to import Met Office fetcher
try:
    from daily_summary import fetch_metoffice_narrative
    HAS_METOFFICE = True
except ImportError:
    HAS_METOFFICE = False
    fetch_metoffice_narrative = None

# Try to import atproto for Bluesky
try:
    from atproto import Client, models as atproto_models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False

# Thresholds for determining significance
COLD_THRESHOLD = -5
EXTREME_COLD = -8


def fetch_current_warnings() -> str:
    """Fetch and format current Met Office warnings for Claude prompt.
    
    Returns formatted string with all warning details, or empty string if none.
    """
    if not HAS_METOFFICE or not fetch_metoffice_narrative:
        return ""
    
    try:
        mo_data = fetch_metoffice_narrative()
        
        warnings_parts = []

        # UK warnings with dates and regions (from dedicated warnings page - reliable)
        uk_warn = mo_data.get("uk_warnings", "")
        if uk_warn and "No warnings" not in uk_warn:
            warnings_parts.append("ACTIVE UK WARNINGS (Met Office): " + uk_warn)

        # NOTE: long_range_warning REMOVED - was producing false positives by
        # incorrectly linking generic warning banners with unrelated date ranges

        if warnings_parts:
            return "MET OFFICE WARNINGS (VERIFIED FROM OFFICIAL SOURCE): " + " | ".join(warnings_parts)
        else:
            return "MET OFFICE WARNINGS: None currently in force. DO NOT invent or assume warnings."

    except Exception as e:
        print(f"  Warning fetch error: {e}")
        return ""


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

        # Truncate if needed (mandatory numbering) - at word boundary
        if len(post) > max_content:
            truncated = post[:max_content - 3]
            last_space = truncated.rfind(' ')
            if last_space > max_content // 2:
                post = truncated[:last_space].rstrip() + "..."
            else:
                post = truncated.rstrip() + "..."

        result.append(indicator + post)

    return result


def generate_commentary(
    model_name: str,
    full_context: str,
    cold_info: dict,
    trend_analysis: dict,
    run_diff: dict = None,
    is_ensemble: bool = True,
    previous_post: str = None
) -> Tuple[str, bool]:
    """Generate Claude CLI commentary with story-first prompt.

    Args:
        model_name: Display name (e.g., "ICON", "UKMO", "MOGREPS")
        full_context: Analysis context string from run_full_analysis
        cold_info: Cold threshold check result
        trend_analysis: Trend persistence result
        run_diff: Run-on-run shift result
        is_ensemble: Whether this is an ensemble model
        previous_post: Text of the previous post from this tracker (for narrative continuity)

    Returns:
        Tuple of (commentary_text, is_fallback)
    """
    # Determine if significant event (more chars allowed)
    significant = is_significant_event(cold_info, trend_analysis)
    max_chars = 450 if significant else 290

    # Build story-first prompt
    model_desc = f"{model_name} ensemble" if is_ensemble else f"{model_name} model"
    member_info = " (40 members)" if model_name == "ICON" else " (18 members)" if model_name == "MOGREPS" else ""

    # Fetch current Met Office warnings
    warnings_data = fetch_current_warnings()

    # Build previous post context for narrative continuity
    if previous_post:
        # Strip run count noise from previous post (legacy cleanup)
        import re
        cleaned_prev = re.sub(r'\d+ consecutive runs( now)?', 'consistent signal', previous_post)
        cleaned_prev = re.sub(r'run #?\d+', 'latest run', cleaned_prev)

        previous_post_section = f"""
YOUR PREVIOUS POST (for narrative continuity):
{cleaned_prev}

NARRATIVE CONTINUITY - DATA IS TRUTH:
- Previous post is CONTEXT only - current ANALYSIS data is the source of truth
- Compare what you said before against what the data NOW shows
- If data confirms previous forecast: "Cold persisting as expected" / "Warming signal strengthening"
- If data contradicts previous post: acknowledge the change - "Models have shifted warmer/colder since last update"
- If previous post mentioned a feature not in current data, DO NOT repeat it - note it has dropped out
- Vary your language - don't use the same phrases as before
- Show EVOLUTION based on what data supports, not what was said before
"""
    else:
        previous_post_section = ""

    # Get current date for prompt context
    now_for_prompt = datetime.now(timezone.utc)
    today_str = now_for_prompt.strftime("%A %d %B %Y")  # e.g., "Sunday 04 January 2026"

    prompt = f"""You are WXD, a weather ensemble analysis bot. Write commentary on this {model_desc}{member_info} 850hPa temperature data for London.

TODAY IS: {today_str} (UTC)

Write a Bluesky post (max {max_chars} chars). This post will be followed by any relevant alerts as thread replies.

DATE REFERENCES - CRITICAL:
- NEVER use vague terms like "the weekend", "Saturday", "next week" without explicit dates
- ALWAYS include the date number: "Saturday 4th", "Sun-Mon 5th-6th", "by Wednesday 8th"
- If today is Saturday/Sunday, "the weekend" is NOW or YESTERDAY - be explicit
- Example BAD: "cold for the weekend" or "by Saturday" (which one? past or future?)
- Example GOOD: "cold locked in through Sunday 5th" or "sharp cold arriving Friday 10th"

STYLE:
- NO PREFIX - don't start with "{model_name}:" or "London 850hPa..." or similar. Just start talking.
- FORECAST FOCUS: The value is predicting what's COMING, not reporting current weather
- If today matches what we've been tracking, acknowledge briefly then pivot to what's NEXT
- Today as context: "Cold holding as forecast, models now show recovery by Thursday 16th"
- Today as revelation (BAD): "Cold peak arriving today!" - we knew this was coming, that's not news
- NEVER use "arriving" for something we've tracked for days/weeks - use "holding", "as forecast", "as tracked"
- Don't parrot the example phrases verbatim every time - vary your language with natural synonyms that don't sound pretentious
- The chart shows days 1-7+, your commentary should cover that range
- Mention model agreement/disagreement and what changed since last run
- Can mention ONE key temperature to anchor the story

PEAK TIMING - CRITICAL (READ THIS CAREFULLY):
- The ANALYSIS below contains "PEAK TIMING:" which tells you if the coldest point is PAST, TODAY, or FUTURE
- If PEAK TIMING says "PAST": STOP. The cold peak HAS ALREADY HAPPENED. You MUST NOT say "peak arriving", "cold holding", "peak persisting". The correct framing is "peak passed [date], now warming" or "cold easing after [date] peak"
- If PEAK TIMING says "TODAY": The peak is NOW. Say "peak today" or "coldest point today", NOT "peak arriving"
- If PEAK TIMING says "FUTURE": You CAN say "cold arriving" or "peak approaching"
- VIOLATION: Any post saying "peak arriving/holding/persisting" when PEAK TIMING is PAST will be WRONG

MULTI-RUN TRENDS - IMPORTANT:
- If ANALYSIS contains "MULTI-RUN TREND:", this means multiple consecutive runs show the same direction
- Progressive cooling = each run getting colder - YOU MUST MENTION THIS ("models trending colder over recent runs")
- Progressive warming = each run getting warmer - YOU MUST MENTION THIS ("models trending warmer over recent runs")
- This is different from single run-to-run shift - it shows SUSTAINED model drift

END-OF-FORECAST TRENDS - IMPORTANT:
- If ANALYSIS contains "END-OF-FORECAST:", there's a late trend reversal at the end of the forecast period
- Late cold return = temps dropping at very end - MENTION THIS ("cold returning by end of period")
- Late warming = temps rising at very end - MENTION THIS ("warming appearing at end of period")
- Do NOT ignore the end of the forecast just because the near-term is the main story

SIGNAL AND TIMING FRAMEWORK:
- SIGNAL tells you event confidence: "strongly supported" = certain it's happening, "strong" = very likely, "emerging" = developing
- TIMING tells you the date window and spread (e.g., "Jan 3-5, +/-2 days")
- NEVER say "confidence low" when SIGNAL is "strongly supported" - the event IS happening, only timing varies
- When signal is strongly supported/strong, lead with certainty: "Cold highly likely for next week" not "Cold possible"
- Use the TIMING window as a range: "coldest period Jan 3-5" not "coldest on Jan 4"
- If models agree on event but differ on exact day, that's NORMAL for 5+ day forecasts - not low confidence

CLARITY ON TIMEFRAMES:
- If PERIODS shows uniform pattern (cold/mild throughout), say that
- If PERIODS shows divergent pattern, mention short-term vs mid/extended outlook
- Mention ensemble spread if relevant (high agreement vs wide spread)

EXTENDED RANGE COVERAGE - CRITICAL:
- Do NOT ignore days 5-10+ just because the main story is near-term
- If the extended range shows a trend reversal (warming after cold, or vice versa), MENTION IT
- When cold is the headline, note if milder conditions return later in the period
- When mild is the headline, note if cold signals appear in the extended range
- If "recovering" pattern detected, YOU MUST mention the warming trend
- Check the RANGE for each period - if max temp is much higher than min, that's warming
- NEVER describe a period as just "cold" if the max shows significant warming
- Example: "Sharp cold through Sunday 5th, but models hint at milder conditions returning around 10th-12th"

TEMPERATURE OSCILLATIONS - IMPORTANT:
- A forecast may show multiple significant temperature swings: cold→warm→cold or warm→cold→warm
- If PATTERN shows oscillation (e.g., "cold -> recovering -> cold"), describe ALL transitions
- Example: "Sharp cold Mon-Tue 6th-7th, brief warming Wed 8th to -1C, then another cold dip by Sat 11th"
- Each significant swing (>3C) deserves mention if it indicates a trend shift
- Don't just pick the coldest point - show the journey through the forecast period

LANGUAGE:
- Use varied, natural language - avoid repetitive phrasing
- Synonyms for confidence: highly likely, well-supported, consistently shown, strongly indicated
- Synonyms for change: adjustment, shift, revision, movement
- Synonyms for notable: marked, significant, appreciable, considerable
- Avoid sensational terms: dramatic, slammed, plunged, locked in
- NEVER mention run counts like "47 consecutive runs" or "run 48" - these are noise. If signal is consistent, say "consistent signal" or "well-supported pattern"

MET OFFICE WARNINGS - ABSOLUTE RULES (VIOLATION = MISINFORMATION):
- ONLY mention warnings if the text "MET OFFICE WARNINGS (VERIFIED" appears in this prompt
- If warning data says "None currently in force" - DO NOT mention warnings AT ALL. Not even "no warnings". Just don't mention warnings.
- If warning data IS provided with actual warnings, you MUST QUOTE VERBATIM:
  * Type: Yellow/Amber/Red (exact color from data)
  * Hazard: Snow/Ice/Rain/Wind (exact hazard from data)
  * Issuer: "Met Office" (ALWAYS attribute)
  * Dates: COPY EXACTLY from the data - do not paraphrase
  * Regions: COPY EXACTLY from the data - do not paraphrase
- NEVER fabricate, extrapolate, or assume warning details beyond what's explicitly provided
- NEVER mention "long-range warnings" unless explicitly stated in the data
- NEVER say "warnings expected", "warnings likely", "warnings issued for [future date]", or "warnings in place"
- NEVER say "Yellow warning" without the exact dates and regions from the data
- If you cannot COPY VERBATIM from the warning data, DO NOT mention any warning
- TEST: Can you point to the exact text in this prompt that supports your warning claim? If not, DELETE IT.

EVIDENCE-BASED CLAIMS - CRITICAL:
- Every factual claim must be traceable to the ANALYSIS data below
- If you state a temperature, it must appear in the data
- If you state a date range, it must appear in the data
- If you mention model agreement/disagreement, it must be in the data
- DO NOT infer, extrapolate, or assume information not explicitly provided
- When uncertain, be vaguer rather than more specific

ANALYSIS:
{full_context}
{warnings_data}
{previous_post_section}
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

            # Truncate at sentence boundary if too long (don't cut mid-sentence)
            if len(text) > max_chars:
                # Find last sentence end within limit
                truncated = text[:max_chars]
                last_period = truncated.rfind('. ')
                if last_period > max_chars // 2:
                    text = truncated[:last_period + 1].strip()
                else:
                    # No good sentence break - find last space
                    last_space = truncated.rfind(' ')
                    if last_space > max_chars // 2:
                        text = truncated[:last_space].strip()
                    # else just use the hard cut

            return text, False

    except Exception as e:
        print(f"  Claude CLI error: {e}")

    # Fallback - still story-first style
    if cold_info:
        temp = cold_info.get('temp', '?')
        date = cold_info.get('date', 'soon')
        temp_desc = "ensemble mean" if is_ensemble else "forecast"
        return f"Cold signal in {model_name} data - {temp_desc} reaches {temp}C around {date}. More details in the analysis below.", True
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
    is_ensemble: bool,
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
            temp_desc = "ensemble mean" if is_ensemble else "forecast"
            alerts.append(f"Extreme cold signal: {model_name} {temp_desc} drops to {temp}C around {date}. This is below the -8C threshold for notable cold.")
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

    # Persistence alert - only at meaningful milestones, not every post
    # Skip the dedicated persistence post entirely - Claude already has this info
    # and will mention it naturally when relevant. The constant "run 47, run 48..."
    # was noise that added no value.
    #
    # If we want persistence alerts back, trigger only at milestones:
    # e.g., if runs in [7, 14, 21, 30] (weekly milestones)

    return alerts


def generate_full_thread(
    model_name: str,
    full_context: str,
    cold_info: dict,
    trend_analysis: dict,
    percentile_analysis: dict = None,
    run_diff: dict = None,
    is_ensemble: bool = True,
    previous_post: str = None
) -> Tuple[List[str], bool]:
    """Generate complete thread with main post and alerts.

    Args:
        previous_post: Text of previous post from this tracker for narrative continuity

    Returns:
        Tuple of (list of numbered posts, is_fallback)
    """
    # Generate main commentary
    main_text, is_fallback = generate_commentary(
        model_name, full_context, cold_info, trend_analysis, run_diff, is_ensemble, previous_post
    )

    # Split main text if needed
    main_posts = split_for_posting(main_text)

    # Build alert posts
    alerts = build_alert_posts(is_ensemble, model_name, cold_info, percentile_analysis, trend_analysis)

    # Combine all posts
    all_posts = main_posts + alerts

    # Add thread numbering
    numbered_posts = add_thread_numbers(all_posts)

    return numbered_posts, is_fallback
