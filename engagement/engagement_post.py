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


def select_topic(state: dict) -> tuple:
    """Select next topic, avoiding recent repeats.

    Returns (category_key, topic_text)
    """
    recent_categories = [t.get("category") for t in state.get("topic_history", [])[-4:]]

    # Prioritize Q&A if we have collected questions
    if state.get("collected_questions") and len(state["collected_questions"]) >= 2:
        return "qa", "Community Q&A"

    # Rotate through categories, avoiding recent ones
    available_categories = [
        cat for cat in TOPIC_CATEGORIES.keys()
        if cat not in recent_categories[-2:]  # Avoid last 2 categories
    ]

    if not available_categories:
        available_categories = list(TOPIC_CATEGORIES.keys())

    category = random.choice(available_categories)
    cat_info = TOPIC_CATEGORIES[category]

    # Select a topic we haven't used recently
    recent_topics = [t.get("topic") for t in state.get("topic_history", [])[-10:]]
    available_topics = [t for t in cat_info["topics"] if t not in recent_topics]

    if not available_topics:
        available_topics = cat_info["topics"]

    topic = random.choice(available_topics)

    return category, topic


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
                       help='Force specific category (weather_education, ai_tech, project_updates, weather_news)')
    parser.add_argument('--collect-questions', action='store_true',
                       help='Only collect questions from replies, do not post')
    parser.add_argument('--qa', action='store_true',
                       help='Force Q&A post using collected questions')
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
    print()

    # Load state
    state = load_state(state_path)

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
        category, topic = select_topic(state)

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
        print("\n" + "=" * 50)
        print("PREVIEW (not posting):")
        for i, post in enumerate(posts):
            print(f"\n--- Post {i+1} ---")
            print(post)
        print("=" * 50)
        return 0

    # Post thread
    print("\nPosting to Bluesky...")
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
