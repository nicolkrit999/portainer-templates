# Memory Index

Lessons for creating and modifying compose files under the current access model (LAN, tailnet, public; see `.claude/rules/networking.md`). Facts about what a stack looks like today live in its compose file and README, not here.

## Core and infrastructure stacks
- [dnsmasq service](dnsmasq_service.md) - wildcard-only resolvers plus the gitea-ssh override, host networking, bind options, why two instances, `.env.example` write workaround
- [traefik-private-forwarder service](traefik_private_forwarder_service.md) - socat passthrough on a macvlan LAN IP to entrypoint 3; owns the one live macvlan network
- [traefik-public service](traefik_public_service.md) - design choices and Traefik 3.7 / Docker facts (egress guard, holder pattern, header handling); the README is authoritative
- [tailscale-admin + traefik-tailnet-forwarder](tailscale_admin_traefik_tailnet_forwarder_service.md) - build lessons for the tailnet-admin gateway; topology lives in `core-infra-topology.md`
- [tailscale-adguard service](tailscale_adguard_service.md) - third Tailscale identity for AdGuard, dnsdist relay sharing its namespace
- [portainer service](portainer_service.md) - reference-copy-only compose (not git-tracked), live `/data` path, ports 9000/9444
- [Public proxy batch lessons](reference_public-proxy-batch-lessons.md) - ip_range+gateway quirk, Traefik path-block limits, CodeIgniter `?/` bypass, local test recipe

## Per-application lessons
- [Batch 2 public wiring (opencloud, trek, hi-events)](batch2-opencloud-trek-hi-events-public-wiring.md) - proxy-header ownership, root-entrypoint TREK, auto-migrating Hi.Events
- [Easy!Appointments public wiring](easy-appointments-public-wiring.md) - release-zip gaps, PROXY_IPS, PHP2Shell, CodeIgniter query-route bypass, test recipe
- [hi-events stack](hi_events_service.md) - underscore vs dash folder naming, eventi hostname override, permission-init containers
- [Gokapi file requests are a user permission](gokapi-file-requests-are-a-user-permission.md) - no env switch; "0" guest limits mean unlimited
- [PrivateBin image ignores PHP size env](privatebin-image-ignores-php-size-env.md) - hard 15M caps, only `conf.php` sizelimit matters
- [PrivateBin lessons](privatebin_service.md) - `/run` tmpfs needs exec, latest = nightly, conf.php behaviour
- [immich backend isolation](immich_backend_isolation.md) - internal backend + ML egress network, multi-network DNS precedence, redeploy order
- [n8n service](n8n_service.md) - init-container ownership-fix pattern, depends_on conditions, backend network
- [sparkyfitness service](sparkyfitness_service.md) - db-init chown, Postgres 18 mount quirk, no server healthcheck
- [grafana service](grafana_service.md) - UID 472 and grafana-init chown, provisioning layout, Discord contact point rendering
- [monitoring stack (unpoller + prometheus)](monitoring_stack_service.md) - shared monitoring-net, prometheus init chown, unpoller InfluxDB/healthcheck lesson
