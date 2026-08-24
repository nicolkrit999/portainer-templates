---
description: Let's Encrypt SAN-bundle certificate groups - which group a new service's hostname belongs to, and the mechanism that makes bundling actually work.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# SAN-bundle certificate groups

## Why this exists

Let's Encrypt enforces a rate limit of **50 new certificates per registered
domain per 168 hours (1 week)**. This repo has ~77 Traefik-routed hostnames,
all under the same domain (`${DOMAIN}`). Requesting one certificate per
router (Traefik's naive default) burns through that quota fast whenever
several services get added/redeployed in the same week - this has caused
two real production incidents in this repo's history (a full-quota
exhaustion, and a second incident where a bad fix attempt burned ~57
individual certificates in one burst for zero benefit).

**The fix**: a certificate can cover up to 100 SAN (Subject Alternative
Name) entries. Instead of one cert per hostname, this repo bundles related
hostnames into 6 groups, each backed by a single multi-SAN certificate
requested by one "anchor" router per group.

## The mechanism - read this before touching cert config on ANY router

1. Exactly **one anchor router per group** carries:
   ```yaml
   traefik.http.routers.<anchor-router>.tls.certresolver: "cf_dns"
   traefik.http.routers.<anchor-router>.tls.domains[0].main: "${ANCHOR_SUBDOMAIN}.${DOMAIN}"
   traefik.http.routers.<anchor-router>.tls.domains[0].sans: "${MEMBER1_SUBDOMAIN}.${DOMAIN},${MEMBER2_SUBDOMAIN}.${DOMAIN},..."
   ```
2. **Every other router that matches ANY hostname in that group** - across
   every entrypoint/tier (family/guest/private/friends), in every member
   service's own compose file, including sibling routers of the SAME
   service on a different tier - must have `tls: "true"` with **NO**
   `tls.certresolver` and **NO** `tls.domains` at all. A router with no
   `certResolver` never calls ACME itself - it purely does SNI-based
   certificate selection from whatever's already in Traefik's store,
   falling back to the default self-signed cert temporarily if nothing
   matches yet, then automatically picking up the real cert once the
   anchor's bundle lands (no restart needed).
3. **This is not optional or "cleaner style" - it is required for the
   bundling to actually work.** Confirmed via a real production incident
   and Traefik's own documented behavior (github.com/traefik/traefik#5317):
   Traefik has NO cross-router coordination for ACME requests. If even ONE
   router matching a bundled hostname has its own `certresolver` set, it
   will independently race the anchor's bundled request - and since a
   single-domain request completes faster than a multi-domain one, the
   un-bundled router wins the race almost every time, defeating the whole
   point and consuming rate-limit budget for nothing.
4. `tls.domains` and `tls.certresolver` must NEVER be added to more than
   one router per group. Never add `tls.domains` "for clarity" on a
   sibling router - it does nothing there except risk becoming a second,
   conflicting bundle definition.

## The 6 groups (as of 2026-08-22)

| Group | Anchor service (router) | Members |
|---|---|---|
| **budgeting** | `actual-budget/actual-server_actual-https-api` (`actual-budget`) | budget, budget-ical, budget-api, budget-tap |
| **media** | `jellyfin` (`jellyfin-family`) | jellyfin, foto (immich), radarr, sonarr, plex, navidrome, kavita, audiobookshelf, ytptube, qbit-torrent |
| **household-travel** | `vikunja` (`vikunja-private`) | vikunja (promemoria), grocy, homebox, casa (homehub), ricette (mealie), sparkyfitness, appuntamenti (easy-appointments), appuntamenti-pma/-swagger/-baikal (easy-appointments' sub-services, added 2026-08-23), home-assistant, viaggi (surmai), trek |
| **infra-ops** | `glances` (`glances`) | glances, portainer, coolify, soketi-coolify, gitea, tugtainer, dockpeek, harborguard, beszel, uptime-kuma, glance, gocron, n8n, pocket-id, adguard, upsnap, apprise-api, gotify, web-check, traefik (dashboard), mailpit, phpldapadmin |
| **utilities** | `duplicati` (`duplicati`) | duplicati, it-tools, omnitools, convertx, stirling-pdf, change-detection, filebrowser, snapotter, moocup, withoutbg, cardyo, datetime, termix, snappyemail, owncloud, miniqr, privatebin, bytestash, openresume, sosse |
| **productivity-creative** | `linkwarden` (`linkwarden`) | linkwarden, affine, draw-io, excalidraw, fossflow, opennotebook, opennotebook-api (opennotebook's own API sub-service, port 5055, added 2026-08-24), paperlessngx, claude (holyclaude - **hostname is `claude`, not `holyclaude`**, confirmed against the live Portainer env, don't assume the directory name), blender, lifeglance, blog (ghost), eventi (hi-events - **hostname is `eventi`, not `hi-events`**, confirmed against the live NAS migration config, added 2026-08-24) |

**Anchor swap 2026-08-23**: the household member moved the anchor role in
4 of the 6 groups away from everyday/critical services onto more
"disposable" ones, so a decommission accident is lower-stakes: `affine` →
`linkwarden` (productivity-creative), `grocy` → `vikunja` (household-travel,
router `vikunja-private`, the private-tier sibling of `vikunja`),
`it-tools` → `duplicati` (utilities), `portainer` → `glances` (infra-ops).
`budgeting`/`actual-budget` and `media`/`jellyfin` were NOT changed. The
new anchors (`linkwarden`, `vikunja`, `duplicati`, `glances`) were also
switched to `restart: always` since they're now ACME-renewal-critical;
`jellyfin` was set to `restart: always` too even though it remains the
media anchor unchanged. The 4 old anchors (`affine`, `grocy`, `it-tools`,
`portainer`) are now ordinary bare-`tls: "true"` members and were left on
their prior restart policy.

Each group is well under the 100-SAN-per-cert limit even at current size -
split a group further only when it actually approaches that limit, not
preemptively.

**Deployment status as of 2026-08-23 ~11:45 CEST**: **all 6 groups are
fully confirmed working, verified per-member not just per-anchor** -
`budgeting`, `media`, `household-travel`, `utilities`,
`productivity-creative`, and `infra-ops`. Every one of the 77 member
hostnames (not just the 6 anchors) was checked individually via
`openssl s_client -connect <host>:443 -servername <host>` -> real Let's
Encrypt issuer, SAN count matching its group's full size, and the exact
same certificate serial shared across every member of that group. Do not
trust a "confirmed issued" claim in this file (or a memory) without that
full per-member check - this file previously asserted `budgeting` was done
when it wasn't, and separately jellyfin's, then `infra-ops`'s, then
(discovered 2026-08-23 in one pass) ALL SIX groups' leftover individual
certs each looked like a "done" bundle from an anchor-only check or log
success alone. The real failure: 24 stale pre-bundle solo certs were
sitting in `acme.json` across every group, each independently winning its
own hostname's SNI tie-break even while the anchor itself served the
correct bundle - anchor-only verification cannot catch this. Full
detection/fix runbook, including the corrected "check every member"
methodology: [[san-bundle-stale-cert-cleanup-runbook]].

`infra-ops`/`portainer`: **fully done as of 2026-08-23 ~11:15 CEST.**
Phase A (all 18 sibling routers across 17 files stripped of
`certresolver`) and the anchor's env-scoping (see
[[san-bundle-anchor-env-scoping]]) were both fixed the night before; the
anchor fired one clean 22-host bundled request that actually succeeded
this morning (no fresh 429 - the prior night's rate limit had fully
cleared). The bundle's real certificate landed correctly in `acme.json`,
but a stale solo `portainer.nicolkrit.ch` cert (predating the SAN-bundle
work) was still winning the SNI tie-break; fixed by removing 18 stale
individual-domain entries from `acme.json` (backup taken first) and
restarting Traefik once more - full detail in
[[san-bundle-stale-cert-cleanup-runbook]]. Verified 3x directly after the
fix: correct issuer, correct full 22-host SAN list, stable across repeated
checks.

