# Bluesky Hashtags Reference

**Last updated:** 2026-01-10
**Source:** Live Bluesky search results

## Rules

1. **Max 2-3 per post** - more looks spammy
2. **Don't tag routine posts** - only when adding value
3. **Respect established communities** - earn your place

---

## Weather Hashtags

### UK Weather (USE SPARINGLY)

| Tag | Community | When to Use |
|-----|-----------|-------------|
| #ukweather | Main UK weather community | Major events only - DON'T SPAM |
| #uksnow | UK Snow Map project territory | Respect their space, snow events only |
| #stormhour | Weather community hour | Check timing, storms only |
| #loveukweather | Enthusiast community | Occasional |

### General Weather

| Tag | Popularity | Use Case |
|-----|------------|----------|
| #weather | High | General weather posts |
| #forecast | Medium | Forecast discussions |
| #snow | Medium | Snow events |
| #storm | Medium | Storm events |
| #rain | Low | Rain events |

### Regional/Specialty

| Tag | Notes |
|-----|-------|
| #euroweather | European weather |
| #ireweather | Ireland weather |
| #azwx | Arizona weather (US format: state+wx) |
| #skiweather | Ski conditions |

---

## Tech/Coding Hashtags

### Python & Programming

| Tag | Popularity | WXD Relevant? |
|-----|------------|---------------|
| #python | Very High | Yes - tech posts |
| #coding | Very High | Yes |
| #programming | High | Yes |
| #opensource | Medium | Yes - we're open source |
| #github | Medium | Yes - project links |
| #code | Medium | Yes |
| #webdev | Medium | Maybe |
| #devops | Low | Infrastructure posts |

### Development Community

| Tag | Notes |
|-----|-------|
| #indiedev | Independent developers |
| #womenwhocode | Inclusive coding community |
| #devtools | Developer tools |
| #softwaredevelopment | Broader dev community |

---

## AI/ML Hashtags

### Claude & Anthropic

| Tag | Popularity | Notes |
|-----|------------|-------|
| #claude | High | Claude AI mentions |
| #claudecode | Medium | Claude Code tool specifically |
| #anthropic | Medium | Company mentions |

### General AI

| Tag | Popularity | Use Case |
|-----|------------|----------|
| #genai | High | Generative AI |
| #llm | Medium | Language model discussions |
| #machinelearning | Medium | ML topics |
| #aiagents | Medium | Automation/agents |
| #chatgpt | Medium | Comparisons |
| #deeplearning | Low | Technical ML |
| #aitools | Low | AI tooling |

### AI Art (NOT for WXD)

| Tag | Notes |
|-----|-------|
| #aiart | AI-generated art community |
| #stablediffusion | Image generation |
| #generativeart | Creative AI |

---

## WXD Post Type → Hashtag Guide

### Regular Automated Posts (4x daily)
```
NO HASHTAGS - would be spam
```

### Major Weather Event
```
#ukweather #weather
(only if genuinely significant)
```

### Snow Event
```
#snow #ukweather
(respect #uksnow - that's UK Snow Map's territory)
```

### Educational Thread (weather)
```
#weather #forecast
```

### Tech Deep Dive (Python/automation)
```
#python #opensource #automation
```

### Claude/AI Post
```
#claude #claudecode #llm
```

### Project Announcement
```
#python #opensource #claudecode
```

### Anthropic/Claude Comparison
```
#claude #anthropic #llm
```

---

## Communities to Respect

| Project | Tag | Notes |
|---------|-----|-------|
| UK Snow Map | #uksnow | Excellent automated snow forecast maps |
| Storm Hour | #stormhour | Timed community event |

---

## Hashtag Discovery

To find new relevant hashtags:

```python
from atproto import Client
import re

client = Client()
client.login(handle, password)

# Search for posts about a topic
results = client.app.bsky.feed.search_posts({'q': 'weather forecast', 'limit': 50})

# Extract hashtags
for post in results.posts:
    tags = re.findall(r'#(\w+)', post.record.text.lower())
    print(tags)
```

---

## Notes

- Bluesky hashtags work via facets (like links)
- The `BlueskyClient` module auto-detects hashtags
- Hashtag popularity changes over time - refresh periodically
