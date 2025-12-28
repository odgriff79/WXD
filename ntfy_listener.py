#!/usr/bin/env python3
"""ntfy listener for WXD preview commands.

Subscribe to wxd-cmd topic:
- 'preview': Run analysis on current/stale data (quick)
- 'fresh': Fetch new data first, then run analysis (isolated, no contamination)

Results sent to wxd-alerts topic.
"""
import subprocess
import requests
import time
import os
import sys

os.chdir('/home/ubuntu/wxd')
sys.stdout.reconfigure(line_buffering=True)

print('WXD ntfy listener started')
print('Commands: "preview" (quick) or "fresh" (fetch new data)')
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

                        if output:
                            # Clean up output for ntfy
                            if 'PREVIEW' in output or 'DRY RUN' in output or 'FRESH' in output:
                                # Find the header
                                for marker in ['FRESH PREVIEW', 'FRESH FETCH', 'DRY RUN', 'PREVIEW']:
                                    if marker in output:
                                        output = output[output.index(marker) - 4:]
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
