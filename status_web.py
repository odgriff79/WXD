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
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

app = FastAPI(title="WXD Status", description="Read-only status dashboard")

DATA_DIR = Path("/home/ubuntu/wxd/data")
STATE_FILE = DATA_DIR / "reply_listener_state.json"

# Cron jobs to track: (name, log_file, schedule_description, success_pattern, expected_times)
CRON_JOBS = [
    ("Daily Summary", "/home/ubuntu/wxd/cron_daily_summary.log", "09:30 UTC", r"Complete|Posted|Success", ["09:30"]),
    ("Main Fetch", "/home/ubuntu/wxd/cron.log", "08:30, 20:30 UTC", r"Complete|fetched|Success", ["08:30", "20:30"]),
    ("ICON Tracker", "/home/ubuntu/wxd/trackers/icon/cron.log", "04/10/16/22 UTC", r"Complete|===", ["04:00", "10:00", "16:00", "22:00"]),
    ("MOGREPS Tracker", "/home/ubuntu/wxd/trackers/mogreps/cron.log", "03/09/15/21 UTC", r"Complete|===", ["03:00", "09:00", "15:00", "21:00"]),
    ("UKMO Tracker", "/home/ubuntu/wxd/trackers/ukmo/cron.log", "07/19 UTC", r"Complete|===", ["07:00", "19:00"]),
    ("Reply Listener", "/home/ubuntu/wxd/cron_replies.log", "Every 15 min", r"Summary|processed", None),
    ("Chart Sync", "/home/ubuntu/wxd/cron_sync.log", "10:15, 22:15 UTC", r"Pushing|commit|No chart changes|nothing to commit", ["10:15", "22:15"]),
    ("Engagement", "/home/ubuntu/wxd/engagement/cron.log", "Tue/Fri 12:00 UTC", r"posted successfully|Thread posted", ["12:00"]),
]


def get_cron_job_status() -> list:
    """Get status of scheduled cron jobs based on log file modification time and content."""
    now = datetime.now(timezone.utc)
    jobs = []

    # Load tracker state for explicit success/failure tracking
    tracker_state = get_tracker_state()

    for name, log_file, schedule, success_pattern, expected_times in CRON_JOBS:
        job = {
            "name": name,
            "schedule": schedule,
            "status": "pending",
            "last_run": None,
            "message": ""
        }

        try:
            log_path = Path(log_file)
            if log_path.exists():
                mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
                hours_since_update = (now - mtime).total_seconds() / 3600
                job["last_run"] = mtime.strftime("%H:%M")

                with open(log_path) as f:
                    lines = f.readlines()

                last_line = lines[-1].strip() if lines else ""
                job["message"] = last_line[:60]

                # Check tracker_state for explicit success/failure (Main Fetch only)
                if name == "Main Fetch" and "tracker_a" in tracker_state:
                    ts = tracker_state["tracker_a"]
                    ts_status = ts.get("status")
                    # Check if state is recent (within 12 hours)
                    ts_time = ts.get("last_success") or ts.get("last_failure", "")
                    if ts_time:
                        try:
                            state_dt = datetime.fromisoformat(ts_time.replace("Z", "+00:00"))
                            state_hours = (now - state_dt).total_seconds() / 3600
                            if state_hours < 12:
                                if ts_status == "failed":
                                    job["status"] = "failed"
                                    job["message"] = ts.get("error", "Unknown error")[:60]
                                    jobs.append(job)
                                    continue
                                elif ts_status == "success":
                                    job["status"] = "complete"
                                    jobs.append(job)
                                    continue
                        except:
                            pass

                # Determine status based on file freshness and content
                if re.search(r"error|fail|fatal|exception|traceback", last_line, re.IGNORECASE):
                    job["status"] = "failed"
                elif re.search(success_pattern, last_line, re.IGNORECASE):
                    # Success pattern found - check if recent enough
                    if hours_since_update < 12:
                        job["status"] = "complete"
                    else:
                        job["status"] = "stale"
                elif hours_since_update < 1:
                    # Recently modified, might still be running
                    job["status"] = "complete"
                elif expected_times:
                    # Check if we're past expected run time
                    current_time = now.strftime("%H:%M")
                    past_runs = [t for t in expected_times if t < current_time]
                    if past_runs and hours_since_update > 2:
                        job["status"] = "pending"
                    else:
                        job["status"] = "complete"
                else:
                    job["status"] = "complete" if hours_since_update < 4 else "pending"
            else:
                job["status"] = "no_log"
                job["message"] = "Log file not found"
        except Exception as e:
            job["status"] = "error"
            job["message"] = str(e)[:60]

        jobs.append(job)

    return jobs


