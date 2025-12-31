#!/usr/bin/env python3
"""
WXD Engagement Post System

Twice-weekly automated engagement posts covering:
- Weather education (850hPa, ensembles, model behavior)
- AI/tech explainers (how Claude works, automation)
- Project updates and features
- Community Q&A from collected replies
- Weather/forecasting news

Schedule: Sunday & Wednesday 18:00 UTC

Target audience: General public and weather enthusiasts with basic knowledge.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import random

# Try to import atproto for Bluesky
try:
    from atproto import Client, models as atproto_models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False


# Topic categories with example prompts
# NOTE: Topics should be reviewed based on current conditions
# Cold pattern active = prioritize cold_relevant and myth_busting topics
# Mild pattern = use general education topics
TOPIC_CATEGORIES = {
    "weather_education": {
        "name": "Weather Education",
        "topics": [
            "What is 850hPa and why do weather trackers use it instead of surface temperature?",
            "What's the difference between ensemble and deterministic weather models?",
            "Why do weather forecasts change between model runs?",
            "How far ahead can weather models reliably forecast?",
            "What causes a 'cold snap' and how do we see it coming in the data?",
            "Why do different weather models sometimes disagree?",
            "What is model 'spread' and what does it tell us about forecast confidence?",
            "How do weather models handle uncertainty?",
            "What's the difference between GFS, ECMWF, and other global models?",
            "Why is the jet stream important for UK winter weather?",
        ]
    },
    "cold_relevant": {
        "name": "Cold Weather Topics",
        "topics": [
            "What -8C at 850hPa actually means for temperatures at ground level",
            "When all 4 models agree on cold - what rare full convergence means for confidence",
            "Run-to-run tracking: why we watch how forecasts change between model updates",
            "Why models agree on the next few days but diverge after day 7",
            "Met Office warning levels explained - Yellow, Amber, Red and what they mean",
            "The jet stream and UK cold snaps - how blocking patterns push Arctic air south",
            "Snow vs ice risk - what conditions favour each type of hazard",
            "The Polar Vortex explained - what it actually is vs tabloid headlines",
            "Why London is milder than NYC or Moscow - the Gulf Stream keeps UK extremes in check",
        ]
    },
    "warm_relevant": {
        "name": "Warm Weather Topics",
        "topics": [
            "What 15C at 850hPa means for heatwave potential at ground level",
            "How WXD tracks summer heat the same way it tracks winter cold",
            "Why UK heatwaves are becoming more common and intense",
            "The Azores High and summer blocking patterns",
            "Heat health alerts - how the Met Office warns for dangerous temperatures",
            "Why humid heat feels worse than dry heat - the role of dewpoint",
            "Urban heat islands - why London can be 5C warmer than the countryside",
            "Night-time temperatures - why they matter for health during heatwaves",
            "Thunderstorm risk - when hot air becomes unstable",
        ]
    },
    "myth_busting": {
        "name": "Cutting Through Hype",
        "topics": [
            "Polar Vortex reality vs tabloid hype - no it is not attacking Britain",
            "Why snow bomb and weather bomb headlines are usually overblown",
            "Do not trust snow depth charts - why they are unreliable beyond 3 days",
            "Walls of snow and other tabloid favourites - what forecasters actually see",
            "Beast from the East comparisons - why every cold spell is not 2018",
            "Reading weather maps critically - spotting sensationalism",
            "Why coldest winter in decades predictions in autumn are meaningless",
            "Model outliers - why one run showing -20C does not mean it will happen",
        ]
    },
    "ai_tech": {
        "name": "AI & Technology",
        "topics": [
            "How does WXD use AI (Claude) to write weather commentary?",
            "What is an LLM and how does it help analyze weather data?",
            "How automation makes weather tracking possible 24/7",
            "The role of Python in modern weather data analysis",
            "How we fetch weather data from official sources automatically",
            "What makes AI-generated weather commentary different from human analysis?",
            "How we prevent AI from over-hyping weather forecasts",
            "The technology behind real-time weather chart generation",
            "Cloud computing and weather data - how WXD runs on a virtual machine",
            "Open source tools that make weather tracking accessible to everyone",
        ]
    },
    "project_updates": {
        "name": "Project Updates",
        "topics": [
            "Recent improvements to WXD tracking accuracy",
            "New features added to the WXD system",
            "Model comparison: which models have been most accurate recently?",
            "Behind the scenes: how WXD handles model run delays",
            "Upcoming features we're working on",
            "Lessons learned from tracking this winter's weather",
        ]
    },
    "weather_news": {
        "name": "Weather & Forecasting News",
        "topics": [
            "Recent developments in numerical weather prediction",
            "How AI is changing weather forecasting globally",
            "Open data initiatives making weather more accessible",
            "Climate patterns affecting current forecasts",
        ]
    }
}


def utcnow() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def get_weather_context() -> dict:
    """Read current weather state from summary_latest.json.

    Returns dict with:
        cold_signal: bool - is there an active cold signal?
        warm_signal: bool - is there an active warm signal?
        min_temp: float - coldest 850hPa temp in forecast
        max_temp: float - warmest 850hPa temp in forecast
        cold_anomaly: float - degrees below seasonal normal (positive = colder than normal)
        warm_anomaly: float - degrees above seasonal normal (positive = warmer than normal)
        anomaly_strength: str - 'extreme', 'significant', 'moderate', 'normal'
        model_agreement: str - 'high', 'medium', 'low'
        season: str - 'winter', 'summer', 'shoulder'
        warnings_active: bool - Met Office warnings in effect
    """
    # Seasonal 850hPa normals for London (recent 10-year averages)
    # UK has warmed significantly - -5°C is now unusual, -10°C is rare (last: Feb 2021)
    SEASONAL_NORMALS = {
        1: 2,    # Jan: ~2°C normal (was 0°C historically)
        2: 2,    # Feb: ~2°C
        3: 4,    # Mar: ~4°C
        4: 6,    # Apr: ~6°C
        5: 9,    # May: ~9°C
        6: 12,   # Jun: ~12°C
        7: 14,   # Jul: ~14°C
        8: 14,   # Aug: ~14°C
        9: 11,   # Sep: ~11°C
        10: 8,   # Oct: ~8°C
        11: 5,   # Nov: ~5°C
        12: 3,   # Dec: ~3°C (was 1°C historically)
    }

    # Determine season based on month
    month = utcnow().month
    if month in [12, 1, 2]:
        season = "winter"
    elif month in [6, 7, 8]:
        season = "summer"
    else:
        season = "shoulder"  # Spring/Autumn

    seasonal_normal = SEASONAL_NORMALS.get(month, 5)

    context = {
        "cold_signal": False,
        "warm_signal": False,
        "min_temp": None,
        "max_temp": None,
        "cold_anomaly": 0,
        "warm_anomaly": 0,
        "anomaly_strength": "normal",
        "model_agreement": "medium",
        "season": season,
        "seasonal_normal": seasonal_normal,
        "warnings_active": False,
    }

    # Try to read summary_latest.json
    summary_path = Path(__file__).parent.parent / "data" / "summary_latest.json"
    if not summary_path.exists():
        return context

    try:
        with open(summary_path, 'r') as f:
            data = json.load(f)

        # Get min and max temps from all models
        models = data.get('models', {})
        min_temps = []
        max_temps = []
        for model_name, model_data in models.items():
            if 'min' in model_data and isinstance(model_data['min'], list):
                model_min = min(model_data['min'])
                min_temps.append(model_min)
            if 'max' in model_data and isinstance(model_data['max'], list):
                model_max = max(model_data['max'])
                max_temps.append(model_max)

        if min_temps:
            coldest = min(min_temps)
            # Use 4-model mean for anomaly calculation (more robust than single coldest)
            mean_min = sum(min_temps) / len(min_temps)
            context["min_temp"] = round(coldest, 1)
            context["mean_min"] = round(mean_min, 1)
            # Calculate cold anomaly from MEAN (consensus), not single coldest model
            context["cold_anomaly"] = round(seasonal_normal - mean_min, 1)
            # Cold signal: mean >5°C below seasonal normal OR any model below -5°C
            context["cold_signal"] = context["cold_anomaly"] > 5 or coldest < -5.0

            # Check model agreement (spread of minimums)
            if len(min_temps) >= 2:
                spread = max(min_temps) - min(min_temps)
                context["model_spread"] = round(spread, 1)
                if spread < 3.0:
                    context["model_agreement"] = "high"
                elif spread > 6.0:
                    context["model_agreement"] = "low"

        if max_temps:
            warmest = max(max_temps)
            mean_max = sum(max_temps) / len(max_temps)
            context["max_temp"] = round(warmest, 1)
            context["mean_max"] = round(mean_max, 1)
            # Calculate warm anomaly from MEAN (consensus)
            context["warm_anomaly"] = round(mean_max - seasonal_normal, 1)
            # Warm signal: mean >5°C above seasonal normal OR any model above 15°C
            context["warm_signal"] = context["warm_anomaly"] > 5 or warmest > 15.0

        # Determine anomaly strength based on max deviation from normal
        max_anomaly = max(context["cold_anomaly"], context["warm_anomaly"])
        if max_anomaly >= 10:
            context["anomaly_strength"] = "extreme"
        elif max_anomaly >= 6:
            context["anomaly_strength"] = "significant"
        elif max_anomaly >= 3:
            context["anomaly_strength"] = "moderate"
        else:
            context["anomaly_strength"] = "normal"

    except Exception as e:
        print(f"  Warning: Could not read weather context: {e}")

    return context


def generate_community_request() -> str:
    """Generate Sunday community request post asking for topic suggestions."""
    return """What weather or forecasting topics would you like WXD to explain?

