# Working notes for long multi-agent jobs (public-access rollout)

Findings from long jobs are kept in files that the coordinator and every subagent re-read on demand, instead of being carried in context or retyped into prompts.

- **Folder:** `/home/krit/momentary/proxy-research/` (outside the repo, private; may contain operational detail, never secrets). Entry point: its `README.md`.
- **Before working on a service:** read `README.md`, `BATCHES.md`, `findings/<service>.md`, `findings/cross-cutting.md` and `findings/subnets.md`. A fact that is not in a file is not known.
- **While working:** append dated entries (`## YYYY-MM-DD HH:MM <who>: <title>`) marked VERIFIED (with how) or UNVERIFIED. Do not rewrite history; corrections are new entries.
- **When reporting back:** at most about 15 lines (what changed, which file has the details, what is open). Long text goes into the findings file.
- **Subnets:** every new backend network takes an explicit /28 from `findings/subnets.md`; add it to the registry before editing the compose.
- **Decisions and user preferences** go into the project memory plan file (`public-access-no-cloudflare-plan-2026-11-03.md`), kept short.
