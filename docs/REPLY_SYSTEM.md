# WXD Reply System Architecture

## Overview

The WXD Reply System monitors replies to WXD posts on Bluesky and responds intelligently using Claude CLI. It implements a multi-tier engagement model with cost controls, abuse prevention, and human-in-the-loop approval for sensitive responses.

**Key Principle:** WXD is a weather analysis service, NOT a free chatbot. All design decisions prioritize cost control and preventing abuse while maintaining genuine weather-related engagement.

---

## Core Components

### Scripts
- `reply_listener.py` - Main reply processing script (cron every 4h)
- `fetch_own_posts.py` - Fetches WXD's post history for audit/analytics

### State Files
- `data/reply_listener_state.json` - Processed replies, chat sessions, usage stats
- `data/corrections_review.json` - Logged corrections for owner review

### Cron Schedule
```
0 */4 * * * cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && python reply_listener.py --post >> cron_replies.log 2>&1
```

---

## User Tiers

| Tier | Definition | Behavior |
|------|------------|----------|
| **Blocked** | DIDs in blocklist | Silent ignore, no processing |
| **Non-follower** | Does not follow WXD | One-time canned message, then ignore |
| **Follower** | Follows WXD | Standard engagement rules |
| **Trusted** | Friends/approved accounts | Higher limits, auto-approve most responses |

### Tier Configuration (in state file)
```json
{
  "blocklist": ["did:plc:troll1", "did:plc:troll2"],
  "trusted_users": [
    {"did": "did:plc:xxx", "handle": "friend.bsky.social", "added": "2025-12-31"}
  ],
  "notified_non_followers": ["did:plc:yyy", "did:plc:zzz"]
}
```

---

## Two-Step Engagement Model

Claude is ONLY invoked when a user explicitly opts in. This prevents abuse and minimizes API costs.

### Step 1: Initial Reply (No Claude Call)
Any first reply from a follower receives a canned acknowledgment:
```
Thanks for the reply! WXD is trialing automated AI responses.
Reply "chat" to continue this conversation.
```

### Step 2: User Opts In with "chat"
If the user replies with "chat", a chat session begins and Claude is invoked.

### Flow Diagram
```
New reply arrives
    |
    +-- Blocked DID? --> Silent ignore
    |
    +-- Pass-through (@tags, mentions)? --> Silent ignore
    |
    +-- Non-follower?
    |       +-- Already notified? --> Silent ignore
    |       +-- Not notified? --> Canned "followers only" msg, mark notified
    |
    +-- Follower:
            +-- Active chat session?
            |       +-- Session expired (>72h)? --> End session, treat as new
            |       +-- Message limit hit? --> Canned "session limit reached"
            |       +-- Within limits? --> Claude call, continue chat
            |
            +-- No active session:
                    +-- Reply is "chat"? --> Start session, Claude call
                    +-- Any other reply? --> Canned "reply 'chat' to continue"
```

---

## Pre-Filters (Before Claude)

These filters run BEFORE any Claude API call to minimize costs:

### 1. Blocklist Check
```python
if author_did in BLOCKLIST:
    return IGNORE
```

### 2. Pass-Through Detection
Replies that are users tagging friends, not engaging with WXD:
```python
def is_pass_through(reply_text: str) -> bool:
    mentions = re.findall(r'@[\w.]+', reply_text)
    # 2+ mentions = tagging friends
    if len(mentions) >= 2:
        return True
    # Mostly @handles
    handle_chars = sum(len(m) for m in mentions)
    if handle_chars > len(reply_text) * 0.5:
        return True
    # Starts with @mention (tagging someone)
    if re.match(r'^@[\w.]+\s', reply_text):
        return True
    return False
```

### 3. Follower Check
Uses Bluesky API to verify the replier follows WXD:
```python
# app.bsky.graph.getFollowers or relationship check
is_follower = check_follows_wxd(client, author_did)
```

### 4. Off-Topic Detection (Optional)
Pattern matching for general AI chat requests:
```python
OFF_TOPIC_PATTERNS = [
    r'\b(write|code|poem|story|help me with)\b',
    r'\b(how are you|hello|hi there|hey bot)\b',
]
```
Response: Canned redirect to claude.ai/ChatGPT

---

## Chat Sessions

### Session Limits

| User Type | Messages per Session | Session Expiry |
|-----------|---------------------|----------------|
| Standard Follower | 5 messages | 72 hours idle |
| Trusted/Friend | 10 messages | 72 hours idle |

### Session State
```json
{
  "active_sessions": {
    "did:plc:xxx": {
      "started": "2025-12-31T10:00:00Z",
      "last_activity": "2025-12-31T12:30:00Z",
      "message_count": 3,
      "thread_uri": "at://did:plc:wxd/app.bsky.feed.post/abc123"
    }
  }
}
```

### Session Lifecycle
1. **Start**: User replies "chat" to WXD's invitation
2. **Continue**: Each reply within limits triggers Claude response
3. **End**: Session expires after 72h idle OR message limit hit
4. **Restart**: User can start new session by replying "chat" again

---

## Claude Classification (When Invoked)

For active chat sessions, Claude classifies replies and generates responses:

### Classifications
| Type | Action | ntfy Approval |
|------|--------|---------------|
| `genuine_question` | Weather-related answer | Required |
| `topic_suggestion` | Brief thanks, log topic | Auto (followers) |
| `appreciation` | Brief thanks | Auto |
| `correction` | Acknowledge, log for review | **Always required** |
| `spam` | Ignore | N/A |