Follow us and reply with your questions - we can only see replies from followers. Popular topics covered Tuesday and Friday.

---

We're building automated community engagement so your questions shape our content. Models, forecasts, tabloid myth-busting - what interests you?"""


def load_state(state_path: Path) -> dict:
    """Load engagement state (topic history, collected questions)."""
    if state_path.exists():
        with open(state_path, 'r') as f:
            return json.load(f)
    return {
        "last_post": None,
        "topic_history": [],
        "collected_questions": [],
        "posts_count": 0
    }


def save_state(state_path: Path, state: dict) -> None:
    """Save engagement state."""
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


def get_recent_replies(handle: str, password: str, since_hours: int = 96) -> list:
    """Fetch recent replies/mentions to collect questions.

    Returns list of potential questions from community.
    """
    if not HAS_ATPROTO or not handle or not password:
        return []

    try:
        client = Client()
        client.login(handle, password)

        # Get notifications (mentions and replies)
        notifications = client.app.bsky.notification.list_notifications()

        questions = []
        cutoff = utcnow() - timedelta(hours=since_hours)

        for notif in notifications.notifications:
            # Check if it's a reply or mention
            if notif.reason in ['reply', 'mention']:
                # Parse timestamp
                try:
                    notif_time = datetime.fromisoformat(
                        notif.indexed_at.replace('Z', '+00:00')
                    )
                    if notif_time < cutoff:
                        continue
                except:
                    continue

                # Get the post text
                if hasattr(notif, 'record') and hasattr(notif.record, 'text'):
                    text = notif.record.text
                    # Check if it looks like a question
                    if '?' in text or any(word in text.lower() for word in
                        ['what', 'why', 'how', 'when', 'where', 'could you', 'can you']):
                        questions.append({
                            "text": text,
                            "author": notif.author.handle,
                            "time": notif.indexed_at,
                            "uri": notif.uri
                        })

        return questions

    except Exception as e:
        print(f"  Error fetching replies: {e}")
        return []


