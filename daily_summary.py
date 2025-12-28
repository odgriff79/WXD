#!/usr/bin/env python3
"""
WXD Daily Summary - Met Office Narrative vs Model Comparison

Fetches Met Office UK forecast and long-range outlook, compares
with WXD model ensemble data, and posts analysis to Bluesky.

Data sources:
- weather.metoffice.gov.uk/forecast/uk (daily narrative)
- weather.metoffice.gov.uk/long-range-forecast (extended outlook)
- WXD tracker data (GFS, ECMWF, ICON, UKMO, MOGREPS)

Legal: Contains public sector information licensed under the
Open Government Licence v3.0

Usage:
    python daily_summary.py              # Post summary
    python daily_summary.py --dry-run    # Preview without posting
    python daily_summary.py --preview    # Same as dry-run
"""

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Optional imports
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from atproto import Client, models as atproto_models
    HAS_ATPROTO = True
except ImportError:
    HAS_ATPROTO = False


# Met Office URLs
METOFFICE_UK_URL = "https://weather.metoffice.gov.uk/forecast/uk"
METOFFICE_LONGRANGE_URL = "https://weather.metoffice.gov.uk/long-range-forecast"

# OGL Attribution (required)
OGL_ATTRIBUTION = "Contains public sector information licensed under the Open Government Licence v3.0"


def utcnow():
    return datetime.now(timezone.utc)


def clean_text(s: str) -> str:
    """Clean whitespace from text."""
    return re.sub(r"\s+", " ", s).strip()


def fetch_metoffice_narrative() -> dict:
    """Fetch Met Office UK forecast narrative from HTML."""
    if not HAS_REQUESTS:
        return {"error": "requests not installed"}

    result = {
        "today_tomorrow": None,
        "days_3_5": None,
        "long_range": None,
        "fetched_at": utcnow().isoformat()
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    }

    try:
        resp = requests.get(METOFFICE_UK_URL, headers=headers, timeout=30)
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        if not HAS_BS4:
            result["error"] = "beautifulsoup4 not installed"
            return result

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Get all text lines
        text = soup.get_text("\n")
        lines = [clean_text(x) for x in text.split("\n")]
        lines = [x for x in lines if x]

        # Extract blocks between section headers
        def block_after(header: str, stop_headers: set) -> list:
            out = []
            in_block = False
            for ln in lines:
                if ln == header:
                    in_block = True
                    continue
                if in_block and ln in stop_headers:
                    break
                if in_block:
                    out.append(ln)
            return out

        stop = {"Today and tomorrow", "3 to 5 day forecast", "Long range forecast",
                "UK weather map", "Cities", "Find a forecast"}

        today_block = block_after("Today and tomorrow", stop)
        d3_5_block = block_after("3 to 5 day forecast", stop)
        long_block = block_after("Long range forecast", stop)

        # Parse each block - filter out noise
        def parse_block(block: list) -> str:
            narrative = [ln for ln in block if not ln.startswith("Updated:")]
            # Remove date-range headings
            narrative = [ln for ln in narrative if not re.match(r"^[A-Z][a-z]{2} \d{1,2} ", ln)]
            # Remove short menu items
            narrative = [ln for ln in narrative if len(ln) > 30]
            return "\n".join(narrative).strip()

        result["today_tomorrow"] = parse_block(today_block) or None
        result["days_3_5"] = parse_block(d3_5_block) or None
        result["long_range"] = parse_block(long_block) or None

    except Exception as e:
        result["error"] = str(e)

    return result


def load_wxd_data() -> dict:
    """Load latest data from all WXD trackers."""
    script_dir = Path(__file__).parent

    data = {
        "tracker_a": None,  # Main ensemble (GFS, ECMWF, GEM)
        "icon": None,       # ICON-EU-EPS
        "ukmo": None,       # UKMO deterministic
        "mogreps": None     # MOGREPS-G ensemble
    }

    # Tracker A - main ensemble
    tracker_a_path = script_dir / "data" / "history_compact.json"
    if tracker_a_path.exists():
        with open(tracker_a_path, 'r') as f:
            data["tracker_a"] = json.load(f)

    # ICON
    icon_path = script_dir / "trackers" / "icon" / "data" / "history.json"
    if icon_path.exists():
        with open(icon_path, 'r') as f:
            data["icon"] = json.load(f)

    # UKMO
    ukmo_path = script_dir / "trackers" / "ukmo" / "data" / "history.json"
    if ukmo_path.exists():
        with open(ukmo_path, 'r') as f:
            data["ukmo"] = json.load(f)

    # MOGREPS
    mogreps_path = script_dir / "trackers" / "mogreps" / "data" / "history.json"
    if mogreps_path.exists():
        with open(mogreps_path, 'r') as f:
            data["mogreps"] = json.load(f)

    return data


