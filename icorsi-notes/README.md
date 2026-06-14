# icorsi-notes

Automatically propose study-note additions whenever `icorsi-sync` delivers new course material.

Watches each course's `_icorsi/` folder (written by `icorsi-sync`) and, when new content
arrives, invokes the `authoring-course-notes` Claude Code skill headlessly to produce the
**gap** - topics present in the source but not yet in your live notes - and deposits proposals
in `<notes_dir>/_suggested/`. You review, edit if you like, and merge. The live notes are
never touched by the bot.

---

## How proposals appear

```
<your course folder>/
├── _icorsi/                  ← written by icorsi-sync (read-only for this bot)
│   ├── 001 - Topic A/
│   └── 002 - Topic B/
└── <notes_dir>/
    ├── my_notes.typ           ← YOUR live notes (never touched by bot)
    └── _suggested/            ← BOT WRITES HERE ONLY
        ├── SUGGESTED.md       ← what's new + where to slot it in
        └── new_topics.typ     ← authored source to review and merge
```

---

## The one thing you'll edit: `courses.json`

Lives in the `/data` volume (never in the image). Map each course folder - relative to
`OWNCLOUD_BASE_PATH` - to per-course options. Edit anytime; no rebuild needed.

```json
{
  "0001 Course Name": {
    "format": "typst",
    "notes_dir": "Notes"
  },
  "0002 Another Course/semester-2": {
    "format": "markdown",
    "notes_dir": "notes"
  },
  "0003 Skip This": null
}
```

Options per entry:

| Option | Default | Meaning |
|---|---|---|
| `format` | `"typst"` | Output format: `"typst"` or `"markdown"` |
| `notes_dir` | `"notes"` | Subfolder (beside `_icorsi/`) for live notes and `_suggested/` |
| `null` | - | Skip this course entirely |

Courses are processed **sequentially in file order**, one at a time.

---

## How it tracks progress

After each run, `<notes_dir>/_suggested/_notes.md` records what was authored and what remains:

```
## Coverage status
STATUS: COMPLETE
Authored: Topic A, Topic B, Topic C
Remaining: none
Continuation: yes
```

- `STATUS: COMPLETE` - course is skipped on future passes until new source material arrives.
- `STATUS: PARTIAL` - run was interrupted (window end, rate-limit, error); next pass resumes
  from `Remaining:` without re-reading sources.
- Missing file - treated conservatively as PARTIAL; bot will re-run the course.

The slow step (reading all source material) only happens **once per course**. After that, the
bot either skips (complete) or continues from the checkpoint (partial).

---

## Controlling when it runs

### Active-hours window (`ACTIVE_HOURS`)
The bot only makes Claude calls within a configured time window (default `00:00-03:00` local
time). This avoids consuming your Claude Max subscription during hours you use it yourself.
Set to empty to run at any time.

The bot will not start a new course if less than `MIN_TASK_WINDOW_SECONDS` remain before the
window ends. A course in progress at window end receives SIGTERM (graceful write) then SIGKILL,
and resumes cleanly on the next pass.

### Instant pause
Create `/data/PAUSE` (e.g. `docker exec icorsi-notes touch /data/PAUSE`) to halt immediately.
Delete it to resume. No restart needed.

### Hard stop
`docker stop icorsi-notes` is safe at any point. The checkpoint in `_suggested/_notes.md` is
updated after every section, so at most the current in-progress section is lost.

---

## Auth setup (one time)

The bot uses your **Claude Max subscription** via OAuth - there is no `ANTHROPIC_API_KEY`.
Exhausting your plan limit triggers a configurable sleep (default 1 h), never API billing.

1. Deploy the stack.
2. Run: `docker exec -it icorsi-notes claude` and complete the OAuth login once.
3. The token persists in `${DOCKER_CONFIG_DIR}/icorsi-notes/claude/` and auto-refreshes.

**Billing safety:** the bot refuses to start if any API-billing credential is present in the
environment (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, Bedrock/Vertex flags). If a non-zero
`total_cost_usd` ever appears in a Claude response, the bot writes `/data/HALT`, sends a
Discord alert, and stops until you remove the file manually.

---

## Settings

| Variable | Default | What it does |
|---|---|---|
| `OWNCLOUD_WEBDAV_URL` | - | ownCloud WebDAV URL |
| `OWNCLOUD_USER` | - | ownCloud username |
| `OWNCLOUD_APP_PASSWORD` | - | ownCloud app password (secret) |
| `OWNCLOUD_HOST_HEADER` | - | Trusted domain for the HTTP `Host` header |
| `OWNCLOUD_BASE_PATH` | - | Base folder; `courses.json` paths are relative to this |
| `DISCORD_WEBHOOK_URL` | - | Optional Discord webhook for per-pass summaries |
| `NOTES_INTERVAL_SECONDS` | `21600` | How often to check for new material (6 h) |
| `LIMIT_BACKOFF_SECONDS` | `3600` | Sleep after hitting the Max plan rate-limit (1 h) |
| `ACTIVE_HOURS` | `00:00-03:00` | Window when Claude calls are allowed; empty = always |
| `MIN_TASK_WINDOW_SECONDS` | `1800` | Minimum window remaining to start a new course |
| `WINDOW_GRACE_MINUTES` | `10` | Grace period for writes before hard kill at window end |
| `RUN_ON_START` | `true` | Run a pass immediately on container start |
| `DRY_RUN` | `false` | Log what would run; invoke nothing |
| `CLAUDE_MODEL` | - | Force a specific Claude model (leave empty for default) |

**Tip:** set `DRY_RUN=true` on first deploy to verify course discovery and rclone mount before
enabling live runs.

---

## Notes quality

The bot runs the full 4-stage authoring pipeline baked into the image:

1. **`cs-material-researcher`** - inventories all topics in the source material
2. **`cs-notes-author`** - writes detailed notes for each gap topic
3. **`cs-notes-formatter`** - formats output in the chosen format (Typst or Markdown)
4. **`cs-notes-auditor`** - checks for omissions, inventions, and formatting errors

Agents and skills are merged into the container's `~/.claude/` on startup, while OAuth
credentials on the same volume are preserved across rebuilds.