def select_topic_with_claude(weather_context: dict, available_topics: list) -> tuple:
    """Use Claude to select the most relevant topic given current weather.

    Returns (category, topic) or None if Claude fails.
    """
    # Build weather summary
    weather_summary = f"""Current weather context for London:
- Season: {weather_context.get('season')}
- 4-model mean minimum: {weather_context.get('mean_min')}°C (coldest model: {weather_context.get('min_temp')}°C)
- Cold anomaly: {weather_context.get('cold_anomaly', 0):+.1f}°C vs December normal of {weather_context.get('seasonal_normal')}°C
- Anomaly strength: {weather_context.get('anomaly_strength', 'normal')}
- Model agreement: {weather_context.get('model_agreement')}"""

    # Format topics
    topics_text = "\n".join([f"- [{cat}] {topic}" for cat, topic in available_topics])

    prompt = f"""WXD is a weather tracking bot. We post educational content twice weekly.

STRATEGY: Educational posts should be VARIED over time, but when significant weather events occur (like extreme cold or heat anomalies), we should capitalize on public interest by selecting topics that help followers understand what they're experiencing.

IMPORTANT - BALANCED APPROACH TO EXTREME WEATHER:

1) DEBUNK TABLOID HYPE: UK tabloids pump out exaggerated headlines ("SNOWMAGEDDON", "POLAR VORTEX ATTACKS BRITAIN"). Our myth_busting category counters this:
   - Don't believe snow depth charts beyond 3 days
   - "Beast from the East" comparisons are usually wrong
   - See through sensationalist headlines

2) BUT RESPECT OFFICIAL WARNINGS: Met Office Yellow/Amber/Red warnings ARE serious and evidence-based. Help followers understand:
   - Why the traffic light system matters
   - When to take warnings seriously vs ignore tabloid noise
   - The difference between clickbait and official guidance

The goal: informed followers who ignore tabloid hysteria but respect official warnings when issued.

Current period context: This is an ACTUAL WEATHER EVENT, not typical seasonal conditions. When anomaly_strength is 'extreme' or 'significant', followers are actively interested AND tabloids are hyping. Choose topics that either explain the real situation OR debunk the hype.

{weather_summary}

Available educational topics (format: [category] topic):
{topics_text}

SELECTION CRITERIA:
- If anomaly is extreme: STRONGLY prioritize myth_busting (counter tabloid hype) OR cold_relevant (explain what's actually happening)
- If anomaly is significant: prioritize cold_relevant or myth_busting
- If anomaly is normal/moderate: pick varied educational content (ai_tech, project_updates, general weather_education)
- Consider model agreement: high agreement = confidence topics; low = uncertainty topics

Pick the ONE topic most relevant RIGHT NOW. Reply with ONLY the exact topic text, nothing else."""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'haiku', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0 and result.stdout.strip():
            selected = result.stdout.strip()
            # Find matching topic
            for cat, topic in available_topics:
                if topic.lower() in selected.lower() or selected.lower() in topic.lower():
                    return cat, topic
    except Exception as e:
        print(f"  Claude topic selection failed: {e}")

    return None


