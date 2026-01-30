#!/usr/bin/env python3
"""ntfy listener for WXD preview commands.

Subscribe to wxd-cmd topic:

Tracker A (main 4-model ensemble):
- 'preview': Run analysis on current/stale data (quick)
- 'fresh': Fetch new data first, then run analysis (isolated)

Tracker B (ICON):
- 'icon': Run ICON analysis on current data (quick)
- 'icon-fresh': Fetch new ICON data first, then analyze (isolated)

Tracker D (UKMO):
- 'ukmo': Run UKMO analysis on current data (quick)
- 'ukmo-fresh': Fetch new UKMO data first, then analyze (isolated)

Tracker C (MOGREPS):
- 'mogreps': Run MOGREPS analysis on current data (quick)
- 'mogreps-fresh': Fetch new MOGREPS data first, then analyze (isolated)

Daily Summary:
- 'summary': Preview daily Met Office summary thread (dry-run)

Engagement:
- 'engagement': Preview engagement post (dry-run)

Reply System:
- 'check': Check for new replies NOW (force run, dry-run)
- 'respond': Check AND respond to new replies NOW (force run, live)

Utilities:
- 'status': Quick system status (replies, trackers, uptime)
- 'oracle': Check Oracle A1 grabber status

Results sent to wxd-alerts topic.
"""
import subprocess
import requests
import time
import os
import sys

os.chdir('/home/ubuntu/wxd')
sys.stdout.reconfigure(line_buffering=True)

# Load Bluesky credentials from ~/.wxd_env
wxd_env_path = os.path.expanduser('~/.wxd_env')
if os.path.exists(wxd_env_path):
    with open(wxd_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                # Handle export VAR=value or VAR=value
                if line.startswith('export '):
                    line = line[7:]
                key, _, value = line.partition('=')
                # Remove quotes if present
                value = value.strip('"').strip("'")
                os.environ[key] = value
    print('Loaded credentials from ~/.wxd_env')

print('WXD ntfy listener started')
print('Commands:')
print('  Tracker A: "preview" (quick) or "fresh" (fetch new)')
print('  Tracker B: "icon" (quick) or "icon-fresh" (fetch new)')
print('  Tracker C: "mogreps" (quick) or "mogreps-fresh" (fetch new)')
print('  Tracker D: "ukmo" (quick) or "ukmo-fresh" (fetch new)')
print('  Daily: "summary" (Met Office summary preview)')
print('  Engagement: "engagement" (preview)')
print('  Cross: "cross" (cross-tracker preview) or "cross-post" (live post)')
print('  Replies: "check" (dry-run) or "respond" (live)')
print('  Status: "status" (quick system overview)')
print('  Clear: "clear-feedback" (clear dashboard feedback queue)')
print('Send to: https://ntfy.sh/wxd-cmd')

# Use ntfy JSON stream API
url = 'https://ntfy.sh/wxd-cmd/json'

def run_command(cmd, timeout=300):
    """Run command and return output."""
    env = os.environ.copy()
    env['PATH'] = '/home/ubuntu/wxd/venv/bin:' + env.get('PATH', '')

    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=timeout, env=env, cwd='/home/ubuntu/wxd'
    )
    return result.stdout + result.stderr

def handle_preview():
    """Quick preview using existing data."""
    print(f'Preview requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'post_bluesky.py', '--dry-run'])
    return output

def handle_fresh():
    """Fetch fresh data (isolated) then preview."""
    print(f'Fresh preview requested at {time.strftime("%H:%M:%S")}')

    # Step 1: Fetch fresh data in preview mode (isolated)
    print('  Fetching fresh data...')
    fetch_output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'fetch.py', '--preview'])

    # Step 2: Run analysis on preview data
    print('  Running analysis...')
    analysis_output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'post_bluesky.py', '--preview'])

    return f"=== FRESH FETCH ===\n{fetch_output}\n\n=== ANALYSIS ===\n{analysis_output}"


def handle_icon():
    """Quick ICON preview using existing data."""
    print(f'ICON preview requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'trackers/icon/post.py', '--dry-run'])
    return output


def handle_icon_fresh():
    """Fetch fresh ICON data (isolated) then preview.
    Note: ICON fetch downloads ~110MB of GRIB data, takes longer.
    """
    print(f'Fresh ICON preview requested at {time.strftime("%H:%M:%S")}')

    # Step 1: Fetch fresh ICON data in preview mode (isolated)
    # Longer timeout due to GRIB downloads (~110MB)
    print('  Fetching fresh ICON data (this may take a few minutes)...')
    fetch_output = run_command(
        ['/home/ubuntu/wxd/venv/bin/python', 'trackers/icon/fetch.py', '--preview'],
        timeout=600  # 10 min timeout for GRIB downloads
    )

    # Step 2: Run ICON analysis on preview data
    print('  Running ICON analysis...')
    analysis_output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'trackers/icon/post.py', '--preview'])

    return f"=== ICON FRESH FETCH ===\n{fetch_output}\n\n=== ICON ANALYSIS ===\n{analysis_output}"


