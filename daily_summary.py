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
METOFFICE_WARNINGS_URL = "https://weather.metoffice.gov.uk/warnings-and-advice/uk-warnings"

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
        "long_range_detail": None,  # From dedicated long-range page
        "long_range_warning": None,  # Any warnings from long-range page
        "uk_warnings": None,  # Summary of active warnings by nation
        "fetched_at": utcnow().isoformat()
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    }

    if not HAS_BS4:
        result["error"] = "beautifulsoup4 not installed"
        return result

    # Helper functions
    def block_after(lines: list, header: str, stop_headers: set) -> list:
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

    def parse_block(block: list) -> str:
        narrative = [ln for ln in block if not ln.startswith("Updated:")]
        # Remove date-range headings
        narrative = [ln for ln in narrative if not re.match(r"^[A-Z][a-z]{2} \d{1,2} ", ln)]
        # Remove short menu items
        narrative = [ln for ln in narrative if len(ln) > 30]
        return "\n".join(narrative).strip()

    # Fetch main UK forecast page
    try:
        resp = requests.get(METOFFICE_UK_URL, headers=headers, timeout=30)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.get_text("\n")
            lines = [clean_text(x) for x in text.split("\n")]
            lines = [x for x in lines if x]

            stop = {"Today and tomorrow", "3 to 5 day forecast", "Long range forecast",
                    "UK weather map", "Cities", "Find a forecast"}

            today_block = block_after(lines, "Today and tomorrow", stop)
            d3_5_block = block_after(lines, "3 to 5 day forecast", stop)
            long_block = block_after(lines, "Long range forecast", stop)

            result["today_tomorrow"] = parse_block(today_block) or None
            result["days_3_5"] = parse_block(d3_5_block) or None
            result["long_range"] = parse_block(long_block) or None
    except Exception as e:
        result["error"] = f"UK page: {e}"

    # Fetch dedicated long-range forecast page for more detail
    try:
        resp = requests.get(METOFFICE_LONGRANGE_URL, headers=headers, timeout=30)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.get_text(" ", strip=True)

            # Extract warning info (Yellow/Amber/Red warning)
            warning_match = re.search(
                r'(Yellow|Amber|Red)\s+warning[^.]*in force[^.]*\.?\s*([A-Z][a-z]{2,8}\s+\d{1,2}\s+[A-Z][a-z]{2}\s*-\s*[A-Z][a-z]{2,8}\s+\d{1,2}\s+[A-Z][a-z]{2})',
                text, re.IGNORECASE
            )
            if warning_match:
                result["long_range_warning"] = f"{warning_match.group(1)} warning: {warning_match.group(2)}"

            # Extract forecast paragraphs (look for substantive content)
            paragraphs = []
            for tag in soup.find_all(['p', 'div']):
                p_text = tag.get_text(' ', strip=True)
                # Look for forecast content (mentions weather terms and is long enough)
                if len(p_text) > 100 and any(word in p_text.lower() for word in
                    ['winds', 'temperatures', 'pressure', 'cold', 'mild', 'rain', 'snow', 'frost', 'showers', 'settled']):
                    # Skip navigation/menu text
                    if not any(skip in p_text.lower() for skip in ['search site', 'skip to', 'menu', 'back weather']):
                        paragraphs.append(p_text)

            # Deduplicate and take first 2 unique paragraphs
            seen = set()
            unique = []
            for p in paragraphs:
                p_key = p[:100]  # Use first 100 chars as key
                if p_key not in seen:
                    seen.add(p_key)
                    unique.append(p)
                if len(unique) >= 2:
                    break

            if unique:
                result["long_range_detail"] = "\n\n".join(unique)

    except Exception as e:
        if "error" in result:
            result["error"] += f"; Long-range page: {e}"
        else:
            result["error"] = f"Long-range page: {e}"

    # Fetch UK warnings page for day-by-day warning status
    try:
        resp = requests.get(METOFFICE_WARNINGS_URL, headers=headers, timeout=30)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.get_text(" ", strip=True)

            # Look for day-by-day warning patterns like:
            # "Thu 1 Jan Yellow weather warning" or "Mon 29 Dec No warnings"
            day_pattern = r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(No warnings|Yellow|Amber|Red)\s*(weather warning)?'
            day_matches = re.findall(day_pattern, text, re.IGNORECASE)

            warning_days = []
            no_warning_days = []
            for match in day_matches:
                day_name, day_num, month, status = match[0], match[1], match[2], match[3]
                date_str = f"{day_name} {day_num} {month}"
                if status.lower() == 'no warnings':
                    no_warning_days.append(date_str)
                else:
                    warning_days.append(f"{date_str}: {status}")

            # Look for nations with warnings
            nations = ['England', 'Scotland', 'Wales', 'Northern Ireland']
            nation_warnings = {}

            for nation in nations:
                pattern = rf'{nation}[^.]*?(Yellow|Amber|Red)\s+warning|' \
                         rf'(Yellow|Amber|Red)\s+warning[^.]*?{nation}'
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    warning_type = match.group(1) or match.group(2)
                    nation_warnings[nation] = warning_type.capitalize()

            # Build summary
            parts = []

            # Add warning days
            if warning_days:
                parts.append("Warnings: " + ", ".join(warning_days[:4]))  # Limit to 4 days

            # Add nations affected
            if nation_warnings:
                by_level = {}
                for nation, level in nation_warnings.items():
                    if level not in by_level:
                        by_level[level] = []
                    by_level[level].append(nation)

                nation_parts = []
                for level in ['Red', 'Amber', 'Yellow']:
                    if level in by_level:
                        nations_str = ', '.join(by_level[level])
                        nation_parts.append(f"{level}: {nations_str}")
                if nation_parts:
                    parts.append("Affected: " + "; ".join(nation_parts))

            if parts:
                result["uk_warnings"] = " | ".join(parts)
            elif no_warning_days and not warning_days:
                result["uk_warnings"] = "No warnings in force"

    except Exception as e:
        pass  # Warnings are optional, don't fail if this doesn't work

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
    today = datetime.now().strftime("%d %m %Y")

    prompt = f"""You are WXD daily summary writer. Write a brief, readable summary of what the weather models suggest is coming.

MET OFFICE NARRATIVE:
{mo_text}

WXD MODEL DATA (850hPa temps, London):
{model_summary}

Write a 280-char Bluesky post:
- Start with "UK Daily {today}:"
- Describe what our models suggest in plain English
- Cold 850hPa temps often mean settled, frosty weather in southern UK - not necessarily stormy
- Wintry showers more likely in north/Scotland with cold air
- NO raw numbers - write it like a weather forecaster would say it
- Be accurate and conversational

Plain text only."""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            input=None,
            capture_output=True,
            text=True,
            timeout=180
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:280]

    except Exception as e:
        print(f"  Claude CLI error: {e}")

    # Fallback - generate summary from model data
    return generate_fallback_summary(model_summary)


