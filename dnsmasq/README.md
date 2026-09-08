# dnsmasq

LAN-facing split-DNS for the household. Answers `*.${DNS_WILDCARD_DOMAIN}` queries from LAN/guest/friends devices with the right IP for each access tier, instead of one universal answer.

## What it does

Runs `network_mode: host` (binds directly to the NAS's existing LAN IP - deliberately not macvlan, which went stale for a sibling service before) and answers DNS via dnsmasq's `--address=/domain/ip` directive:

- A general wildcard rule points every `*.${DNS_WILDCARD_DOMAIN}` hostname at `${DNS_TARGET_IP}` (the NAS's own LAN IP, reaching Traefik's family-tier wildcard bind directly).
- A more-specific override list (dozens of individual `--address=` entries, one per private-tier-only hostname) points those hostnames at `${DNS_PRIVATE_IP}` instead - `../traefik-private-forwarder/`'s dedicated macvlan LAN IP. dnsmasq resolves the most-specific match automatically (standard, documented behavior - no extra flags needed), so this coexists safely with the wildcard rule; every hostname NOT in the override list just falls through to the wildcard, unaffected.
- `--server=/domain/ip` exceptions for hostnames deliberately Cloudflare-Tunnel-only and never migrated to Traefik (`gitea-ssh`, `ssh` - Cloudflare Access SSH applications) - without these, the wildcard rule above would intercept them too and point LAN clients at this NAS instead of letting them resolve via real public DNS to Cloudflare's edge. Confirmed broken this way once (2026-08-23); check the Cloudflare Tunnel dashboard's public hostname list (not this repo) before adding another such exception.
- `--filter-AAAA`/`--filter-rr=HTTPS`/`--filter-rr=SVCB` - this resolver only ever answers for its one domain, so filtering these record types globally is safe and prevents IPv6/HTTPS-record queries leaking Cloudflare's real public edge for a domain that's supposed to be locally overridden.

## Why it exists (permanent infrastructure, not a stopgap)

UniFi's gateway UI doesn't support wildcard DNS natively. The long-term plan is either migrating this ruleset into the gateway's own internal dnsmasq, or having UniFi's "Forward Domain" feature delegate the domain to this container - either way, this container itself isn't going away. `restart: always` because split-DNS for the whole household depends on it now.

Deliberately not attached to `cloudflare-web` or `traefik-proxy` - this is a raw DNS (port 53) service, not HTTP.

## Sibling

`../dnsmasq-tailnet/` is the Tailscale-facing equivalent, answering the same domain for tailnet-connected clients with a different (tailnet, not LAN) target IP - see that stack's own README.

## Environment variables

| Variable | Purpose |
|---|---|
| `DNS_WILDCARD_DOMAIN` | The domain this resolver answers for (matches the household's real domain). |
| `DNS_TARGET_IP` | The NAS's own LAN IP - the wildcard answer for everything except private-tier overrides. |
| `DNS_PRIVATE_IP` | `../traefik-private-forwarder/`'s dedicated macvlan LAN IP - the override target for private-tier-only hostnames. |

## Adding a new service

If the new service is private-tier-only (the default for new services, per `.claude/rules/networking.md`), add its hostname to the `--address=` override list here too, or it silently falls through to the wildcard and never reaches the private forwarder correctly. See `adding-compose-services` skill's DNS step - this file and `../dnsmasq-tailnet/` almost always need the same new hostname added together.
