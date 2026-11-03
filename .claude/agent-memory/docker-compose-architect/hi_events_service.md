---
name: hi-events-service
description: hi-events stack layout - underscore vs dash folder naming, eventi hostname override, permission-init containers, pinned images
metadata:
  type: project
---

`hi-events/docker-compose.yml` (migrated 2026-08-24 from a manually run NAS all-in-one compose into git; real production data). Routed by the standard private + `-tailnet` router pair, also public through `traefik-public` (network `public-hi-events`); runtime facts for that are in [[batch2-opencloud-trek-hi-events-public-wiring]].

- **Folder naming is a deliberate mismatch:** repo directory `hi-events` (dash), real NAS folder `hi_events` (underscore): `${VOLUME_DATA}/hi_events/postgres`, `${VOLUME_CONFIG}/hi_events/data/redis`, `${VOLUME_CONFIG}/hi_events/uploads`. Never "fix" this to `hi-events`: it would point at an empty path and orphan live data.
- **Hostname `eventi.${DOMAIN}`:** `HI_EVENTS_SUBDOMAIN=eventi` (not `hi-events`), one of the repo's known subdomain overrides (like `homehub` -> `casa`, `mealie` -> `ricette`, `holyclaude` -> `claude`).
- **Three `alpine:3.19` one-shot init containers** (postgres, redis, all-in-one uploads), `restart: "no"`, gate the real services with `depends_on: condition: service_completed_successfully`.
- **Pins:** `postgres:18` (live data is PG 18; a newer major would refuse to start on it), `redis:8.10.3`, `daveearley/hi.events-all-in-one:v2.0.0`. `container_name: all-in-one` (no prefix) matches the live name and the `traefik-public` backend URL `http://all-in-one:80`. `VITE_API_URL_SERVER` stays the literal `http://all-in-one:80/api` (container-to-container).
- **No PUID/PGID** on any service; `TZ` is set only on `all-in-one`.
- Networks: the stack's default network for postgres/redis, plus `traefik-proxy` and `public-hi-events` for `all-in-one` (no separate `-backend` network or explicit /28 yet: UNVERIFIED whether that is intended).
- `.env.example` write workaround: see [[dnsmasq-service]].