def handle_ukmo():
    """Quick UKMO preview using existing data."""
    print(f'UKMO preview requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'trackers/ukmo/post.py', '--dry-run'])
    return output


def handle_ukmo_fresh():
    """Fetch fresh UKMO data (isolated) then preview."""
    print(f'Fresh UKMO preview requested at {time.strftime("%H:%M:%S")}')

    # Step 1: Fetch fresh UKMO data in preview mode (isolated)
    print('  Fetching fresh UKMO data...')
    fetch_output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'trackers/ukmo/fetch.py', '--preview'])

    # Step 2: Run UKMO analysis on preview data
    print('  Running UKMO analysis...')
    analysis_output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'trackers/ukmo/post.py', '--preview'])

    return f"=== UKMO FRESH FETCH ===\n{fetch_output}\n\n=== UKMO ANALYSIS ===\n{analysis_output}"


def handle_mogreps():
    """Quick MOGREPS preview using existing data."""
    print(f'MOGREPS preview requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'trackers/mogreps/post.py', '--dry-run'])
    return output


def handle_mogreps_fresh():
    """Fetch fresh MOGREPS data (isolated) then preview.
    Note: MOGREPS fetch downloads from AWS S3, may take a few minutes.
    """
    print(f'Fresh MOGREPS preview requested at {time.strftime("%H:%M:%S")}')

    # Step 1: Fetch fresh MOGREPS data in preview mode (isolated)
    print('  Fetching fresh MOGREPS data (AWS S3)...')
    fetch_output = run_command(
        ['/home/ubuntu/wxd/venv/bin/python', 'trackers/mogreps/fetch.py', '--preview'],
        timeout=600  # 10 min timeout for S3 downloads
    )

    # Step 2: Run MOGREPS analysis on preview data
    print('  Running MOGREPS analysis...')
    analysis_output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'trackers/mogreps/post.py', '--preview'])

    return f"=== MOGREPS FRESH FETCH ===\n{fetch_output}\n\n=== MOGREPS ANALYSIS ===\n{analysis_output}"


