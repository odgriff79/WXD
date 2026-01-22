#!/usr/bin/env python3
"""
SSW Monitor for WXD - GEFS Ensemble-Based (Hardened)
Computes true SSW probability from GEFS 31-member ensemble

Based on standard major SSW criterion:
  Zonal-mean zonal wind at 10 hPa, 60°N reverses to easterly (U10 < 0)

Run with --debug on first use to verify NOMADS variable/coord names.
Run with --post to post to Bluesky when thresholds met.
Run with --dry-run to test posting logic without actually posting.
"""
import xarray as xr
import numpy as np
import json
import argparse
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import sys

# Matplotlib (optional - for chart generation)
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# Add parent for lib imports
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === CONFIG ===
OUTPUT_DIR = Path('/home/ubuntu/wxd/ssw')
CACHE_DIR = OUTPUT_DIR / 'cache'

# SSW detection thresholds (m/s)
THRESHOLDS = {
    'ssw_trigger': 0,      # Easterly = major SSW (standard definition)
    'vulnerable': 10,      # Vortex weakening
}

# Alert probability thresholds (% of ensemble members)
PROB_THRESHOLDS = {
    'watch': 10,           # >= 10% members
    'alert': 25,           # >= 25% members
    'strong': 50,          # >= 50% members
}

# Forecast window for SSW detection (days)
LEAD_WINDOW = (5, 16)

# History and state files
HISTORY_FILE = OUTPUT_DIR / 'history.json'
STATE_FILE = OUTPUT_DIR / 'state.json'

# Posting configuration
POST_COOLDOWN_HOURS = 24
HISTORY_DAYS_NORMAL = 30   # Keep 30 days for AI context/engagement
HISTORY_DAYS_ELEVATED = 30  # Same during active signal

# === DYNAMIC DIMENSION DETECTION ===
# GEFS uses various naming conventions; detect dynamically
ENS_CANDIDATES = ("ens", "member", "ens_member", "ensmem", "ensemble")
TIME_CANDIDATES = ("time", "valid_time", "forecast_time")
LAT_CANDIDATES = ("lat", "latitude")
LON_CANDIDATES = ("lon", "longitude")
LEV_CANDIDATES = ("lev", "isobaric", "isobaricInhPa", "level", "plev")

# Variable name candidates for U-wind on pressure levels
UGRD_CANDIDATES = ("ugrdprs", "ugrd", "u", "uwnd")


def pick_dim(da, candidates, context=""):
    """Find first matching dimension name from candidates."""
    for c in candidates:
        if c in da.dims:
            return c
    raise ValueError(f"[{context}] None of {candidates} found in dims={list(da.dims)}")


def pick_coord(ds, candidates, context=""):
    """Find first matching coordinate name from candidates."""
    for c in candidates:
        if c in ds.coords:
            return c
    raise ValueError(f"[{context}] None of {candidates} found in coords={list(ds.coords)}")


def pick_var(ds, candidates, context=""):
    """Find first matching variable name from candidates."""
    for c in candidates:
        if c in ds.data_vars:
            return c
    raise ValueError(f"[{context}] None of {candidates} found in vars={list(ds.data_vars)}")


def get_gefs_cycle_url(run_date: datetime, cycle: str = '00') -> str:
    """
    Construct GEFS OPeNDAP URL for given date/cycle.
    
    GEFS via NOMADS OPeNDAP is at:
      https://nomads.ncep.noaa.gov/dods/gefs/gefs{YYYYMMDD}/gefs_pgrb2ap5_{CC}z
    
    Verify by checking: https://nomads.ncep.noaa.gov/dods/gefs/
    """
    date_str = run_date.strftime('%Y%m%d')
    # pgrb2ap5 = pressure gribs, 0.5 degree, all members
    # Alternatives that may exist: gefs_pgrb2sp25 (0.25deg), etc.
    return f"https://nomads.ncep.noaa.gov/dods/gefs/gefs{date_str}/gefs_pgrb2ap5_all_{cycle}z"


