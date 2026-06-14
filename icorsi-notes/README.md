# icorsi-notes

Automatically propose study-note additions whenever `icorsi-sync` delivers new course material.

Watches each course's `_icorsi/` folder (written by `icorsi-sync`) and, when new content
arrives, invokes the `authoring-course-notes` Claude Code skill headlessly to produce the
**gap** - the topics present in the source but not yet in your live notes - and deposits it
in `Notes/_suggested/`. You review, edit if you like, and merge. The live notes are never
touched by the bot.

---

## How proposals appear

```
<your course folder>/
├── _icorsi/                ← written by icorsi-sync (read-only for this bot)
│   ├── 001 - Recursion/
│   └── 002 - Sorting/
└── Notes/
    ├── fondamenti_notes.typ  ← YOUR live notes (never touched by bot)
    ├── _notes.md             ← pipeline inventory (read-only for bot)
    └── _suggested/           ← BOT WRITES HERE ONLY
        ├── SUGGESTED.md      ← what's new + where to slot it in
        └── new_topics.typ    ← authored .typ (or .md) source to merge
```

You compile the final PDF with one command on your Nix PC:

```bash
CSNOTES="$HOME/nix/templates/krit/dev-environments/language-combined/cs-notes"
nix develop "$CSNOTES" --command typst compile Notes/fondamenti_notes.typ
```

---

## The one thing you'll edit: `courses.json`

Lives in the `/data` volume. Map each course folder (relative to `OWNCLOUD_BASE_PATH`) to
per-course options. Edit it anytime - no rebuild, picked up on next pass.

```json
{
  "0001 Tecnica Digitale": {
    "format": "typst",
    "notes_dir": "Notes"
  },
  "0003 Fondamenti di informatica/2-semestre": {
    "format": "typst",
    "notes_dir": "Notes"
  },
  "0004 Skip This": null
}
```

Options per entry:

| Option | Default | Meaning |
|---|---|---|
| `format` | `"typst"` | Output format: `"typst"` or `"markdown"` |
| `notes_dir` | `"Notes"` | Subfolder (beside `_icorsi/`) for live notes and `_suggested/` |
| `null` | - | Skip this course |

---

## Controlling when it runs

### Active-hours window (`ACTIVE_HOURS`)
By default the bot runs only between `01:00` and `07:00` (NAS local time) so it never
competes with your own Max subscription usage during the day. Change the window or set to
empty to run at any time.

### Instant pause
Create `/data/PAUSE` (e.g. `docker exec icorsi-notes touch /data/PAUSE`) to halt the bot
immediately. Delete it to resume. No restart needed.

### Hard stop
`docker stop icorsi-notes` (or stop the stack in Portainer). Safe at any point - a course's
fingerprint only advances after a successful run, so an interrupted course simply re-runs on
the next pass.

---

## Auth setup (one time)

The bot uses your **Claude Max subscription** via OAuth - there is no `ANTHROPIC_API_KEY`.
This means exhausting your plan limit triggers a configurable sleep (default 1 h), never API
billing.

1. Deploy the stack. The `/root/.claude` volume starts empty.
2. Run: `docker exec -it icorsi-notes claude` and complete the subscription OAuth login once.
3. The token persists in `${DOCKER_CONFIG_DIR}/icorsi-notes/claude/` and auto-refreshes there.

**Alternative:** copy `${DOCKER_CONFIG_DIR}/claude/data/.credentials.json` from `holyclaude`
into this volume - but a separate login avoids two containers racing the same token refresh.

---

## Settings

| Variable | Default | What it does |
|---|---|---|
| `OWNCLOUD_WEBDAV_URL` | - | ownCloud WebDAV URL (same as icorsi-sync) |
| `OWNCLOUD_USER` | - | ownCloud username |
| `OWNCLOUD_APP_PASSWORD` | - | ownCloud app password (secret) |
| `OWNCLOUD_HOST_HEADER` | - | Trusted domain for the HTTP Host header |
| `OWNCLOUD_BASE_PATH` | - | Base folder; courses.json paths are relative to this |
| `DISCORD_WEBHOOK_URL` | - | Optional Discord webhook for run summaries |
| `NOTES_INTERVAL_SECONDS` | `21600` | How often to check for new material (6 h) |
| `LIMIT_BACKOFF_SECONDS` | `3600` | Sleep time after hitting Max plan limit (1 h) |
| `ACTIVE_HOURS` | `01:00-07:00` | Window when Claude calls are allowed; empty = always |
| `RUN_ON_START` | `true` | Run a pass immediately on container start |
| `DRY_RUN` | `false` | List what would be proposed; invoke nothing |
| `CLAUDE_MODEL` | - | Force a specific Claude model (leave empty for default) |

---

## Notes quality

The bot runs the **full 4-stage authoring pipeline** (`cs-material-researcher` →
`cs-notes-author` → `cs-notes-formatter` → `cs-notes-auditor`) with the same models and
faithfulness audit loop as a desktop run. The only step skipped is `typst compile` / PDF
output - that intentionally stays in your Nix workspace, where you can review and recompile
on demand.
