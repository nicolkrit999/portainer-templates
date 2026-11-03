# Gotcha: `icorsi-sync` StackGitRedeploy needs an explicit `endpointId`

The `icorsi-sync` Portainer stack (id `265`) once had no stored endpoint
association in Portainer's database (`StackList` shows `EndpointId: 3` for it
on 2026-11-04, so this may have healed; UNVERIFIED whether the 404 still
occurs). Calling
`mcp__portainer__StackGitRedeploy` on it **without** an explicit
`endpointId` parameter 404s with `"Unable to find the environment
associated to the stack inside the database"` - even though other stacks in
this environment redeploy fine without passing it (it's normally inferred
from the stack `id`).

**How to apply:** keep passing `endpointId: 3` explicitly on every
`StackGitRedeploy` call for `icorsi-sync` (harmless if the stack is fixed, needed
if not). This is in addition to, not instead of, the mandatory full-`Env`
resupply rule in `.claude/rules/portainer-instance.md` - both apply
together on this stack.

Discovered 2026-09-28 during the third recurrence of the icorsi-sync token
outage (see `icorsi-sync/README.md` for the outage/recovery procedure
itself).
