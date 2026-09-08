# UniFi-Poller: USG Insights (grafana.com ID 11313)

## Source
https://grafana.com/grafana/dashboards/11313/ community dashboard,
unmodified structure aside from the fixes below.

## What it's for
Gateway/router-focused detail: the USG/UDM's own identity (Gateway Details
table - IP, MAC, model, serial, firmware version), speed test results,
uplink latency, CPU/RAM utilization for the gateway AND every adopted
access point, load averages, and WAN/LAN throughput and packet-level detail
(multicast/broadcast, drops, errors). This is the "how is my router/gateway
and APs doing, resource-wise" dashboard - it does not cover individual
clients (see Client Insights) or site-wide aggregate counts (see Network
Sites).

## Fixes applied (2026-09-09)
- `table-old` panel (1) converted to `table`, and `singlestat` panels (6)
  converted to `stat` - both removed from Grafana core years ago; on
  Grafana 13.2.1 these threw "an error occurred with the plugin".
- Datasource references (`${DS_PROMETHEUS}`) hardcoded to a concrete object:
  `{"type": "prometheus", "uid": "prometheus"}` - see the Network Sites
  README's "Not portable as-is" note, same caveat applies here.

## Notes
- **"Purposely Empty Row"** is intentional, named that way by the original
  dashboard author as a visual spacer - not a bug, nothing to fix.
- The per-AP CPU/RAM panels correctly show all 3 access points once the
  datasource fix above is applied - each AP's device-level metrics come
  through as `type="udm"` (not `type="uap"`) in this household's controller
  API responses, which is why they show up fine here (this dashboard queries
  generic device metrics, not a `type="uap"` filter) but would NOT show up
  correctly on any future panel that specifically filters `type="uap"`.

## Where the actual dashboard JSON lives
Not provisioned via Grafana's file-provider (imported via the UI instead).
The patched JSON is checked into this repo at
`grafana/dashboards/11313-usg-insights-patched.json` for reference and
re-import if ever needed - re-importing it is a manual step, not automatic
on deploy.