### Claude Prompt Template
```
You are WXD, a weather analysis bot on Bluesky. Analyze this reply.

YOUR POST: {parent_text}
REPLY FROM USER: {reply_text}
CONVERSATION HISTORY: {session_history}

Classify and respond. Categories:
1. genuine_question - Weather question → helpful answer
2. topic_suggestion - Future topic idea → brief thanks
3. appreciation - Thanks/praise → brief thanks
4. correction - Error pointed out → acknowledge, flag
5. spam - Off-topic/promotional → ignore

Output JSON:
{
    "classification": "...",
    "should_respond": true/false,
    "response_text": "max 280 chars",
    "reason": "explanation"
}
```

---

## Usage Limits & Cost Control

### Daily Limits (Initial - TBD based on usage)
```json
{
  "limits": {
    "daily_claude_calls": 10,
    "daily_active_sessions": 3,
    "per_user_daily": 3,
    "per_user_daily_trusted": 10
  }
}
```

### Usage Tracking
```json
{
  "usage": {
    "today": {
      "date": "2025-12-31",
      "claude_calls": 5,
      "replies_sent": 3,
      "sessions_started": 2
    },
    "this_week": 23,
    "this_month": 89
  },
  "per_user_today": {
    "did:plc:xxx": 2,
    "did:plc:yyy": 1
  }
}
```

### Limit Enforcement
- Daily limit hit → Skip all Claude calls for rest of day
- Per-user limit hit → Ignore further replies from that user
- ntfy alert at 80% and 100% of limits

---

## ntfy Integration

### Notifications Sent
1. **Correction received** - Always notify for review
2. **Question pending approval** - For genuine_question classification
3. **Limit warnings** - At 80% and 100% of daily limits
4. **Daily digest** - Summary of activity (optional)

### ntfy Commands (Future)
```
approve <reply_id>   - Approve pending response
reject <reply_id>    - Reject, don't respond
trust @handle        - Add to trusted users
block @handle        - Add to blocklist
untrust @handle      - Remove from trusted
```

---

## Canned Responses

Pre-defined responses that don't require Claude:

```python
CANNED_RESPONSES = {
    "non_follower": "Thanks for reaching out! WXD replies are currently limited to followers. Follow for weather updates and responses.",

    "chat_invitation": "Thanks for the reply! WXD is trialing automated AI responses. Reply 'chat' to continue this conversation.",

    "session_limit": "You've reached the message limit for this chat session. Start a new conversation anytime by replying 'chat' to a future post.",

    "daily_limit": "WXD has reached its daily response limit. Check back tomorrow!",

    "off_topic": "WXD is a weather analysis bot focused on UK forecasts. For general AI chat, try claude.ai or ChatGPT."
}
```

---

## Corrections Handling

Corrections are special - they always require human review:

### Flow
1. Claude classifies reply as `correction`
2. Immediate acknowledgment posted: "Thanks for the feedback, noted for review"
3. Correction logged to `data/corrections_review.json`
4. ntfy notification sent to owner
5. Owner reviews and decides if action needed

### Correction Log Format
```json
{
  "corrections": [
    {
      "id": "corr_001",
      "date": "2025-12-31T10:00:00Z",
      "author_handle": "user.bsky.social",
      "author_did": "did:plc:xxx",
      "original_post_uri": "at://...",
      "reply_text": "Actually the GFS shows...",
      "status": "pending",
      "reviewed": null,
      "action_taken": null
    }
  ]
}
```

---

## Command Line Interface

```bash
# Dry run - show what would happen
python reply_listener.py

# Live mode - actually post replies
python reply_listener.py --post

# Check specific number of posts
python reply_listener.py --limit 5

# Set max replies per run
python reply_listener.py --max-replies 3

# Future: Different modes
python reply_listener.py --auto          # Auto-approve safe responses
python reply_listener.py --notify        # Require approval for all
python reply_listener.py --dry-run       # Log only, no posts
```

---

## Monitoring & TODOs

### Active Monitoring
- [ ] Review 72h session expiry - adjust based on engagement patterns
- [ ] Set final daily Claude limits after observing usage
- [ ] Review per-user limits monthly
- [ ] Monitor for abuse patterns

### Future Enhancements
- [ ] ntfy command processing for trust/block management
- [ ] Daily digest notifications
- [ ] Analytics dashboard
- [ ] Sentiment tracking across conversations

---

## Security Considerations

1. **Credentials** - Never hardcoded, always from environment variables
2. **Rate limiting** - Hard caps prevent runaway costs
3. **Blocklist** - Immediate filter for known bad actors
4. **Follower-only** - Limits exposure to random accounts
5. **Two-step opt-in** - Prevents drive-by abuse
6. **State file security** - Contains DIDs, keep gitignored if sensitive

---

## File Locations

```
wxd/
├── reply_listener.py          # Main script
├── fetch_own_posts.py         # Post history fetcher
├── data/
│   ├── reply_listener_state.json    # Main state (gitignored)
│   ├── corrections_review.json      # Corrections log (gitignored)
│   └── post_history.json            # Post history cache
├── docs/
│   └── REPLY_SYSTEM.md              # This document
└── cron_replies.log                 # Cron output log
```

---

## Version History

| Date | Change |
|------|--------|
| 2025-12-31 | Initial architecture design |
| TBD | Implementation of full system |
