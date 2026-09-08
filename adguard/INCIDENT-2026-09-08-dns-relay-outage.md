# 2026-09-08: DNS relay outage - root cause, fix, and implementation log

Status as of last edit: **step 2's cutover is DONE and live** - `dnsdist`
replaced `socat` as the actual relay serving real traffic on `:53`
(`tailscale-adguard`'s `dns-relay`), validated first via a `:5300` canary
(0/500 failures at 100x+ the outage-causing query rate - see
[[adguard-dnsdist-burst-test-results-2026-09-08]] for full data), then a
follow-up fix raised the container's file-descriptor limit (Docker default
1024 -> 65536) after dnsdist's own startup warning flagged its
configuration could need more than that. Step 1 (static IP) also done.
Steps 3-6 (deleting the `macvlan-host-shim` relay, `oom_score_adj`,
tugtainer TZ, cpuset) **not yet started** - this is the next real work
remaining, not just polish. This file is the durable, git-tracked record -
read this before re-investigating any AdGuard/Tailscale DNS outage, so the
same investigation doesn't have to happen twice.

## Implementation log - two real bugs hit deploying step 2, both fixed

Worth reading before touching this canary again, or writing any similar
init-container-writes-a-config-file pattern elsewhere in this repo:

1. **The new `ADGUARD_INTERNAL_IP` var didn't reach the live containers on
   first deploy.** Git-tracking a new variable in `.env.example` does NOT
   auto-populate it into a live Portainer stack's actual environment - that
   needs to be added to the stack's env separately (done manually via the
   Portainer UI in this case, deliberately avoiding this session's own
   `StackUpdate`/`StackGitRedeploy` tools to sidestep the git-detach and
   env-wipe risks documented in `.claude/rules/portainer-instance.md` for
   exactly this kind of change). Symptom: `adguard` got a random dynamic IP
   instead of its intended static one (empty `IPAMConfig` on inspection).
