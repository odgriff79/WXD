"""Unified context builder for all reply types.

This module provides a single ReplyContext class that builds context
for Claude responses, working uniformly across all trackers and post types.

Any feature added here automatically applies to ALL replies.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import json


class ReplyContext:
    """Unified context builder for all reply types.

    Usage:
        context = ReplyContext(parent_uri, reply_text, parent_text).build()
    """

    def __init__(self, parent_uri: str, reply_text: str, parent_text: str = ""):
        self.parent_uri = parent_uri
        self.reply_text = reply_text
        self.parent_text = parent_text
        self._context_parts = []

        # Lazy import to avoid circular deps
        from lib.bluesky import get_post_type
        self.post_type = get_post_type(parent_uri, parent_text)

    def build(self) -> str:
        """Build unified context string.

        Features added here apply to ALL post types automatically.
        """
        # 1. SSW context (if SSW post or SSW mentioned)
        if self.post_type == 'ssw' or self._mentions_ssw():
            self._add_ssw_context()

        # 2. Forecast data for forecast posts
        if self.post_type in ('main', 'icon', 'ukmo', 'mogreps', 'unknown'):
            self._add_forecast_context()

        # 3. Query-triggered contexts (work for ANY post type)
        self._add_query_triggered_contexts()

        return '\n\n'.join(self._context_parts)

    def _mentions_ssw(self) -> bool:
        """Check if reply or parent mentions SSW/stratosphere."""
        combined = (self.reply_text + ' ' + self.parent_text).lower()
        ssw_keywords = ['ssw', 'stratospher', 'polar vortex', 'vortex', 'strat',
                       'sudden warming', '10hpa', '10 hpa']
        return any(kw in combined for kw in ssw_keywords)

    def _mentions_trends(self) -> bool:
        """Check if user asks about trends/statistics."""
        text = self.reply_text.lower()
        trend_keywords = ['trend', 'significant', 'statistic', 'r squared', 'r²',
                         'p-value', 'regression', 'linear', 'consistent', 'pattern']
        return any(kw in text for kw in trend_keywords)

    def _mentions_model_comparison(self) -> bool:
        """Check if user asks about model comparisons."""
        text = self.reply_text.lower()
        return any(kw in text for kw in ['gfs', 'ecm', 'icon', 'compare', 'vs', 'versus', 'difference'])

    def _mentions_temporal(self) -> bool:
        """Check if user asks about temporal comparison."""
        text = self.reply_text.lower()
        return any(kw in text for kw in ['yesterday', '24h', 'last run', 'previous', 'changed'])

    def _add_ssw_context(self):
        """Add SSW context with trend analysis."""
        try:
            history_path = Path('/home/ubuntu/wxd/ssw/history.json')
            if not history_path.exists():
                return

            with open(history_path) as f:
                history = json.load(f)

            runs = history.get('runs', [])
            if not runs:
                return

            # Get last 7 days of data
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            recent_runs = []
            seen_ts = set()
            for r in runs:
                ts = r['timestamp'][:16]
                if ts not in seen_ts:
                    seen_ts.add(ts)
                    try:
                        run_time = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
                        if run_time > cutoff:
                            recent_runs.append(r)
                    except:
                        pass

            if not recent_runs:
                return

            latest = recent_runs[-1]
            current_prob = latest.get('probability', 0)
            current_level = latest.get('level', 'NORMAL')
            current_u10 = latest.get('current_u10', 0)

            probs = [r.get('probability', 0) for r in recent_runs]
            min_prob = min(probs)
            max_prob = max(probs)
            watch_count = sum(1 for r in recent_runs if r.get('level') in ['WATCH', 'ALERT', 'STRONG'])

            # Calculate trend statistics
            trend_section = ""
            n = len(probs)
            if n >= 3:
                stats = self._calculate_trend_stats(probs)
                trend_section = f"""
