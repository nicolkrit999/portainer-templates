---
description: Instance-specific operational rules for this Portainer setup - MCP tools and migration workflow.
---

# Portainer instance

## MCP tools

Environment ID is `3` for every call below (`docker_proxy` takes it as
`environment_id`; `StackUpdate`/`StackGitRedeploy` as `endpointId`). Call
`get_guidance` once per session first (the server refuses every other call until
then); it covers `select` projection and safe-mutation patterns in more depth.

`[SSL: CERTIFICATE_VERIFY_FAILED]` errors are intermittent: retry later in the
same session. If every call 404s and a direct `curl` to the Portainer UI also
fails, suspect the MCP server's own `PORTAINER_URL` (`.mcp.json`) before
assuming an outage: it must be a plain `https://<host>` (port 443) name that the
`portainer` (private) / `portainer-tailnet` routers serve, reachable from where the
session runs (LAN or tailnet).

- **List stacks** → `StackList`, `select: "[].{id:Id,name:Name}"`. Stack names
  are **not unique** (duplicates happen): resolve by id.
- **Live env vars** → `StackInspect` (`id`, `select: "Env"`). Values are NOT
  redacted on this server: never print them, show names only (`Env[].name`)
  unless the user needs a value. A literal `[REDACTED]` is a placeholder, never
  pass it back into a redeploy.
- **Current compose file** → `StackFileInspect` (`id`).
- **Update env/file** → `StackUpdate` (`id`, `endpointId`, `Env`,
  `StackFileContent`). **⚠️ Silently detaches a git-tracked stack from git**
  (`GitConfig` becomes `null`; confirmed 2026-08-22 on 6 stacks). Do not use it
  on a stack that is or may be git-tracked unless the user accepts that; let a
  repo-committed fix arrive through the normal git-poll cycle.
- **Redeploy a git-tracked stack** → `StackGitRedeploy` (`id`, `endpointId`,
  `Env`; add `RepullImageAndRedeploy: true` only to force an image re-pull).
  Leave `RepositoryReferenceName` and the other `Repository*` fields unset. It
  does not touch `GitConfig`, so it is also the tool for env-only fixes.
  **⚠️ MANDATORY: always call `StackInspect(id, select: "{env:Env}")` first and
  pass the full returned list back as `Env` on the redeploy, every time, even
  for a plain "pull the latest commit".** Omitting `Env` does not preserve the
  stack's env: it wipes it and deploys every `${VAR}` blank (2026-08-22: n8n
  crash-looped on blank `N8N_ENCRYPTION_KEY`/`POSTGRES_PASSWORD`, sparkyfitness
  refused to init its DB; both recovered only because the secrets were still
  known). If `StackInspect` already returns `Env: null`, an earlier redeploy
  wiped it: **do not guess or invent values**, stop and ask the user for the real
  secrets. Treat every `StackGitRedeploy` as env-destructive unless the full env
  was just re-supplied in that exact call. Incident:
  [[portainer-stackgitredeploy-env-wipe]] (project memory).
- **Containers, exec, connectivity tests** → `docker_proxy`: `environment_id`,
  `method`, `path` (e.g. `/containers/json`), optional `query_params` (a map;
  never a `?query` inside `path`), `body`, `headers`, `select`. Exec is
  `POST /containers/{id}/exec` then `POST /exec/{execId}/start`, both with
  `headers: {"Content-Type": "application/json"}` or the API answers 400; the
  output is a multiplexed binary stream, so use commands whose success or
  failure is all you need (`ls -ld`, `nc -z`).
- **Container logs** → `docker_proxy` `GET /containers/{name}/logs` with
  `query_params: {stdout: "true", stderr: "true", tail: "200"}` (without
  `stdout`/`stderr` Docker answers 400; never `follow`). `select` is ignored for
  logs. Responses over ~50K chars are saved to a file: grep that file instead of
  reading it, and decode it as JSON first if grepping literal ANSI codes does not
  match (the raw file is JSON-string-escaped).
- **Container inspect** → `docker_proxy` `GET /containers/{name}/json`, projecting
  only what you need (`Mounts[].{Type,Source,Destination}`). Never select
  `Config.Env`: it is not redacted (project memory
  `portainer-container-inspect-not-redacted`).

## Migration workflow (.env files)

When extracting stacks from Portainer and creating `.env` files:

- `/home/krit/momentary/portainer-env/<service>/.env` - **real values including secrets** (private, never committed)
- `.env.example` in the repo - placeholder values (`your-password-here`)

Never leave secrets empty in the momentary `.env`. If the original stacks are deleted and secrets were not captured, they are permanently lost.