def select_topic(state: dict, weather_context: dict = None) -> tuple:
    """Select next topic, using Claude + anomaly-based weather context.

    First tries Claude for intelligent selection, falls back to weighted random.

    Returns (category_key, topic_text)
    """
    recent_categories = [t.get("category") for t in state.get("topic_history", [])[-4:]]
    recent_topics = [t.get("topic") for t in state.get("topic_history", [])[-10:]]

    # Prioritize Q&A if we have collected questions
    if state.get("collected_questions") and len(state["collected_questions"]) >= 2:
        return "qa", "Community Q&A"

    if weather_context is None:
        weather_context = get_weather_context()

    season = weather_context.get("season", "shoulder")

    # Build list of available topics (not recently used)
    available_topics = []
    for cat, cat_info in TOPIC_CATEGORIES.items():
        if cat in recent_categories[-2:]:
            continue
        # Skip seasonal categories when not relevant
        if cat == "cold_relevant" and season == "summer":
            continue
        if cat == "warm_relevant" and season == "winter":
            continue

        for topic in cat_info["topics"]:
            if topic not in recent_topics:
                available_topics.append((cat, topic))

    if not available_topics:
        # Fallback: use all topics
        for cat, cat_info in TOPIC_CATEGORIES.items():
            for topic in cat_info["topics"]:
                available_topics.append((cat, topic))

    # Try Claude for intelligent selection
    print("  Asking Claude to select most relevant topic...")
    result = select_topic_with_claude(weather_context, available_topics[:15])  # Limit to 15 topics
    if result:
        print(f"  Claude selected: {result[0]} - {result[1][:50]}...")
        return result

    # Fallback: weighted random selection based on anomaly
    print("  Falling back to weighted random selection...")
    cold_anomaly = weather_context.get("cold_anomaly", 0)
    warm_anomaly = weather_context.get("warm_anomaly", 0)
    anomaly_strength = weather_context.get("anomaly_strength", "normal")

    weighted = []
    for cat, topic in available_topics:
        weight = 1
        if cold_anomaly > warm_anomaly:
            if anomaly_strength in ["extreme", "significant"]:
                if cat in ["cold_relevant", "myth_busting"]:
                    weight = 5
                elif cat == "weather_education":
                    weight = 2
        elif warm_anomaly > cold_anomaly:
            if anomaly_strength in ["extreme", "significant"]:
                if cat == "warm_relevant":
                    weight = 5
        weighted.extend([(cat, topic)] * weight)

    return random.choice(weighted) if weighted else random.choice(available_topics)