def debug_dataset_structure(url: str):
    """
    One-time debug: print dataset structure to verify variable/coord names.
    Run this on the Oracle VM first to confirm naming conventions.
    """
    print(f"\n{'='*60}")
    print(f"DEBUG: Inspecting GEFS dataset structure")
    print(f"URL: {url}")
    print(f"{'='*60}\n")
    
    try:
        ds = xr.open_dataset(url)
        
        print("COORDINATES:")
        for name, coord in ds.coords.items():
            print(f"  {name}: shape={coord.shape}, dtype={coord.dtype}")
            if len(coord) <= 10:
                print(f"      values: {coord.values}")
            else:
                print(f"      first 5: {coord.values[:5]}")
                print(f"      last 5:  {coord.values[-5:]}")
        
        print("\nDIMENSIONS:")
        for dim, size in ds.dims.items():
            print(f"  {dim}: {size}")
        
        print("\nDATA VARIABLES:")
        for name, var in ds.data_vars.items():
            print(f"  {name}: dims={var.dims}, shape={var.shape}")
        
        print("\n" + "="*60)
        print("DETECTION TEST:")
        try:
            lev_coord = pick_coord(ds, LEV_CANDIDATES, "level")
            print(f"  Level coord: '{lev_coord}' -> values: {ds[lev_coord].values[:10]}...")
        except ValueError as e:
            print(f"  Level coord: FAILED - {e}")
        
        try:
            ugrd_var = pick_var(ds, UGRD_CANDIDATES, "U-wind")
            print(f"  U-wind var: '{ugrd_var}' -> dims: {ds[ugrd_var].dims}")
        except ValueError as e:
            print(f"  U-wind var: FAILED - {e}")
        
        ds.close()
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def fetch_gefs_u10_ensemble(run_date: datetime = None, cycle: str = '00') -> dict:
    """
    Fetch 10hPa zonal wind from GEFS ensemble via OPeNDAP.
    Returns zonal-mean U-wind at 60°N for all ensemble members.
    
    Uses dynamic dimension detection to handle NOMADS naming variations.
    """
    if run_date is None:
        run_date = datetime.now(timezone.utc)
    
    url = get_gefs_cycle_url(run_date, cycle)
    logger.info(f"Fetching GEFS from: {url}")
    
    try:
        ds = xr.open_dataset(url)
        
        # === DYNAMIC DETECTION ===
        lev_coord = pick_coord(ds, LEV_CANDIDATES, "level")
        lat_coord = pick_coord(ds, LAT_CANDIDATES, "latitude")
        lon_coord = pick_coord(ds, LON_CANDIDATES, "longitude")
        ugrd_var = pick_var(ds, UGRD_CANDIDATES, "U-wind")
        
        logger.info(f"Detected: lev={lev_coord}, lat={lat_coord}, lon={lon_coord}, var={ugrd_var}")
        
        # === SELECT 10 hPa LEVEL ===
        # GEFS typically uses hPa (millibars), but check units
        lev_values = ds[lev_coord].values
        
        # Find closest level to 10 hPa
        target_level = 10
        if lev_values.max() > 1100:
            # Stored in Pa, convert target
            target_level = 1000  # 10 hPa = 1000 Pa
        
        u_wind = ds[ugrd_var]
        
        # Select level FIRST (with nearest), then lat band
        u_wind = u_wind.sel(**{lev_coord: target_level}, method='nearest')
        
        # === SELECT 60°N LATITUDE BAND ===
        # Check latitude direction (N→S vs S→N)
        lat_vals = ds[lat_coord].values
        lat_ascending = lat_vals[0] < lat_vals[-1]
        
        # 58-62°N band for 60°N zonal mean
        if lat_ascending:
            lat_slice = slice(58, 62)
        else:
            lat_slice = slice(62, 58)
        
        # Apply lat slice SEPARATELY
        u_wind = u_wind.sel(**{lat_coord: lat_slice})
        
        # === ZONAL MEAN ===
        # Average over longitude and latitude band
        zonal_mean = u_wind.mean(dim=[lon_coord, lat_coord])
        
        # === DETECT ENSEMBLE AND TIME DIMS ===
        ens_dim = pick_dim(zonal_mean, ENS_CANDIDATES, "ensemble")
        time_dim = pick_dim(zonal_mean, TIME_CANDIDATES, "time")
        
        logger.info(f"Zonal mean dims: {zonal_mean.dims}, ens={ens_dim}, time={time_dim}")
        
        n_members = zonal_mean.sizes[ens_dim]
        
        ds.close()
        
        return {
            'success': True,
            'data': zonal_mean,
            'ens_dim': ens_dim,
            'time_dim': time_dim,
            'run_date': run_date.isoformat(),
            'cycle': cycle,
            'n_members': n_members,
            'url': url,
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch GEFS: {e}")
        return {'success': False, 'error': str(e), 'run_date': run_date.isoformat()}


def compute_ssw_probability(zonal_mean_data: xr.DataArray,
                            ens_dim: str,
                            time_dim: str,
                            lead_window_days: tuple = LEAD_WINDOW) -> dict:
    """
    Compute SSW probability from ensemble U10 data.
    
    SSW probability = % of members where min(U10) < 0 over forecast window
    
    Uses timestamp-based window detection (not step count) for robustness.
    """
    # === COMPUTE TIME WINDOW FROM ACTUAL TIMESTAMPS ===
    times = zonal_mean_data[time_dim].values
    t0 = times[0]
    
    # Convert to days from forecast start
    dt_days = (times - t0) / np.timedelta64(1, 'D')
    
    # Boolean mask for lead window
    mask = (dt_days >= lead_window_days[0]) & (dt_days <= lead_window_days[1])
    valid_indices = np.where(mask)[0]
    
    if len(valid_indices) == 0:
        logger.warning(f"No timesteps in window day {lead_window_days[0]}-{lead_window_days[1]}")
        # Fallback: use all available
        valid_indices = np.arange(len(times))
    
    # Subset to forecast window
    window_data = zonal_mean_data.isel(**{time_dim: valid_indices})
    
    # === COMPUTE STATISTICS ===
    # For each member: find minimum U10 in window
    min_u10_per_member = window_data.min(dim=time_dim)
    
    n_members = zonal_mean_data.sizes[ens_dim]
    
    # Count members with reversal (U10 < 0 = major SSW criterion)
    n_reversals = int((min_u10_per_member < THRESHOLDS['ssw_trigger']).sum().values)
    n_vulnerable = int((min_u10_per_member < THRESHOLDS['vulnerable']).sum().values)
    
    ssw_prob = (n_reversals / n_members) * 100
    vulnerable_prob = (n_vulnerable / n_members) * 100
    
    # Ensemble mean and spread
    ens_mean = float(window_data.mean().values)
    ens_min = float(min_u10_per_member.min().values)
    ens_max = float(min_u10_per_member.max().values)
    
    # Current analysis (first timestep, ensemble mean)
    current_u10 = float(zonal_mean_data.isel(**{time_dim: 0}).mean(dim=ens_dim).values)
    
    # Actual window range used
    actual_days = (dt_days[valid_indices[0]], dt_days[valid_indices[-1]])
    
    return {
        'ssw_probability': round(ssw_prob, 1),
        'vulnerable_probability': round(vulnerable_prob, 1),
        'n_members': n_members,
        'n_reversals': n_reversals,
        'ensemble_mean_u10': round(ens_mean, 1),
        'ensemble_min_u10': round(ens_min, 1),
        'ensemble_max_u10': round(ens_max, 1),
        'current_u10': round(current_u10, 1),
        'lead_window': f"Day {actual_days[0]:.1f}-{actual_days[1]:.1f}",
        'n_timesteps_in_window': len(valid_indices),
    }


def determine_alert_level(ssw_prob: float, current_u10: float) -> dict:
    """
    Determine alert level based on probability and current state.
    """
    if ssw_prob >= PROB_THRESHOLDS['strong']:
        level = 'STRONG'
        color = 'red'
    elif ssw_prob >= PROB_THRESHOLDS['alert']:
        level = 'ALERT'
        color = 'orange'
    elif ssw_prob >= PROB_THRESHOLDS['watch']:
        level = 'WATCH'
        color = 'yellow'
    else:
        level = 'NORMAL'
        color = 'green'
    
    # Vortex state description
    if current_u10 > 30:
        vortex_state = 'strong'
    elif current_u10 > 15:
        vortex_state = 'moderate'
    elif current_u10 > 0:
        vortex_state = 'weak'
    else:
        vortex_state = 'reversed'
    
    return {
        'level': level,
        'color': color,
        'vortex_state': vortex_state,
        'should_alert': level in ['ALERT', 'STRONG'],
    }


def get_ecmwf_chart_url(run_date: datetime = None) -> str:
    """
    Get ECMWF extended zonal wind chart URL for corroboration.

    This is the correct ECMWF product: Sub-seasonal range ensemble U10@60N.
    Just returns the URL (no fragile API parsing).
    """
    if run_date is None:
        run_date = datetime.now(timezone.utc)

    # ECMWF extended range: 00z and 12z runs
    base_time = run_date.strftime('%Y%m%d') + '0000'

    return (
        f"https://charts.ecmwf.int/products/extended-zonal-mean-zonal-wind"
        f"?area=nh&base_time={base_time}"
    )


# === HISTORY AND STATE MANAGEMENT ===

def load_history() -> dict:
    """Load run history from JSON file."""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception as e:
            logger.warning(f"Failed to load history: {e}")
    return {"runs": []}


def save_history(history: dict):
    """Save run history to JSON file."""
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def add_to_history(history: dict, run_data: dict, is_elevated: bool) -> dict:
    """Add a run to history and prune old entries."""
    history["runs"].append(run_data)

    # Determine retention period
    retention_days = HISTORY_DAYS_ELEVATED if is_elevated else HISTORY_DAYS_NORMAL
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    # Prune old runs
    history["runs"] = [
        r for r in history["runs"]
        if datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) > cutoff
    ]

    return history