Also note: 4 of `infra-ops`'s listed members (`adguard`, `dockpeek`,
`gocron`, `upsnap`) have compose files in this repo but are **not actually
deployed** anywhere (no running container, no Portainer stack) - harmless
for the SAN-bundle mechanism (a router with no live container just never
matches any traffic), but worth knowing if their absence from `StackList`
or `docker ps` output is ever confusing.

## ⚠️ Removing or decommissioning an anchor service - mandatory step

**Never delete, stop permanently, or remove the Traefik router/labels of an
anchor service (`actual-budget`, `jellyfin`, `grocy`, `portainer`,
`it-tools`, `affine`) without first moving its anchor role to another
still-live member of the same group.** The certificate itself lives in
Traefik's `acme.json` store, keyed by domain, not owned by any particular
container - so deleting the anchor does NOT immediately break the other
members' TLS (they do pure SNI-based lookup against whatever's already in
the store, regardless of whether the anchor's router still exists).

**The real danger is silent, delayed loss of renewal.** The anchor's router
is the ONLY place in the whole group carrying `tls.certresolver` +
`tls.domains[0].main`/`.sans`. If that router disappears, nothing is left
to request renewal - the existing cert keeps working fine for weeks/months
(Let's Encrypt certs are valid ~90 days, Traefik attempts renewal ~30 days
before expiry), then it silently fails to renew and every member of that
group flips to Traefik's default self-signed cert all at once, with no
obvious link back to whatever decommissioning caused it.

**Before removing/replacing an anchor's stack**: copy its
`tls.certresolver: "cf_dns"` and both `tls.domains[0].main`/`.sans` labels
onto another router that will remain live in the same group, update
`${ANCHOR_SUBDOMAIN}` references in the table below to the new anchor, then
remove the labels from (or fully delete) the old anchor. Do this BEFORE
deleting the old anchor, not after - never leave a group with zero routers
carrying `tls.certresolver`, even briefly, unless you're intentionally
letting that group's cert lapse.

## Adding a new service - mandatory step

**Every new service with a Traefik router needs its hostname added to a
SAN group.** Check the table above:

- If an existing group's theme genuinely fits (e.g. a new media app →
  `media`, a new infra/admin tool → `infra-ops`), add the new hostname to
  that group's **anchor router's** `tls.domains[0].sans` list (and add the
  matching `${NEW_SERVICE_SUBDOMAIN}` var to the **anchor's own**
  `.env.example`, value copied from the new service's real configured
  hostname - never invent a value, verify it from the new service's own
  compose file/env). The new service's own router(s) get bare `tls: "true"`,
  no `certresolver`, no `tls.domains` - same as every other non-anchor
  router in that group.
- If no existing group fits well, or you're unsure which one is the best
  fit, **do not guess and do not silently create a new group** - stop and
  ask the user, proposing either (a) the closest-fitting existing group
  with your reasoning, or (b) a new dedicated group if the service doesn't
  fit any theme, explaining why.
- **After deploying, update the table in this file** with the new
  member (and new group, if one was created) so it stays the single
  source of truth - this file is what every future session/agent checks,
  not a private memory that isn't visible outside this session.
