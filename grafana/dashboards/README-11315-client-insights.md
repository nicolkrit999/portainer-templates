# UniFi-Poller: Client Insights (grafana.com ID 11315)

## Source
https://grafana.com/grafana/dashboards/11315/ - designed for "UniFi Poller
v2.0.1", recommends pairing with dashboard 11311 (Network Sites). Unmodified
structure aside from the fixes below.

## What it's for
Per-client detail across the whole network: bandwidth per client (transfer
rate, top talkers), WiFi radio quality where applicable (RSSI, signal/noise,
CCQ, retries, roam count), connection quality percentage, channel/AP-radio/
MAC-vendor breakdowns, and a few device-category-filtered panels (e.g.
Echo/Fire TV, Cameras). This is the "which specific device is doing what"
dashboard - the finest-grained of the three.

## Fixes applied (2026-09-09)
- `table-old` panels (2) converted to `table` - removed from Grafana core
  years ago; on Grafana 13.2.1 these threw "an error occurred with the
  plugin".
- Datasource references (`${DS_PROMETHEUS}`) hardcoded to a concrete object:
  `{"type": "prometheus", "uid": "prometheus"}` - see the Network Sites
  README's "Not portable as-is" note, same caveat applies here.

## Known "no data" panels (expected, not bugs)
- **Client Bandwidth: Echo & Fire TV**, **Client Bandwidth: Cameras** - these
  are device-category filters. They show "no data" simply because this
  household has no matching devices right now (no Echo/Fire TV, no cameras
  yet). The Cameras panel was deliberately kept rather than removed, since
  cameras may be added later - it will populate automatically the moment a
  matching client appears, no dashboard change needed.

## Radio-quality panels and the misclassified-AP nuance
Most panels here rely on genuinely wireless clients (radio signal/noise/CCQ
etc. are meaningless for wired clients, and correctly show no series for
them). This dashboard DOES have real data for this household's wireless
clients - confirmed via `ap_name` being populated on ~1300 metric series and
real per-client radio protocol values (ac/ax) in the raw unpoller export.
Do not assume a "no data" WiFi panel here means broken wireless monitoring -
check whether it's a genuinely radio-specific metric (expected to be data-ful)
vs. a device-category filter (expected empty if no matching device exists)
before treating either as a bug.

## Where the actual dashboard JSON lives
Not provisioned via Grafana's file-provider (imported via the UI instead).
The patched JSON is checked into this repo at
`grafana/dashboards/11315-client-insights-patched.json` for reference and
re-import if ever needed - re-importing it is a manual step, not automatic
on deploy.