def load_state() -> dict:
    """Load posting state from JSON file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
    return {
        "elevated_runs": 0,
        "last_level": "NORMAL",
        "last_probability": 0.0,
        "signal_started": None,
        "subsided_posted": False,
        "last_post_time": None,
        "last_posted_commentary": None
    }


def save_state(state: dict):
    """Save posting state to JSON file."""
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_recent_runs_summary(history: dict, hours: int = 24) -> dict:
    """Get summary of runs in the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    recent = [
        r for r in history.get("runs", [])
        if datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) > cutoff
    ]

    if not recent:
        return {"count": 0, "elevated_count": 0, "runs": []}

    elevated_count = sum(1 for r in recent if r.get("probability", 0) >= PROB_THRESHOLDS["watch"])

    return {
        "count": len(recent),
        "elevated_count": elevated_count,
        "runs": recent
    }


def get_trend_description(history: dict) -> str:
    """Analyze probability trend over recent history."""
    runs = history.get("runs", [])
    if len(runs) < 3:
        return "insufficient data"

    # Get last 7 days of probabilities
    recent = runs[-min(len(runs), 28):]  # ~7 days at 4x/day
    probs = [r.get("probability", 0) for r in recent]

    if len(probs) < 3:
        return "insufficient data"

    # Simple trend detection
    first_half = sum(probs[:len(probs)//2]) / (len(probs)//2)
    second_half = sum(probs[len(probs)//2:]) / (len(probs) - len(probs)//2)

    diff = second_half - first_half

    if diff > 5:
        return "rising"
    elif diff < -5:
        return "falling"
    else:
        return "stable"


# === CHART GENERATION ===

def generate_ssw_history_chart(history: dict, output_path: Path) -> bool:
    """
    Generate rolling SSW probability chart from history.
    Shows last 7 days of probability with threshold lines.
    """
    if not HAS_MATPLOTLIB:
        logger.warning("matplotlib not installed, skipping chart")
        return False

    try:
        runs = history.get("runs", [])
        if len(runs) < 2:
            logger.warning("Not enough history for chart")
            return False

        # Filter to last 7 days for chart (history may have 30 days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        runs = [r for r in runs if datetime.fromisoformat(
            r["timestamp"].replace("Z", "+00:00")) > cutoff]

        if len(runs) < 2:
            logger.warning("Not enough recent history for chart")
            return False

        # Extract timestamps and probabilities
        timestamps = []
        probabilities = []
        levels = []

        for run in runs:
            try:
                ts = datetime.fromisoformat(run["timestamp"].replace("Z", "+00:00"))
                timestamps.append(ts)
                probabilities.append(run.get("probability", 0))
                levels.append(run.get("level", "NORMAL"))
            except Exception:
                continue

        if len(timestamps) < 2:
            logger.warning("Not enough valid data points for chart")
            return False

        # Dark theme matching other WXD charts
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))

        # Plot probability line
        ax.plot(timestamps, probabilities, color='#4ECDC4', linewidth=2.5,
                marker='o', markersize=4, label='SSW Probability')

        # Fill under the line
        ax.fill_between(timestamps, 0, probabilities, color='#4ECDC4', alpha=0.2)

        # Threshold lines
        ax.axhline(y=PROB_THRESHOLDS['watch'], color='#FFD93D', linestyle='--',
                   alpha=0.8, linewidth=1.5, label=f"WATCH ({PROB_THRESHOLDS['watch']}%)")
        ax.axhline(y=PROB_THRESHOLDS['alert'], color='#FF8C42', linestyle='--',
                   alpha=0.8, linewidth=1.5, label=f"ALERT ({PROB_THRESHOLDS['alert']}%)")
        ax.axhline(y=PROB_THRESHOLDS['strong'], color='#FF6B6B', linestyle='--',
                   alpha=0.8, linewidth=1.5, label=f"STRONG ({PROB_THRESHOLDS['strong']}%)")

        # Mark WATCH/ALERT/STRONG points with colored markers
        for i, (ts, prob, level) in enumerate(zip(timestamps, probabilities, levels)):
            if level == 'WATCH':
                ax.scatter([ts], [prob], color='#FFD93D', s=80, zorder=5, edgecolors='white', linewidths=1)
            elif level == 'ALERT':
                ax.scatter([ts], [prob], color='#FF8C42', s=100, zorder=5, edgecolors='white', linewidths=1)
            elif level == 'STRONG':
                ax.scatter([ts], [prob], color='#FF6B6B', s=120, zorder=5, edgecolors='white', linewidths=1)

        # Formatting
        ax.set_xlabel('Date (UTC)', fontsize=12)
        ax.set_ylabel('SSW Probability (%)', fontsize=12)
        ax.set_ylim(0, max(60, max(probabilities) + 10))

        # Title with current value
        current_prob = probabilities[-1] if probabilities else 0
        current_level = levels[-1] if levels else "NORMAL"
        ax.set_title(f'SSW Probability - Rolling History (Current: {current_prob:.0f}% {current_level})',
                     fontsize=14)

        ax.legend(loc='upper left', fontsize=9)
        ax.grid(True, alpha=0.3)

        # Date formatting
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        fig.autofmt_xdate()

        # Watermark
        fig.text(0.99, 0.01, 'wxd-london.bsky.social | GEFS 31-member ensemble',
                 fontsize=8, color='gray', alpha=0.6,
                 ha='right', va='bottom', transform=fig.transFigure)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, facecolor='#1a1a2e')
        plt.close()

        logger.info(f"SSW chart saved: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Error generating SSW chart: {e}")
        import traceback
        traceback.print_exc()
        return False


