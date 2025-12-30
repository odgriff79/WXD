# WXD Migration Plan: AMD Micro → ARM A1.Flex

**Status**: Waiting for Oracle A1.Flex instance (PAYG upgrade initiated 2024-12-30)

## Background

- **Current VM**: Oracle AMD micro (1GB RAM, 2 CPU, ~47GB storage)
- **New VM**: Oracle ARM A1.Flex (24GB RAM, 4 OCPU, 145GB storage)
- **Strategy**: Keep Evo_mon on AMD micro, migrate WXD to A1.Flex
- **Total storage**: 192GB (under 200GB free tier limit)

---

## Pre-Migration Checklist

- [ ] A1.Flex instance acquired (grabber script running, check `grab_a1.log`)
- [ ] Note new VM IP address
- [ ] Generate/copy SSH key to new VM
- [ ] Update local `.vm_config` with new IP (for WXD remote commands)

---

## Phase 1: New VM Initial Setup

### 1.1 SSH Access
```bash
# From Windows - first connection
ssh -i "PATH_TO_KEY" ubuntu@NEW_VM_IP

# Add to known hosts, verify connection
```

### 1.2 System Updates
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3-pip python3-venv curl
```

### 1.3 Swap File (optional - may not need with 24GB RAM)
```bash
# Only if needed for memory-intensive operations
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## Phase 2: WXD Environment Setup

### 2.1 Clone Repository
```bash
cd ~
git clone https://github.com/odgriff79/WXD.git wxd
cd wxd
```

### 2.2 Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2.3 ECCODES (for ICON GRIB processing)
```bash
sudo apt install -y libeccodes-dev eccodes-bin
pip install eccodes cfgrib
```

### 2.4 Bluesky Credentials
```bash
# Create environment file
nano ~/.wxd_env

# Add:
export BSKY_HANDLE="wxd-london.bsky.social"
export BSKY_PASSWORD="your-app-password"

# Secure it
chmod 600 ~/.wxd_env
```

---

## Phase 3: Claude CLI Installation

### 3.1 Install Node.js
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version  # Should be v20.x
```

### 3.2 Install Claude CLI
```bash
sudo npm install -g @anthropic-ai/claude-code
claude --version
```

### 3.3 Authorize Claude CLI
```bash
# Option A: Browser auth (if GUI available)
claude auth login

# Option B: API key auth (headless)
claude auth login --api-key
# Paste your Anthropic API key when prompted
```

### 3.4 Verify Claude CLI
```bash
claude -p "Say hello"
# Should return a response without errors
```

**IMPORTANT**: Claude CLI auth is per-machine. Cannot copy from old VM.

---

## Phase 4: ntfy Listener Setup

### 4.1 Create Listener Script
```bash
# Copy listen_ntfy.sh from repo or create:
nano ~/wxd/listen_ntfy.sh

# Make executable
chmod +x ~/wxd/listen_ntfy.sh
```

### 4.2 Start Listener
```bash
nohup bash ~/wxd/listen_ntfy.sh >> ~/ntfy.log 2>&1 &
```

### 4.3 Test Remote Commands
```powershell
# From Windows
powershell -Command "Invoke-RestMethod -Method Post -Uri 'https://ntfy.sh/YOUR_CHANNEL' -Body 'preview'"
```

---

## Phase 5: Cron Setup

### 5.1 Copy Cron Schedule
```bash
crontab -e

# Add all WXD cron jobs (times in UTC):

# Tracker A - 4-model ensemble
30 8,20 * * * cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && python fetch.py && python post_bluesky.py >> ~/cron.log 2>&1

# ICON - German ensemble
0 4,10,16,22 * * * cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && bash trackers/icon/cron_icon.sh >> ~/cron.log 2>&1

# MOGREPS - UK ensemble
0 3,9,15,21 * * * cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && bash trackers/mogreps/cron_mogreps.sh >> ~/cron.log 2>&1

# UKMO - UK deterministic
0 7,19 * * * cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && bash trackers/ukmo/cron_ukmo.sh >> ~/cron.log 2>&1

# Daily Summary
30 9 * * * cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && python daily_summary.py >> ~/cron.log 2>&1

# Chart sync to GitHub Pages
15 10,22 * * * cd ~/wxd && bash sync_charts.sh >> ~/cron.log 2>&1

