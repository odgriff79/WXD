#!/usr/bin/env python3
"""ntfy listener for WXD preview commands.

Subscribe to wxd-cmd topic. When 'preview' received, run dry-run and send to wxd-alerts.
"""
import subprocess
import requests
import time
import os
import sys

os.chdir('/home/ubuntu/wxd')
sys.stdout.reconfigure(line_buffering=True)

print('WXD ntfy listener started')
print('Send "preview" to https://ntfy.sh/wxd-cmd')

# Use ntfy JSON stream API
url = 'https://ntfy.sh/wxd-cmd/json'

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
                    if msg.get('event') == 'message' and msg.get('message', '').strip().lower() == 'preview':
                        print(f'Preview requested at {time.strftime("%H:%M:%S")}')
                        
                        # Run dry-run
                        env = os.environ.copy()
                        env['PATH'] = '/home/ubuntu/wxd/venv/bin:' + env.get('PATH', '')
                        
                        result = subprocess.run(
                            ['/home/ubuntu/wxd/venv/bin/python', 'post_bluesky.py', '--dry-run'],
                            capture_output=True, text=True, timeout=300, env=env, cwd='/home/ubuntu/wxd'
                        )
                        
                        output = result.stdout
                        if 'PREVIEW' in output:
                            output = output[output.index('PREVIEW'):]
                        output = output[:3500]  # ntfy limit
                        
                        requests.post('https://ntfy.sh/wxd-alerts', data=output.encode('utf-8'))
                        print('Preview sent to wxd-alerts')
                except json.JSONDecodeError:
                    pass
    except requests.exceptions.Timeout:
        print('Reconnecting...')
    except Exception as e:
        print(f'Error: {e}')
        time.sleep(5)
