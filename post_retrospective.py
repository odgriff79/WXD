#!/usr/bin/env python3
"""Post the 3-days-in retrospective thread to Bluesky."""

import os
import sys
import time
from atproto import Client

MAX_CHARS = 300

# Raw content without numbering - will be numbered after splitting
RAW_POSTS = [
    "3 days in - what we've learned\n\nWXD launched Dec 27 with 4 models on a 1GB RAM VM. 72 hours later: 7 model trackers, daily Met Office summaries, weather warnings, engagement posts, remote commands. Same tiny server.\n\nHere's what worked, what broke, and what we learned building in public.",

    "The Pacific Ocean incident\n\nMOGREPS tracker showed completely inverted data vs references. Spent hours checking calculations.\n\nRoot cause? Longitude convention. Our code used 359.87° (0-360 format). MOGREPS uses -180 to +180. With nearest-neighbor matching, we fetched the Pacific Ocean instead of London.\n\nFix: Use -0.1278° directly.",

    "UKMO too warm\n\nFirst UKMO implementation showed -6.9°C when verification sites showed -8°C.\n\nProblem: Used \"seamless\" model which smooths extremes for nicer transitions.\n\nFix: Switched to deterministic 10km model. Now matches reality.\n\nLesson: \"Seamless\" isn't always better. For cold alerts, accuracy beats smoothness.",

    "ICON - when APIs fail\n\nOpen-Meteo doesn't provide ICON 850hPa. Returns NULL.\n\nSolution: Go direct to DWD (German weather service) GRIB files. 40-member ensemble, ~110MB per run.\n\nChallenge: ICON uses unstructured icosahedral grid (164,984 cells). Standard tools don't work.\n\nFix: Python eccodes + grid definition file.",

    "The 1GB RAM reality\n\nClaude AI commentary spikes memory. ICON downloads 110MB. All on 1GB.\n\nSolution 1: 2GB swap file. Not elegant but prevents OOM kills.\n\nSolution 2: Process GRIB files sequentially, one at a time, clean up aggressively.\n\nResult: Load average stays ~0.02. The VM handles everything.",

    "Confidence vs timing confusion\n\nEarly posts said \"Confidence: low\" when all 4 models agreed on cold. Made it sound uncertain.\n\nProblem: Conflated two things:\n- Will cold happen? (YES - all models agree)\n- Exactly which day? (less certain)\n\nFix: \"Cold locked in. Timing: Jan 3-5 (±2 days)\"\n\nResearched Met Office/ECMWF practices to get this right.",

    "Daily Met Office integration\n\nAdded daily summary thread that scrapes Met Office narrative and compares with WXD numerical data.\n\nAlso scrapes active weather warnings - Yellow/Amber/Red alerts posted separately.\n\nGives context that pure numbers don't. \"Met Office says cold, our models agree, here's the detail.\"",

    "Alert threading\n\nCold alerts, warm alerts, model divergence, rapid swings - all posted as replies to main forecast, not separate posts.\n\nCreates tidy threads. Keeps timeline clean. All context in one place.\n\nPercentile framing added: \"100% of GFS members below -5°C by Dec 30\" tells you ensemble agreement at a glance.",

    "Trend persistence\n\nNow tracks consecutive runs showing same signal.\n\n\"Cold signal run #7, strengthening\" means 7 runs in a row with cold, and it's getting colder each time.\n\n\"Cold signal run #4, weakening\" means signal persists but is easing.\n\nRun persistence = confidence the signal is real, not noise.",

    "Bimodal detection\n\nSometimes ensembles split into distinct scenarios.\n\n\"GFS: 73% cold (-8°C) vs 27% mild (-1°C)\" means the ensemble doesn't agree internally. Two possible futures.\n\nMore useful than just showing the mean, which would hide this uncertainty.",

    "Remote control\n\nCan trigger previews, fresh fetches, and status checks from phone via ntfy.sh.\n\n10+ commands: preview each tracker, force fresh data, check Met summary, test engagement posts.\n\nUseful for monitoring when away from computer.",

    "What's next\n\nDevelopment will plateau as things stabilize. That's fine - it runs itself.\n\nPlanning migration to larger VM as project matures. But proving it works on minimal resources first felt important.\n\nMore retrospectives when significant changes happen. Questions welcome."
]

def split_post(text, max_chars):
    """Split a post into chunks that fit within max_chars, breaking at paragraph or sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        # Find a good break point
        # First try paragraph break
        break_point = remaining[:max_chars].rfind('\n\n')
        if break_point < max_chars // 2:
            # Try single newline
            break_point = remaining[:max_chars].rfind('\n')
        if break_point < max_chars // 2:
            # Try sentence break
            break_point = remaining[:max_chars].rfind('. ')
            if break_point > 0:
                break_point += 1  # Include the period
        if break_point < max_chars // 2:
            # Last resort: break at space
            break_point = remaining[:max_chars].rfind(' ')
        if break_point < 0:
            break_point = max_chars

        chunks.append(remaining[:break_point].strip())
        remaining = remaining[break_point:].strip()

    return chunks

def prepare_posts():
    """Split long posts and add numbering."""
    all_chunks = []

    for post in RAW_POSTS:
        # Reserve space for "[XX/XX] " prefix (9 chars)
        effective_max = MAX_CHARS - 9
        chunks = split_post(post, effective_max)
        all_chunks.extend(chunks)

    # Add numbering
    total = len(all_chunks)
    numbered = [f"[{i+1}/{total}] {chunk}" for i, chunk in enumerate(all_chunks)]

    return numbered

POSTS = prepare_posts()

def post_thread(dry_run=False):
    """Post all messages as a threaded reply chain."""

    if dry_run:
        print("=== DRY RUN - Thread Preview ===\n")
        for i, post in enumerate(POSTS):
            print(f"--- Post {i+1}/12 ({len(post)} chars) ---")
            print(post)
            print()
        return

    # Get credentials
    handle = os.environ.get('BSKY_HANDLE')
    password = os.environ.get('BSKY_PASSWORD')

    if not handle or not password:
        print("ERROR: BSKY_HANDLE and BSKY_PASSWORD must be set")
        sys.exit(1)

    # Login
    client = Client()
    client.login(handle, password)
    print(f"Logged in as {handle}")

    parent_uri = None
    parent_cid = None
    root_uri = None
    root_cid = None

    for i, text in enumerate(POSTS):
        print(f"Posting {i+1}/12... ", end="", flush=True)

        # Build reply reference if not first post
        reply_ref = None
        if parent_uri and parent_cid:
            reply_ref = {
                "root": {"uri": root_uri, "cid": root_cid},
                "parent": {"uri": parent_uri, "cid": parent_cid}
            }

        # Post
        response = client.send_post(text=text, reply_to=reply_ref)

        # Store references for threading
        parent_uri = response.uri
        parent_cid = response.cid
        if i == 0:
            root_uri = response.uri
            root_cid = response.cid

        print(f"OK ({len(text)} chars)")

        # Rate limit - wait between posts
        if i < len(POSTS) - 1:
            time.sleep(2)

    print(f"\nThread posted successfully!")
    print(f"Root: {root_uri}")

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    post_thread(dry_run)
