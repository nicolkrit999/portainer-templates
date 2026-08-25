# Memory Index

- [n8n service](n8n_service.md) - init-container chown pattern for UID/GID mismatch crash loops; depends_on condition nuances
- [sparkyfitness service](sparkyfitness_service.md) - 3-service compose, verified v0.17.3 pins, volume paths, no-guessed-healthcheck rationale
- [dnsmasq service](dnsmasq_service.md) - stopgap DNS, host networking, no Cloudflare/Traefik, restart:"no"; .env.example Write-tool deny-rule workaround; includes dnsmasq-tailnet sibling for Tailscale hairpin-NAT bug (2026-08-22)
- [traefik-private-forwarder service](traefik_private_forwarder_service.md) - socat TCP-passthrough sidecar, macvlan+traefik-proxy only, no Cloudflare/self-router, restart:unless-stopped
- [portainer service](portainer_service.md) - migrated from bare docker run, exact live /data path preserved, restart:always exception, docker.sock rw hardcoded
- [traefik-tailnet-forwarder service](traefik_tailnet_forwarder_service.md) - HAProxy sidecar fixing Tailscale-IP-rewrite bug; now joins tailscale-admin's namespace via network_mode:service:X (host-mode reverted, conflicted with Traefik's own wildcard bind)
- [tailscale-admin service](tailscale_admin_service.md) - second Tailscale identity, non-host sidecar pattern (devices: only for tun, no host volume mount), ip_unprivileged_port_start sysctl fix for the forwarder sharing its namespace (2026-08-22)
- [SAN-bundle groups](san_bundle_groups.md) - LE rate-limit fix, 6-group per-router tls.domains rollout; anchors/members/mechanism/.env.example workaround (2026-08-22)
- [hi-events service](hi_events_service.md) - manual-NAS-to-git migration; hi_events (underscore) vs hi-events (dash) folder mismatch, eventi hostname override, joined productivity-creative SAN group (2026-08-24)
- [openspeedtest service](openspeedtest_service.md) - 4-tier Traefik, NO tailnet-admin router (multi-tier services don't get one), utilities SAN member (2026-08-25)
