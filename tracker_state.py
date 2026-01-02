#!/usr/bin/env python3
"""
Tracker State Management

Maintains a JSON file tracking the last successful run of each tracker/job.
Dashboard reads this instead of parsing logs.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

STATE_FILE = Path('/home/ubuntu/wxd/data/tracker_state.json')

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def record_success(tracker_name: str, run_id: str = None):
    """Record a successful tracker run."""
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    state[tracker_name] = {
        'last_success': now,
        'run_id': run_id,
        'status': 'success'
    }
    save_state(state)
    print(f'  State recorded: {tracker_name} success at {now}')

def record_failure(tracker_name: str, error: str = None):
    """Record a failed tracker run."""
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    # Keep last success time if exists
    existing = state.get(tracker_name, {})
    state[tracker_name] = {
        'last_success': existing.get('last_success'),
        'last_failure': now,
        'error': error[:100] if error else None,
        'status': 'failed'
    }
    save_state(state)

def get_tracker_status(tracker_name: str) -> dict:
    """Get status for a specific tracker."""
    state = load_state()
    return state.get(tracker_name, {'status': 'unknown'})

def get_all_status() -> dict:
    """Get status for all trackers."""
    return load_state()

if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3:
        action = sys.argv[1]
        tracker = sys.argv[2]
        if action == 'success':
            run_id = sys.argv[3] if len(sys.argv) > 3 else None
            record_success(tracker, run_id)
        elif action == 'failure':
            error = sys.argv[3] if len(sys.argv) > 3 else None
            record_failure(tracker, error)
    else:
        print(json.dumps(get_all_status(), indent=2))
