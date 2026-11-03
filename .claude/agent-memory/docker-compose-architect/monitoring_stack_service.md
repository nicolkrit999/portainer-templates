---
name: monitoring-stack-service
description: unpoller + prometheus internal-only backing services for grafana - shared monitoring-net, prometheus UID 65534 init chown, unpoller InfluxDB/healthcheck lesson
metadata:
  type: project
---

Internal-only backing services for [[grafana-service]] (added 2026-09-02): no Traefik labels, no hostname, no published ports. Reached only over the shared external network `monitoring_network` (`name: monitoring-net`, `external: true`), declared identically in the `unpoller`, `prometheus` and `grafana` stacks. This shared cross-stack network predates the per-stack `<stack>-backend` /28 convention and has no explicit subnet (not in the subnet registry: UNVERIFIED). A new exporter or alertmanager just attaches to it; no router or DNS work is needed unless it needs its own hostname.

- **`unpoller`** (`ghcr.io/unpoller/unpoller`, v5.2.2): polls the UniFi controller, Prometheus metrics on `:9130`, `cpus: 4.0`. Needs a local READ-ONLY UniFi API user created by hand in the UniFi console before `UNIFI_POLLER_USER/PASSWORD` mean anything; flag this every time. `UP_UNIFI_CONTROLLER_0_SAVE_DPI: "true"` is a poller-side flag, required in addition to controller-side Traffic Identification, or `unpoller_site_dpi_*` stays empty. The image HAS a built-in healthcheck (`unpoller --health`, no shell needed) that fails if ANY enabled output is unreachable; InfluxDB output is on by default with nothing listening, which kept the container unhealthy for weeks until `UP_INFLUXDB_DISABLE: "true"` (2026-11-04). Disable unused outputs rather than looking for another healthcheck.
- **`prometheus`** (`prom/prometheus`, v3.14.0 pinned in the compose): no PUID/PGID, the image hardcodes UID/GID 65534 (same pattern as Grafana's 472). `prometheus-init` (alpine, root) chowns `${VOLUME_CONFIG}/prometheus` to 65534:65534 on every deploy, so no manual chown. The scrape config is read from the HOST copy `${VOLUME_CONFIG}/prometheus/prometheus.yml:ro`, not from the repo's `prometheus/prometheus.yml`: repo edits do not reach the container until the host copy is updated. Retention 30d.

**Why:** the healthcheck and host-copy behaviour are invisible in the compose file and cost weeks/debugging rounds.
**How to apply:** when touching these stacks, check unpoller's enabled outputs against reachable targets, and remind the user to copy changed config files to the host path.