def summarize_model_data(wxd_data: dict) -> str:
    """Create a concise summary of current model signals."""
    lines = []

    # Tracker A
    if wxd_data.get("tracker_a"):
        runs = wxd_data["tracker_a"].get("runs", [])
        if runs:
            latest = runs[0]
            models = latest.get("models", {})
            temps = []
            for model_key, model_data in models.items():
                means = model_data.get("mean", [])
                if means:
                    min_temp = min(t for t in means if t is not None)
                    temps.append(f"{model_key.upper()}: {min_temp:.1f}C")
            if temps:
                lines.append(f"Main ensemble: {', '.join(temps)}")

    # ICON
    if wxd_data.get("icon"):
        runs = wxd_data["icon"].get("runs", [])
        if runs:
            latest = runs[0]
            means = latest.get("mean", [])
            if means:
                min_temp = min(t for t in means if t is not None)
                lines.append(f"ICON-EU-EPS: min {min_temp:.1f}C")

    # UKMO
    if wxd_data.get("ukmo"):
        runs = wxd_data["ukmo"].get("runs", [])
        if runs:
            latest = runs[0]
            temps = latest.get("temperature_850hPa", [])
            if temps:
                min_temp = min(t for t in temps if t is not None)
                lines.append(f"UKMO det: min {min_temp:.1f}C")

    # MOGREPS
    if wxd_data.get("mogreps"):
        runs = wxd_data["mogreps"].get("runs", [])
        if runs:
            latest = runs[0]
            means = latest.get("mean", [])
            mins = latest.get("min", [])
            if means:
                coldest_mean = min(t for t in means if t is not None)
                coldest_member = min(t for t in mins if t is not None) if mins else None
                if coldest_member:
                    lines.append(f"MOGREPS: mean {coldest_mean:.1f}C, coldest member {coldest_member:.1f}C")
                else:
                    lines.append(f"MOGREPS: mean {coldest_mean:.1f}C")

    return "\n".join(lines) if lines else "No model data available"


def get_claude_comparison(metoffice: dict, model_summary: str) -> str:
    """Use Claude CLI to compare Met Office narrative vs WXD models."""

    # Build Met Office context
    mo_parts = []
    if metoffice.get("today_tomorrow"):
        mo_parts.append(f"Today/Tomorrow: {metoffice['today_tomorrow'][:300]}")
    if metoffice.get("days_3_5"):
        mo_parts.append(f"Days 3-5: {metoffice['days_3_5'][:300]}")
    if metoffice.get("long_range"):
        mo_parts.append(f"Long range: {metoffice['long_range'][:300]}")

    mo_text = "\n".join(mo_parts) if mo_parts else "Met Office narrative not available"

    from datetime import datetime
    today = datetime.now().strftime("%d %b")

    prompt = f"""You are WXD daily summary writer. Write a brief, readable summary of what the weather models suggest is coming.

MET OFFICE NARRATIVE:
{mo_text}

WXD MODEL DATA (850hPa temps, London):
{model_summary}

Write a 280-char Bluesky post:
- Start with "Met Office Summary {today}:"
- Describe what the weather signals suggest in plain English
- Mention if cold/mild/unsettled based on the 850hPa temps
- Compare to Met Office narrative if they differ significantly
- NO raw numbers or stats - write it like a weather forecaster would say it
- Be conversational but informative

Plain text only."""

    try:
        result = subprocess.run(
            ['claude', '-p', prompt, '--max-tokens', '150'],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:280]

    except Exception as e:
        print(f"  Claude CLI error: {e}")

    # Fallback - generate summary from model data
    return generate_fallback_summary(model_summary)


