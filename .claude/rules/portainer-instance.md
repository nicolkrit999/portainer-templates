---
description: Instance-specific operational rules for this Portainer setup - MCP tools and migration workflow.
---

# Portainer instance

## MCP tools

Environment ID is `3` for every call below. Confirmed working 2026-08-22
(this server's connection has intermittently thrown a persistent
`[SSL: CERTIFICATE_VERIFY_FAILED]` error across sessions for no discernible
reason - if a call fails this way, just retry later in the same session
rather than assuming the tool itself is broken; it cleared on its own more
than once this session).

- List stacks → `mcp__portainer__StackList` (project with `select` to
  `{id:Id,name:Name}` - stack names are **not unique**, duplicates happen,
  see the 2026-08-22 memory on this)
- Inspect a stack's live env vars → `mcp__portainer__StackInspect` with
  `select: Env`
- Inspect a stack's current compose file content →
  `mcp__portainer__StackFileInspect`
- Update a stack's env/file → `mcp__portainer__StackUpdate` - **⚠️ silently
  detaches the stack from git tracking if it was originally a git-stack**
  (`GitConfig` becomes `null`). Confirmed 2026-08-22 after using this on 6
  live git-tracked stacks. Do not use this on a stack you know or suspect
  is git-tracked unless you've confirmed with the user that the detachment
  is acceptable - prefer letting a repo-committed fix reach the stack via
  the normal git-poll cycle instead, even if that means a few minutes'
  delay.
- Inspect/manage containers, or exec into one to test connectivity → `mcp__portainer__docker_proxy`
  with `GET /containers/json`, or `POST /containers/{id}/exec` +
  `POST /exec/{execId}/start` (needs `headers: {"Content-Type": "application/json"}`
  on both calls or the API 400s) - useful for testing whether a container
  can actually reach a given backend target, e.g. confirmed 2026-08-22 that
  Traefik's own container cannot route to the NAS's LAN IP directly, only
  to `host.docker.internal`.
- Read container logs → `mcp__portainer__docker_proxy` with
  `GET /containers/{name}/logs?stdout=true&stderr=true&tail=N` - responses
  over ~50K chars get saved to a file; grep that file rather than reading
  it whole, and decode it as JSON first if grepping literal `` ANSI
  codes doesn't match (the raw file is JSON-string-escaped).
- `get_guidance` (call once per session before heavy use) covers response
  projection via `select`, redaction behavior, and safe-mutation patterns
  in more depth than this file does.

## Migration workflow (.env files)

When extracting stacks from Portainer and creating `.env` files:

- `/home/krit/momentary/portainer-env/<service>/.env` - **real values including secrets** (private, never committed)
- `.env.example` in the repo - placeholder values (`your-password-here`)

Never leave secrets empty in the momentary `.env`. If the original stacks are deleted and secrets were not captured, they are permanently lost.
