# claude-home - synced copies, do not edit here

This directory holds **manual copies** of agents and skills whose source of
truth lives in `~/dotfiles-private/claude/`. Edit there, then re-sync here.

## What's copied

- `agents/cs-material-researcher.md`, `agents/cs-notes-auditor.md`,
  `agents/cs-notes-author.md`, `agents/cs-notes-formatter.md` - copies of the
  4 agents in `~/dotfiles-private/claude/school/.claude/agents/`.
- `skills/authoring-course-notes/` - a copy of
  `~/dotfiles-private/claude/parked/authoring-course-notes/`.

**The dotfiles-private versions are the source of truth.** Never edit the
copies in this directory directly - edit the source, then re-sync.

## Re-sync commands

```bash
cp ~/dotfiles-private/claude/school/.claude/agents/cs-material-researcher.md ~/github-repos/personal/portainer-templates/icorsi-notes/claude-home/agents/cs-material-researcher.md
cp ~/dotfiles-private/claude/school/.claude/agents/cs-notes-auditor.md ~/github-repos/personal/portainer-templates/icorsi-notes/claude-home/agents/cs-notes-auditor.md
cp ~/dotfiles-private/claude/school/.claude/agents/cs-notes-author.md ~/github-repos/personal/portainer-templates/icorsi-notes/claude-home/agents/cs-notes-author.md
cp ~/dotfiles-private/claude/school/.claude/agents/cs-notes-formatter.md ~/github-repos/personal/portainer-templates/icorsi-notes/claude-home/agents/cs-notes-formatter.md
cp -r ~/dotfiles-private/claude/parked/authoring-course-notes/. ~/github-repos/personal/portainer-templates/icorsi-notes/claude-home/skills/authoring-course-notes/
```

## Drift check

```bash
for f in cs-material-researcher cs-notes-auditor cs-notes-author cs-notes-formatter; do
  diff ~/dotfiles-private/claude/school/.claude/agents/$f.md ~/github-repos/personal/portainer-templates/icorsi-notes/claude-home/agents/$f.md
done
diff -r ~/dotfiles-private/claude/parked/authoring-course-notes/ ~/github-repos/personal/portainer-templates/icorsi-notes/claude-home/skills/authoring-course-notes/
```

## Exception

`CLAUDE.md` in this directory is **NOT** a copy - it is the icorsi-notes
daemon's own constraints file and is edited here directly.