# === POSTING DECISION LOGIC ===

def should_post(current_result: dict, state: dict, recent_runs: dict) -> tuple[bool, str]:
    """
    Determine if we should post based on current result and state.

    Returns (should_post: bool, reason: str)
    """
    prob = current_result.get("ssw_probability_pct", 0)
    level = current_result.get("alert", {}).get("level", "NORMAL")
    last_level = state.get("last_level", "NORMAL")
    last_post_time = state.get("last_post_time")

    # Check cooldown
    if last_post_time:
        try:
            last_dt = datetime.fromisoformat(last_post_time.replace("Z", "+00:00"))
            hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if hours_since < POST_COOLDOWN_HOURS:
                return False, f"cooldown ({hours_since:.1f}h since last post)"
        except Exception:
            pass

    # Level change (escalation or de-escalation)
    if level != last_level:
        if level == "NORMAL" and last_level != "NORMAL":
            # Signal subsided
            if not state.get("subsided_posted", False):
                return True, "signal_subsided"
        elif level != "NORMAL":
            return True, f"level_change_{last_level}_to_{level}"

    # Threshold reached (first time or daily update while elevated)
    if prob >= PROB_THRESHOLDS["watch"]:
        if last_level == "NORMAL":
            return True, "threshold_reached"
        else:
            # Already elevated - daily update
            return True, "elevated_daily_update"

    return False, "below_threshold"


