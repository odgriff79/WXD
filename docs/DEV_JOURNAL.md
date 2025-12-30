# WXD Development Journal

A narrative record of WXD's development - problems, solutions, and lessons learned. Used for periodic "dev retrospective" engagement posts.

---

## Project Genesis (Dec 27, 2025)

**Initial idea:** Automated weather ensemble bot for Bluesky. Fetch 850hPa temperature data from multiple models, generate AI commentary, post automatically.

**Day 1 scope:** Single tracker (Tracker A) with 4 models via Open-Meteo:
- GFS (31 members)
- ECM (51 members)
- AIFS (51 members, AI-based)
- GEM (21 members)

**Infrastructure:** Oracle Cloud free tier - 1GB RAM, 1 OCPU. Ambitious for what we were planning.

---

## The 1GB RAM Challenge

Running Claude CLI for AI commentary on a 1GB VM was... optimistic.

**Problem:** Claude CLI would occasionally spike memory usage, causing OOM kills.

**Solution:** Added 2GB swap file. Not fast, but keeps things alive during commentary generation.

**Lesson:** Start minimal, add resources as needed. The VM handles 4 trackers, daily summaries, and 24/7 ntfy listener with load average ~0.02. The swap is insurance, not constant use.

---

## Tracker Expansion (Dec 28-29)

Original plan was just Tracker A. Then scope creep happened (the good kind):

### Tracker B: ICON-EU-EPS
**Problem:** Open-Meteo doesn't provide ICON 850hPa data. Returns NULL.

**Solution:** Go direct to source - DWD GRIB files. 40-member ensemble, ~110MB download per run.

**Challenge:** ICON uses unstructured icosahedral grid (164,984 cells). Normal GRIB tools don't work.

**Solution:** Python eccodes + grid definition file. Find nearest cell to London (index 113327), extract values.

**Lesson:** When APIs fail, the raw data is usually available somewhere. It's just harder.

### Tracker D: UKMO Global
**Problem:** First implementation used `ukmo_seamless` which smoothed extremes. Showed -6.9°C when actual was -8°C.

**Solution:** Switched to `ukmo_global_deterministic_10km`. Matches verification sites.

**Lesson:** "Seamless" models prioritize smooth transitions over accuracy at extremes. For cold alerts, use the deterministic.

### Tracker C: MOGREPS-G
This one taught us the most lessons.

---

## The MOGREPS Pacific Disaster (Dec 29)

**Symptom:** Chart showed completely inverted trend vs reference data. We thought the data was wrong.

**Root cause:** Longitude convention mismatch.
- Our code: 359.87° (0-360 convention, for London at -0.1278°)
- MOGREPS files: -180 to +180 convention

With `method='nearest'`, 359.87° snapped to 179.86° - the **Pacific Ocean**, not London.

**Fix:** Use -0.1278° directly instead of converting to 0-360.

**Debug confirmation:** After fix, selection was -0.14° (London). Before fix, 179.86° (middle of Pacific).

**Lesson:** Always verify coordinates in the actual data. "It's fetching data" doesn't mean it's the right location.

---

## MOGREPS S3 Timing Issues

**Problem:** MOGREPS files on AWS S3 upload progressively. Early cron runs had incomplete forecast ranges.

**Original timing:** 4 hours after run
**Problem:** Only partial forecast hours available

**New timing:** 9 hours after run (03:00, 09:00, 15:00, 21:00 UTC)

**Added safeguards:**
1. Minimum 4 forecast hours required before posting
2. Abort if run-to-run shift exceeds 10°C (indicates comparing to corrupted data)

**Lesson:** External data sources have their own schedules. You can't force them to be ready when you want.

---

## The Dry-Run Discipline

**Incident:** Posted something broken to live Bluesky before testing.

**Rule established:** ALWAYS `--dry-run` first. No exceptions.

**Implementation:** Added `--dry-run` flag to every tracker and script.

**Lesson:** It's faster to test than to apologize.

---

## Commentary Contradictions (Dec 30)

**Problem:** Posts said "Confidence: low" when all 4 models agreed on cold and it had persisted 7+ runs. Confusing.

**Root cause:** Conflating two different uncertainties:
1. Signal confidence (will cold happen?) - HIGH
2. Timing precision (exactly which day?) - LOWER

Saying "low confidence" made it sound like cold might not happen.

**Solution:** Researched Met Office, ECMWF, NWS best practices. Consulted GPT-4, Gemini, Claude. Consensus:

> Never collapse signal confidence and timing uncertainty into a single label.

**New framework:**
- SIGNAL: locked / strong / emerging / weak
- TIMING: date window with spread (±days)

**Example before:** "Confidence: low"
**Example after:** "Cold locked in (4/4 models, run 7). Coldest period Jan 3-5."

**Lesson:** Weather uncertainty has multiple dimensions. Communicate each clearly.

---

## The GRIB File Size Reality

ICON downloads ~110MB of GRIB per run. On a 1GB VM with swap.

**Approach:**
- Process files sequentially, one at a time
- Only keep what we need in memory
- Clean up aggressively

**Result:** Works fine. Load stays low. The VM is surprisingly capable.

**Lesson:** Big data doesn't require big infrastructure if you're careful about memory.

---

## Chart Gallery on GitHub Pages

**Problem:** Bluesky image compression. Charts looked fuzzy.

**Solution:** Host full-res charts on GitHub Pages. `sync_charts.sh` pushes after each run.

**URL:** odgriff79.github.io/WXD/

**Lesson:** Use platforms for what they're good at. Bluesky for engagement, GitHub for assets.

---

