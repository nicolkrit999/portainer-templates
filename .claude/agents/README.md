# Subagent roster - portainer-templates

This repo is a flat collection of ~95 Docker-Compose service directories deployed
via Portainer. The agents below are scoped, least-privilege helpers. Three are
read-only reviewers/researchers that **run in their own context and return only a
compact report** - that is the point: they keep large fan-out work (scanning the
service dirs, web research) out of the main conversation's token budget.

Shared conventions live in [`../rules/`](../rules/) (`secrets.md`,
`networking.md`, `volumes.md`, `conventions.md`, `portainer-instance.md`,
`core-infra-topology.md`, `service-directory.md`) and the gotchas in
[`../rules/gotchas/`](../rules/gotchas/). Every
agent reads those so all of them - and the human-facing `CLAUDE.md` - share one
source of truth.

## The agents

| Agent | Role | Tools | Model | Writes files? |
|-------|------|-------|-------|---------------|
| [`docker-compose-architect`](docker-compose-architect.md) | Create / modify / review compose files. The anchor agent - owns all the conventions (two Traefik routers, per-stack backend network, `traefik-public` exposure) and the deploy/verify handoff. | Read, Write, Edit, … | sonnet | **Yes** |
| [`service-researcher`](service-researcher.md) | Research a new service's official image, env, volumes, ports, healthcheck → compact spec. | Read, WebFetch, WebSearch | haiku | No |
| [`compose-security-auditor`](compose-security-auditor.md) | Read-only security scan: hardcoded secrets, exposed ports and publish bypasses, privileged, tailnet allowlist, public exposure outside `traefik-public`, backing services on shared networks, unpinned images, default-volume leaks → severity table. | Read, Grep, Glob | opus | No |
| [`compose-consistency-linter`](compose-consistency-linter.md) | Read-only convention check: TZ, restart, no `version:`, quoting, volume pools, hostname, private + tailnet routers with bare TLS, backend network, no relative bind mounts, `.env.example` minimalism → compliance report. | Read, Grep, Glob | haiku | No |

## When to use which (by trigger)

- **Adding a new service** → `service-researcher` (get the spec) → then
  `docker-compose-architect` (build the compose from the spec).
- **Editing an existing service** → `docker-compose-architect` directly.
- **"Audit / security check my composes"** → `compose-security-auditor`.
- **"Are my composes consistent / following conventions?"** → `compose-consistency-linter`.

## Orchestration pattern (shared house style)

Phase chain: **Research → Plan → Implement → Review → Verify**

```
service-researcher ─▶ docker-compose-architect ─▶ compose-security-auditor
   (spec)                 (writes compose)        compose-consistency-linter
                                                        (read-only review)
```

- Pass each subagent the **objective (the WHY)**, not just a bare query - e.g.
  "researching Paperless-ngx because we're adding it (private only, or also
  public through `traefik-public`)," so the spec already accounts for the exposure.
- The orchestrator (main Claude) evaluates each return, asks follow-ups, and runs
  **at most 3 cycles**; store intermediate specs/reports rather than re-deriving.
- One clear input → one clear output per agent. Reviewers never edit - they hand
  findings back to the architect to apply.

## Current access model (all agents assume this)

Every service gets a `<svc>-private` router (core Traefik entrypoint `${TRAEFIK_ENTRYPOINT_3}`)
and a `<svc>-tailnet` router (`${TRAEFIK_ENTRYPOINT_7}`), bare `tls: "true"`, one wildcard
certificate issued by the `traefik-dashboard` router. Multi-container stacks use one
`<stack>-backend` network with an explicit /28 from the subnet registry. Public exposure
is an additive router and `public-<app>` network in `traefik-public`. The Cloudflare
Tunnel, `cloudflare-web`, the family/guest/friends tiers, SAN groups and per-service DNS
steps no longer exist (retired 2026-11-03); see `../rules/networking.md`.

## Adding more agents

Keep the roster small and focused (this is a YAML/compose repo, not a polyglot
codebase). New agents should: use least-privilege `tools`, pick a `model` by task
weight (Haiku = search/simple, Sonnet = review/multi-file, Opus =
architecture/security analysis), reference `../rules/` instead of restating
conventions, and define a fixed compact Output Format.
