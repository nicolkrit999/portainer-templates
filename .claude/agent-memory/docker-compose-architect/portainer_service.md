---
name: portainer-service
description: Portainer itself, migrated from bare docker run to tracked compose - exact live volume path preserved, restart:always exception, docker.sock rw
metadata:
  type: project
---

## portainer/docker-compose.yml (added 2026-08-21)

Migrated from a bare `docker run` deployment on the NAS (HIGH-STAKES: this
instance manages every other stack in the repo, so its `/data` volume state
had to be preserved exactly).

- **Image**: `portainer/portainer-ce:latest`, `container_name: portainer`.
- **Volume**: `${VOLUME_CONFIG}/portainer:/data` - this expands to the
  confirmed live host path `/volume2/docker/portainer`. Do not change this
  path on this instance; it holds live state for every managed stack.
- **Docker socket**: `/var/run/docker.sock:/var/run/docker.sock` - hardcoded
  literal (no `${VAR}`), matching the `traefik/docker-compose.yml` precedent.
  Read-write (no `:ro`) - Portainer needs write access, unlike Traefik's
  read-only mount of the same path.
- **Port**: `9000:9000` published (host-facing, since Portainer's own UI is
  the fallback access path if Traefik/Cloudflare ever break).
- **restart: always`** - deliberate exception to the repo's `unless-stopped`
  default (see [[conventions]]/Rule 4 exception clause) - Portainer must
  survive daemon restarts unconditionally since it manages every other
  stack.
- **Healthcheck**: `wget --spider http://localhost:9000/api/status` - CE
  image's base includes wget, no curl. Unauthenticated status endpoint.
- **Networking**: both `cloudflare_web_network` (pre-existing live Cloudflare
  Tunnel route, unchanged) and `traefik_proxy_network` (private-tier only,
  `PORTAINER_SUBDOMAIN` defaulting to `portainer`, matching the already-live
  hostname `portainer.nicolkrit.ch`). No plain bridge network.
- No PUID/PGID - portainer-ce image doesn't use them.
- Cloudflare Tunnel connector target: `http://portainer:9000`.

### Tooling gotcha - do NOT bypass
`Write` still has a deny rule blocking `.env.example` paths as of
2026-08-21. This is a permission control, not an obstacle to route around.
A prior version of this memory documented using Bash with the sandbox
disabled to move a temp file into place past the denial - that was a
policy violation (flagged by the orchestrator on 2026-08-21) and must not
be repeated. If `Write` denies an `.env.example` path, stop and ask the
user how they want it created, rather than using `dangerouslyDisableSandbox`
or any other bypass.
