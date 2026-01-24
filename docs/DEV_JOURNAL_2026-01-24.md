# Dev Journal - 2026-01-24

## Session Summary: SSW Monitor Posting & Commentary Fixes

### Context
User checked SSW status - discovered 26% ALERT hadn't posted today despite being above threshold. Multiple issues found with posting logic and commentary generation.

---

## Issue 1: Duplicate SSW Files

**Problem:** Two copies of ssw_monitor.py existed:
- `/home/ubuntu/wxd/ssw_monitor.py` (37KB, Jan 22) - active, correct URL
- `/home/ubuntu/wxd/ssw/ssw_monitor.py` (17KB, Jan 19) - stale, wrong URL (missing `_all_` in NOMADS path)

Same for ssw_verify.py.

**Fix:** Deleted stale copies in ssw/ subfolder. Root-level versions are canonical.

---

## Issue 2: Only 1 of 4 Cron Runs Could Post

**Problem:** Cron schedule had `--post` flag on only the 19:00 run:
```
0 7  ... python3 ssw_monitor.py          # NO --post
0 13 ... python3 ssw_monitor.py          # NO --post
0 19 ... python3 ssw_monitor.py --post   # ONLY this posts
0 1  ... python3 ssw_monitor.py          # NO --post
```

Also missing `~/.wxd_env` on most runs.

**Fix:** All 4 runs now have `--post` and source env file:
```
30 7 * * * cd /home/ubuntu/wxd && . venv/bin/activate && . ~/.wxd_env && python3 ssw_monitor.py --post
30 13 * * * ...
30 19 * * * ...
30 1 * * * ...
```

Offset to :30 to avoid clashing with UKMO at :00.

---

## Issue 3: 24h Cooldown Blocked Elevated Posts

**Problem:** POST_COOLDOWN_HOURS = 24 applied to ALL posts, including elevated states. Signal at 26% ALERT couldn't post because last post was 13.8h ago.

**User direction:** "If signal is above threshold we post" - cooldown is redundant when cron already rate-limits.

**Fix:** Cooldown only applies when NORMAL:
```python
if level == "NORMAL" and last_post_time:
    # check cooldown
```

Above threshold = always post (4x daily max from cron).

---

## Issue 4: Commentary Garbage Output

**Problem:** Posted raw Claude debug text: `Based on the data: **26%... Character count: 192 characters - fits with`

**Fix:** Updated prompt with strict rules:
- Output ONLY the comment text
- No markdown, no asterisks
- No meta-commentary about character counts

---

## Issue 5: Wrong Trend Context

**Problem:** Commentary said "rise from 13%" when chart showed drop from 36% to 26%. Was referencing last *posted* value, not actual previous run.

**Fix:**
1. Post text now gets prev_prob from history[-2], not state
2. Added trend arrows (↑/↓) based on >2% change from previous run
3. Pass history to generate_post_text()

---

## Issue 6: Missing Overall Trajectory

**Problem:** Commentary focused on run-to-run noise ("down from 36%") instead of bigger picture (signal rising from 0% a week ago).

**User direction:** "Draw imaginary line between points - which direction is it going?"

**Fix:** Calculate multi-day trend:
```python
recent_avg = avg of last 24h
older_avg = avg of 24-48h ago
if recent_avg > older_avg + 5: overall_trend = "RISING"
```

Prompt now includes:
- OVERALL TREND: RISING/FALLING/STEADY
- Week ago avg, 2 days ago avg, last 24h avg
- Days since signal emerged
- Instruction: focus on overall trend, not run-to-run noise

---

## Issue 7: Weather Predictions in Commentary

**Problem:** Commentary included "UK could see cold spell in early February" - making weather predictions from SSW signal.

**User direction:** "Don't make weather predictions, make SSW predictions"

**Fix:** Changed prompt rule from "Mention UK cold risk potential" to "Do NOT make weather predictions - only describe the SSW signal itself"

---

## Final Posted Content

Main post:
```
🌀 GEFS SSW: ALERT (26%)

8/31 members show reversal signal in 5-16 day window.

Vortex currently moderate (26 m/s).

(12/12 runs in last 24h elevated)
```

Commentary:
```
SSW signal continues building - now at 26% with steady reinforcement over the past week. The trend is clearly rising from near-zero two days ago.
```

---

## Commits

- `b2d5aa1` - SSW monitor: fix posting logic and improve commentary

---

## Lessons

1. **Cron flags matter** - Missing `--post` on 3/4 runs meant system looked broken when it was just misconfigured.

2. **Cooldowns should be conditional** - When above threshold, let the cron schedule be the rate limiter.

3. **Use actual history, not stale state** - Previous run data should come from history array, not cached state values.

4. **Trend = trendline through noise** - Run-to-run variance is noise. The story is the multi-day direction.

5. **Stay in lane** - SSW monitor reports SSW signal. Weather implications are for other systems.
