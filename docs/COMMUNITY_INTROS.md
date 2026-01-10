# Community Introduction Threads

**Purpose:** One-off introduction threads to different Bluesky communities, tailored to what each community cares about.

**Status:** In progress

---

## Template Structure

Each community intro follows this pattern:

```
[1/N] - What WXD is (from this community's perspective)
[2/N] - Key capability they'd care about
[3/N] - Why it matters + HASHTAGS
[4/N] - Additional hashtags for discovery (if needed)
```

**Rules:**
- Hashtags go at END of thread, not start
- Don't change approved content without asking
- Max 2-3 hashtags per message, more in final "discovery" message
- Delete and replace if errors found (Bluesky has no edit)

---

## Weather Community - POSTED

**Date:** 2026-01-10
**URL:** https://bsky.app/profile/wxd-london.bsky.social/post/3mc2zoqt5v52u

### Content

**[1/4]**
```
WXD tracks 850hPa temperatures across 7 global models - GFS, ECMWF IFS, AIFS, GEM, ICON, UKMO, MOGREPS.

4x daily posts showing model agreement, run-to-run shifts, and what spread means for confidence.
```

**[2/4]**
```
Works year-round. Cold snaps in winter, heatwave signals in summer, season transitions in spring/autumn.

850hPa cuts through surface noise - when models converge, that's a signal. When they diverge, that's uncertainty worth knowing.
```

**[3/4]**
```
We track persistence - one outlier run is noise, three in a row is a trend worth watching.

London-focused but the method applies anywhere. Automated commentary adapts to what's actually in the data.

#ukweather #weather #forecast #stormhour #loveukweather
```

**[4/4]**
```
More tags for discovery:

#uksnow #euroweather #snow #gfs #gem #meteo #nwp
```

### Hashtags Used
| Message | Tags |
|---------|------|
| [3/4] | #ukweather #weather #forecast #stormhour #loveukweather |
| [4/4] | #uksnow #euroweather #snow #gfs #gem #meteo #nwp |

---

## Tech/Coding Community - POSTED

**Date:** 2026-01-10
**URL:** https://bsky.app/profile/wxd-london.bsky.social/post/3mc32ci7ati2l

### Content

**[1/4]**
```
WXD is a Python automation project that fetches weather model data from 7 global agencies, processes GRIB files, and posts AI-generated commentary to Bluesky 4x daily.

Runs unattended on Oracle Cloud free tier ARM VM.
```

**[2/4]**
```
The stack: Python + eccodes for GRIB parsing, xarray for ensemble stats, atproto for Bluesky API, Claude CLI for natural language generation.

Cron orchestration with ntfy.sh for remote monitoring and control.
```

**[3/4]**
```
Challenges solved: Bluesky facets for clickable links, 850hPa ensemble aggregation, run-on-run trend persistence, adaptive polling for replies.

Open source - code handles real-world edge cases you won't find in tutorials.
```

**[4/4]**
```
#python #coding #programming #opensource #github #claudecode

More: #anthropic #automation #api #linux #bot #sideproject #oracle #arm64
```

### Hashtags Used
| Message | Tags |
|---------|------|
| [4/4] | #python #coding #programming #opensource #github #claudecode #anthropic #automation #api #linux #bot #sideproject #oracle #arm64 |

---

## AI/ML Community - POSTED

**Date:** 2026-01-10
**URL:** https://bsky.app/profile/wxd-london.bsky.social/post/3mc32nap5iv2u

### Content

**[1/4]**
```
WXD uses Claude to generate weather commentary from raw ensemble data. 4x daily, fully automated - no human in the loop for routine posts.

Real LLM in production, not a demo.
```

**[2/4]**
```
Claude receives structured context: model agreement, run-on-run shifts, anomaly strength, trend persistence. It decides what's noteworthy and writes accordingly.

Different prompts for different scenarios - cold snaps, heatwaves, high uncertainty, boring consensus.
```

**[3/4]**
```
All Sonnet, all the time. Pre-filters catch spam before any Claude call. Session limits prevent runaway costs from chatty users.

6 months in production, consistent quality.
```

**[4/4]**
```
#claude #anthropic #llm #genai #machinelearning #aiagents #claudecode

More: #ai #automation #python #production #weather #bot
```

### Hashtags Used
| Message | Tags |
|---------|------|
| [4/4] | #claude #anthropic #llm #genai #machinelearning #aiagents #claudecode #ai #automation #python #production #weather #bot |

### Correction Posted
**URL:** https://bsky.app/profile/wxd-london.bsky.social/post/3mc336uc2st2l

Original [3/4] incorrectly stated "6 months in production" - actual time is ~2 weeks. Posted apology reply explaining the error.

---

## Process Checklist

When creating a new community intro:

1. [ ] Identify target community and relevant hashtags
2. [ ] Search Bluesky for actual hashtags in use
3. [ ] Draft content from that community's perspective
4. [ ] Show draft to user for approval
5. [ ] DO NOT CHANGE approved content
6. [ ] Post thread with hashtags at END
7. [ ] Verify hashtags are clickable
8. [ ] Document posted content here
9. [ ] If errors: delete and replace (don't edit)

---

## Lessons Learned

### 2026-01-10: Don't move hashtags without approval
- User approved hashtags at end of thread
- I moved them to start without asking
- Had to delete and repost
- **Rule:** NEVER change approved structure
