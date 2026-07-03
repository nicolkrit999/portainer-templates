---
name: syncing-icorsi-copies
description: Use this skill when checking whether the manual copies of the icorsi-notes claude-home agents and skill have drifted from their dotfiles-private source, or re-syncing them after an edit. Triggers include 'sync the icorsi copies', 'check icorsi drift', 'did the icorsi agents drift', 're-sync claude-home', 'I edited the school agents', or any edit to the school cs-material-researcher/cs-notes-auditor/cs-notes-author/cs-notes-formatter agents or the authoring-course-notes skill in ~/dotfiles-private/claude/. Does NOT cover editing the agents or skill content itself (edit in dotfiles-private, then invoke this skill to propagate) and does NOT cover icorsi-notes/claude-home/CLAUDE.md, which is not a copy and is edited in place.
---

# Syncing icorsi copies

`icorsi-notes/claude-home/` in this repo holds manual copies of 4 agents
(`cs-material-researcher.md`, `cs-notes-auditor.md`, `cs-notes-author.md`,
`cs-notes-formatter.md`, sourced from
`~/dotfiles-private/claude/school/.claude/agents/`) and one skill directory
(`skills/authoring-course-notes/`, sourced from
`~/dotfiles-private/claude/parked/authoring-course-notes/`).

The authoritative command list - both the diff commands and the re-copy
commands - lives in `icorsi-notes/claude-home/README.md`. Always read that
README before acting; do not hardcode or duplicate its commands here, since
it may be updated independently of this skill.

This is a mechanical, single-agent procedure - no agent loop is needed.

## Procedure

1. Read `icorsi-notes/claude-home/README.md` and run the drift-check diffs it
   documents (the 4 agent file diffs plus the `diff -r` on
   `authoring-course-notes/`).
2. If every diff is empty: report "in sync" and stop.
3. If any diff shows drift, determine direction before touching anything:
   - Source of truth is **always** `~/dotfiles-private/claude/...`. If the
     drift is because the source changed and the copy is stale, re-copy
     source → copy using the exact commands from the README.
   - If the **copy** has changes the source lacks (someone edited
     `claude-home` directly, which the README forbids), STOP and ask the
     user before overwriting anything. Never silently discard those edits -
     they may need to be ported back into dotfiles-private first.
4. After re-copying, re-run the same drift-check diffs to confirm every one
   is now empty. Report exactly which files were re-synced (by path), or
   confirm nothing needed re-syncing.

## Exit condition

All diffs listed in the README (4 agent files + the `authoring-course-notes`
directory diff) come back empty.

## Out of scope

- Editing agent or skill content: make the change in
  `~/dotfiles-private/claude/...` first, then invoke this skill to propagate
  it - this skill only copies, it does not author content.
- `icorsi-notes/claude-home/CLAUDE.md`: this is the daemon's own constraints
  file, not a copy of anything, and is edited in place - never diffed or
  re-synced.
