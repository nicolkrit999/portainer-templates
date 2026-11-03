# Gotcha: CPU scheduling priority pattern + rollback point

A repo-wide CPU scheduling priority pass landed 2026-09-07 across all
then-deployed stacks (43 at the time). When adding or
reviewing a service's resource settings, follow this pattern:

- `cpu_shares: 4096` - critical infra (adguard, tailscale-adguard,
  macvlan-host-shim, traefik, dnsmasq, pocket-id, etc.).
- `cpu_shares: 2048` - daily-use apps.
- Hard `cpus:` ceilings - known CPU hogs (immich-machine-learning,
  jellyfin, duplicati, qbit-torrent, tugtainer, unpoller, harborguard,
  stirling-pdf, coolify, attic).
- No ad-hoc `mem_limit`/`cpu_shares` blocks on low-resource tools that
  don't need them - remove stale ones rather than leaving them.

**Rollback point:** git tag `v4.0.9-pre-performance-tweaks` (points at `99c2f3c`,
the commit just before the pass). The branch history was rewritten since, so the
pre-pass hashes quoted in older notes (`4f55e75`, `7fcf6d9`, `8566e3d`) are not
reachable from `develop`; use the tag, not those hashes. If this tuning is ever
suspected of causing a scheduling/starvation problem, the tag is a clean revert
target for the whole change.

**Stale IDs:** old notes mention stacks 336 and 337; they are one merged stack now
(`tailscale-admin_traefik-tailnet-forwarder`, id 350, see
`.claude/rules/core-infra-topology.md`), and both services in it keep
`cpu_shares: 4096`.