def get_model_run_status() -> dict:
    """Get status of model runs by parsing history files."""
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    result = {}

    # Main fetch models (GFS, ECMWF IFS, ECMWF AIFS, GEM) - runs 2x daily
    main_models = ["GFS", "ECMWF_IFS", "ECMWF_AIFS", "GEM"]
    for model in main_models:
        result[model] = {"08:30": "pending", "20:30": "pending"}

    # Check main cron.log for today's fetches
    try:
        main_log = Path("/home/ubuntu/wxd/cron.log")
        if main_log.exists():
            mtime = datetime.fromtimestamp(main_log.stat().st_mtime, tz=timezone.utc)
            if mtime.strftime("%Y-%m-%d") == today_str:
                run_time = "08:30" if mtime.hour < 15 else "20:30"
                with open(main_log) as f:
                    if "4/4 models fetched" in f.read():
                        for model in main_models:
                            result[model][run_time] = "complete"
    except:
        pass

    # Tracker models - parse history.json AND cron.log for today's runs
    trackers = {
        "ICON": {
            "history": "/home/ubuntu/wxd/trackers/icon/data/history.json",
            "run_key": "run_hour",
            "cron_log": "/home/ubuntu/wxd/trackers/icon/cron.log"
        },
        "MOGREPS": {
            "history": "/home/ubuntu/wxd/trackers/mogreps/data/history.json",
            "run_key": "run_hour",
            "cron_log": "/home/ubuntu/wxd/trackers/mogreps/cron.log"
        },
        "UKMO": {
            "history": "/home/ubuntu/wxd/trackers/ukmo/data/history.json",
            "run_key": "run_label",
            "cron_log": "/home/ubuntu/wxd/trackers/ukmo/cron.log"
        },
    }

    for model, info in trackers.items():
        result[model] = {"00z": "pending", "06z": "pending", "12z": "pending", "18z": "pending"}
        try:
            # First check history.json
            history_path = Path(info["history"])
            if history_path.exists():
                with open(history_path) as f:
                    history = json.load(f)

                for run in history.get("runs", [])[:10]:
                    fetched_at = run.get("fetched_at", "")
                    if today_str in fetched_at or (now - datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))).total_seconds() < 86400:
                        run_hour = run.get(info["run_key"], "")
                        if run_hour:
                            hour_str = run_hour.replace("z", "").zfill(2) + "z"
                            if hour_str in result[model]:
                                result[model][hour_str] = "complete"

            # Also check cron.log for today's runs (backup if history not updated)
            cron_path = Path(info["cron_log"])
            if cron_path.exists():
                mtime = datetime.fromtimestamp(cron_path.stat().st_mtime, tz=timezone.utc)
                if mtime.strftime("%Y-%m-%d") == today_str:
                    with open(cron_path) as f:
                        content = f.read()
                    # Look for "Data: fetched <today>..., 12z" pattern
                    # Get all matches and check which are from today
                    matches = re.findall(r"Data: fetched (\d{4}-\d{2}-\d{2}).*?, (\d{2})z", content)
                    for date_str, hour in matches:
                        if date_str == today_str:
                            hour_str = hour + "z"
                            if hour_str in result[model]:
                                result[model][hour_str] = "complete"
        except:
            pass

    return result


