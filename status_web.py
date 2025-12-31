#!/usr/bin/env python3
"""
WXD Status Web Interface

Simple read-only FastAPI app for browser-based status and feedback review.

Run: uvicorn status_web:app --host 0.0.0.0 --port 8080
Access: http://VM_IP:8080 (via SSH tunnel or direct if firewall allows)

Endpoints:
  /           - Main status dashboard (HTML)
  /api/status - JSON status data
  /api/feedback - Recent feedback/training logs
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import json
from datetime import datetime, timezone
from pathlib import Path

app = FastAPI(title="WXD Status", description="Read-only status dashboard")

DATA_DIR = Path("/home/ubuntu/wxd/data")
STATE_FILE = DATA_DIR / "reply_listener_state.json"


def get_system_status() -> dict:
    """Get current system status."""
    status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "replies": {},
        "trackers": {},
        "feedback_count": 0,
        "pending_actions": []
    }

    # Reply listener state
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                state = json.load(f)
            status["replies"] = {
                "last_run": state.get("last_run", "Never"),
                "active_sessions": len(state.get("active_sessions", {})),
                "processed_count": len(state.get("processed_replies", []))
            }
    except Exception as e:
        status["replies"]["error"] = str(e)

    # Training/feedback log (inside state file)
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                state = json.load(f)
            logs = state.get("training_log", [])
            status["feedback_count"] = len(logs)
            # Count unreviewed (no 'reviewed' flag)
            unreviewed = [l for l in logs if not l.get("reviewed")]
            status["pending_actions"] = len(unreviewed)
    except:
        pass

    # Tracker status (last lines from cron logs)
    cron_files = [
        ("/home/ubuntu/wxd/cron.log", "tracker_a"),
        ("/home/ubuntu/wxd/trackers/icon/cron.log", "icon"),
        ("/home/ubuntu/wxd/trackers/mogreps/cron.log", "mogreps"),
        ("/home/ubuntu/wxd/trackers/ukmo/cron.log", "ukmo"),
    ]
    for log_path, name in cron_files:
        try:
            with open(log_path) as f:
                lines = f.readlines()
                if lines:
                    status["trackers"][name] = lines[-1].strip()[:80]
        except:
            status["trackers"][name] = "No log"

    return status


def get_feedback_logs(limit: int = 50) -> list:
    """Get recent feedback/training logs from state file."""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                state = json.load(f)
            logs = state.get("training_log", [])
            # Return most recent first
            return sorted(logs, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]
    except:
        pass
    return []


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Main status dashboard."""
    status = get_system_status()
    feedback = get_feedback_logs(20)

    # Build HTML
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>WXD Status</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="60">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
               background: #1a1a2e; color: #eee; margin: 0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ color: #00d4ff; margin-bottom: 5px; }}
        .timestamp {{ color: #888; font-size: 14px; margin-bottom: 20px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
        .card {{ background: #16213e; border-radius: 8px; padding: 20px; }}
        .card h2 {{ margin-top: 0; color: #00d4ff; font-size: 18px; }}
        .stat {{ font-size: 24px; font-weight: bold; color: #4ade80; }}
        .stat.warning {{ color: #fbbf24; }}
        .stat.error {{ color: #f87171; }}
        .label {{ color: #888; font-size: 12px; text-transform: uppercase; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #333; }}
        th {{ color: #888; font-size: 12px; text-transform: uppercase; }}
        .feedback-item {{ background: #1e3a5f; margin: 10px 0; padding: 15px; border-radius: 8px;
                         border-left: 4px solid #00d4ff; }}
        .feedback-item.super {{ border-left-color: #fbbf24; }}
        .feedback-item.correction {{ border-left-color: #f87171; }}
        .feedback-meta {{ color: #888; font-size: 12px; margin-bottom: 5px; }}
        .feedback-text {{ color: #fff; }}
        .feedback-context {{ color: #666; font-size: 13px; margin-top: 8px; font-style: italic; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
                 text-transform: uppercase; margin-left: 8px; }}
        .badge.super {{ background: #fbbf24; color: #000; }}
        .badge.correction {{ background: #f87171; color: #000; }}
        .badge.pending {{ background: #f87171; color: #fff; }}
        a {{ color: #00d4ff; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>WXD Status Dashboard</h1>
        <div class="timestamp">Last updated: {status['timestamp'][:19]} UTC (auto-refresh 60s)</div>

        <div class="grid">
            <div class="card">
                <h2>📨 Reply System</h2>
                <div class="stat">{status['replies'].get('active_sessions', 0)}</div>
                <div class="label">Active Sessions</div>
                <table>
                    <tr><td>Last Run</td><td>{status['replies'].get('last_run', 'Never')[:19]}</td></tr>
                    <tr><td>Processed</td><td>{status['replies'].get('processed_count', 0)}</td></tr>
                </table>
            </div>

            <div class="card">
                <h2>📝 Feedback Queue</h2>
                <div class="stat {'warning' if status['pending_actions'] > 0 else ''}">{status['pending_actions']}</div>
                <div class="label">Pending Review</div>
                <table>
                    <tr><td>Total Logged</td><td>{status['feedback_count']}</td></tr>
                </table>
            </div>

            <div class="card">
                <h2>📊 Trackers</h2>
                <table>
                    <tr><th>Tracker</th><th>Last Activity</th></tr>
"""

    for tracker, last_line in status.get("trackers", {}).items():
        html += f"<tr><td>{tracker.upper()}</td><td>{last_line[:50]}</td></tr>\n"

    html += """
                </table>
            </div>
        </div>

        <div class="card" style="margin-top: 20px;">
            <h2>📋 Recent Feedback & Observations</h2>
"""

    if feedback:
        for item in feedback:
            item_type = item.get("type", "unknown")
            badge_class = "super" if "super" in item_type else "correction" if "correction" in item_type else ""
            card_class = badge_class

            html += f"""
            <div class="feedback-item {card_class}">
                <div class="feedback-meta">
                    {item.get('timestamp', '')[:19]} — @{item.get('author', 'unknown')}
                    <span class="badge {badge_class}">{item_type.replace('_', ' ')}</span>
                </div>
                <div class="feedback-text">{item.get('message', '')}</div>
                <div class="feedback-context">Context: {item.get('context', '')[:150]}</div>
            </div>
"""
    else:
        html += "<p>No feedback logged yet.</p>"

    html += """
        </div>

        <div style="margin-top: 20px; color: #666; font-size: 12px;">
            <a href="/api/status">API: /api/status</a> |
            <a href="/api/feedback">API: /api/feedback</a>
        </div>
    </div>
</body>
</html>
"""
    return html


@app.get("/api/status")
async def api_status():
    """JSON status endpoint."""
    return get_system_status()


@app.get("/api/feedback")
async def api_feedback(limit: int = 100):
    """JSON feedback logs endpoint."""
    return get_feedback_logs(limit)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
