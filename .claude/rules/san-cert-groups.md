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
| **household-travel** | `grocy` (`grocy`) | grocy, homebox, casa (homehub), ricette (mealie), sparkyfitness, promemoria (vikunja), appuntamenti (easy-appointments), home-assistant, viaggi (surmai), trek |
| **infra-ops** | `portainer` (`portainer`) | portainer, coolify, soketi-coolify, gitea, tugtainer, dockpeek, harborguard, beszel, uptime-kuma, glances, glance, gocron, n8n, pocket-id, adguard, upsnap, apprise-api, gotify, web-check, traefik (dashboard), mailpit, phpldapadmin |
| **utilities** | `it-tools` (`it-tools`) | it-tools, omnitools, convertx, stirling-pdf, change-detection, filebrowser, duplicati, snapotter, moocup, withoutbg, cardyo, datetime, termix, snappyemail, owncloud, miniqr, privatebin, bytestash, openresume, sosse |
| **productivity-creative** | `affine` (`affine`) | affine, draw-io, excalidraw, fossflow, opennotebook, paperlessngx, linkwarden, claude (holyclaude - **hostname is `claude`, not `holyclaude`**, confirmed against the live Portainer env, don't assume the directory name), blender, lifeglance, blog (ghost) |

Each group is well under the 100-SAN-per-cert limit even at current size -
split a group further only when it actually approaches that limit, not
preemptively.

**Deployment status as of 2026-08-22 evening (corrected)**: `budgeting`,
`media`, `utilities`, `productivity-creative` all have Phase A deployed
correctly (siblings stripped of `certresolver`, confirmed via logs to have
fully stopped the sibling-router race - each anchor now fires exactly one
bundled ACME request instead of N individual ones) and Phase B run (old
individual certs deleted to force reissuance) - **but the bundled cert has
NOT actually landed for any of the four yet**: all four are still being
served Traefik's self-signed default cert as of this check, because every
retry is hitting Let's Encrypt's 429 rate limit (confirmed via live
Traefik logs, `retry after 2026-08-22 ~18:0x UTC` = ~20:0x CEST). An
earlier note in this file claiming `budgeting`'s bundled cert was
"confirmed issued" was premature/wrong - do not trust that claim, verify
directly (`openssl s_client -connect <host>:443 -servername <host>` and
check the issuer isn't `TRAEFIK DEFAULT CERT`) before telling the user any
group is done. `household-travel` has Phase A deployed but its individual
member certificates haven't yet been deleted to force the bundle (Phase B
not run) - unaffected by the current rate-limit block since it never
triggered new ACME requests. `infra-ops`/`portainer` anchor is written in
`portainer/docker-compose.yml` but not yet deployed (Portainer itself isn't
tracked as a normal Portainer stack - deploying compose changes to it needs
a careful manual step, not a routine git-poll redeploy).

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
