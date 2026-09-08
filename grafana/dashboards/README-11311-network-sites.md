# UniFi-Poller: Network Sites (grafana.com ID 11311)

## Source
https://grafana.com/grafana/dashboards/11311/ - "Updated for Poller v2.0"
community dashboard, unmodified structure aside from the fixes below.

## What it's for
Site-level overview: device counts (USW/UAP/USG/Stations), uplink health
(latency, speed test), aggregate data transfer split by subsystem
(wan/lan/wlan/www/vpn), and client counts over time. This is the
"is my network healthy at a glance" dashboard, not per-device or per-client
detail (see the other two).

## Fixes applied (2026-09-09)
- `singlestat` panels (5) converted to `stat` - `singlestat` was removed from
  Grafana core years ago; on Grafana 13.2.1 these threw "an error occurred
  with the plugin". Value/threshold logic was carried over on a best-effort
  basis; sparkline/exact coloring may not match the original.
- Datasource references (`${DS_PROMETHEUS}`, plus a `${DS_UNIFI_POLLER}`
  token that appears in this dashboard family but is never declared as an
  input - a real bug in the original dashboard, not something introduced
  here) were hardcoded to a concrete object:
  `{"type": "prometheus", "uid": "prometheus"}`.

## Not portable as-is
That hardcoded `uid: "prometheus"` only works because this repo's
`grafana/provisioning/datasources/prometheus.yml` pins the Prometheus
datasource to exactly that UID. Importing this dashboard into a different
Grafana instance without a datasource of that same UID will silently
reproduce the "no data" bug this fix was meant to solve - check/match the
UID first.

## Known "no data" panels (expected, not bugs)
- **Data Transfer by Category** - needs unpoller's DPI export enabled
  (`UP_UNIFI_CONTROLLER_0_SAVE_DPI=true` in `unpoller/docker-compose.yml`,
  added 2026-09-09). Confirmed working after that fix.

## Template variables
- `Controller` - which unpoller-polled controller ("source" label) to show;
  `$__all` by default (all controllers, only one exists here).
- `Site` - which UniFi site; `Default (default)` is this household's only
  site.
- `Subsystem` - filters some panels to wan/lan/wlan/www/vpn.

## Where the actual dashboard JSON lives
Not provisioned via Grafana's file-provider (imported via the UI instead -
see `grafana/provisioning/dashboards/default.yml`'s own comment), but the
patched JSON that fixed the issues above IS checked into this repo at
`grafana/dashboards/11311-network-sites-patched.json`, for reference and
re-import if the live dashboard is ever lost or needs re-applying. This is a
reference copy only - re-importing it does not automatically happen on
deploy, unlike `provisioning/`'s contents (and even those need a manual host
sync, see `.claude/rules/portainer-instance.md` / project memory on the
2026-09-08/09 Grafana provisioning incident for why).
