# Chart Sync Audit

**Created**: 2026-01-25
**Status**: COMPLETE

## Current State

### Charts Generated

| Chart | Source Path | Synced? | On Pages? |
|-------|-------------|---------|-----------|
| Main ensemble | `data/chart_latest.png` | ✓ Yes | ✓ Yes |
| ICON-EU-EPS | `trackers/icon/data/chart_latest.png` | ✓ Yes | ✓ Yes |
| UKMO Global | `trackers/ukmo/data/chart_latest.png` | ✓ Yes | ✓ Yes |
| MOGREPS-G | `trackers/mogreps/data/chart_latest.png` | ✓ Yes | ✓ Yes |
| **SSW History** | `ssw/ssw_history_chart.png` | ✗ No | ✗ No |

### Sync Mechanism

- `sync_charts.sh` copies charts to `docs/charts/` and pushes to GitHub
- Runs on cron at 10:15, 22:15 UTC
- GitHub Pages serves from `docs/` directory

### Issues Found

1. **SSW chart not synced** - `ssw/ssw_history_chart.png` exists but not copied to `docs/charts/`
2. **SSW not on index.html** - No card for SSW probability history
3. **Wrong GitHub link** - Footer has `ogrisel/WXD` instead of `odgriff79/WXD`

## Plan

### Phase 1: Add SSW Chart to Sync

Edit `sync_charts.sh` to include:
```bash
if [ -f ssw/ssw_history_chart.png ]; then
    cp ssw/ssw_history_chart.png docs/charts/ssw.png
    echo "  ssw.png updated"
fi
```

### Phase 2: Add SSW Card to index.html (Seasonal)

SSW only relevant Oct-Apr. Added card with JavaScript conditional display:
- Card hidden by default (`style="display:none"`)
- JS checks month: if Oct(9) - Apr(3), show card
- Rest of year: card stays hidden

### Phase 3: Fix GitHub Link

Change footer from:
```html
<a href="https://github.com/ogrisel/WXD">GitHub</a>
```
To:
```html
<a href="https://github.com/odgriff79/WXD">GitHub</a>
```

### Phase 4: Run Sync

```bash
./sync_charts.sh
```

## Future Considerations

- Add chart timestamps (show when each chart was last updated)
- Add chart descriptions/tooltips
- Consider adding engagement/educational charts if generated
- Mobile-responsive improvements

## Validation

After implementation:
1. Visit https://odgriff79.github.io/WXD/
2. Verify all 5 charts visible (main, icon, ukmo, mogreps, ssw)
3. Verify GitHub link works
4. Check mobile view