2. **`$ADGUARD_INTERNAL_IP` inside the canary's config-writing heredoc was
   the exact same bare-`$VAR`-gets-Compose-interpolated bug already
   documented in this repo** (`macvlan-host-shim/README.md`'s `$ip` incident,
   `adguard/README.md`'s original entrypoint-patch incident) - missed again
   here despite being documented twice already. Fixed by escaping as
   `$$ADGUARD_INTERNAL_IP` so the container's own shell substitutes it at
   runtime from the value passed via the service's `environment:` block,
   not Compose at file-parse time. **If you're writing a new init-container
   config-writer heredoc anywhere in this repo, grep for bare `$VAR` in it
   before shipping - this is now the THIRD time this exact bug has been
   hit.**
3. **`dnsdist` 2.0's YAML schema requires `protocol` on every `backends:`
   entry, not just every `binds:` entry.** Not documented clearly in
   dnsdist's own docs at a glance - the error
   (`backends[0]: missing field 'protocol'`) only shows up at container
   startup. Fixed by adding `protocol: Do53` under the `backends:` list
   item too.
4. **The init container's own idempotency (`if file exists, skip`) means a
   broken file doesn't self-heal on redeploy** - after either fix above,
   the corrupted `dnsdist-canary.yml` had to be manually deleted from
   `${VOLUME_CONFIG}/tailscale-adguard/` before redeploying, or the init
   container just keeps skipping regeneration forever.

**Confirmed live and healthy after both fixes** (`dns-relay-canary`
container, `docker_proxy` inspect): `state: running`, `health: healthy`,
`RestartCount: 0`. Its own startup log confirms a clean load: listening on
`0.0.0.0:5300`, ACL restricted to `100.64.0.0/10`, backend `adguard`
(`172.27.255.247:53`) marked `up`. The still-live `socat` `dns-relay` on
`:53` was never touched or interrupted by any of this.

**Not yet done**: the actual burst/stress validation against the canary
(per the "Deployment sequence" section below) before considering step 2
ready for cutover, and steps 3-6.

## The problem

This household loses **all** internet connectivity, on any device, whenever
a device has Tailscale connected with an active Mullvad exit node and the
DNS relay chain described below hiccups - Tailscale's client claims the
OS's global default-route DNS domain the moment it's connected (regardless
of exit-node status), routing 100% of that device's DNS through
`tailscale-adguard`'s dedicated Tailscale identity. If that relay is down
even briefly, DNS fails completely, which looks exactly like "no internet"
(and makes Firefox show a false captive-portal prompt, since that trigger
fires on total DNS failure).

Two confirmed real incidents:

1. **An earlier one-off**, an afternoon before this repo had any CPU
   priority/cap tuning: sustained CPU contention from a one-time 80k-asset
   Immich ML backlog job (first-time OCR + facial recognition, not a
   recurring schedule - already finished by the time of incident #2) slowed
   the relay's `fork()` calls enough that it effectively stalled.
2. **2026-09-08, 09:07-09:22 UTC** (= 11:07-11:22 CEST local - the relay
   containers have no `TZ` set and run on UTC internally, confirmed via
   `docker exec <container> date` on three of them; get this conversion
   right before trusting any timestamp in this incident). System CPU was
   low (10-18%, confirmed via Grafana) - this one was root-caused with hard
   evidence instead: AdGuard's own `querylog.json`
   (`/opt/adguardhome/work/data/querylog.json` inside the `adguard`
   container) shows queries-per-minute jumping from a baseline of ~15-40 to
   **298 at 09:08, 180 at 09:09, 98 at 09:10 UTC**, almost entirely
   attributed to `tailscale-adguard`'s own internal IP (the single client
   identity every tailnet device's traffic collapses into - a known,
   accepted limitation of this relay design, see "Two Tailscale identities
   in this repo" below). The domains queried
   (`mqtt.c10r.facebook.com`, `mask.icloud.com`, `init.itunes.apple.com`,
   `dgw.c10r.facebook.com`) are classic phone-wake-from-standby
   background-refresh/push-notification traffic - nothing anomalous, just a
   normal device reconnecting and generating ~300 DNS lookups in under a
   minute.

## Root cause: `socat`'s UDP relay model, not CPU, not a scheduled job

Both incidents trace back to the same structural weakness: `tailscale-adguard`'s
`dns-relay` service and the (lower-traffic, but structurally identical)
`macvlan-host-shim` relay both use `socat UDP-LISTEN:53,fork` /
`TCP-LISTEN:53,fork`. Per `socat`'s own manpage, `fork` should not be used
with `UDP-LISTEN` at all - there's a documented race where the parent
`connect()`s to the first sender's address, and a datagram arriving from a
*different* peer before the socket rehashes produces a silent drop /
port-unreachable. This is architectural, not a tuning problem:
`max-children=` only caps concurrency (making drops worse under a burst,
not better) and `backlog=` (`socat`'s documented default is 5) is TCP-only,
doesn't touch the UDP race at all. Even a trivially low rate like the ~5qps
average of incident #2's burst is enough to expose this once anything
slows the relay down (CPU contention) or arrives concurrently enough
(a real query burst) - this explains both incidents with one mechanism.

### Theories investigated and ruled out - don't re-litigate these

- **`tugtainer`'s `UPDATE_CONTAINERS` cron** (`0 7 * * *`, and yes,
  `tugtainer/docker-compose.yml` really is missing this repo's standard
  `TZ: "${TZ}"` env var - a real hygiene gap, see the low-priority fix
  below) - seemed to fit well at first, but live `tugtainer` logs (fetched
  fresh, not a stale export) show no record of that cron actually firing on
  the day of incident #2, and once the relay containers' own UTC-vs-local
  timestamps were corrected, the schedule doesn't even line up with the
  real outage window anymore.
- **The `change-detection` stack restarting** at 09:18:58 UTC, on the same
  `traefik-proxy` Docker network as the relay's target - real, but happens
  11+ minutes after the query-volume spike (09:08 UTC) that actually
  explains the failure. At most a very minor tail-end contributor, not the
  trigger. Nothing else in the entire container fleet was created/recreated
  anywhere in the relevant time window (checked via an epoch-range filter
  across every container).
- **CPU starvation, for incident #2 specifically** - system CPU was
  10-18%, `immich_machine_learning` was ~0.1-0.2% CPU, and live cgroup
  stats confirmed `adguard` had `throttled_periods: 0` and
  `tailscale-adguard-dns-relay` had `RestartCount: 0` - zero CFS throttling,
  no crash, no restart. CPU pinning of any kind would not have prevented
  this specific incident (it's still worth doing for other reasons - see
  the `cpuset` item in the fix plan below - but not because it fixes this).
- **AdGuard's own `ratelimit` setting** (a default of 20qps/24, applied per
  subnet, with silent drops) was proposed as possibly the *real* proximate
  mechanism, since the relay collapses the whole tailnet into one client
  identity/one rate-limit bucket. Checked directly against the live config
  and **debunked**: `AdGuardHome.yaml` already has `ratelimit: 0` (disabled
  in AdGuard Home's semantics, not "0 allowed"), confirmed via
  `docker exec adguard grep ratelimit /opt/adguardhome/conf/AdGuardHome.yaml`.

## The verified fix plan

Written up, then reviewed independently by three adversarial verifier
agents (fact-check / risk-and-blast-radius / alternatives-hunt) plus a peer
session with visibility into the actual device/VLAN mix and Ubiquiti
network config this session can't see directly. **Unanimous approval,
4/4**, all required corrections already folded into the plan below - this
is the final version, not a draft.

### 1. Prerequisite: give `adguard` a static IP on `traefik-proxy`

`adguard/docker-compose.yml` currently declares no static IP on
`traefik_proxy_network`. `dnsdist` (see step 2) resolves its backend
address ONCE at config-parse time - no hostname resolution, unlike `socat`
which re-resolved `adguard:53` via Docker's embedded DNS on every
connection. Deploying against the bare hostname `adguard` would fail closed
on the household's only DNS path. Assign a real `ipv4_address` (mirroring
the existing `TAILSCALE_ADGUARD_INTERNAL_IP` pattern) and reference the
literal IP everywhere downstream. Low-risk, deploy and verify on its own
first.

### 2. Replace `socat` with `dnsdist` on `tailscale-adguard`'s `dns-relay`, staged via canary

The actual root-cause fix - this is the relay that caused both incidents.

- Image `powerdns/dnsdist-20` (current stable is `2.0.8`/`2.0.9`; `-21` is
  only a 2.1.0-beta, don't use it).
- Prefer dnsdist 2.0's native YAML config (`-C file.yml`,
  `binds`/`backends`/`pools`) over hand-written Lua - simpler, less error
  prone. Listen `0.0.0.0:53` (UDP+TCP), single backend = the static IP from
  step 1, port 53 - not the hostname.
- **No packet cache.** AdGuard already caches; caching at the relay would
  blind AdGuard's own query log (the exact tool that diagnosed this
  incident) and delay blocklist changes from taking effect. Concurrency is
  the problem being fixed, not cache misses.
