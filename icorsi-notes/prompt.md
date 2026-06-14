Use the `authoring-course-notes` skill to PROPOSE study-note additions for the course in the current directory, from the material in its `_icorsi/` folder as the source.

**Pipeline state file:** use `<notes_dir>/_suggested/_notes.md` as the persistent cross-night checkpoint. The daemon reads its `## Coverage status` block to decide whether to resume or start fresh, and reads `STATUS:` after every run to decide whether the course is complete.

**Incremental writes (CRITICAL - do NOT batch at the end):** author **one section at a time**. Immediately after finishing each section: (1) write that section's `.typ`/`.md` file into `<notes_dir>/_suggested/`, then (2) rewrite the `## Coverage status` block at the top of `<notes_dir>/_suggested/_notes.md` to reflect the current state. The daemon may send SIGTERM at any moment (window end, limit, stop), so the on-disk state must always be up-to-date. Losing the one in-progress section is acceptable; losing the record of everything already done is not.

**Status block format** (rewrite after every section, keep at top of `_notes.md`):
```
## Coverage status
STATUS: COMPLETE
Authored: Topic A, Topic B, Topic C
Remaining: none
Continuation: yes
```
Use `STATUS: PARTIAL` until `Remaining` is empty, then set `STATUS: COMPLETE`. `Continuation: yes` if `_suggested/_notes.md` already had content when this run started.

**Resuming a partial run:** if `<notes_dir>/_suggested/_notes.md` already exists with an inventory, skip the inventory stage and continue from the `Remaining:` list. Do not re-read source files already listed in the inventory; do not re-author topics already in `Authored:`.

**Gap calculation:** the topics to propose are those present in `_icorsi/` source but absent from BOTH the live notes in `<notes_dir>/` AND `Authored:` in the status block. Read the live notes to understand existing coverage and match style (read-only). Write **only** into `<notes_dir>/_suggested/`.

**On completion:** update or create `<notes_dir>/_suggested/SUGGESTED.md` summarising what is in `_suggested/` and where each piece slots into the live notes.

Stay **strictly additive** - never rewrite or comment on existing sections in the live notes. Run the faithfulness audit loop on all new content authored this run. Do **not** compile to PDF, run `nix`, or build figures requiring the Nix environment. Never modify the live notes, the course-root `_notes.md`, or anything inside `_icorsi/`.

When done, output a one-line summary: whether this was a continuation, what was authored, and how many sections remain (e.g. "Continued: authored 2 sections (Sorting, Graph Traversal); 3 remain" or "Completed: authored 5 sections; none remain").
