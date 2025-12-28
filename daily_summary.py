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


def fetch_metoffice_narrative() -> dict:
    """Fetch Met Office UK forecast narrative."""
    if not HAS_REQUESTS:
        return {"error": "requests not installed"}

    result = {
        "uk_forecast": None,
        "long_range": None,
        "fetched_at": utcnow().isoformat()
    }

    headers = {
        "User-Agent": "WXD Weather Bot (wxd-london.bsky.social)"
    }

    # Fetch UK forecast page
    try:
        resp = requests.get(METOFFICE_UK_URL, headers=headers, timeout=30)
        if resp.status_code == 200:
            # The Met Office site loads content via JS, but there's usually
            # some text in meta tags or structured data
            text = resp.text

            # Try to extract forecast text from various sources
            if HAS_BS4:
                soup = BeautifulSoup(text, 'html.parser')

                # Look for forecast summary in meta description
                meta = soup.find('meta', attrs={'name': 'description'})
                if meta and meta.get('content'):
                    result["uk_forecast"] = meta['content']

                # Look for any forecast text divs
                for div in soup.find_all(['p', 'div'], class_=re.compile(r'forecast|summary|outlook', re.I)):
                    if div.text and len(div.text) > 50:
                        result["uk_forecast"] = div.text.strip()
                        break
            else:
                # Basic regex extraction
                match = re.search(r'<meta name="description" content="([^"]+)"', text)
                if match:
                    result["uk_forecast"] = match.group(1)

    except Exception as e:
        result["uk_error"] = str(e)

    # Fetch long-range forecast
    try:
        resp = requests.get(METOFFICE_LONGRANGE_URL, headers=headers, timeout=30)
        if resp.status_code == 200:
            text = resp.text

            if HAS_BS4:
                soup = BeautifulSoup(text, 'html.parser')

                # Look for long-range text
                meta = soup.find('meta', attrs={'name': 'description'})
                if meta and meta.get('content'):
                    result["long_range"] = meta['content']

                # Look for outlook sections
                for section in soup.find_all(['section', 'div'], class_=re.compile(r'outlook|long-range|extended', re.I)):
                    text_content = section.get_text(separator=' ', strip=True)
                    if len(text_content) > 100:
                        result["long_range"] = text_content[:1000]
                        break
            else:
                match = re.search(r'<meta name="description" content="([^"]+)"', text)
                if match:
                    result["long_range"] = match.group(1)

    except Exception as e:
        result["longrange_error"] = str(e)

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
    """Use Claude CLI to summarize WXD model data."""

    prompt = f"""You are WXD daily summary writer. Summarize the current model signals for London 850hPa.

WXD MODEL DATA (850hPa temperatures over London, next 7 days):
{model_summary}

Write a Bluesky post (max 280 chars) that:
1. Highlights the coldest signal and which model(s) show it
2. Notes any model agreement/disagreement
3. Start with "Daily Summary:" to identify this post type
4. Mention specific temperatures and dates if cold (<-5C)

Plain text only (no emojis, hashtags, or markdown)."""

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
    """Generate summary when Claude CLI unavailable."""
    # Parse temperatures from model summary
    import re
    temps = re.findall(r'(-?\d+\.?\d*)C', model_summary)
    if temps:
        temps_float = [float(t) for t in temps]
        coldest = min(temps_float)
        if coldest <= -7:
            return f"Daily Summary: Strong cold signal across models. Coldest: {coldest}C at 850hPa. All trackers showing sub-zero temps through the week."
        elif coldest <= -5:
            return f"Daily Summary: Cold signal detected. Models show {coldest}C minimum at 850hPa. Check individual trackers for timing."
        else:
            return f"Daily Summary: Models showing {coldest}C minimum at 850hPa. No significant cold signals currently."
    return "Daily Summary: Model data collected. See individual tracker posts for details."


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
    if metoffice.get("uk_forecast"):
        print(f"  UK forecast: {metoffice['uk_forecast'][:100]}...")
    else:
        print("  UK forecast: not available")
    if metoffice.get("long_range"):
        print(f"  Long range: {metoffice['long_range'][:100]}...")
    else:
        print("  Long range: not available")

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