def generate_metoffice_post(metoffice: dict) -> str:
    """Generate post 1: Met Office summary - today/tomorrow."""
    from datetime import datetime
    today = datetime.now().strftime("%d %m %Y")

    narrative = metoffice.get("today_tomorrow", "") or "Forecast unavailable"

    header = f"UK Daily {today} - Met Office says:\n\n"
    max_narrative = 280 - len(header)
    if len(narrative) > max_narrative:
        narrative = narrative[:max_narrative-3] + "..."

    return header + narrative


def generate_metoffice_longrange_post(metoffice: dict) -> str:
    """Generate post for long range outlook."""
    parts = []

    if metoffice.get("days_3_5"):
        parts.append(f"Days 3-5: {metoffice['days_3_5']}")

    if metoffice.get("long_range"):
        parts.append(f"Long range: {metoffice['long_range']}")

    if not parts:
        return None

    text = "\n".join(parts)
    if len(text) > 280:
        text = text[:277] + "..."

    return text


def generate_ai_commentary(metoffice: dict, model_summary: str) -> str:
    """Generate AI commentary - alert for significant weather in Met Office forecast."""

    # Combine all Met Office text for analysis
    mo_all = ""
    if metoffice.get("today_tomorrow"):
        mo_all += metoffice["today_tomorrow"] + " "
    if metoffice.get("days_3_5"):
        mo_all += metoffice["days_3_5"] + " "
    if metoffice.get("long_range"):
        mo_all += metoffice["long_range"] + " "
    if metoffice.get("long_range_detail"):
        mo_all += metoffice["long_range_detail"] + " "

    # Add any warnings
    warnings_text = ""
    if metoffice.get("long_range_warning"):
        warnings_text = f"\nACTIVE WARNING: {metoffice['long_range_warning']}"
    if metoffice.get("uk_warnings"):
        warnings_text += f"\nUK WARNINGS: {metoffice['uk_warnings']}"

    mo_all_lower = mo_all.lower()

    prompt = f"""Scan Met Office forecast for significant weather. Write 220 chars max alert.

MET OFFICE TEXT:
{mo_all[:600]}
{warnings_text}

WXD MODELS (850hPa): {model_summary}

Write brief WXD alert:
- Start with "WXD Alert:" if significant weather mentioned (wintry, snow, frost, cold, gales, ice, warning)
- Start with "WXD view:" if nothing notable
- IMPORTANT: If there's an ACTIVE WARNING, mention it with dates
- Highlight any wintry/cold/frost signals from Met Office
- Note if models support or contradict Met Office
- Be direct and factual

Plain text only."""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'sonnet', '-p', prompt],
            input=None,
            capture_output=True,
            text=True,
            timeout=180
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:250]
    except Exception as e:
        print(f"  Claude CLI error: {e}")

    # Fallback - scan for significant weather keywords
    alert_words = ['wintry', 'snow', 'sleet', 'ice', 'icy', 'frost', 'freezing', 'gale', 'severe', 'warning']
    cold_words = ['cold', 'colder', 'chilly', 'cool']

    has_alert = any(word in mo_all_lower for word in alert_words)
    has_cold = any(word in mo_all_lower for word in cold_words)
    has_warning = bool(metoffice.get("long_range_warning"))

    temps = re.findall(r'(-?\d+\.?\d*)C', model_summary)
    coldest = min(float(t) for t in temps) if temps else 5

    if has_alert:
        return f"WXD Alert: Met Office flagging wintry conditions. Models confirm with 850hPa temps well below freezing. Watch for frost, ice risk, and wintry showers especially in the north."
    elif has_cold and coldest <= -5:
        return f"WXD Alert: Met Office noting colder spell. Models strongly support - significant cold signal at 850hPa. Sharp frosts likely, settled but cold in south."
    elif has_cold:
        return f"WXD view: Met Office mentions cooler weather. Models show chilly conditions ahead with overnight frosts likely."
    elif coldest <= -5:
        return f"WXD view: Models showing significant cold signal at 850hPa - frosty conditions ahead. Often settled and sunny in south, wintry showers in north."
    else:
        return f"WXD view: Nothing significant flagged. Quiet weather pattern continuing."