TREND ANALYSIS (linear regression on {n} runs):
- Direction: {stats['direction']} ({stats['slope']:+.2f}% per run)
- R² = {stats['r_squared']:.2f} ({stats['r_squared']*100:.0f}% variance explained)
- t-statistic = {stats['t_stat']:.1f} (significant if |t|>2)
- Statistically significant trend: {'YES (p<0.05)' if stats['is_significant'] else 'NO'}"""

            vortex_strength = "strong" if current_u10 > 30 else "moderate" if current_u10 > 15 else "weak"

            context = f"""SSW (SUDDEN STRATOSPHERIC WARMING) STATUS:
Current probability: {current_prob:.0f}% ({current_level})
Current polar vortex: {current_u10:.0f} m/s ({vortex_strength})
Last 7 days range: {min_prob:.0f}%-{max_prob:.0f}%
WATCH events (≥10%): {watch_count} in last 7 days
{trend_section}
WXD probability thresholds: WATCH ≥10%, ALERT ≥25%, STRONG ≥50%

CRITICAL - SSW DEFINITION:
- Major SSW = zonal wind REVERSAL at 60°N, 10hPa (westerly → easterly)
- Current m/s is VORTEX STRENGTH, not a threshold
- Source: WMO definition, Charlton & Polvani 2007"""

            self._context_parts.append(context)

        except Exception as e:
            print(f"    Error loading SSW context: {e}")

    def _add_forecast_context(self):
        """Add forecast data context."""
        try:
            summary_path = Path('/home/ubuntu/wxd/data/summary_latest.json')
            if not summary_path.exists():
                return

            with open(summary_path) as f:
                data = json.load(f)

            models = data.get('models', {})
            if not models:
                return

            # Get multi-model mean for key dates
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)

            context_lines = ["FORECAST DATA (850hPa temps, multi-model):"]

            # Show next 7 days summary
            for model_name, model_data in list(models.items())[:4]:
                if 'mean' in model_data:
                    temps = model_data['mean'][:14]  # First 7 days (12h intervals)
                    if temps:
                        min_t = min(temps)
                        max_t = max(temps)
                        context_lines.append(f"  {model_name}: {min_t:.1f}°C to {max_t:.1f}°C range")

            if len(context_lines) > 1:
                self._context_parts.append('\n'.join(context_lines))

        except Exception as e:
            print(f"    Error loading forecast context: {e}")

    def _add_query_triggered_contexts(self):
        """Add contexts triggered by reply keywords. Works for ANY post type."""

        # Trend/statistics analysis
        if self._mentions_trends():
            self._add_trend_analysis()

        # Model comparison
        if self._mentions_model_comparison():
            self._add_model_comparison()

        # Temporal comparison (yesterday vs today)
        if self._mentions_temporal():
            self._add_temporal_comparison()

    def _add_trend_analysis(self):
        """Add run-over-run trend analysis for forecast temperatures."""
        try:
            history_path = Path('/home/ubuntu/wxd/data/history_compact.json')
            if not history_path.exists():
                return

            with open(history_path) as f:
                data = json.load(f)

            runs = data.get('runs', [])
            if len(runs) < 3:
                return

            # Get target date (3 days from now)
            from datetime import datetime, timezone, timedelta
            target = datetime.now(timezone.utc) + timedelta(days=3)
            target_date = target.strftime('%Y-%m-%d')

            # Extract multi-model mean for target date across runs
            target_temps = []
            for run in runs[-10:]:
                timestamps = run.get('timestamps', [])
                mmm = run.get('multi_model_mean', [])
                for i, ts in enumerate(timestamps):
                    if target_date in ts and i < len(mmm):
                        target_temps.append(mmm[i])
                        break

            if len(target_temps) < 3:
                return

            stats = self._calculate_trend_stats(target_temps)

            context = f"""FORECAST TREND ANALYSIS (for {target_date}):
