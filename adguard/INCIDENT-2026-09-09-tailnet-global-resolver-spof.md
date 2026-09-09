# Tailnet global-resolver single point of failure - root cause, fix, verification

## The problem

2026-09-09 ~16:50-17:01 CEST: a household member's `nixos-desktop` lost
general internet connectivity while connected to Tailscale (felt like "no
internet", not "DNS is slow"). Disabling Tailscale entirely restored it
immediately; re-enabling broke it again. Investigated live across three
cooperating Claude sessions: this repo (NAS/infra side), a UniFi/network-side
session, and a session with shell access on the affected desktop itself.

## Root cause - confirmed, not theoretical

The tailnet's Tailscale admin console (DNS settings) had exactly **one**
Global Nameserver: `100.72.14.7` (the `adguard-dns` Tailscale identity, see
"Surviving an active Tailscale exit node" below), with **Override Local
DNS** enabled. That means every tailnet device, whenever Tailscale is
active, routes 100% of its DNS through that single node - `Domains: ~.`
always wins the DNS race over any local/LAN resolver config on the client
(confirmed directly: the affected desktop's own `resolved.nix` settings,
including its own `FallbackDNS`, never got a chance to matter while
Tailscale was up - tailscaled overrides the system resolver wholesale).

**This makes `100.72.14.7` a tailnet-wide DNS single point of failure by
construction.** Any transient failure reaching that one node - not a crash,
just an unreachable/degraded network path - takes down DNS resolution for
every tailnet device simultaneously, and because raw IP routing keeps
working, it presents as "the internet is completely down" rather than "DNS
is broken."

### What was NOT the cause (ruled out with real evidence, don't re-litigate)

- **Not AdGuard itself down/crashing.** `adguard` container: `RestartCount: 0`,
  continuously healthy, zero errors logged in the exact 16:51-16:53 incident
  window (checked directly against real UTC timestamps).
- **Not the `dnsdist` relay (`tailscale-adguard-dns-relay`) failing.**
  Uninterrupted 30s healthcheck cycles, zero gaps, zero errors, 16:48-16:56
  continuous.
- **Not Tailscale grants/ACLs.** The live grants policy gives the desktop's
  owning account (`autogroup:admin`) unrestricted access - checked directly,
  and confirmed empirically (zero packets from the desktop's tailnet IP ever
  appeared in `tailscale-adguard`'s own drop log, which DOES show constant,
  unrelated, expected drops for a different device - see below).
- **Not the Mullvad exit node itself.** A live repro (scripted exit-node
  off -> 8s -> on, with a packet capture running throughout) produced **zero**
  unanswered DNS queries - every query answered in under ~1ms, including
  during the exit-node-off gap.
- **Not the desktop's `resolved.nix` config** (`DNSSEC=false`, `Domains=~.`,
  `FallbackDNS`, opportunistic DoT) - all confirmed non-issues on their own
  merits, and moot anyway while Tailscale is up (see above).

### What the real failure looked like

`tailscale-adguard`'s own magicsock log (the Tailscale identity fronting
`100.72.14.7`) shows the desktop's peer connection (`disco` short-code
`[1mBgw]`, LAN IP `192.168.1.211:41641` - matches the desktop's own
`tailscale ping`/`netcheck` output exactly) repeatedly re-negotiating its
path three times in under 90 seconds, then a full **disco key change**
(consistent with a local tailscaled restart/reinit) a few minutes later.
The desktop's own `journalctl -u tailscaled` shows the DNS-forward-failing
health check flapping - interleaved `ok`/`error` lines, not a clean hard
failure - for the same window. Read together: the transport path
(magicsock/DERP) between this specific client and `100.72.14.7` was
unstable during the incident; the resolver and relay themselves were never
unreachable from the NAS's own perspective. **A single global nameserver
with no fallback turns any client-specific or transient transport hiccup
into a full DNS outage for that client**, which is the actual mechanism -
distinct from (and less dramatic than) "AdGuard went down."

