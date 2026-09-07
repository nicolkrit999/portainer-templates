# dnsmasq-tailnet

The Tailscale-facing sibling of `../dnsmasq/` - same image, same `network_mode: host` pattern, same overall purpose (split-DNS for `*.${DNS_WILDCARD_DOMAIN}`), but answering tailnet-connected clients instead of LAN ones, with a different fix underneath.

## Why it's a separate instance, not a rule added to the LAN one

Root cause (confirmed via SSH diagnosis, 2026-08-22): a Tailscale-connected device gets DNS answers pointing at the NAS's LAN IP, same as everyone else - but the NAS's own host network stack can't hairpin back to its own LAN IP on Traefik's published port (`curl` to the LAN IP from the NAS itself times out; `curl` to `127.0.0.1` with the same Host header works fine). Tailscale's subnet-router forwarding hits this exact same hairpin limitation relaying traffic back out to the LAN IP. Traefik itself isn't the problem - its entrypoints would happily accept a connection arriving directly on the tailnet interface.

**Fix**: answer DNS with the NAS's own *tailnet* IP instead of its LAN IP for Tailscale-connected clients. Traffic then arrives directly on `tailscale0` with no hairpin hop at all. A genuinely separate dnsmasq instance (not a change to the LAN-facing one) so it can bind specifically to the tailnet IP without touching or depending on the original - both already run `network_mode: host`, so a second instance is safe.

## Admin-gated hostname override (the part that matters most operationally)

The simple "every hostname resolves to the same tailnet IP" description above no longer holds for admin-gated hostnames. A second, independent Tailscale identity (`tailscale-admin`, now living in `../tailscale-admin_traefik-tailnet-forwarder/`) fronts those via its own forwarder + Traefik entrypoint - see that stack's README for the full mechanism. Those hostnames need their own more-specific `--address=` rule pointing at `${TAILSCALE_ADMIN_IP}` instead of the general wildcard's `${TAILNET_IP}`.

**In practice this override list covers almost every service, not a small special case** - `adding-compose-services` gives every new private-tier service a `tailnet-admin` router by default, so virtually every new service needs its hostname added to this override list too, or it silently falls through to the wildcard and never reaches Traefik's `tailnet-admin` entrypoint correctly (confirmed real bug, 2026-09-02).

dnsmasq's `--address` syntax natively supports multiple domains in one directive (`--address=/<domain>[/<domain>...]/[<ipaddr>]`) - this repo keeps every admin-gated hostname in one shared rule rather than one rule per hostname, for a single easy-to-audit place as the list grows.

Same `--server=/domain/ip` exceptions as the LAN-facing sibling for Cloudflare-Tunnel-only hostnames (`gitea-ssh`, `ssh`) - keep both files in sync if another such exception is ever needed.

`--log-queries` is on permanently (added 2026-08-23 to diagnose a remote tailnet client's queries never reaching this interface at all) - one line per query per tailnet client, acceptable at this household's scale, avoids a redeploy-just-to-debug round trip.

## Environment variables

| Variable | Purpose |
|---|---|
| `DNS_WILDCARD_DOMAIN` | Same domain as the LAN-facing sibling. |
| `TAILNET_IP` | The NAS's own primary-node tailnet IP - the wildcard answer for non-admin-gated hostnames. |
| `TAILSCALE_ADMIN_IP` | `tailscale-admin`'s own tailnet IP (see `../tailscale-admin_traefik-tailnet-forwarder/README.md`) - the override target for admin-gated hostnames. |

## Adding a new service

Add its hostname to the admin-gated `--address=` override rule here (almost always required, see above) AND to `../dnsmasq/`'s private-tier override list. Literal hostname segments in the override list match each service's own `${..._SUBDOMAIN}` value, not necessarily its directory name - two confirmed historical mismatches: `claude` (not `holyclaude`) and `soketi-coolify` (not `coolify-realtime`). Check the live env before assuming a hostname matches its folder name.
