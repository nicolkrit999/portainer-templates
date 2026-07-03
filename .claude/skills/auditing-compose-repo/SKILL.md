---
name: auditing-compose-repo
description: Use this skill when the user wants a repo-wide check across services that already exist in this Portainer homelab repo. Trigger phrases include 'audit my composes', 'security check the repo', 'are my composes consistent', 'sweep all services', 'check the whole repo for violations'. It runs compose-security-auditor and compose-consistency-linter across all ~70 service directories in parallel, triages the combined findings by severity with the user, dispatches docker-compose-architect to apply exact fixes, and re-runs only the affected reviewer(s) on the changed services. It does NOT cover onboarding a brand-new service (use adding-compose-services for that, which includes its own scoped review loop) and it does NOT edit files itself - all fixes are applied by docker-compose-architect.
---

# Auditing the Compose Repo

Orchestrated in the main chat. You (the orchestrator) dispatch each agent below
in order and loop the fix step - agents cannot call each other.

## Agent loop

1. **SWEEP** - dispatch `compose-security-auditor` and
   `compose-consistency-linter` repo-wide, in parallel. Each fans out over all
   service directories (`**/docker-compose.yml`) in its own context and returns
   a compact report - this keeps the scan itself out of the main token budget.

2. **TRIAGE** - merge both reports into one findings table, ordered by
   severity (CRITICAL, HIGH, MEDIUM, LOW). If the list is large, ask the user
   which findings to fix; CRITICAL secrets findings are always fixed first,
   without waiting for the user to prioritize.

3. **FIX** - dispatch `docker-compose-architect` with the exact findings to
   address (file, finding, required fix). Reviewers never edit files
   themselves - all changes go through the architect.

4. **RE-CHECK** - re-run only the reviewer(s) whose findings were just
   addressed (don't re-run the linter if only security findings were fixed,
   and vice versa), scoped to the changed services rather than the whole repo
   when possible.

5. Repeat steps 3→4 up to 3 cycles total. If findings remain open after cycle
   3, stop looping and report them to the user instead of continuing.

## Exit condition

No open CRITICAL or HIGH findings remain. MEDIUM/LOW findings may remain open
only if the user has explicitly accepted them - do not treat silence as
acceptance.

## Out of scope

- Bringing a new service into the repo - that's `adding-compose-services`,
  which runs its own research → build → scoped review loop for the one new
  file instead of a repo-wide sweep.
