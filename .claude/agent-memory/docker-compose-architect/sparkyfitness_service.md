---
name: sparkyfitness-service
description: SparkyFitness (fitness/nutrition tracker) - 3-service compose, volume paths, and version pins confirmed 2026-07-09
metadata:
  type: project
---

Added `sparkyfitness/docker-compose.yml`: sparkyfitness-db (postgres:18.3-alpine),
sparkyfitness-server (codewithcj/sparkyfitness_server:v0.17.3), sparkyfitness-frontend
(codewithcj/sparkyfitness:v0.17.3). Fresh deploy, no data migration.

**Why the version pin matters:** a prior service-researcher pass in this session
claimed v0.16.9 was current; the user independently verified v0.17.3 is the correct
current tag on Docker Hub for both `codewithcj/sparkyfitness_server` and
`codewithcj/sparkyfitness`. Don't trust cached/remembered version numbers for this
image without reverifying against Docker Hub directly.

**Volume paths used** (proposed, pending final user confirmation in `.env`):
- `${VOLUME_DATA}/sparkyfitness/db` - postgres data (bulk, not config-class, per volumes.md)
- `${VOLUME_DATA}/sparkyfitness/backups`
- `${VOLUME_DATA}/sparkyfitness/uploads`

**Networking:** frontend is the only service on `cloudflare_web_network`; db+server
sit on a private `sparkyfitness_internal` (docker name `sparkyfitness-internal`)
bridge network, non-external. Cloudflare Tunnel target: `http://sparkyfitness-frontend:80`.

**Healthcheck judgment call:** upstream has no verified HTTP health endpoint on the
server container (a prior research pass speculated `/api/health` without confirming
it exists - do not trust that). Omitted server healthcheck entirely with an explanatory
YAML comment rather than guessing at `curl`/`nc` availability in that image. DB uses
`pg_isready`, frontend (nginx) uses `curl -f http://localhost:80/` since that only
tests nginx itself, not an unverified app route.

**Env vars deliberately left out of compose:** SPARKY_FITNESS_EMAIL_* and OIDC vars -
optional and out of scope for first deploy, no stubs added to keep the compose lean.

See [[docker-compose-conventions]] for repo-wide rules this followed.
