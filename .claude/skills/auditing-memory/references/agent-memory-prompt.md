# Agent brief: audit agent-memory files against the repo

Same classification as `user-memory-prompt.md` (read it first; every rule there applies), with these differences.

- Store: `<repo>/.claude/agent-memory/docker-compose-architect/` (git-tracked; the only agent with memory here -
  re-enumerate, others may appear). Files are per-service notes (`<svc>_service.md`), public-wiring notes and
  lesson files. Your files: `<FILE_LIST_PATH>` (paths relative to the repo). Touch nothing outside
  `.claude/agent-memory/`.
- The shared `MEMORY.md` index of the agent dir is NOT yours. Report `INDEX:` lines for REWRITTEN files and
  `INDEX-REMOVE: <agent-dir>/<file>` for DELETED files.
- Per-service notes have a direct counterpart: the service's `docker-compose.yml`, its `.env.example`, and its
  row in `.claude/rules/service-directory.md`. Check container names, images/pins, networks, subnets, router
  names, volumes, healthchecks, env var names, published ports against them. A lesson about a mechanism or
  trap that still exists in the repo counts as having a counterpart. A lesson about something fixed or removed
  is HISTORICAL. A tool/format recipe with no repo counterpart is RECIPE.
- Prefix every report line's file with `<agent-dir>/`.