Run-over-run change in multi-model mean across last {stats['n']} runs:
- Direction: {stats['direction']} ({stats['slope']:+.2f}°C per run)
- R² = {stats['r_squared']:.2f} ({stats['r_squared']*100:.0f}% variance explained)
- t-statistic = {stats['t_stat']:.1f} (significant if |t|>2)
- Statistically significant trend: {'YES (p<0.05)' if stats['is_significant'] else 'NO'}
- Latest: {target_temps[-1]:.1f}°C, earliest: {target_temps[0]:.1f}°C"""

            self._context_parts.append(context)

        except Exception as e:
            print(f"    Error calculating forecast trend: {e}")

    def _add_model_comparison(self):
        """Add cross-model comparison context."""
        try:
            summary_path = Path('/home/ubuntu/wxd/data/summary_latest.json')
            if not summary_path.exists():
                return

            with open(summary_path) as f:
                data = json.load(f)

            models = data.get('models', {})
            if not models:
                return

            context_lines = ["MODEL COMPARISON (current run):"]
            for model_name, model_data in models.items():
                if 'mean' in model_data:
                    temps = model_data['mean']
                    if temps:
                        coldest = min(temps)
                        coldest_idx = temps.index(coldest)
                        context_lines.append(f"  {model_name}: coldest {coldest:.1f}°C at step {coldest_idx}")

            if len(context_lines) > 1:
                self._context_parts.append('\n'.join(context_lines))

        except Exception as e:
            print(f"    Error loading model comparison: {e}")

    def _add_temporal_comparison(self):
        """Add comparison with previous run."""
        try:
            history_path = Path('/home/ubuntu/wxd/data/history_compact.json')
            if not history_path.exists():
                return

            with open(history_path) as f:
                data = json.load(f)

            runs = data.get('runs', [])
            if len(runs) < 2:
                return

            current = runs[-1].get('multi_model_mean', [])
            previous = runs[-2].get('multi_model_mean', [])

            if not current or not previous:
                return

            # Compare first 7 days
            current_7d = current[:14]
            previous_7d = previous[:14]

            if len(current_7d) >= 14 and len(previous_7d) >= 14:
                current_mean = sum(current_7d) / len(current_7d)
                previous_mean = sum(previous_7d) / len(previous_7d)
                shift = current_mean - previous_mean

                direction = "warmer" if shift > 0.1 else "colder" if shift < -0.1 else "unchanged"

                context = f"""RUN-TO-RUN COMPARISON:
Current run mean (7-day): {current_mean:.1f}°C
Previous run mean (7-day): {previous_mean:.1f}°C
Shift: {shift:+.1f}°C ({direction})"""

                self._context_parts.append(context)

        except Exception as e:
            print(f"    Error loading temporal comparison: {e}")

    @staticmethod
    def _calculate_trend_stats(values: list) -> dict:
        """Calculate linear regression statistics."""
        import statistics

        n = len(values)
        if n < 3:
            return {'slope': 0, 'r_squared': 0, 't_stat': 0, 'is_significant': False, 'direction': 'insufficient data', 'n': n}

        x = list(range(n))
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(values)

        num = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denom = sum((x[i] - x_mean) ** 2 for i in range(n))
        slope = num / denom if denom else 0
        intercept = y_mean - slope * x_mean

        ss_tot = sum((v - y_mean) ** 2 for v in values)
        ss_res = sum((values[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot else 0

        if n > 2 and denom > 0 and ss_res >= 0:
            mse = ss_res / (n - 2)
            se_slope = (mse / denom) ** 0.5
            t_stat = abs(slope / se_slope) if se_slope else 0
        else:
            t_stat = 0

        is_significant = t_stat > 2
        direction = 'upward' if slope > 0.01 else 'downward' if slope < -0.01 else 'flat'

        return {
            'slope': slope,
            'r_squared': r_squared,
            't_stat': t_stat,
            'is_significant': is_significant,
            'direction': direction,
            'n': n
        }


# Convenience function
def build_reply_context(parent_uri: str, reply_text: str, parent_text: str = "") -> str:
    """Build unified context for a reply. Use this from reply_listener.py."""
    return ReplyContext(parent_uri, reply_text, parent_text).build()
