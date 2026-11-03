---
name: grafana-service
description: Grafana compose - UID 472 and the grafana-init chown, provisioning layout and why repo edits do not reach the container, Discord contact point rendering, monitoring-net
metadata:
  type: project
---

`grafana/docker-compose.yml` (added 2026-09-02): standard private + `-tailnet` router pair, bare `tls`, no DNS step. Networks: `traefik-proxy` and the shared external `monitoring-net` (also used by `prometheus` and `unpoller`, see [[monitoring-stack-service]]). Image `grafana/grafana-enterprise` (version pinned in the compose).

- **No PUID/PGID:** the image hardcodes UID 472 and ignores those vars. `grafana-init` (alpine, root) runs on every deploy: `chown -R 472:472` + `chmod -R 0700` on `${VOLUME_CONFIG}/grafana`, so no manual chown is needed. The explicit `chmod` is required because the NAS volume's `ugacl` layer overrides POSIX bits until reset.
- **Bind mounts are host copies:** the container reads `${VOLUME_CONFIG}/grafana/provisioning`, NOT the repo's `grafana/provisioning/`. Editing the repo files changes nothing until the host copy is updated by hand; `docker restart grafana` is the safe way to pick up new provisioning files.
- **Discord contact point:** Grafana's alerting provisioning does not interpolate env vars reliably (grafana/grafana#54984, #56437). The repo ships `contactpoints.yml.template` with a `__DISCORD_ALERT_WEBHOOK_URL__` placeholder and `grafana-init` renders `contactpoints.yml` with `sed`. The rendered file is created as root, so the init command chowns it to 472 again (a chmod alone left it unreadable). `DISCORD_ALERT_WEBHOOK_URL` is a real secret.
- **Datasource and dashboards:** `provisioning/datasources/prometheus.yml` points at `http://prometheus:9090` (default). Vanilla file provisioning cannot fetch dashboards by grafana.com ID; the three unpoller dashboards (11311, 11313, 11315) are committed as `*-patched.json` under `grafana/dashboards/` and must be copied to `${VOLUME_CONFIG}/grafana/provisioning/dashboards/json/` on the host. Alert rules live in `provisioning/alerting/rules.yml`.
- Env needed in Portainer: `TZ`, `VOLUME_CONFIG`, `ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_SUBDOMAIN`, `DOMAIN`, `DISCORD_ALERT_WEBHOOK_URL`, `TRAEFIK_ENTRYPOINT_3`, `TRAEFIK_ENTRYPOINT_7`.

**Why:** the UID/ACL and host-copy behaviour cost several debugging rounds on 2026-09-02/09.
**How to apply:** when touching Grafana provisioning, edit the repo file AND say that the host copy must be updated; keep the init command's chown/chmod order.
