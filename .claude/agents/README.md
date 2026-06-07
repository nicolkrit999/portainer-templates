# Subagent roster — portainer-templates

This repo is a flat collection of ~70 Docker-Compose service directories deployed
via Portainer. The agents below are scoped, least-privilege helpers. Three are
read-only reviewers/researchers that **run in their own context and return only a
compact report** — that is the point: they keep large fan-out work (scanning 70
service dirs, web research) out of the main conversation's token budget.

Shared conventions live in [`../rules/`](../rules/) (`secrets.md`,
`networking.md`, `volumes.md`, `conventions.md`). Every agent reads those so all
of them — and the human-facing `CLAUDE.md` — share one source of truth.

## The agents

| Agent | Role | Tools | Model | Writes files? |
|-------|------|-------|-------|---------------|
| [`docker-compose-architect`](docker-compose-architect.md) | Create / modify / review compose files. The anchor agent — owns all the conventions and the Portainer/Cloudflare handoff. | Read, Write, Edit, … | inherit | **Yes** |
| [`service-researcher`](service-researcher.md) | Research a new service's official image, env, volumes, ports, healthcheck → compact spec. | Read, WebFetch, WebSearch | sonnet | No |
| [`compose-security-auditor`](compose-security-auditor.md) | Read-only security scan: hardcoded secrets, exposed ports, privileged, unpinned images, default-volume leaks → severity table. | Read, Grep, Glob | sonnet | No |
| [`compose-consistency-linter`](compose-consistency-linter.md) | Read-only convention check: TZ, restart, no `version:`, quoting, volume pools, hostname, Cloudflare block → compliance report. | Read, Grep, Glob | sonnet | No |

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

- Pass each subagent the **objective (the WHY)**, not just a bare query — e.g.
  "researching Paperless-ngx because we're adding it behind the Cloudflare
  tunnel," so the spec already accounts for external access.
- The orchestrator (main Claude) evaluates each return, asks follow-ups, and runs
  **at most 3 cycles**; store intermediate specs/reports rather than re-deriving.
- One clear input → one clear output per agent. Reviewers never edit — they hand
  findings back to the architect to apply.

## Adding more agents

Keep the roster small and focused (this is a YAML/compose repo, not a polyglot
codebase). New agents should: use least-privilege `tools`, pick a `model` by task
weight (Haiku = search/simple, Sonnet = review/multi-file, Opus =
architecture/security analysis), reference `../rules/` instead of restating
conventions, and define a fixed compact Output Format.
