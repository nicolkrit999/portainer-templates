# CLAUDE.md

A collection of Docker Compose files for self-hosted services deployed via Portainer with git-based stack management. There are no build steps, tests, or package managers.

## Compose work

For any task involving creating or modifying compose files, use the `docker-compose-architect` subagent. Invoke it via the Agent tool with `subagent_type: "docker-compose-architect"`.

## Subagents & delegation

Full roster and orchestration notes: `.claude/agents/README.md`. Delegate by trigger:

- **Creating / modifying / reviewing a compose file** → `docker-compose-architect` (the anchor agent; writes files).
- **Adding a *new* service** → `service-researcher` first (compiles a compact image/env/volume/port/healthcheck spec via web research), then hand that spec to `docker-compose-architect`.
- **"Audit / security-check my composes"** → `compose-security-auditor` (read-only: secrets, exposed ports, privileged, unpinned images, default-volume leaks).
- **"Are my composes consistent / following conventions?"** → `compose-consistency-linter` (read-only: TZ, restart, no `version:`, quoting, volume pools, hostname, Cloudflare block).

The three read-only agents fan out across the ~70 service dirs in their own context and return only a compact report — use them to keep large scans and web research out of the main token budget.

**Orchestration:** Research → Plan → Implement → Review → Verify. Pass each subagent the objective (the *why*), not just a bare query. Evaluate each return and iterate at most 3 cycles; reviewers never edit — they hand findings back to the architect to apply.

## Shared conventions (`.claude/rules/`)

The canonical compose conventions live in `.claude/rules/` and are referenced by every agent: `secrets.md` (no hardcoded secrets, use `${VAR}`), `networking.md` (Cloudflare Tunnel block, `<svc>.nicolkrit.ch` hostnames, connector handoff), `volumes.md` (`/volume2` SSD vs `/volume1` HDD bind-mounts), `conventions.md` (2-space indent, no `version:`, quote-all-env, TZ=Europe/Zurich, default user `krit` / PUID 1000 / PGID 10). A non-blocking PostToolUse hook (`.claude/hooks/validate-compose.sh`) warns on `version:`, unquoted env values, and hardcoded-secret patterns when a `docker-compose.yml` is edited.

## Token optimization (RTK)

RTK is installed and a Claude Code hook auto-rewrites Bash tool calls — `git status` becomes `rtk git status` transparently. This covers all git and `docker`/`docker compose` commands.

**The hook does not cover built-in tools.** `Read`, `Grep`, and `Glob` bypass RTK entirely. Always prefer shell equivalents via Bash so RTK can intercept and filter the output:

- `cat`/`head` instead of `Read`
- `grep`/`rg` instead of `Grep`
- `find` instead of `Glob`

This applies to all file reading and searching in this repo.