- Don't bother explicitly setting `setMaxUDPOutstanding`/
  `setMaxTCPClientThreads` - their defaults (65536 / 10 threads) are
  already ~100x the observed burst peak; setting them "to sane bounded
  values" would only lower them, a regression against a burst, not a fix.
- Healthcheck: use the official image's own built-in HEALTHCHECK
  (`dnsdist -C ... -e showVersion()` against the control socket), not a
  custom `nc -z` check.
- Keep `network_mode: service:tailscale-adguard`, keep `cpu_shares: 4096`.
- **Must be staged via a canary, never a hot swap**: since `dns-relay`
  shares `tailscale-adguard`'s network namespace, add a SEPARATE
  `dns-relay-canary` service first, dnsdist listening on `:5300` (not 53)
  with the real intended config, running ALONGSIDE the still-live `socat`
  relay on :53. Validate against the canary (`dig @<tailnet-ip> -p 5300`,
  config accepted, and deliberately replay a burst of **several multiples**
  of the observed ~300/min peak - not just a 1:1 match, since nothing stops
  multiple household members' phones independently waking on the
  exit-node path at once, e.g. after a flight or the NAS itself bouncing,
  which multiplies the burst since they all collapse into the same relay
  identity). Only after that passes: a single cutover commit that flips
  dnsdist to :53 and deletes the socat service, with the old socat
  `command:` line kept in the commit message as the instant rollback.
