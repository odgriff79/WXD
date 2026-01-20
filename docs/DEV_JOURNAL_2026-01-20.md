# Dev Journal - 2026-01-20

## Session Summary: SHIFT Context Fix & Post Registry Enforcement

### Context
User ran `wxd feedback` and identified an ICON post with misleading commentary: "Sharp warming revision: models now show Wednesday 21st at -0.9C (previously forecast -0.8C)" - citing a 0.1C cooler change as evidence of warming.

---

## Issue 1: Claude Cited Wrong Temperature Values

**Problem:** ICON commentary said "Sharp warming revision" but cited -0.8C → -0.9C (0.1C cooler) instead of the actual significant shift.

**Root Cause:**
- Actual significant shift was at Jan 21 12:00 UTC: +0.7C → +3.1C (+2.5C warmer)
- But Jan 21 00:00 showed -0.8C → -0.9C (noise)
- SHIFT context only said "Model moved 2.5C warmer around 2026-01-21" without the actual values
- Claude grabbed wrong values from TEMPERATURE TRAJECTORY section

**Fix:** Added actual temperature values to SHIFT context in `trackers/shared/analysis.py`:
```
SHIFT: Model moved 2.5C warmer since last run around 2026-01-21 (+0.7C → +3.1C) - USE THESE EXACT VALUES IF MENTIONING THE SHIFT
```

Updated both `analyze_run_diff_ensemble()` and `analyze_run_diff_deterministic()` to return `prev_temp` and `curr_temp` values.

**Files:** `trackers/shared/analysis.py` lines 458-492, 531-567, 887-893

---

## Issue 2: Session Fumbled Post Lookup

**Problem:** When investigating the feedback, I fumbled with raw Bluesky API calls instead of using the post registry - wasted time and made errors.

**Root Cause:** Didn't follow documented workflow. Post registry had the data all along.

**Fix:** Added enforcement to CLAUDE.md:

1. **STOP AND READ section** (top of file):
   - "Feedback/post lookup? Use `data/post_registry.json` - DO NOT fumble with raw API calls"

2. **DO NOT section**:
   - "Fumble with raw Bluesky API calls when looking up posts - USE `data/post_registry.json`. The registry exists for a reason. Incident logged 2026-01-20."

3. **Post Lookup instructions** added with grep/jq examples

---

## Verification

**Post Registry Status:** All 9 tracker types registering correctly:
- ICON: 27 posts (latest 2026-01-20T16:01)
- MOGREPS: 30 posts (latest 2026-01-20T15:02)
- UKMO: 10 posts (latest 2026-01-20T07:00)
- Main: 10 posts (latest 2026-01-20T09:28)
- daily_summary: 11 posts
- engagement: 11 posts
- met_warnings: 2 posts
- weekly: 6 posts
- manual: 15 posts

Total: 122 registered posts.

**ICON Dry-Run Test:** New commentary correctly describes oscillation pattern without citing wrong values.

---

## Commits

- `8fb9379` - Fix SHIFT context to include actual temperature values, add post registry enforcement

---

## Lessons

1. **When systems exist, use them** - Post registry was there and working. Fumbling with raw API calls wasted time and caused confusion.

2. **Context must be unambiguous** - Giving Claude a direction ("2.5C warmer") without the actual values lets it pick wrong ones from other data.

3. **Log incidents in CLAUDE.md** - Future sessions need to see what went wrong to avoid repeating mistakes.
