# dnsmasq-tailnet

The Tailscale-facing sibling of `../dnsmasq/` - same image, same `network_mode: host` pattern, same overall purpose (split-DNS for `*.${DNS_WILDCARD_DOMAIN}`), but answering tailnet-connected clients instead of LAN ones, with a different fix underneath.

## Why it's a separate instance, not a rule added to the LAN one

Root cause (confirmed via SSH diagnosis, 2026-08-22): a Tailscale-connected device gets DNS answers pointing at the NAS's LAN IP, same as everyone else - but the NAS's own host network stack can't hairpin back to its own LAN IP on Traefik's published port (`curl` to the LAN IP from the NAS itself times out; `curl` to `127.0.0.1` with the same Host header works fine). Tailscale's subnet-router forwarding hits this exact same hairpin limitation relaying traffic back out to the LAN IP. Traefik itself isn't the problem - its entrypoints would happily accept a connection arriving directly on the tailnet interface.

**Fix**: answer DNS with the NAS's own *tailnet* IP instead of its LAN IP for Tailscale-connected clients. Traffic then arrives directly on `tailscale0` with no hairpin hop at all. A genuinely separate dnsmasq instance (not a change to the LAN-facing one) so it can bind specifically to the tailnet IP without touching or depending on the original - both already run `network_mode: host`, so a second instance is safe.

## The wildcard and the `gitea-ssh` override

Tailnet access to the web services runs through the tailnet-admin gateway: a second, independent Tailscale identity (`tailscale-admin`, living in `../tailscale-admin_traefik-tailnet-forwarder/`) fronts Traefik's `tailnet-admin` entrypoint behind an allowlist of the owner's devices - see that stack's README for the full mechanism. So the single wildcard rule answers every `*.${DNS_WILDCARD_DOMAIN}` hostname (and the bare domain) with `${TAILSCALE_ADMIN_IP}`, the gateway's tailnet IP. There is no per-hostname list any more: a new service needs no DNS change.

One more-specific override, `gitea-ssh.${DNS_WILDCARD_DOMAIN}`, answers with `${TAILNET_IP}` (the NAS's own tailnet IP). Git over SSH is not HTTP and bypasses the gateway: Gitea publishes it on the NAS as host port 2222, so the name must reach the NAS directly. Clients need `Port 2222` in their ssh config. It is private only and never forwarded by the gateway. dnsmasq prefers the most specific match, so the override coexists with the wildcard.

`--log-queries` is on permanently (added 2026-08-23 to diagnose a remote tailnet client's queries never reaching this interface at all) - one line per query per tailnet client, acceptable at this household's scale, avoids a redeploy-just-to-debug round trip.

## Environment variables

| Variable | Purpose |
|---|---|
| `DNS_WILDCARD_DOMAIN` | Same domain as the LAN-facing sibling. |
| `TAILNET_IP` | The NAS's own primary-node tailnet IP - the address this resolver listens on, and the answer for `gitea-ssh`. |
| `TAILSCALE_ADMIN_IP` | `tailscale-admin`'s own tailnet IP (see `../tailscale-admin_traefik-tailnet-forwarder/README.md`) - the wildcard answer for every other hostname. |

## Adding a new service

Nothing to do here: the wildcard already answers the new hostname. Only a name that must NOT go through the gateway (a non-HTTP service published on the NAS itself, like `gitea-ssh`) needs its own more-specific `--address=` line, here and in `../dnsmasq/`.