# Weekly changelog (Sunday 01:00)
0 1 * * 0 cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && python engagement/weekly_changelog.py >> ~/cron.log 2>&1

# Community request (Sunday 12:00)
0 12 * * 0 cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && python engagement/engagement_post.py --type community >> ~/cron.log 2>&1

# Educational posts (Tue/Fri 12:00)
0 12 * * 2,5 cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && python engagement/engagement_post.py --type educational >> ~/cron.log 2>&1
```

### 5.2 Verify Cron
```bash
crontab -l
```

---

## Phase 6: Testing (Dry Run)

### 6.1 Test Each Tracker
```bash
cd ~/wxd && source venv/bin/activate && source ~/.wxd_env

# Tracker A
python post_bluesky.py --dry-run

# ICON
python trackers/icon/post.py --dry-run

# UKMO
python trackers/ukmo/post.py --dry-run

# MOGREPS
python trackers/mogreps/post.py --dry-run

# Daily Summary
python daily_summary.py --dry-run
```

### 6.2 Test Data Fetching
```bash
# Tracker A
python fetch.py

# ICON (downloads ~110MB)
python trackers/icon/fetch.py

# UKMO
python trackers/ukmo/fetch.py

# MOGREPS
python trackers/mogreps/fetch.py
```

### 6.3 Test Claude CLI Integration
```bash
# Run a tracker that uses Claude commentary
python post_bluesky.py --dry-run
# Check that AI commentary appears, not fallback text
```

---

## Phase 7: Cutover

### 7.1 Disable Cron on Old VM
```bash
# SSH to OLD VM
ssh -i "PATH_TO_KEY" ubuntu@OLD_VM_IP
crontab -r  # Remove all cron jobs
# Or comment them out: crontab -e
```

### 7.2 Enable Cron on New VM
```bash
# Already set up in Phase 5
# Verify: crontab -l
```

### 7.3 Update Local Config
```bash
# Update C:\Users\o_gri\REPO\WXD\.vm_config with new IP
VM_IP=NEW_VM_IP
```

### 7.4 Test Remote Orchestration
```powershell
# From Windows - test SSH to new VM
ssh -i "PATH_TO_KEY" ubuntu@NEW_VM_IP "cd ~/wxd && source venv/bin/activate && source ~/.wxd_env && python post_bluesky.py --dry-run"
```

---

## Phase 8: Post-Migration Verification

### 8.1 Monitor First Scheduled Runs
```bash
# Watch cron log
tail -f ~/cron.log

# Check recent posts worked
ls -la ~/wxd/trackers/*/data/chart_latest.png
```

### 8.2 Verify All Trackers Posted
- [ ] Tracker A (08:30 or 20:30 UTC)
- [ ] ICON (04:00, 10:00, 16:00, or 22:00 UTC)
- [ ] MOGREPS (03:00, 09:00, 15:00, or 21:00 UTC)
- [ ] UKMO (07:00 or 19:00 UTC)
- [ ] Daily Summary (09:30 UTC)

### 8.3 Check Bluesky
- Visit https://bsky.app/profile/wxd-london.bsky.social
- Verify posts are appearing with AI commentary
- Check thread numbering is correct

---

## Rollback Plan

If migration fails:
1. Re-enable cron on old VM: `crontab -e` (uncomment jobs)
2. Revert `.vm_config` to old IP
3. Debug issues on new VM without affecting live posts

---

## Old VM (Keep Running)

The AMD micro will continue running Evo_mon:
- No changes needed
- Leave as backup/fallback
- Could repurpose later

---

## Notes

- **Claude CLI auth**: Must be done interactively on new VM
- **ECCODES**: Required for ICON GRIB processing - verify ARM compatibility
- **Storage**: 145GB boot volume, plenty of space for all data
- **Memory**: 24GB RAM eliminates need for aggressive swap usage
- **Budget alert**: £1/month set up - will notify if charges occur

---

## Timeline

1. **Now**: Grabber running, waiting for instance
2. **Instance acquired**: ~30 min setup (Phases 1-3)
3. **Testing**: ~30 min (Phases 4-6)
4. **Cutover**: ~10 min (Phase 7)
5. **Verification**: Monitor for 24 hours

Total active time: ~1-2 hours