## Daily Summary Thread

Added Met Office narrative scraping + comparison with WXD ensemble data.

**Approach:** Fetch Met Office text, let Claude summarize and compare with our numerical data.

**Result:** Gives context that pure numbers don't. "Met Office says cold next week, our models agree, here's the detail."

---

## Engagement System Evolution

**Original:** Just forecast posts.
**Added:** Educational posts about weather topics.
**Evolved:** Context-aware topic selection based on current weather.

If data shows cold signal, weight toward cold-relevant topics. Summer? Warm topics.

**Schedule:**
- Sunday 12:00: Community request (ask for topics)
- Monday 20:00: Collect replies
- Tuesday 12:00: Educational post
- Friday 12:00: Educational post

---

## Resource Planning

The 1GB VM works. But as the project grows, we're planning migration to more capable instance.

**Why:**
- Faster fetches
- More headroom for concurrent operations
- Potential for additional trackers

**Philosophy:** Prove it works on minimal resources first. Scale when justified.

---

## What's Next

Development will naturally plateau as things stabilize. That's fine - the system runs itself.

Periodic retrospectives like this capture what was learned. If there's significant new development, another retrospective post.

---

## Key Lessons Summary

1. **1GB RAM can do a lot** if you're careful about memory
2. **Swap file as insurance** - not elegant, but works
3. **Verify coordinates** - "it's fetching" doesn't mean "it's correct"
4. **Always dry-run** - faster to test than apologize
5. **Multiple uncertainties** - communicate each dimension clearly
6. **Go to source** when APIs fail - raw data is usually available
7. **Start minimal, scale when justified**
8. **External data has its own schedule** - you can't force it

---

## Posted Retrospectives

### "3 Days In" Thread (Dec 30, 2025)

Hardcopy of retrospective thread posted to Bluesky:

---

**[1/12] 3 days in - what we've learned**

WXD launched Dec 27 with 4 models on a 1GB RAM VM. 72 hours later: 7 model trackers, daily Met Office summaries, weather warnings, engagement posts, remote commands. Same tiny server.

Here's what worked, what broke, and what we learned building in public.

**[2/12] The Pacific Ocean incident**

MOGREPS tracker showed completely inverted data vs references. Spent hours checking calculations.

Root cause? Longitude convention. Our code used 359.87° (0-360 format). MOGREPS uses -180 to +180. With nearest-neighbor matching, we fetched the Pacific Ocean instead of London.

Fix: Use -0.1278° directly.

**[3/12] UKMO too warm**

First UKMO implementation showed -6.9°C when verification sites showed -8°C.

Problem: Used "seamless" model which smooths extremes for nicer transitions.

Fix: Switched to deterministic 10km model. Now matches reality.

Lesson: "Seamless" isn't always better. For cold alerts, accuracy beats smoothness.

**[4/12] ICON - when APIs fail**

Open-Meteo doesn't provide ICON 850hPa. Returns NULL.

Solution: Go direct to DWD (German weather service) GRIB files. 40-member ensemble, ~110MB per run.

Challenge: ICON uses unstructured icosahedral grid (164,984 cells). Standard tools don't work.

Fix: Python eccodes + grid definition file. Find nearest cell, extract values.

**[5/12] The 1GB RAM reality**

Claude AI commentary spikes memory. ICON downloads 110MB. All on 1GB.

Solution 1: 2GB swap file. Not elegant but prevents OOM kills.

Solution 2: Process GRIB files sequentially, one at a time, clean up aggressively.

Result: Load average stays ~0.02. The VM handles everything.

**[6/12] Confidence vs timing confusion**

Early posts said "Confidence: low" when all 4 models agreed on cold. Made it sound uncertain.

Problem: Conflated two things:
- Will cold happen? (YES - all models agree)
- Exactly which day? (less certain)

Fix: "Cold locked in. Timing: Jan 3-5 (±2 days)"

Researched Met Office/ECMWF practices to get this right.

**[7/12] Daily Met Office integration**

Added daily summary thread that scrapes Met Office narrative and compares with WXD numerical data.

Also scrapes active weather warnings - Yellow/Amber/Red alerts posted separately.

Gives context that pure numbers don't. "Met Office says cold, our models agree, here's the detail."

**[8/12] Alert threading**

Cold alerts, warm alerts, model divergence, rapid swings - all posted as replies to main forecast, not separate posts.

Creates tidy threads. Keeps timeline clean. All context in one place.

Percentile framing added: "100% of GFS members below -5°C by Dec 30" tells you ensemble agreement at a glance.

**[9/12] Trend persistence**

Now tracks consecutive runs showing same signal.

"Cold signal run #7, strengthening" means 7 runs in a row with cold, and it's getting colder each time.

"Cold signal run #4, weakening" means signal persists but is easing.

Run persistence = confidence the signal is real, not noise.

**[10/12] Bimodal detection**

Sometimes ensembles split into distinct scenarios.

"GFS: 73% cold (-8°C) vs 27% mild (-1°C)" means the ensemble doesn't agree internally. Two possible futures.

More useful than just showing the mean, which would hide this uncertainty.

**[11/12] Remote control**

Can trigger previews, fresh fetches, and status checks from phone via ntfy.sh.

10+ commands: preview each tracker, force fresh data, check Met summary, test engagement posts.

Useful for monitoring when away from computer.

**[12/12] What's next**

Development will plateau as things stabilize. That's fine - it runs itself.

Planning migration to larger VM as project matures. But proving it works on minimal resources first felt important.

More retrospectives when significant changes happen. Questions welcome.

---

*Last updated: Dec 30, 2025*