# === POST TEXT GENERATION ===

def generate_post_text(result: dict, state: dict, recent_runs: dict, reason: str) -> str:
    """Generate Bluesky post text based on result and context."""
    prob = result.get("ssw_probability_pct", 0)
    level = result.get("alert", {}).get("level", "NORMAL")
    u10 = result.get("current_u10_60n_ms", 0)
    vortex = result.get("alert", {}).get("vortex_state", "unknown")
    n_reversals = result.get("ensemble", {}).get("n_reversals", 0)
    n_members = result.get("ensemble", {}).get("n_members", 31)

    # Run agreement context
    run_count = recent_runs.get("count", 0)
    elevated_count = recent_runs.get("elevated_count", 0)

    if reason == "signal_subsided":
        return "🌀 SSW signal subsided: Back below 10%. Vortex stable."

    # Build main post
    if level == "STRONG":
        emoji_level = "🌀 SSW Strong Signal"
    elif level == "ALERT":
        last_prob = state.get("last_probability", 0)
        if prob > last_prob:
            emoji_level = "🌀 SSW Alert ↑"
        else:
            emoji_level = "🌀 SSW Alert"
    else:
        emoji_level = "🌀 SSW Watch"

    # Main text
    text = f"{emoji_level}: {prob:.0f}% of GEFS members ({n_reversals}/{n_members}) show reversal signal in 5-16 day window.\n\n"
    text += f"Vortex currently {vortex} ({u10:.0f} m/s)."

    # Run agreement context
    if run_count > 1:
        if elevated_count == run_count:
            text += f"\n\n({elevated_count}/{run_count} runs in last 24h elevated)"
        elif elevated_count == 1:
            text += f"\n\n(First run to reach threshold in 24h)"
        else:
            text += f"\n\n({elevated_count}/{run_count} runs in last 24h also elevated)"

    return text