def generate_fallback_summary(model_summary: str) -> str:
    """Generate written narrative summary when Claude CLI unavailable."""
    import re
    from datetime import datetime

    today = datetime.now().strftime("%d %b")
    temps = re.findall(r'(-?\d+\.?\d*)C', model_summary)

    if temps:
        temps_float = [float(t) for t in temps]
        coldest = min(temps_float)

        if coldest <= -8:
            return f"Met Office Summary {today}: Models unanimous - significant cold incoming. All trackers flagging an Arctic outbreak with 850hPa temps well below freezing. Expect sharp frosts and possible wintry hazards across the UK this week."
        elif coldest <= -5:
            return f"Met Office Summary {today}: Cold signal strengthening across ensemble models. Upper-level temps dropping below -5C threshold - classic cold air signature. Worth watching for frost and wintry showers, especially in the north."
        elif coldest <= 0:
            return f"Met Office Summary {today}: Models showing a chilly spell ahead with 850hPa temps near or below freezing. Not extreme, but expect overnight frosts and cooler than average conditions through the forecast period."
        else:
            return f"Met Office Summary {today}: Models suggesting near-normal or mild conditions. No significant cold signals detected at 850hPa level. Settled weather likely to continue."

    return f"Met Office Summary {today}: Model data collected - see individual tracker posts for detailed breakdown."


def post_to_bluesky(text: str, reply_to: dict = None,
                    handle: str = None, password: str = None) -> dict:
    """Post to Bluesky, optionally as reply (for threading)."""
    if not HAS_ATPROTO or not handle or not password:
        return None

    try:
        client = Client()
        client.login(handle, password)

        if reply_to:
            # Create reply reference
            reply_ref = atproto_models.AppBskyFeedPost.ReplyRef(
                parent=atproto_models.create_strong_ref(reply_to),
                root=atproto_models.create_strong_ref(reply_to)
            )
            response = client.send_post(text=text, reply_to=reply_ref)
        else:
            response = client.send_post(text=text)

        return {"uri": response.uri, "cid": response.cid}

    except Exception as e:
        print(f"  Bluesky error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='WXD Daily Summary')
    parser.add_argument('--dry-run', '-n', action='store_true', help='Preview without posting')
    parser.add_argument('--preview', '-p', action='store_true', help='Same as dry-run')
    args = parser.parse_args()

    dry_run = args.dry_run or args.preview

    # Credentials
    bsky_handle = os.environ.get('BSKY_HANDLE')
    bsky_password = os.environ.get('BSKY_PASSWORD')

    print(f"WXD Daily Summary - {utcnow().isoformat()}")
    if dry_run:
        print("DRY RUN MODE - will NOT post")
    print()

    # Step 1: Fetch Met Office narrative
    print("Fetching Met Office narrative...")
    metoffice = fetch_metoffice_narrative()
    if metoffice.get("error"):
        print(f"  Error: {metoffice['error']}")
    else:
        if metoffice.get("today_tomorrow"):
            print(f"  Today/Tomorrow: {metoffice['today_tomorrow'][:80]}...")
        if metoffice.get("days_3_5"):
            print(f"  Days 3-5: {metoffice['days_3_5'][:80]}...")
        if metoffice.get("long_range"):
            print(f"  Long range: {metoffice['long_range'][:80]}...")
        if not any([metoffice.get("today_tomorrow"), metoffice.get("days_3_5"), metoffice.get("long_range")]):
            print("  No narrative sections found")

    # Step 2: Load WXD model data
    print()
    print("Loading WXD model data...")
    wxd_data = load_wxd_data()
    model_summary = summarize_model_data(wxd_data)
    print(f"  {model_summary.replace(chr(10), ', ')}")

    # Step 3: Get Claude comparison
    print()
    print("Generating comparison...")
    main_text = get_claude_comparison(metoffice, model_summary)
    print(f"  Main post ({len(main_text)} chars):")
    print(f"  {main_text}")

    if dry_run:
        print()
        print("=" * 50)
        print("PREVIEW (not posting):")
        print()
        print(f"POST: {main_text}")
        print("=" * 50)
        print()
        print("(Attribution in pinned post)")
        return 0

    # Step 4: Post to Bluesky (single post, attribution in pinned)
    print()
    print("Posting to Bluesky...")

    result = post_to_bluesky(main_text, handle=bsky_handle, password=bsky_password)
    if result:
        print(f"  Posted: {result['uri']}")
    else:
        print("  Failed to post")
        return 1

    print()
    print("Daily summary posted successfully")
    return 0


if __name__ == "__main__":
    exit(main())
