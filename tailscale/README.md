# tailscale

The household's **primary** Tailscale identity - puts this NAS on the tailnet and advertises the LAN subnet route so other tailnet devices can reach LAN-only things through it.

## Why `network_mode: host` + `privileged: true`

Tailscale needs direct control of a TUN device and host-level routing to act as a subnet router. This is also exactly why nothing else can bind a host-published port directly on this node's tailnet IP: host mode puts `tailscale0` in the same network namespace as every other host-published port on this machine, including Traefik's own wildcard bind for the family entrypoint. This constraint is the reason `../tailscale-admin_traefik-tailnet-forwarder/` exists as a *second*, non-host-mode identity instead of trying to share this one - see that stack's README for the full story.

## Environment variables

| Variable | Purpose |
|---|---|
| `TAILSCALE_ADVERTISE_ROUTES` | CIDR(s) this node advertises as reachable via subnet routing (the LAN subnet). |
| `DOCKER_CONFIG_DIR` | Base path for this node's persistent Tailscale state. |

## Related stacks

This repo has **three independent Tailscale identities**, each solving a different problem - don't confuse them:

| Stack | Purpose | Networking |
|---|---|---|
| `tailscale` (this one) | Primary node, LAN subnet router | `network_mode: host` |
| `../tailscale-admin_traefik-tailnet-forwarder/` | Fronts admin-gated (`tailnet-admin`) Traefik routes with PROXY-protocol source-IP preservation | Ordinary Docker networking, own namespace |
| `../tailscale-adguard/` | Gives AdGuard its own tailnet IP so devices using a Tailscale exit node still resolve DNS through AdGuard | Ordinary Docker networking, own namespace |

Read `.claude/rules/core-infra-topology.md` before any structural change here (network mode, image, capabilities) - this is core infra with repo-wide blast radius.