def generate_claude_commentary(result: dict, history: dict, state: dict) -> str:
    """Generate AI commentary for significant events using Claude CLI."""
    prob = result.get("ssw_probability_pct", 0)
    level = result.get("alert", {}).get("level", "NORMAL")

    # Only generate commentary for ALERT or STRONG
    if level not in ["ALERT", "STRONG"]:
        return None

    # Build history summary for prompt
    runs = history.get("runs", [])[-28:]  # Last week
    prob_history = [f"{r.get('probability', 0):.0f}%" for r in runs[-7:]]
    trend = get_trend_description(history)

    prompt = f"""You are WXD, a weather bot. Write a brief (max 200 chars) follow-up comment on this SSW signal.

Current: {prob:.0f}% probability, {level} level
Recent trend: {trend}
Last 7 runs: {' → '.join(prob_history)}
Vortex: {result.get('alert', {}).get('vortex_state', 'unknown')} ({result.get('current_u10_60n_ms', 0):.0f} m/s)

Be factual. Note if signal is emerging, strengthening, or persisting. Mention UK cold risk potential (2-4 weeks lag) if appropriate.
No emoji. No hype. One or two sentences max."""

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '--model', 'haiku', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            commentary = result.stdout.strip()[:280]  # Ensure within limit
            return commentary
    except Exception as e:
        logger.warning(f"Claude commentary failed: {e}")

    return None


