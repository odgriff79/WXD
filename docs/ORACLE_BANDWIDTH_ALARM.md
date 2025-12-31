# Oracle Cloud Bandwidth Alarm Setup

Instructions for setting up an email alert when outbound bandwidth exceeds 80% of the 10 TB monthly free tier limit.

---

## Prerequisites

- Oracle Cloud account with Compute instance running
- Email address for notifications

---

## Step 1: Navigate to Monitoring

1. Log in to [Oracle Cloud Console](https://cloud.oracle.com)
2. Click the **hamburger menu** (☰) in the top-left
3. Go to **Observability & Management** → **Monitoring** → **Alarms**

---

## Step 2: Create New Alarm

1. Click **Create Alarm**
2. Fill in the **Alarm Definition**:
   - **Alarm name**: `WXD-Direct Bandwidth Warning`
   - **Alarm severity**: `Warning`
   - **Alarm body**: `Monthly outbound bandwidth has exceeded 80% of the 10 TB free tier limit. Review usage immediately.`

---

## Step 3: Configure Metric

1. In **Metric description**:
   - **Compartment**: Select your compartment (likely root)
   - **Metric namespace**: `oci_computeagent`
   - **Metric name**: `NetworksBytesOut`
   - **Interval**: `1 day` (or `1 hour` for more frequent checks)
   - **Statistic**: `Sum`

2. **Dimension**:
   - **resourceDisplayName**: Your instance name (e.g., `wxd-arm-vm`)

---

## Step 4: Set Trigger Rule

1. **Trigger rule**:
   - **Operator**: `greater than`
   - **Value**: `8796093022208` (8 TB in bytes = 80% of 10 TB)
   - **Trigger delay minutes**: `60`

**Note**: The free tier resets monthly. For cumulative monthly tracking, you may need to use a custom metric or adjust the aggregation window.

### Alternative: Daily Rate-Based Alert

If cumulative monthly isn't available, set a daily rate alert:
- **Value**: `293817902694` (~274 GB/day would hit 10 TB in ~36 days)
- This catches unusual spikes before they accumulate

---

## Step 5: Configure Notifications

1. Under **Notifications**:
   - **Destination**: Click **Create a topic**
   - **Topic name**: `wxd-bandwidth-alerts`
   - **Subscription protocol**: `Email`
   - **Subscription email**: Your email address

2. After creating, you'll receive a **confirmation email** - click the link to confirm

---

## Step 6: Review and Create

1. Review all settings
2. Click **Create Alarm**
3. Alarm status should show **OK** (green)

---

## Verification

1. Go back to **Monitoring** → **Alarms**
2. Your alarm should appear with status **OK**
3. Test by temporarily lowering the threshold (then reset it)

---

## Alternative: OCI CLI Method

If you prefer CLI:

```bash
# Create notification topic
oci ons topic create \
  --compartment-id <COMPARTMENT_OCID> \
  --name wxd-bandwidth-alerts

# Create email subscription (note topic OCID from above)
oci ons subscription create \
  --compartment-id <COMPARTMENT_OCID> \
  --topic-id <TOPIC_OCID> \
  --protocol EMAIL \
  --subscription-endpoint your@email.com

# Create alarm
oci monitoring alarm create \
  --compartment-id <COMPARTMENT_OCID> \
  --display-name "WXD-Direct Bandwidth Warning" \
  --metric-compartment-id <COMPARTMENT_OCID> \
  --namespace oci_computeagent \
  --query-text 'NetworksBytesOut[1d]{resourceDisplayName = "wxd-arm-vm"}.sum()' \
  --severity WARNING \
  --destinations '["<TOPIC_OCID>"]' \
  --is-enabled true \
  --pending-duration PT1H \
  --body "Monthly bandwidth exceeding 80% of free tier" \
  --resolution "Review WXD-Direct usage"
```

---

## Notes

- Oracle's free tier includes 10 TB outbound data per month
- The metric `NetworksBytesOut` tracks all egress traffic
- WXD-Direct uses ~8 MB/day (~0.0008% of monthly limit)
- This alarm is precautionary - current usage is negligible

---

## Monitoring Dashboard (Optional)

For ongoing visibility:

1. Go to **Observability & Management** → **Monitoring** → **Metrics Explorer**
2. Query: `NetworksBytesOut[1d].sum()` with your instance filter
3. Save as a chart for quick access