def generate_qa_post(questions: list) -> str:
    """Generate a Q&A post from collected questions using Claude."""
    if not questions:
        return None

    # Take up to 3 questions
    selected = questions[:3]

    questions_text = "\n".join([
        f"- @{q['author']}: {q['text'][:150]}"
        for q in selected
    ])

    prompt = f"""You are WXD, a weather tracking project for London. Write a friendly Q&A post answering community questions.

QUESTIONS FROM FOLLOWERS:
{questions_text}

Write a Bluesky thread (2-3 posts, each max 280 chars).

RULES:
- Be friendly and approachable
- Give accurate, helpful answers
- Keep it simple for general audience
- Reference WXD tracking where relevant
- Thank people for their questions

FORMAT: Return posts separated by ---
Post 1 should acknowledge the questions
Following posts answer them briefly"""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print(f"  Claude error: {e}")

    return None


def generate_engagement_post(category: str, topic: str) -> str:
    """Generate an engagement post using Claude."""

    cat_name = TOPIC_CATEGORIES.get(category, {}).get("name", category)

    prompt = f"""You are WXD, a weather tracking project that monitors 850hPa temperatures for London using multiple weather models (GFS, ECMWF, AIFS, GEM, ICON, MOGREPS, UKMO).

Write an engaging educational Bluesky thread about:
CATEGORY: {cat_name}
TOPIC: {topic}

TARGET AUDIENCE: General public and weather enthusiasts with basic knowledge (not experts).

CRITICAL FORMAT:
- Write 2-3 posts, each max 280 characters
- Separate posts with --- on its own line
- Start IMMEDIATELY with the first post text
- NO preamble like "Let me..." or "Here is..." or "I will..."
- NO labels like "Post 1:" or "**Post 1:**"
- NO markdown formatting (no **, no #, no *)
- NO thinking out loud - just the post content
- Plain text only

CONTENT RULES:
- Be friendly, informative, not condescending
- Use simple language, explain jargon
- Relate to WXD project where natural
- No emojis
- End with something that invites engagement (question, thought)
- Be factually accurate about meteorology and technology

Structure:
- First post: Hook/intro to the topic
- Second post: Main explanation
- Third post (optional): How it relates to WXD or invitation to engage"""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print(f"  Claude error: {e}")

    # Fallback
    return f"""Ever wondered about {topic.lower()}?

It's one of the key concepts behind how WXD tracks cold air for London.

---

More on this topic coming soon. Questions? Reply and we'll cover them in our next Q&A post."""


def add_thread_indicators(posts: list) -> list:
    """Add thread indicators [1/3], [2/3], etc to START of posts.

    Only adds indicators if there are 2+ posts.
    Matches post_bluesky.py format for consistency.
    """
    if len(posts) < 2:
        return posts

    # Add indicators at START of all posts
    result = []
    total = len(posts)
    for i, post in enumerate(posts):
        indicator = f"[{i+1}/{total}] "
        # Only add if it fits within 300 char limit
        if len(post) + len(indicator) <= 300:
            result.append(indicator + post)
        else:
            result.append(post)
    return result