def post_to_bluesky(text: str, commentary: str = None, image_path: Path = None, dry_run: bool = False) -> bool:
    """Post to Bluesky with optional image using atproto client directly."""
    if dry_run:
        logger.info(f"[DRY RUN] Would post:\n{text}")
        if image_path and image_path.exists():
            logger.info(f"[DRY RUN] With image: {image_path}")
        if commentary:
            logger.info(f"[DRY RUN] With commentary reply:\n{commentary}")
        return True

    try:
        import os
        from atproto import Client
        from atproto import models as atproto_models

        # Load credentials
        handle = os.environ.get('BSKY_HANDLE')
        password = os.environ.get('BSKY_PASSWORD')
        if not handle or not password:
            raise ValueError("BSKY_HANDLE and BSKY_PASSWORD must be set")

        client = Client()
        client.login(handle, password)

        # Upload image if provided
        embed = None
        if image_path and image_path.exists():
            with open(image_path, 'rb') as f:
                image_data = f.read()
            upload = client.upload_blob(image_data)
            embed = {
                '$type': 'app.bsky.embed.images',
                'images': [{
                    'alt': 'SSW probability rolling history chart',
                    'image': upload.blob
                }]
            }
            logger.info(f"Image uploaded: {image_path}")

        # Post main text
        if embed:
            response = client.send_post(text=text, embed=embed)
        else:
            response = client.send_post(text=text)
        logger.info(f"Posted: https://bsky.app/profile/{handle}/post/{response.uri.split('/')[-1]}")

        # Register in post registry
        try:
            from data.post_registry import register_post
            register_post(uri=response.uri, tracker='ssw', model=None, text_preview=text[:100])
        except Exception as e:
            logger.warning(f"Failed to register post: {e}")

        # Post commentary as reply if provided
        if commentary:
            parent_ref = atproto_models.create_strong_ref(response)
            reply_ref = atproto_models.AppBskyFeedPost.ReplyRef(
                parent=parent_ref,
                root=parent_ref
            )
            reply_response = client.send_post(text=commentary, reply_to=reply_ref)
            logger.info(f"Commentary posted as reply")

        return True

    except Exception as e:
        logger.error(f"Bluesky post failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def select_gefs_cycle(now: datetime) -> tuple[datetime, str]:
    """
    Select which GEFS cycle to use based on current time.
    Allow 4-5 hours for GEFS processing/availability.
    """
    hour = now.hour
    
    # Cycle availability (approximate):
    # 00z ready by ~05z, 06z ready by ~11z, 12z ready by ~17z, 18z ready by ~23z
    if 5 <= hour < 11:
        return now, '00'
    elif 11 <= hour < 17:
        return now, '06'
    elif 17 <= hour < 23:
        return now, '12'
    else:
        # After 23z or before 05z: use yesterday's 18z
        if hour < 5:
            return now - timedelta(days=1), '18'
        else:
            return now, '18'


def run_ssw_monitor(debug: bool = False, post: bool = False, dry_run: bool = False) -> dict:
    """
    Main monitoring routine.

    Args:
        debug: Inspect dataset structure and exit
        post: Post to Bluesky if thresholds met
        dry_run: Test posting logic without actually posting
    """
    run_time = datetime.now(timezone.utc)
    logger.info(f"SSW monitor starting at {run_time.isoformat()}")

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Select GEFS cycle
    run_date, cycle = select_gefs_cycle(run_time)

    # === LATENCY PROBE ===
    # Log which cycle we're targeting and the data age
    cycle_init_time = datetime.combine(run_date.date(), datetime.min.time(), tzinfo=timezone.utc)
    cycle_init_time = cycle_init_time.replace(hour=int(cycle))
    data_age_hours = (run_time - cycle_init_time).total_seconds() / 3600
    logger.info(f"LATENCY: Targeting {run_date.strftime('%Y%m%d')}/{cycle}z (data age: {data_age_hours:.1f}h)")
    
    # Debug mode: just inspect dataset structure
    if debug:
        url = get_gefs_cycle_url(run_date, cycle)
        success = debug_dataset_structure(url)
        return {'debug': True, 'success': success, 'url': url}
    
    # Fetch GEFS ensemble data
    gefs_result = fetch_gefs_u10_ensemble(run_date, cycle)
    
    if not gefs_result['success']:
        # Try previous cycle as fallback
        logger.warning(f"Primary cycle failed, trying fallback...")
        prev_cycles = [('18', -1), ('12', 0), ('06', 0), ('00', 0)]
        cycle_idx = {'00': 0, '06': 1, '12': 2, '18': 3}[cycle]
        
        for i in range(1, 4):
            fallback_idx = (cycle_idx - i) % 4
            fb_cycle = ['00', '06', '12', '18'][fallback_idx]
            fb_date = run_date - timedelta(days=1) if fallback_idx > cycle_idx else run_date
            
            gefs_result = fetch_gefs_u10_ensemble(fb_date, fb_cycle)
            if gefs_result['success']:
                logger.info(f"Fallback succeeded: {fb_date.strftime('%Y%m%d')}/{fb_cycle}z")
                break
    
    if not gefs_result['success']:
        error_output = {
            'timestamp': run_time.isoformat(),
            'status': 'error',
            'error': gefs_result.get('error', 'Unknown error'),
        }
        # Still save error state
        (OUTPUT_DIR / 'ssw_status.json').write_text(json.dumps(error_output, indent=2))
        return error_output
    
    # Compute SSW probability
    ssw_stats = compute_ssw_probability(
        gefs_result['data'],
        gefs_result['ens_dim'],
        gefs_result['time_dim']
    )
    
    # Determine alert level
    alert_info = determine_alert_level(
        ssw_stats['ssw_probability'],
        ssw_stats['current_u10']
    )
    
    # Get ECMWF chart URL for corroboration
    ecmwf_url = get_ecmwf_chart_url(run_date)
    
    # Log successful fetch latency
    actual_latency = (run_time - cycle_init_time).total_seconds() / 3600
    logger.info(f"LATENCY: Fetch succeeded at {actual_latency:.1f}h after cycle init")

    # Compile output
    output = {
        'timestamp': run_time.isoformat(),
        'model_run': f"{run_date.strftime('%Y%m%d')}/{cycle}z",
        'data_age_hours': round(actual_latency, 1),
        'status': 'ok',
        
        # Primary metrics (what WeatherIsCool shows)
        'ssw_probability_pct': ssw_stats['ssw_probability'],
        'vulnerable_probability_pct': ssw_stats['vulnerable_probability'],
        'current_u10_60n_ms': ssw_stats['current_u10'],
        
        # Ensemble statistics
        'ensemble': {
            'n_members': ssw_stats['n_members'],
            'n_reversals': ssw_stats['n_reversals'],
            'mean_u10': ssw_stats['ensemble_mean_u10'],
            'min_u10': ssw_stats['ensemble_min_u10'],
            'max_u10': ssw_stats['ensemble_max_u10'],
        },
        
        # Alert status
        'alert': alert_info,
        
        # Metadata
        'lead_window': ssw_stats['lead_window'],
        'n_timesteps': ssw_stats['n_timesteps_in_window'],
        
        # ECMWF corroboration (URL only, no fragile API)
        'ecmwf_chart_url': ecmwf_url,
        
        # Definition reference
        'ssw_definition': 'Major SSW = zonal-mean zonal wind at 10 hPa, 60°N reverses to easterly (U < 0)',
    }
    
    # Save output
    output_file = OUTPUT_DIR / 'ssw_status.json'
    output_file.write_text(json.dumps(output, indent=2))
    logger.info(f"Saved: {output_file}")

    # Alert logging
    if alert_info['should_alert']:
        logger.warning(
            f"⚠️  SSW {alert_info['level']}: "
            f"{ssw_stats['ssw_probability']:.0f}% probability | "
            f"Current U10: {ssw_stats['current_u10']:.1f} m/s | "
            f"Vortex: {alert_info['vortex_state']}"
        )
    else:
        logger.info(
            f"SSW status: {alert_info['level']} | "
            f"{ssw_stats['ssw_probability']:.0f}% prob | "
            f"U10: {ssw_stats['current_u10']:.1f} m/s"
        )

    # === HISTORY AND STATE MANAGEMENT ===
    is_elevated = ssw_stats['ssw_probability'] >= PROB_THRESHOLDS['watch']

    # Load history and state
    history = load_history()
    state = load_state()

    # Add current run to history
    run_record = {
        "timestamp": run_time.isoformat(),
        "cycle": cycle,
        "probability": ssw_stats['ssw_probability'],
        "n_reversals": ssw_stats['n_reversals'],
        "n_members": ssw_stats['n_members'],
        "current_u10": ssw_stats['current_u10'],
        "level": alert_info['level'],
        "data_age_hours": round(actual_latency, 1)
    }
    history = add_to_history(history, run_record, is_elevated)
    save_history(history)

    # Get recent runs for context
    recent_runs = get_recent_runs_summary(history, hours=24)

    # === POSTING LOGIC ===
    if post or dry_run:
        do_post, reason = should_post(output, state, recent_runs)
        logger.info(f"Post decision: {do_post} ({reason})")

        if do_post:
            # Generate post text
            post_text = generate_post_text(output, state, recent_runs, reason)
            logger.info(f"Post text ({len(post_text)} chars): {post_text[:100]}...")

            # Generate rolling history chart
            chart_path = OUTPUT_DIR / 'ssw_history_chart.png'
            chart_ok = generate_ssw_history_chart(history, chart_path)
            if chart_ok:
                logger.info(f"Chart generated: {chart_path}")
            else:
                chart_path = None  # Don't try to attach if generation failed

            # Generate AI commentary for significant events
            commentary = generate_claude_commentary(output, history, state)

            # Post to Bluesky with chart
            if post_to_bluesky(post_text, commentary, image_path=chart_path, dry_run=dry_run):
                # Update state after successful post
                state["last_post_time"] = run_time.isoformat()
                state["last_posted_commentary"] = post_text
                if reason == "signal_subsided":
                    state["subsided_posted"] = True
                else:
                    state["subsided_posted"] = False

    # Update state
    state["last_level"] = alert_info['level']
    state["last_probability"] = ssw_stats['ssw_probability']
    if is_elevated and state.get("signal_started") is None:
        state["signal_started"] = run_time.isoformat()
    elif not is_elevated:
        state["signal_started"] = None
    state["elevated_runs"] = recent_runs.get("elevated_count", 0)

    save_state(state)

    return output


def main():
    parser = argparse.ArgumentParser(
        description='SSW Monitor - GEFS ensemble-based sudden stratospheric warming probability'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Debug mode: inspect GEFS dataset structure and exit'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output JSON to stdout'
    )
    parser.add_argument(
        '--post',
        action='store_true',
        help='Post to Bluesky if thresholds met'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Test posting logic without actually posting'
    )

    args = parser.parse_args()

    result = run_ssw_monitor(
        debug=args.debug,
        post=args.post,
        dry_run=getattr(args, 'dry_run', False)
    )

    if args.json or args.debug:
        print(json.dumps(result, indent=2))

    # Exit code based on status
    if result.get('status') == 'error':
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