def get_system_status() -> dict:
    """Get current system status."""
    status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "replies": {},
        "trackers": {},
        "cron_jobs": [],
        "model_runs": {},
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

    # Cron job status
    status["cron_jobs"] = get_cron_job_status()

    # Model run status
    status["model_runs"] = get_model_run_status()

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
        .badge.complete {{ background: #4ade80; color: #000; }}
        .badge.failed {{ background: #f87171; color: #fff; }}
        .badge.running {{ background: #fbbf24; color: #000; }}
        a {{ color: #00d4ff; }}
        .status-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }}
        .status-dot.complete {{ background: #4ade80; }}
        .status-dot.pending {{ background: #888; }}
        .status-dot.failed {{ background: #f87171; }}
        .status-dot.running {{ background: #fbbf24; }}
        .status-dot.stale {{ background: #f97316; }}
        .badge.stale {{ background: #f97316; color: #fff; }}
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

        <div class="grid" style="margin-top: 20px;">
            <div class="card">
                <h2>⏰ Cron Jobs</h2>
                <table>
                    <tr><th>Job</th><th>Schedule</th><th>Status</th><th>Last</th></tr>
"""

    for job in status.get("cron_jobs", []):
        status_class = job.get("status", "pending")
        html += f"""
                    <tr>
                        <td><span class="status-dot {status_class}"></span>{job['name']}</td>
                        <td style="font-size:11px;">{job['schedule']}</td>
                        <td><span class="badge {status_class}">{status_class}</span></td>
                        <td>{job.get('last_run', '-')}</td>
                    </tr>
"""

    html += """
                </table>
            </div>

            <div class="card">
                <h2>🌐 Model Runs Today</h2>
                <p style="font-size:12px;color:#888;margin-bottom:10px;">Main fetch (08:30/20:30 UTC)</p>
                <table>
                    <tr><th>Model</th><th>08:30</th><th>20:30</th></tr>
"""

    # Main models (GFS, ECMWF_IFS, ECMWF_AIFS, GEM)
    main_models = ["GFS", "ECMWF_IFS", "ECMWF_AIFS", "GEM"]
    for model_name in main_models:
        runs = status.get("model_runs", {}).get(model_name, {})
        html += f"<tr><td>{model_name.replace('_', ' ')}</td>"
        for run_time in ["08:30", "20:30"]:
            status_class = runs.get(run_time, "pending")
            symbol = "✓" if status_class == "complete" else "○"
            color = "#4ade80" if status_class == "complete" else "#888"
            html += f'<td style="text-align:center;color:{color};font-weight:bold;">{symbol}</td>'
        html += "</tr>\n"

    html += """
                </table>
                <p style="font-size:12px;color:#888;margin:15px 0 10px 0;">Independent trackers (model run times)</p>
                <table>
                    <tr><th>Tracker</th><th>00z</th><th>06z</th><th>12z</th><th>18z</th></tr>
"""

    # Tracker models (ICON, MOGREPS, UKMO)
    tracker_models = ["ICON", "MOGREPS", "UKMO"]
    for model_name in tracker_models:
        runs = status.get("model_runs", {}).get(model_name, {})
        html += f"<tr><td>{model_name}</td>"
        for run_time in ["00z", "06z", "12z", "18z"]:
            status_class = runs.get(run_time, "pending")
            symbol = "✓" if status_class == "complete" else "○"
            color = "#4ade80" if status_class == "complete" else "#888"
            html += f'<td style="text-align:center;color:{color};font-weight:bold;">{symbol}</td>'
        html += "</tr>\n"

    html += """
                </table>
                <div style="margin-top:10px;font-size:11px;color:#888;">✓ = fetched today, ○ = pending/not yet</div>
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


# Import Met Office fetcher
import sys
sys.path.insert(0, '/home/ubuntu/wxd')
try:
    from daily_summary import fetch_metoffice_narrative
    HAS_METOFFICE = True
except ImportError:
    HAS_METOFFICE = False


def get_metoffice_summary() -> dict:
    """Fetch current Met Office summary for dashboard."""
    if not HAS_METOFFICE:
        return {"error": "Met Office fetcher not available"}
    
    try:
        data = fetch_metoffice_narrative()
        return {
            "uk_warnings": data.get("uk_warnings", "No warnings data"),
            "long_range_warning": data.get("long_range_warning", ""),
            "today_tomorrow": data.get("today_tomorrow", "")[:200] if data.get("today_tomorrow") else "",
            "fetched": True
        }
    except Exception as e:
        return {"error": str(e), "fetched": False}


def get_tracker_state() -> dict:
    """Read tracker state from state file."""
    state_file = Path('/home/ubuntu/wxd/data/tracker_state.json')
    if not state_file.exists():
        return {}
    try:
        with open(state_file) as f:
            return json.load(f)
    except:
        return {}