def handle_summary():
    """Preview daily Met Office summary thread."""
    print(f'Daily summary preview requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'daily_summary.py', '--dry-run'])
    return output


def handle_engagement():
    """Preview engagement post."""
    print(f'Engagement preview requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'engagement/engagement_post.py', '--dry-run'])
    return output


def handle_oracle():
    """Check Oracle A1 grabber status."""
    import subprocess
    print(f'Oracle grabber status at {time.strftime("%H:%M:%S")}')
    ps_result = subprocess.run(['pgrep', '-f', 'grab_a1_instance'], capture_output=True, text=True)
    running = bool(ps_result.stdout.strip())
    try:
        with open('/home/ubuntu/grab_a1.log', 'r') as f:
            lines = f.readlines()
            last_lines = ''.join(lines[-10:])
    except:
        last_lines = 'No log found'
    status = 'RUNNING' if running else 'STOPPED'
    return f'ORACLE GRABBER: {status}\n\n{last_lines}'


def handle_check():
    """Check for new replies (dry-run, no responses sent)."""
    print(f'Reply check requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'reply_listener.py', '--force'])
    return output


def handle_respond():
    """Check AND respond to new replies (live mode)."""
    print(f'Reply respond requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'reply_listener.py', '--force', '--post'])
    return output


def handle_clear_feedback():
    """Clear the feedback queue."""
    print(f'Clear feedback requested at {time.strftime("%H:%M:%S")}')
    result = subprocess.run(
        ['python3', 'reply_listener.py', '--clear-feedback'],
        cwd='/home/ubuntu/wxd',
        capture_output=True,
        text=True
    )
    return result.stdout or result.stderr or 'Feedback queue cleared'

def handle_synthesis():
    """Cross-tracker synthesis - compare all models."""
    print(f'Cross-tracker synthesis requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'cross_tracker_synthesis.py'])
    return output


def handle_synthesis_post():
    """Cross-tracker synthesis - compare all models and POST."""
    print(f'Cross-tracker synthesis POST requested at {time.strftime("%H:%M:%S")}')
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'cross_tracker_synthesis.py', '--post'])
    return output


def handle_ssw():
    """SSW Monitor - check stratospheric warming status."""
    print(f'SSW status requested at {time.strftime("%H:%M:%S")}')
    import json
    from datetime import datetime, timezone

    # Run monitor and return status
    output = run_command(['/home/ubuntu/wxd/venv/bin/python', 'ssw_monitor.py', '--json'])

    # Read the status file
    try:
        with open('/home/ubuntu/wxd/ssw/ssw_status.json') as f:
            status = json.load(f)

        # Check if fetch failed - fall back to history
        if status.get('status') == 'error':
            try:
                with open('/home/ubuntu/wxd/ssw/history.json') as f:
                    history = json.load(f)
                if history.get('runs'):
                    last = history['runs'][-1]
                    prob = last.get('probability', 'N/A')
                    level = last.get('level', 'Unknown')
                    u10 = last.get('current_u10', 'N/A')
                    ts = last.get('timestamp', 'Unknown')
                    # Calculate age
                    try:
                        ts_dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        age_hrs = (datetime.now(timezone.utc) - ts_dt).total_seconds() / 3600
                        age_str = f" (data {age_hrs:.0f}h old)"
                    except:
                        age_str = ""
                    summary = f"SSW STATUS (CACHED){age_str}\n{'='*30}\nProbability: {prob}%\nAlert: {level}\nCurrent U10 @60N: {u10} m/s\n\nNote: Live fetch failed, using last good data"
                    return summary
            except Exception as e:
                pass  # Fall through to error
            return f"SSW STATUS: Fetch failed, no cached data\nError: {status.get('error', 'Unknown')}"

        # Normal case - fresh data
        prob = status.get('ssw_probability_pct', 'N/A')
        level = status.get('alert', {}).get('level', 'Unknown')
        u10 = status.get('current_u10_60n_ms', 'N/A')
        model_run = status.get('model_run', 'Unknown')

        # Calculate timing info
        # GEFS runs: 00z, 06z, 12z, 18z with ~7h processing latency
        from datetime import timedelta
        timing_str = ""
        next_avail_str = ""
        try:
            if '/' in model_run:
                date_part, cycle = model_run.split('/')
                cycle_hour = int(cycle.replace('z', ''))
                run_dt = datetime.strptime(f'{date_part}{cycle_hour:02d}', '%Y%m%d%H').replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)

                # When this data became available (~7h after init)
                data_avail = run_dt + timedelta(hours=7)
                avail_ago = (now - data_avail).total_seconds() / 60  # minutes
                if avail_ago >= 0:
                    if avail_ago < 60:
                        timing_str = f"fresh {int(avail_ago)}min ago"
                    else:
                        timing_str = f"avail {avail_ago/60:.1f}h ago"
                else:
                    timing_str = "still processing"

                # Find next cycle after current one
                cycles = [0, 6, 12, 18]
                current_idx = cycles.index(cycle_hour)
                next_cycle = cycles[(current_idx + 1) % 4]

                # Next run datetime
                if next_cycle > cycle_hour:
                    next_run = run_dt.replace(hour=next_cycle)
                else:
                    next_run = run_dt.replace(hour=next_cycle) + timedelta(days=1)

                # Available ~7h after run init
                next_avail = next_run + timedelta(hours=7)
                hrs_until = (next_avail - now).total_seconds() / 3600

                if hrs_until > 0:
                    next_avail_str = f"Next: {next_cycle:02d}z @ ~{next_avail.strftime('%H:%M')} UTC ({hrs_until:.1f}h)"
                else:
                    next_avail_str = f"Next: {next_cycle:02d}z ready NOW"
        except:
            pass

        lines = [
            "SSW STATUS",
            "=" * 30,
            f"Probability: {prob}%",
            f"Alert: {level}",
            f"Current U10 @60N: {u10} m/s",
            f"Run: {model_run} ({timing_str})" if timing_str else f"Run: {model_run}",
        ]
        if next_avail_str:
            lines.append(next_avail_str)
        return "\n".join(lines)
    except Exception as e:
        return output or f"SSW check error: {e}"


def handle_status():
    """Quick system status summary."""
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    print(f'Status requested at {time.strftime("%H:%M:%S")}')

    lines = []
    lines.append(f"WXD STATUS - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 40)

    # Check reply listener state
    try:
        state_path = Path('/home/ubuntu/wxd/data/reply_listener_state.json')
        if state_path.exists():
            with open(state_path) as f:
                state = json.load(f)
            last_run = state.get('last_run', 'Never')[:19] if state.get('last_run') else 'Never'
            sessions = len(state.get('active_sessions', {}))
            processed = len(state.get('processed_replies', []))
            lines.append(f"\n📨 REPLIES")
            lines.append(f"  Last run: {last_run}")
            lines.append(f"  Active sessions: {sessions}")
            lines.append(f"  Processed: {processed}")
    except Exception as e:
        lines.append(f"\n📨 REPLIES: Error - {e}")

    # Check recent cron logs
    cron_files = [
        ('/home/ubuntu/wxd/cron.log', 'Tracker A'),
        ('/home/ubuntu/wxd/trackers/icon/cron.log', 'ICON'),
        ('/home/ubuntu/wxd/trackers/mogreps/cron.log', 'MOGREPS'),
        ('/home/ubuntu/wxd/trackers/ukmo/cron.log', 'UKMO'),
    ]

    lines.append(f"\n📊 TRACKERS (last line)")
    for log_path, name in cron_files:
        try:
            with open(log_path) as f:
                last_line = f.readlines()[-1].strip()[:50] if f.readlines() else 'Empty'
            # Re-read to get actual last line
            with open(log_path) as f:
                all_lines = f.readlines()
                last_line = all_lines[-1].strip()[:60] if all_lines else 'Empty'
            lines.append(f"  {name}: {last_line}")
        except Exception as e:
            lines.append(f"  {name}: No log")

    # ntfy listener status
    try:
        import subprocess
        ps = subprocess.run(['pgrep', '-f', 'ntfy_listener'], capture_output=True, text=True)
        ntfy_running = 'RUNNING' if ps.stdout.strip() else 'STOPPED'
    except:
        ntfy_running = 'Unknown'

    lines.append(f"\n🔔 SERVICES")
    lines.append(f"  ntfy listener: {ntfy_running}")

    # Uptime
    try:
        with open('/proc/uptime') as f:
            uptime_secs = float(f.read().split()[0])
        days = int(uptime_secs // 86400)
        hours = int((uptime_secs % 86400) // 3600)
        lines.append(f"  VM uptime: {days}d {hours}h")
    except:
        pass

    return '\n'.join(lines)


while True:
    try:
        # Stream messages with timeout
        with requests.get(url, stream=True, timeout=60) as r:
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                import json
                try:
                    msg = json.loads(line)
                    if msg.get('event') == 'message':
                        cmd = msg.get('message', '').strip().lower()

                        output = None
                        if cmd == 'preview':
                            output = handle_preview()
                        elif cmd == 'fresh':
                            output = handle_fresh()
                        elif cmd == 'icon':
                            output = handle_icon()
                        elif cmd == 'icon-fresh':
                            output = handle_icon_fresh()
                        elif cmd == 'ukmo':
                            output = handle_ukmo()
                        elif cmd == 'ukmo-fresh':
                            output = handle_ukmo_fresh()
                        elif cmd == 'mogreps':
                            output = handle_mogreps()
                        elif cmd == 'mogreps-fresh':
                            output = handle_mogreps_fresh()
                        elif cmd == 'summary':
                            output = handle_summary()
                        elif cmd == 'engagement':
                            output = handle_engagement()
                        elif cmd == 'oracle':
                            output = handle_oracle()
                        elif cmd == 'check':
                            output = handle_check()
                        elif cmd == 'respond':
                            output = handle_respond()
                        elif cmd == 'status':
                            output = handle_status()
                        elif cmd == 'clear-feedback':
                            output = handle_clear_feedback()
                        elif cmd == 'cross':
                            output = handle_synthesis()
                        elif cmd == 'cross-post':
                            output = handle_synthesis_post()
                        elif cmd == 'ssw':
                            output = handle_ssw()

                        if output:
                            # Clean up output for ntfy
                            if 'PREVIEW' in output or 'DRY RUN' in output or 'FRESH' in output or 'ICON' in output or 'UKMO' in output or 'MOGREPS' in output:
                                # Find the header - check model-specific markers first
                                for marker in ['MOGREPS FRESH FETCH', 'MOGREPS ANALYSIS', 'MOGREPS-G',
                                              'UKMO FRESH FETCH', 'UKMO ANALYSIS', 'UKMO Fetch',
                                              'ICON FRESH FETCH', 'ICON ANALYSIS', 'ICON-EU-EPS',
                                              'FRESH PREVIEW', 'FRESH FETCH', 'DRY RUN', 'PREVIEW']:
                                    if marker in output:
                                        idx = output.index(marker)
                                        # Go back a bit for context but not too far
                                        start = max(0, idx - 10)
                                        output = output[start:]
                                        break
                            output = output[:3500]  # ntfy limit

                            requests.post('https://ntfy.sh/wxd-alerts', data=output.encode('utf-8'))
                            print(f'Response sent to wxd-alerts')
                except json.JSONDecodeError:
                    pass
    except requests.exceptions.Timeout:
        print('Reconnecting...')
    except Exception as e:
        print(f'Error: {e}')
        time.sleep(5)
