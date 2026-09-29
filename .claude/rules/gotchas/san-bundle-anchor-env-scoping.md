# Gotcha: a SAN-bundle anchor's `.env` only needs its OWN group's vars

Each of the SAN-bundle groups (see `.claude/rules/san-cert-groups.md`) has
exactly one **anchor router**, whose only job is to request one Let's
Encrypt certificate covering its own group's member hostnames - nothing
else. The anchor's `tls.domains[0].main`/`.sans` labels are the literal
hostname list going ON that one certificate, so the anchor's `.env` only
needs `${..._SUBDOMAIN}` vars for its own group's members, never any other
group's.

**Mental model:** each SAN group is one certificate-request errand run by
one specific service. That service's shopping list (its `.env`) only needs
the items for its own errand - it never needs another errand's shopping
list, because it's not the one running that errand.

**Real bug this caused (2026-08-22/23):** Portainer is the anchor for the
`infra-ops` group. Its live `.env` only had `PORTAINER_SUBDOMAIN` + `DOMAIN`
defined (left over from when it was a lone, unbundled router). After adding
the `infra-ops` anchor's `tls.domains[0].sans` label - referencing 20 other
services' `${..._SUBDOMAIN}` vars - every one of those vars resolved to an
empty string, producing a garbage SAN list (`.nicolkrit.ch` repeated 20
times) and no valid ACME request. Fixed by adding all 20 missing
`${..._SUBDOMAIN}=value` lines to Portainer's live `.env`.

**How to apply:** when adding a new service to an existing SAN group (see
that rule file's "Adding a new service" section), the new
`${NEW_SERVICE_SUBDOMAIN}` var only needs to be added to that group's
ANCHOR's own `.env`/`.env.example` - never to the new service's own `.env`,
and never to any other group's anchor. If a service ever moves between
groups, its subdomain var moves with it: removed from the old anchor's env,
added to the new one's.
