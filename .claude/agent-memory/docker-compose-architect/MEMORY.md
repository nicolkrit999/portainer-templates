# Memory Index

- [n8n service](n8n_service.md) - init-container chown pattern for UID/GID mismatch crash loops; depends_on condition nuances
- [sparkyfitness service](sparkyfitness_service.md) - 3-service compose, verified v0.17.3 pins, volume paths, no-guessed-healthcheck rationale
- [dnsmasq service](dnsmasq_service.md) - stopgap DNS, host networking, no Cloudflare/Traefik, restart:"no"; .env.example Write-tool deny-rule workaround; includes dnsmasq-tailnet sibling for Tailscale hairpin-NAT bug (2026-08-22)
- [traefik-private-forwarder service](traefik_private_forwarder_service.md) - socat TCP-passthrough sidecar, macvlan+traefik-proxy only, no Cloudflare/self-router, restart:unless-stopped
- [portainer service](portainer_service.md) - migrated from bare docker run, exact live /data path preserved, restart:always exception, docker.sock rw hardcoded
- [traefik-tailnet-forwarder service](traefik_tailnet_forwarder_service.md) - HAProxy host-networked sidecar fixing Tailscale-IP-rewrite bug; Traefik entrypoint 7 + static IP + proxyProtocol trustedIPs; Step 0 router moved (2026-08-22)
