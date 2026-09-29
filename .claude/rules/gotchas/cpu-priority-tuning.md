# Gotcha: CPU scheduling priority pattern + rollback point

A repo-wide CPU scheduling priority pass landed 2026-09-07 (commits
`7fcf6d9` + `8566e3d`) across all 43 deployed stacks. When adding or
reviewing a service's resource settings, follow this pattern:

- `cpu_shares: 4096` - critical infra (adguard, tailscale-adguard,
  macvlan-host-shim, traefik, dnsmasq, pocket-id, etc.).
- `cpu_shares: 2048` - daily-use apps.
- Hard `cpus:` ceilings - known CPU hogs (immich-machine-learning,
  jellyfin, duplicati, qbit-torrent, tugtainer, unpoller, harborguard,
  stirling-pdf, coolify, attic).
- No ad-hoc `mem_limit`/`cpu_shares` blocks on low-resource tools that
  don't need them - remove stale ones rather than leaving them.

**Rollback point:** git tag `v4.0.9-pre-performance-tweaks`, on the commit
immediately before this pass (`4f55e75`). If this tuning pass is ever
suspected of causing a scheduling/starvation problem, that tag is a clean
revert target for the whole change, not just individual files.

**Stale-ID note (historical, only relevant if digging through old
records):** an earlier working checklist referenced stack IDs 336
(`traefik-tailnet-forwarder`) and 337 (`tailscale-admin`) as separate
stacks that both got `cpu_shares: 4096`. As of 2026-09-08 these are ONE
merged stack (`tailscale-admin_traefik-tailnet-forwarder`, id 350) - see
`.claude/rules/core-infra-topology.md`. The `cpu_shares: 4096` setting is
still present on both services within the merged stack; don't go looking
for a live stack 336 or 337.
