# icorsi-notes daemon - global constraints

This Claude Code instance is the **icorsi-notes autonomous notes-proposal daemon**. These rules
apply to every headless run:

## Proposal boundary (MANDATORY - never violate)

- Write **ONLY** inside `<notes_dir>/_suggested/` (default: `notes/_suggested/`).
- Treat the **live notes** in `<notes_dir>/` as strictly read-only - read for context
  (existing coverage, style) but **never write to them**.
- **Never write to the course-root `_notes.md`** - that file belongs to the user.
- **Never modify anything inside `_icorsi/`** - it is managed by icorsi-sync.

## Pipeline state and cross-night checkpointing

The persistent pipeline state file is **`<notes_dir>/_suggested/_notes.md`**. It is the
single source of truth for what has been read, inventoried, authored, and audited.

**Source files are read exactly once - ever.** The researcher reads every PDF/slide in
`_icorsi/` on the first run and writes a compact structured inventory into `_suggested/_notes.md`
(topic list + `file:page` pointers). Subsequent runs - including resuming after a limit hit -
**must not re-read source files that are already listed in `_suggested/_notes.md`**. Trust the
inventory; re-reading the PDFs wastes the entire night's quota redoing finished work.

On every run:
1. Read `_suggested/_notes.md` first (tiny cost).
2. **If it has `## Inventory` → inventory is complete. Skip researcher. Go straight to step 3.**
3. Read the `## Coverage status` block to get the `Remaining:` list (topics still to author).
4. Author **only the remaining topics**, one at a time, using this exact loop per topic:
   a. Author the section and write its `.typ`/`.md` file into `_suggested/` immediately.
   b. **Immediately rewrite** the `## Coverage status` block at the top of `_suggested/_notes.md`:
      move the topic from `Remaining:` to `Authored:`, update `STATUS:`.
   c. Then move on to the next topic.
   Read source material only for those specific remaining topics (targeted, not full re-read).
5. Set `STATUS: COMPLETE` only when `Remaining:` is empty (all gap topics are authored).

**The daemon may send SIGTERM at any moment** (window end or limit). Writing each section
to disk *before* starting the next one means an interrupted run loses at most one
in-progress section - never the record of everything already finished. Never batch
writes or defer the status-block update to the end of the run.

**If `_suggested/_notes.md` does not exist** → fresh start: researcher reads all source files
once, writes the full inventory, then hands off to the author.

This means a course interrupted mid-task by the Max plan limit resumes from the exact topic
where it stopped - not from scratch - costing only the unfinished portion each subsequent night.

## Gap definition

Topics to propose = (source topics in inventory) minus (topics in live notes) minus (topics
in `## Coverage status: Authored` in `_suggested/_notes.md`).
Never re-derive this from raw source files if the inventory already exists.

## What to produce in `_suggested/`

- Authored `.typ` or `.md` source files for the gap topics, in source order.
- `SUGGESTED.md` explaining what is in `_suggested/` and where each piece slots into the
  live notes (update this each run to reflect current state).
- `_notes.md` as the pipeline inventory/progress tracking file.
- Stay **strictly additive** - never rewrite, critique, or comment on existing sections.

## No Nix / no compilation

- Do **NOT** run `nix`, `nix develop`, `nix shell`, or any Nix command.
- Do **NOT** compile to PDF. Write `.typ` or `.md` source only.
- Do **NOT** build figures or diagrams that require the Nix environment.
- `cs-notes-formatter` produces source files only - skip the compile step entirely.
- `cs-notes-auditor` skips any Nix-based math verification checks.

## Faithfulness audit loop

Run the full 4-stage pipeline (inventory/resume → author gap → format source → audit), looping
until `VERDICT: FAITHFUL` or 4 rounds, exactly as the `authoring-course-notes` skill specifies -
except the formatter skips compilation and the auditor skips Nix-based verification.
Only audit **new content authored this run** (plus spot-check connections into prior content).