def post_thread(posts: list, handle: str, password: str) -> bool:
    """Post a thread to Bluesky.

    Args:
        posts: List of post texts
        handle: Bluesky handle
        password: App password

    Returns:
        True if successful
    """
    if not HAS_ATPROTO or not handle or not password:
        return False

    try:
        client = Client()
        client.login(handle, password)

        root = None
        parent = None

        for i, text in enumerate(posts):
            text = text.strip()[:300]  # Ensure within limit

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
            print(f"  Posted {i+1}/{len(posts)}")

            if root is None:
                root = {'uri': response.uri, 'cid': response.cid}
            parent = {'uri': response.uri, 'cid': response.cid}

        return True

    except Exception as e:
        print(f"  Bluesky error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='WXD Engagement Post System')
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Preview without posting')
    parser.add_argument('--category', '-c', type=str,
                       help='Force specific category (weather_education, ai_tech, project_updates, weather_news, cold_relevant, myth_busting)')
    parser.add_argument('--collect-questions', action='store_true',
                       help='Only collect questions from replies, do not post')
    parser.add_argument('--qa', action='store_true',
                       help='Force Q&A post using collected questions')
    parser.add_argument('--community-request', action='store_true',
                       help='Post Sunday community request asking for topic suggestions')
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    state_path = script_dir / "data" / "engagement_state.json"
    state_path.parent.mkdir(exist_ok=True)

    # Credentials
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    print(f"WXD Engagement System - {utcnow().isoformat()}")
    if args.dry_run:
        print("DRY RUN MODE - will NOT post")

    # Get weather context for relevant topic selection
    weather_context = get_weather_context()
    print(f"Weather context: season={weather_context['season']}, Dec normal={weather_context.get('seasonal_normal')}°C")
    print(f"  4-model mean min: {weather_context.get('mean_min')}°C (coldest: {weather_context['min_temp']}°C)")
    print(f"  Cold anomaly: {weather_context.get('cold_anomaly', 0):+.1f}°C vs normal → {weather_context.get('anomaly_strength', 'normal')}")
    print(f"  Model spread: {weather_context.get('model_spread', 0)}°C → agreement: {weather_context['model_agreement']}")
    print()

    # Load state
    state = load_state(state_path)

    # Community request mode (Sunday post)
    if args.community_request:
        print("Generating community request post...")
        content = generate_community_request()
        posts = [p.strip() for p in content.split('---') if p.strip()]

        print(f"Generated {len(posts)} posts:")
        for i, post in enumerate(posts):
            print(f"\n  [{i+1}] ({len(post)} chars):")
            print(f"  {post[:200]}{'...' if len(post) > 200 else ''}")

        if args.dry_run:
            preview_posts = add_thread_indicators(posts)
            print("\n" + "=" * 50)
            print("PREVIEW (not posting):")
            for i, post in enumerate(preview_posts):
                print(f"\n--- Post {i+1} ---")
                print(post)
            print("=" * 50)
            return 0

        print("\nPosting to Bluesky...")
        posts = add_thread_indicators(posts)
        success = post_thread(posts, bsky_handle, bsky_password)
        if success:
            print("  Community request posted!")
            state["last_community_request"] = utcnow().isoformat()
            save_state(state_path, state)
        else:
            print("  Failed to post")
            return 1
        return 0

    # Collect questions mode
    if args.collect_questions:
        print("Collecting questions from recent replies...")
        questions = get_recent_replies(bsky_handle, bsky_password)
        if questions:
            print(f"  Found {len(questions)} potential questions:")
            for q in questions[:5]:
                print(f"    - @{q['author']}: {q['text'][:60]}...")

            # Add to state (avoiding duplicates)
            existing_uris = {q['uri'] for q in state.get('collected_questions', [])}
            new_questions = [q for q in questions if q['uri'] not in existing_uris]
            state['collected_questions'] = state.get('collected_questions', []) + new_questions
            save_state(state_path, state)
            print(f"  Added {len(new_questions)} new questions to queue")
        else:
            print("  No new questions found")
        return 0

    # Select topic
    if args.qa:
        category, topic = "qa", "Community Q&A"
    elif args.category:
        category = args.category
        if category in TOPIC_CATEGORIES:
            topic = random.choice(TOPIC_CATEGORIES[category]["topics"])
        else:
            print(f"Unknown category: {category}")
            return 1
    else:
        category, topic = select_topic(state, weather_context)

    print(f"Category: {category}")
    print(f"Topic: {topic}")
    print()

    # Generate content
    print("Generating content...")
    if category == "qa" and state.get("collected_questions"):
        content = generate_qa_post(state["collected_questions"][:3])
        if content:
            # Clear answered questions
            state["collected_questions"] = state.get("collected_questions", [])[3:]
    else:
        content = generate_engagement_post(category, topic)

    if not content:
        print("  Failed to generate content")
        return 1

    # Parse into posts
    posts = [p.strip() for p in content.split('---') if p.strip()]

    print(f"Generated {len(posts)} posts:")
    for i, post in enumerate(posts):
        print(f"\n  [{i+1}] ({len(post)} chars):")
        print(f"  {post[:200]}{'...' if len(post) > 200 else ''}")

    if args.dry_run:
        preview_posts = add_thread_indicators(posts)
        print("\n" + "=" * 50)
        print("PREVIEW (not posting):")
        for i, post in enumerate(preview_posts):
            print(f"\n--- Post {i+1} ---")
            print(post)
        print("=" * 50)
        return 0

    # Post thread
    print("\nPosting to Bluesky...")
    posts = add_thread_indicators(posts)
    success = post_thread(posts, bsky_handle, bsky_password)

    if success:
        print("  Thread posted successfully!")

        # Update state
        state["last_post"] = utcnow().isoformat()
        state["posts_count"] = state.get("posts_count", 0) + 1
        state["topic_history"] = state.get("topic_history", []) + [{
            "category": category,
            "topic": topic,
            "time": utcnow().isoformat()
        }]
        # Keep only last 20 topics in history
        state["topic_history"] = state["topic_history"][-20:]
        save_state(state_path, state)
    else:
        print("  Failed to post thread")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
