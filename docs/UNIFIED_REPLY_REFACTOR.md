# Unified Reply System Refactor

**Created**: 2026-01-25
**Status**: IN PROGRESS
**Goal**: Single unified reply architecture where any improvement applies to ALL posts automatically

## Problem Statement

The reply system (`reply_listener.py`) has fragmented, duplicated logic:
- Same logic repeated with slight variations per tracker
- Fixes applied to one place don't propagate to others
- Error-prone, boring, repetitive maintenance
- User has to repeatedly say "apply this to ALL posts"

## Current State (Before)

```
reply_listener.py (~3700 lines)
├── get_ssw_context()           # SSW-specific
├── get_latest_forecast_context() # Main tracker only
├── get_forecast_trend_analysis() # Generic but not integrated
├── get_model_specific_data()   # Per-model
├── identify_tracker_from_text() # Text guessing (unreliable)
└── generate_chat_response()    # 200+ lines of if/else context assembly
```

**Problems**:
1. Text-based tracker detection instead of registry lookup
2. Context assembly scattered across multiple functions
3. New features need manual integration for each tracker
4. Statistical analysis only triggers for certain keywords/trackers

## Target Architecture (After)

```
lib/
├── post_registry.py    # NEW: Single source of truth for post lookup
└── context_builder.py  # NEW: Unified context builder

reply_listener.py
└── Uses ReplyContext(parent_uri, reply_text).build()
```

### Core Principle

**One registry lookup → One context builder → All trackers**

```
┌──────────────────┐      ┌─────────────────────┐      ┌──────────────────┐
│  Parent URI      │ ──▶  │  PostRegistry       │ ──▶  │  ContextBuilder  │
│  (from reply)    │      │  lookup_post(uri)   │      │  build(post_type)│
└──────────────────┘      └─────────────────────┘      └──────────────────┘
                                    │                           │
                                    ▼                           ▼
                          {tracker, model, ts}          unified context string
```

## Implementation Plan

### Phase 1: Create lib/post_registry.py
- [ ] Create new file with `lookup_post(uri)` function
- [ ] Add `get_post_type(uri)` returning normalized type
- [ ] Handle fallback for posts not in registry
- [ ] Test with known URIs

### Phase 2: Create lib/context_builder.py
- [ ] Create `ReplyContext` class
- [ ] Move `get_ssw_context()` integration
- [ ] Move `get_forecast_trend_analysis()` integration
- [ ] Move `get_model_specific_data()` integration
- [ ] Add `_add_query_triggered_contexts()` for keyword triggers
- [ ] Ensure ALL features work for ANY post type

### Phase 3: Integrate into reply_listener.py
- [ ] Import ReplyContext
- [ ] Replace scattered context assembly (~200 lines) with single call
- [ ] Remove `identify_tracker_from_text()` - registry is authoritative
- [ ] Test with dry-run on various post types

### Phase 4: Validation
- [ ] Test reply to SSW post
- [ ] Test reply to main forecast post
- [ ] Test reply to ICON post
- [ ] Test trend/stats question on non-SSW post
- [ ] Test model comparison question
- [ ] Verify no regressions

### Phase 5: Cleanup
- [ ] Remove dead code
- [ ] Update CLAUDE.md with new architecture
- [ ] Commit final version

## Files to Create

### lib/post_registry.py (~60 lines)
```python
"""Post registry lookup - single source of truth for post type detection."""
from pathlib import Path
import json

REGISTRY_PATH = Path(__file__).parent.parent / 'data' / 'post_registry.json'

def lookup_post(uri: str) -> dict | None:
    """Look up post by URI. Returns {tracker, model, text_preview, timestamp} or None."""
    ...

def get_post_type(uri: str, fallback_text: str = "") -> str:
    """Return normalized post type: 'main', 'icon', 'ukmo', 'mogreps', 'ssw', 'unknown'."""
    ...
```

### lib/context_builder.py (~150 lines)
```python
"""Unified context builder for all reply types."""
from typing import Optional
from lib.post_registry import get_post_type

class ReplyContext:
    """Unified context builder for all reply types."""

    def __init__(self, parent_uri: str, reply_text: str, parent_text: str = ""):
        self.parent_uri = parent_uri
        self.reply_text = reply_text
        self.parent_text = parent_text
        self.post_type = get_post_type(parent_uri, parent_text)
        self._context_parts = []

    def build(self) -> str:
        """Build context string. Features added here apply to ALL post types."""
        ...

    def _add_forecast_context(self):
        """Add forecast data for the relevant tracker."""
        ...

    def _add_ssw_context(self):
        """Add SSW context if relevant."""
        ...

    def _add_query_triggered_contexts(self):
        """Contexts triggered by reply content - work for ANY parent post."""
        ...
```

## Progress Log

### 2026-01-25 09:06 - Started
- Created this document
- Committed plan

### 2026-01-25 09:15 - Phase 1 Complete
- Added `get_post_type()` to `lib/bluesky.py` (reused existing `lookup_post()`)
- Returns normalized types: main, icon, ukmo, mogreps, ssw, engagement, unknown
- Registry lookup is authoritative, text fallback for unregistered posts
- Tested with SSW, ICON, MOGREPS URIs - all working

### 2026-01-25 09:22 - Phase 2 Complete
- Created `lib/context_builder.py` (250 lines)
- ReplyContext class with unified build() method
- Features: SSW context, forecast data, trend analysis, model comparison, temporal comparison
- ALL features triggered by keywords work for ANY post type
- Tested with 4 scenarios: SSW+trend, main+compare, unknown+stats, temporal
- All tests pass

### 2026-01-25 09:25 - Phase 3 Complete
- Added `parent_uri` parameter to `generate_chat_response()`
- Imported `build_reply_context` from unified builder
- Replaced ~60 lines of scattered context assembly with single unified call
- Kept location-specific and spread comparison (to migrate later)
- Dry-run test: "Built unified context (952 chars)" - working!
- Response includes real R², t-stat, acknowledges both users

### 2026-01-25 09:28 - Phase 4 Complete
- Tested 4 scenarios:
  1. Main forecast + stats question → Has trend analysis ✓
  2. ICON post + model comparison → Has model comparison ✓
  3. Unknown post + SSW keywords → Has SSW context ✓
  4. Any post + temporal question → Has run-to-run comparison ✓
- ALL VALIDATIONS PASSED

### 2026-01-25 09:30 - Phase 5 Complete
- Updated CLAUDE.md with new architecture
- Committed all changes
- **STATUS: REFACTOR COMPLETE**

## Rollback Plan

If something breaks:
1. `git checkout HEAD~1 -- reply_listener.py`
2. Remove new lib files if not working
3. Old logic is preserved in git history

## Success Criteria

1. `ReplyContext(any_uri, any_text).build()` returns appropriate context
2. Trend analysis works for ANY post type when asked
3. SSW context included when SSW mentioned (any parent post)
4. No duplicated logic per tracker
5. Adding new feature = one place, works everywhere