## The fix - applied 2026-09-09, Tailscale admin console only

DNS -> Global nameservers: `100.72.14.7` (AdGuard, ad-blocking, kept as
**first/preferred**) with four public Quad9 fallbacks added beneath it
(`9.9.9.9`, `149.112.112.112`, `2620:fe::fe`, `2620:fe::9` - Tailscale adds
a provider's full address set atomically as one entry). Tailscale queries
all configured global nameservers in parallel and takes the fastest
response, so this is not strict fallback-on-failure ordering - it's a race,
and **the deliberate trade-off is: ad-blocking can leak when Quad9 answers
first (e.g. during any future AdGuard hiccup), in exchange for DNS/internet
access never fully breaking again.** No compose or dashboard change - this
lives entirely in Tailscale's own admin console, not in this repo.

**Why the fallback couldn't be a second AdGuard-style resolver at another
`100.x` tailnet address**: any resolver reachable only via the tailnet rides
the same magicsock/DERP transport that was the actual failure point here -
a second `100.x` address doesn't add real path diversity. The fallback
needed to be reachable independently of tailnet transport health, hence
public IPs.

**Global override was deliberately kept, not narrowed to split-DNS-only.**
A tempting-looking alternative fix is to stop overriding local DNS globally
and only use AdGuard for the household's own domain (split-DNS) - avoids
the SPOF entirely, since off-domain queries would just use the client's own
local/default resolver. **Rejected for this household**: the internal
domain is 100% self-hosted, ad-free services - AdGuard's entire value is
blocking ads/trackers on *everything else*. Narrowing scope to
split-DNS-only would have removed ad-blocking coverage precisely where it's
needed (general browsing, especially on mobile/remote devices using
Tailscale) while keeping it only where it's not needed. If this bites again,
don't re-propose "restrict to split-DNS" as the fix.

## Open item - real, unresolved, and NOT this repo's DNS-server config

During the incident, `drive-api.proton.me` resolved to a local Traefik
instance (self-signed `...traefik.default` cert) on the affected device.
**Checked and ruled out as an AdGuard/dnsmasq server-side bug**: AdGuard's
`rewrites:` list is empty, its conditional-forward upstream config only
matches `nicolkrit.ch` (`'[/nicolkrit.ch/]192.168.1.95'` - the
`macvlan-host-shim` IP, see the sibling README section below), and both
`dnsmasq` and `dnsmasq-tailnet`'s `--address=` wildcard rules only ever
match `${DNS_WILDCARD_DOMAIN}` (this household's own domain) and its
explicit subdomains - nothing in any of these three configs could produce a
match for `proton.me`. Since resolution is a race (not an ordered
preference) once multiple nameservers are configured, a stale/wrong cached
answer arriving fast would still win regardless of which nameserver is
"supposed" to answer - the likely explanation is a client-side DNS-cache
artifact from the instability window itself, not a server misconfiguration
in this repo. Not fully closed; revisit if it recurs, ideally with the
actual captured DNS response (which nameserver answered, what TTL) rather
than just the end symptom.

## Verification

- Fix applied and confirmed live in the Tailscale admin console
  (`tailscale dns status` on the desktop now shows 5 global resolvers, AdGuard
  first).
- Root-cause chain (adguard clean -> dnsdist clean -> magicsock churn on the
  specific peer) confirmed via real UTC-timestamped log correlation across
  `adguard`, `tailscale-adguard-dns-relay`, and `tailscale-adguard`
  containers, cross-checked against the desktop's own `journalctl`/pcap
  evidence.
- No live repro of the actual transport-level failure was obtained (the
  exit-node-toggle repro tested a different, unrelated mechanism and came
  back clean) - the fix addresses the failure *class* (single point of
  failure), not a confirmed reproducible root cause for why that specific
  peer's path degraded on 2026-09-09. If a similar flap recurs, check
  `tailscale-adguard`'s magicsock log for the affected peer's disco
  short-code first (this file's method above), not `adguard`'s own logs.