- Known limitation, unchanged either way, not part of this fix: AdGuard's
  query log will still collapse every tailnet device into one client
  identity (dnsdist doesn't preserve source IP on a plain listener any more
  than socat did). A real fix exists (DNAT without MASQUERADE + a return
  route inside `adguard`) but is real complexity for a nice-to-have -
  separate future experiment only, not part of this plan.
- Alternatives seriously considered and rejected: **CoreDNS+`forward`**
  (viable fallback, no cache without a separate plugin - moot now that
  we're deliberately not caching at the relay anyway, closer call than it
  first appears, but dnsdist's bounded-concurrency knobs and being
  purpose-fit for exactly this job still make it the better pick).
  **HAProxy** ruled out entirely - open-source HAProxy has NO UDP
  load-balancing mode at all (`mode udp` is an Enterprise-only add-on
  module; some blog posts claim otherwise and are wrong, despite this repo
  already using HAProxy elsewhere for `traefik-tailnet-forwarder`).
  **Reusing `dnsmasq` itself** as the relay (tool-reuse angle) rejected -
  same cache-shadowing problem as socat's own cache, plus
  `--dns-forward-max` and EDNS/DNSSEC-rewriting quirks a pure relay
  shouldn't introduce. **Pure nftables DNAT** (genuinely viable here -
  `tailscale0` is a real TUN device, not userspace) rejected as the primary
  fix - survives a burst fine (kernel conntrack doesn't care about ~5qps)
  but zero caching, zero rate-limiting, zero observability, and entangles
  the fix with Tailscale's own netfilter rule management in that namespace
  (a documented upstream fragility, tailscale#13754) - keep as a documented
  fallback only if dnsdist proves too operationally heavy.
- Topology-level alternative seriously considered and rejected: collapsing
  `tailscale-adguard` into AdGuard's own netns
  (`network_mode: container:adguard`) would remove this relay hop entirely
  AND fix the source-IP-collapse limitation for free - genuinely
  attractive, but it puts Tailscale's netfilter/route management inside
  the namespace serving the whole household's LAN DNS, creates a
  cross-stack netns dependency that breaks on every AdGuard restart, and
  conflicts with the deliberate macvlan `priority: 100` already in place.
  Real upside, wrong risk profile for the household's sole DNS
  infrastructure - the current two-Tailscale-node design (see
  `tailscale-adguard/README.md`) stays as-is.

### 3. Delete `macvlan-host-shim`'s relay entirely - as TWO separate commits

- `dnsmasq` (`network_mode: host`) can bind the shim's IP
  (`${MACVLAN_SHIM_IP}`) directly - no relay process needed for this path
  at all.
- **Real crash risk**, not theoretical: this repo has already crash-looped
  `dnsmasq` once from a similar wildcard/permissive-binding collision with
  `systemd-resolved` on port 53 (`failed to create listening socket for
  port 53: Address in use`) - `--bind-interfaces` was the original fix for
  exactly that. Walking back toward `--bind-dynamic` risks reopening that
  exact failure mode, and with `restart: always` that's a crash-loop = total
  household LAN split-DNS loss, not just a degraded shim path. Add
  `--except-interface=lo` alongside `--bind-dynamic` as a defensive
  measure - harmless if unneeded, the downside if it IS needed is a total
  outage.
- **Two separate commits, never one** (also avoids a redeploy-ordering
  race, since `macvlan-host-shim` and `dnsmasq` are separate stacks on the
  same 5-minute git-poll interval):
  - **Commit A**: remove both `socat` lines from `macvlan-host-shim`, keep
    its `ip link`/route-add job (still load-bearing for the reply path).
    Verify AdGuard's conditional-forward for internal domains still
    resolves, and that `${MACVLAN_SHIM_IP}:53` is genuinely free
    afterward. Worst case if this alone is wrong: AdGuard's internal-domain
    forwarding breaks - low blast radius, LAN DNS itself untouched.
  - **Commit B** (only after A is verified): add
    `--listen-address=${MACVLAN_SHIM_IP}`, swap `--bind-interfaces` →
    `--bind-dynamic`, add `--except-interface=lo`, on `dnsmasq`. Verify
    BOTH `dig @${DNS_TARGET_IP} <a private-tier host>` AND
    `dig @${MACVLAN_SHIM_IP}` answer correctly before considering this
    done.
  - Pre-check before commit B: with `--listen-address` given and no
    `--interface`, dnsmasq will NOT listen on `127.0.0.1` unless
    `127.0.0.1` is itself given as an explicit `--listen-address` (true
    under today's `--bind-interfaces` too, not a regression) - confirm
    nothing on the NAS queries dnsmasq via `127.0.0.1` before this swap.
  - Healthcheck note: after this change, `macvlan-host-shim`'s healthcheck
    asserting liveness on `${MACVLAN_SHIM_IP}:53` is really checking a
    DIFFERENT container (`dnsmasq`) - a cross-stack liveness assertion.
    Fine, but make it a deliberate, documented choice in the compose file,
    not a silently-inherited leftover.

### 4. `cpuset: "0-4"` on the four known CPU hogs ONLY, ships LAST

Not causally connected to either confirmed incident (the real mechanism is
a `socat` UDP race, not CPU contention - `adguard` showed zero CFS
throttling even during the CPU-contention-driven afternoon incident), so
there's no urgency to bundle this with the actual fix.

- Add `cpuset: "0-4"` to exactly FOUR services: `immich_machine_learning`,
  `jellyfin`, `duplicati`, `qbit-torrent` (this NAS has 6 logical CPUs,
  0-5). Leaves core 5 reachable by anything unpinned, including the whole
  DNS chain.
- Explicitly do NOT add `cpuset` to the DNS chain itself (`adguard`,
  `macvlan-host-shim`, `tailscale-adguard`, `dns-relay`) - correct cgroup v2
  semantics: an unpinned container inherits the root cpuset (all cores),
  and true exclusivity requires `cpuset.cpus.partition=root`, which Docker
  exposes no knob for at all. Pinning the DNS chain to one core would only
  cap it, never protect it, while turning a single stuck process into a
  guaranteed total outage instead of a probabilistic one. This is a
  load-bearing design decision, not an oversight - if it looks like a bug,
  it isn't.
- Only ONE core reserved, not two - AdGuard's whole chain measurably uses
  ~0.06% of a CPU; a second core buys nothing while pushing every
  `cpus: 4.0` ceiling elsewhere in the repo out of reach in practice.
- Deliberately NOT the repo-wide version (~70 files) that an earlier draft
  of this plan proposed: all 73 Portainer stacks here git-poll `main`
  every 5 minutes with no canary/webhook gate, so a commit touching ~70
  files would hard-recreate ~70 containers inside a single poll window -
  real CPU spike plus mass churn on the shared `traefik-proxy` network
  (the same network whose churn was already flagged as a possible minor
  contributor to incident #2, here at ~70x scale). The 4-file version gets
  the same practical effect (core 5 stays free) at a small fraction of the
  blast radius.
- Rejected alternative: a systemd cgroup slice via `/etc/docker/daemon.json`
  would cover all 111 running containers instead of just the 4 repo-managed
  hogs, but lives outside git on a NAS whose firmware updates could wipe it
  with zero trace in this repo, and requires a full `dockerd` restart (all
  containers bounce at once). Revisit only if non-repo containers are later
  found to meaningfully contend for CPU.

### 5. `oom_score_adj: -800` on the DNS chain

Add to `adguard`, `macvlan-host-shim`, `tailscale-adguard`, `dns-relay`.
Cheap, real, unrelated to either actual incident (neither was a memory/OOM
event) but reasonable insurance. Bundle with #6, low-risk, any time.

### 6. Lower priority, pure hygiene - does not fix either incident

`tugtainer/docker-compose.yml` is missing this repo's standard
`TZ: "${TZ}"` env var - add it, and move `UPDATE_CONTAINERS`'s schedule off
hours anyone is awake. This is purely hygiene (the theory that this caused
the outage was investigated and debunked, see above) - label the commit
message accordingly so it's never mistakenly credited with fixing anything
it didn't fix.

### Also observed, optional, not part of this fix

While verifying (and debunking) the `ratelimit` theory directly against
live `AdGuardHome.yaml`, two unrelated things came up worth a future look:

- `cache_size: 4194304` (4MiB) is AdGuard Home's factory default,
  unchanged. Irrelevant to either confirmed incident (queries were refused
  at the relay layer, never reaching AdGuard's own cache logic at all) -
  worth revisiting now that this plan deliberately avoids caching at the
  relay layer, which makes AdGuard's own cache the only cache left in the
  whole path.
- `upstream_dns` has exactly ONE entry
  (`https://dns10.quad9.net/dns-query` - the same upstream seen failing
  intermittently with `unexpected EOF` throughout the day of incident #2)
  and `fallback_dns: []` is empty. `upstream_mode: load_balance` is moot
  with only one upstream configured. A real, separate resilience gap - a
  Quad9 blip currently has zero fallback - unrelated to the root cause
  this plan addresses.

## Mandatory pre-flight, before touching anything

Capture and save to disk `StackInspect(id, select: "{env:Env}")` for
Portainer stacks **316** (dnsmasq), **347** (adguard), **348**
(macvlan-host-shim), **349** (tailscale-adguard). `StackGitRedeploy` (used
for any rollback under time pressure) is env-destructive unless the full
`Env` is explicitly re-supplied in that same call - see
`.claude/rules/portainer-instance.md` for the documented past incident this
broke (n8n + sparkyfitness). If any of the four already returns
`Env: null`, STOP and get the real values from the user before touching
anything.

Operational precondition: do this with someone physically present (not
remotely, not on a Friday), with at least one device already manually
pointed at a public resolver (e.g. `1.1.1.1`) as a manual fallback so the
household isn't fully blind if a step goes wrong mid-deploy.

**Rollback safety net already in place from unrelated prior work**: git tag
`v4.0.9-pre-performance-tweaks` on commit `4f55e75` is a known-good point
from before ANY of the CPU-priority tuning landed (`cpu_shares`/`cpus`
across the repo, 2026-09-07). Not a substitute for the per-step rollback
plan below, but a documented last-resort anchor if something in this whole
area needs a wider revert.

## Deployment sequence

1. Pre-flight (above).
2. Static IP for `adguard` (#1) - deploy, verify, done on its own.
3. `dnsdist` canary on `:5300` alongside live `socat` (#2) - burst-test
   deliberately - single cutover commit to `:53` + delete `socat` - verify
   real tailnet DNS from an actual exit-node device - soak ≥24h through at
   least one real phone-wake burst before considering this step closed.
4. Commit A (drop shim's socat) → verify → commit B (dnsmasq
   `--bind-dynamic`) (#3) → verify both listeners → soak 24h.
5. `oom_score_adj` + tugtainer TZ (#5 + #6) - cheap, independent, bundle
   together, any time.
6. The 4-service `cpuset` change (#4) - LAST, its own commit, only after
   steps 2-4 above are deployed and confirmed stable.

Rollback per step: a pre-written revert commit pushed to `main`, followed
immediately by a manual `StackGitRedeploy` with the captured `Env`
re-supplied in that same call - don't wait on the 5-minute poll while DNS
is down. For the relay swap specifically, the canary structure means the
practical fallback is just re-adding the `socat` service, a known-good
config already sitting in git history.

## Verification trail

Reviewed by three independent adversarial agents (fact-check /
risk-and-blast-radius / alternatives-hunt), all returning APPROVE WITH
CHANGES with non-conflicting corrections (all folded in above), plus a peer
session with direct visibility into the actual device/VLAN mix and
Ubiquiti network config: confirmed AdGuard only serves the Trusted/Family
VLANs (IoT and Guest are on entirely separate DNS paths, untouched by this
plan), no UniFi-native DNS filtering exists to collide with any of these
changes, and nothing at the Wi-Fi/roaming/L2 layer reaches into the Docker
network where these changes live. **4/4 unanimous approval.**
