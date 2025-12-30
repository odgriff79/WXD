# WXD Confidence Framework

## Problem Statement

Previously WXD used a single "Confidence: low/medium/high" label that conflated two distinct concepts:
1. **Signal confidence** - Will this weather event happen?
2. **Timing precision** - Exactly when will it peak?

This caused misleading posts like "Confidence: low" when 4/4 models agreed on cold (signal was strong) but the coldest day varied by ±2 days (timing was uncertain).

## Research Summary

Consulted Met Office, ECMWF, NWS best practices plus GPT-4, Gemini, and Claude (Dec 2024).

### Key Findings

1. **Never collapse signal and timing into one label** - They are independent uncertainties
2. **"Low confidence" triggers users to think the event might not happen** - Creates false negatives
3. **Run persistence is a confidence asset** - 7+ consecutive runs showing same signal = high confidence
4. **Use date ranges, not specific days** - "Jan 3-5" not "Jan 4" for ensemble forecasts

### Professional Terminology

| Service | Signal Language | Timing Language |
|---------|-----------------|-----------------|
| Met Office | "High confidence in...", "Well-established signal" | "Timing remains uncertain", "Between Tuesday and Thursday" |
| ECMWF | "Ensemble agreement is strong", "Signal is well-established" | "Spread increases around day 6-8", "Principal uncertainty concerns timing" |
| NWS | "High confidence in [event]", "Pattern is locked in" | "Timing details will become clearer", "Window of..." |

## WXD Implementation

### Signal Strength (Event Confidence)

Based on model agreement + run persistence:

| Level | Criteria | Label |
|-------|----------|-------|
| **Locked** | 4/4 models agree AND 5+ runs persistent | "Signal locked" |
| **Strong** | 3-4/4 models agree OR 3+ runs persistent | "Strong signal" |
| **Emerging** | 2/4 models agree, <3 runs | "Emerging signal" |
| **Weak** | 1/4 models, no persistence | "Weak/uncertain signal" |

### Timing Spread (Temporal Precision)

Based on range of coldest/warmest day across models:

| Spread | Days | Label |
|--------|------|-------|
| **Tight** | ±1 day | "Timing: tight" |
| **Moderate** | ±2 days | "Timing: ±2 days" |
| **Broad** | ±3+ days | "Timing: broad (±3+ days)" |

### Output Format

**Old (misleading):**
```
Cold signal has persisted seven runs. Confidence: low
```

**New (clear):**
```
Cold signal locked (4/4 models, run 7). Coldest period Jan 3-5.
```

Or with explicit labels:
```
Signal: locked | Timing: ±2 days (Jan 3-5)
```

### Context String Format

The analysis context passed to Claude CLI includes:
```
SIGNAL: [locked/strong/emerging] ([X]/4 models, run [N])
TIMING: Coldest [date range] (±[N] days spread)
```

## References

- Met Office ensemble forecasting: https://www.metoffice.gov.uk/blog/2025/what-are-ensemble-forecasts-and-how-does-the-met-office-use-them
- National Academies - Communicating Forecast Uncertainty: https://nap.nationalacademies.org/read/11699/chapter/6
- ECMWF Ensemble Fact Sheet: https://www.ecmwf.int/en/about/media-centre/focus/2017/fact-sheet-ensemble-weather-forecasting
- WMO Forecast Uncertainty Communication: https://wmo.int/media-magazine-article/communicating-forecast-uncertainty-service-providers

## Changelog

- 2024-12-30: Initial framework based on cross-AI research (GPT-4, Gemini, Claude)
