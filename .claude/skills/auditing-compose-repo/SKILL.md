---
name: auditing-compose-repo
description: Use this skill whenever the user wants a repo-wide check across services that already exist in this Portainer homelab repo - 'audit my composes', 'security check the repo', 'are my composes consistent', 'sweep all services', 'check the whole repo for violations', 'lint everything', or after a large refactor to confirm nothing drifted. It runs compose-security-auditor and compose-consistency-linter across all ~95 compose files in parallel, merges and triages the findings by severity with the user, has docker-compose-architect apply exact fixes, and re-runs only the affected reviewer on the changed services. NOT for onboarding a new service (adding-compose-services has its own scoped review loop); it never edits files itself, all fixes go through the architect.
---

# Auditing the compose repo

You (the orchestrator, in the main chat) dispatch the agents in order and loop the fix step. Agents cannot call each other. The two reviewers are read-only and fan out over every compose file in their own context, which keeps a ~95-file scan out of the main token budget; what each one checks is defined in its own agent file and in `.claude/rules/`, so it is not repeated here.

## Loop

1. **Sweep.** Dispatch `compose-security-auditor` and `compose-consistency-linter` repo-wide, in parallel (`**/docker-compose.yml`, including `actual-budget/*/`). Tell each the objective: a repo-wide check against the current access model (two routers per service, bare TLS, wildcard certificate, `traefik-public` as the only public path).

2. **Triage.** Merge both reports into one table ordered CRITICAL, HIGH, MEDIUM, LOW. Fix CRITICAL secrets findings first without waiting for the user. For a long list, ask the user which of the rest to fix. Separate real deviations from deliberate leftovers (stacks kept in the repo but not deployed still follow the rules; the core stacks are exempt from the router checklist).

3. **Fix.** Dispatch `docker-compose-architect` with the exact findings (file, finding, required fix). It also lists any `${VAR}` that the live Portainer env must gain or lose. Reviewers never edit, because a reviewer that fixes its own findings stops being independent.

4. **Re-check.** Re-run only the reviewer whose findings were addressed, scoped to the changed services when possible.

5. Repeat fix and re-check up to 3 cycles in total; then report what is still open instead of iterating further.

## Done when

No CRITICAL or HIGH finding is open. MEDIUM and LOW may stay open only if the user explicitly accepted them; silence is not acceptance. Remind the user that fixed compose files reach Portainer through a redeploy with the stack's full `Env` re-supplied (`.claude/rules/portainer-instance.md`).
