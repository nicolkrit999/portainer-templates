---
description: Instance-specific operational rules for this Portainer setup - MCP tools and migration workflow.
---

# Portainer instance

## MCP tools

Use `mcp__portainer__listLocalStacks` and `mcp__portainer__dockerProxy` (environmentId: 3).
Never try `listStacks`, `getStackFile`, or `listEnvironments` - they always return 503 on this instance.

- List stacks → `mcp__portainer__listLocalStacks`
- Inspect containers/config → `mcp__portainer__dockerProxy` with `GET /containers/json`

## Migration workflow (.env files)

When extracting stacks from Portainer and creating `.env` files:

- `/home/krit/momentary/portainer-env/<service>/.env` - **real values including secrets** (private, never committed)
- `.env.example` in the repo - placeholder values (`your-password-here`)

Never leave secrets empty in the momentary `.env`. If the original stacks are deleted and secrets were not captured, they are permanently lost.