def generate_stats_post(model_summary: str) -> str:
    """Generate post 3: Stats for London."""
    from datetime import datetime
    today = datetime.now().strftime("%d %m %Y")

    header = "London 850hPa:\n"
    # model_summary already has the stats formatted
    stats = model_summary.replace("\n", " | ")

    if len(header + stats) > 280:
        stats = stats[:280 - len(header) - 3] + "..."

    return header + stats


def post_to_bluesky(text: str, reply_to: dict = None, root_post: dict = None,
                    handle: str = None, password: str = None) -> dict:
    """Post to Bluesky, optionally as reply (for threading)."""
    if not HAS_ATPROTO or not handle or not password:
        return None

    try:
        client = Client()
        client.login(handle, password)

        if reply_to:
            # Use root_post if provided, otherwise reply_to is both parent and root
            root = root_post if root_post else reply_to

            # Create StrongRef objects manually
            parent_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
                uri=reply_to["uri"],
                cid=reply_to["cid"]
            )
            root_ref = atproto_models.ComAtprotoRepoStrongRef.Main(
                uri=root["uri"],
                cid=root["cid"]
            )

            reply_ref = atproto_models.AppBskyFeedPost.ReplyRef(
                parent=parent_ref,
                root=root_ref
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
        if metoffice.get("long_range_warning"):
            print(f"  WARNING: {metoffice['long_range_warning']}")
        if metoffice.get("long_range_detail"):
            print(f"  Long range detail: {metoffice['long_range_detail'][:80]}...")
        if metoffice.get("uk_warnings"):
            print(f"  UK Warnings: {metoffice['uk_warnings']}")
        if not any([metoffice.get("today_tomorrow"), metoffice.get("days_3_5"), metoffice.get("long_range")]):
            print("  No narrative sections found")

    # Step 2: Load WXD model data
    print()
    print("Loading WXD model data...")
    wxd_data = load_wxd_data()
    model_summary = summarize_model_data(wxd_data)
    print(f"  {model_summary.replace(chr(10), ', ')}")

    # Step 3: Generate thread posts
    print()
    print("Generating thread posts...")

    post1 = generate_metoffice_post(metoffice)
    print(f"  Post 1 - Met Office Today ({len(post1)} chars):")
    print(f"    {post1[:80]}...")

    post2 = generate_metoffice_longrange_post(metoffice)
    if post2:
        print(f"  Post 2 - Met Office Long Range ({len(post2)} chars):")
        print(f"    {post2[:80]}...")
    else:
        print("  Post 2 - Met Office Long Range: (skipped - no data)")

    post3 = generate_ai_commentary(metoffice, model_summary)
    print(f"  Post 3 - AI Commentary ({len(post3)} chars):")
    print(f"    {post3[:80]}...")

    post4 = generate_stats_post(model_summary)
    print(f"  Post 4 - Stats ({len(post4)} chars):")
    print(f"    {post4[:80]}...")

    if dry_run:
        print()
        print("=" * 50)
        print("PREVIEW (not posting):")
        print()
        print("POST 1 (Met Office Today):")
        print(post1)
        print()
        if post2:
            print("POST 2 (Met Office Long Range) - reply:")
            print(post2)
            print()
        print("POST 3 (AI Commentary) - reply:")
        print(post3)
        print()
        print("POST 4 (Stats) - reply:")
        print(post4)
        print("=" * 50)
        print()
        print("(Attribution in pinned post)")
        return 0

    # Step 4: Post thread to Bluesky
    print()
    print("Posting thread to Bluesky...")

    # Post 1: Met Office today (root of thread)
    result1 = post_to_bluesky(post1, handle=bsky_handle, password=bsky_password)
    if not result1:
        print("  Failed to post Met Office today")
        return 1
    print(f"  Post 1: {result1['uri']}")
    root_post = result1  # All replies point to this as root
    last_result = result1

    # Post 2: Met Office long range (if available)
    if post2:
        result2 = post_to_bluesky(post2, reply_to=last_result, root_post=root_post,
                                   handle=bsky_handle, password=bsky_password)
        if not result2:
            print("  Failed to post Met Office long range")
            return 1
        print(f"  Post 2: {result2['uri']}")
        last_result = result2

    # Post 3: AI Commentary
    result3 = post_to_bluesky(post3, reply_to=last_result, root_post=root_post,
                               handle=bsky_handle, password=bsky_password)
    if not result3:
        print("  Failed to post AI commentary")
        return 1
    print(f"  Post 3: {result3['uri']}")

    # Post 4: Stats
    result4 = post_to_bluesky(post4, reply_to=result3, root_post=root_post,
                               handle=bsky_handle, password=bsky_password)
    if not result4:
        print("  Failed to post stats")
        return 1
    print(f"  Post 4: {result4['uri']}")

    print()
    print("Daily summary thread posted successfully")
    return 0


if __name__ == "__main__":
    exit(main())
