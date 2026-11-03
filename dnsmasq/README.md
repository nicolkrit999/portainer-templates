# dnsmasq

LAN-facing split-DNS for the household. Answers every `*.${DNS_WILDCARD_DOMAIN}` query from LAN devices with the private forwarder's IP, so names resolve to the private Traefik entrypoint at home.

## What it does

Runs `network_mode: host` (binds directly to the NAS's existing LAN IP - deliberately not macvlan, which went stale for a sibling service before) and answers DNS via dnsmasq's `--address=/domain/ip` directive:

- One wildcard rule points every `*.${DNS_WILDCARD_DOMAIN}` hostname (and the bare domain) at `${DNS_PRIVATE_IP}` - `../traefik-private-forwarder/`'s dedicated macvlan LAN IP, which forwards to Traefik's `private` entrypoint. There is no per-hostname list any more: a new service needs no DNS change.
- One more-specific override, `gitea-ssh.${DNS_WILDCARD_DOMAIN}`, points at `${DNS_TARGET_IP}` (the NAS's own LAN IP) instead. Git over SSH is not HTTP: Gitea publishes it on the NAS as host port 2222, so the name must reach the NAS itself rather than the Traefik forwarder. dnsmasq prefers the most specific match, so the override coexists with the wildcard. Clients need `Port 2222` in their ssh config (`Host gitea-ssh.<domain>`). It is private only and never forwarded by the gateway.
- `${DNS_TARGET_IP}` is also the address this resolver listens on (together with `${MACVLAN_SHIM_IP}`).
- `--filter-AAAA`/`--filter-rr=HTTPS`/`--filter-rr=SVCB` - this resolver only ever answers for its one domain, so filtering these record types globally is safe and prevents IPv6/HTTPS-record queries leaking the real public records (the public CNAMEs at Cloudflare) for a domain that's supposed to be locally overridden.

## Why it exists (permanent infrastructure, not a stopgap)

UniFi's gateway UI doesn't support wildcard DNS natively. The long-term plan is either migrating this ruleset into the gateway's own internal dnsmasq, or having UniFi's "Forward Domain" feature delegate the domain to this container - either way, this container itself isn't going away. `restart: always` because split-DNS for the whole household depends on it now.

Deliberately not attached to `traefik-proxy` - this is a raw DNS (port 53) service, not HTTP.

## Sibling

`../dnsmasq-tailnet/` is the Tailscale-facing equivalent, answering the same domain for tailnet-connected clients with a different (tailnet, not LAN) target IP - see that stack's own README.

## Environment variables

| Variable | Purpose |
|---|---|
| `DNS_WILDCARD_DOMAIN` | The domain this resolver answers for (matches the household's real domain). |
| `DNS_TARGET_IP` | The NAS's own LAN IP - the address this resolver listens on, and the answer for `gitea-ssh`. |
| `DNS_PRIVATE_IP` | `../traefik-private-forwarder/`'s dedicated macvlan LAN IP - the wildcard answer for every other hostname. |
| `MACVLAN_SHIM_IP` | The `../macvlan-host-shim/` IP, bound as a second listen address (must match that stack's value). |

## Adding a new service

Nothing to do here: the wildcard already answers the new hostname. Only a name that must NOT go to Traefik (a non-HTTP service published on the NAS itself, like `gitea-ssh`) needs its own more-specific `--address=` line, here and in `../dnsmasq-tailnet/`.
