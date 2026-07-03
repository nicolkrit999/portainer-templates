---
name: authoring-course-notes
description: "Use this skill when creating detailed study notes or course documentation from source material and (optionally) compiling them to PDF - for any CS or math course (linear algebra, calculus, discrete math, statistics, programming). Triggers: 'make notes for this chapter', 'write detailed notes on …', 'turn this course material into a PDF', 'create documentation explaining every topic in …', 'compile these notes to PDF', 'typst/latex notes for …'. Works from ANY course folder (callable by name without an absolute path). Orchestrates reading the source → authoring the explanations → formatting/compiling through the project's `cs-notes` Nix dev environment (Typst, LaTeX via Tectonic, Pandoc, diagrams, plotting, Python). Use whenever study notes / documentation should be produced as a polished file, especially when LaTeX/Typst/PDF compilation is involved. NOT for a page-capped exam cheat sheet (maximal density fitted to a hard page limit) - that's creating-exam-cheat-sheets."
---

# Authoring course notes

Produce detailed, faithful study notes/documentation from course material and compile them to a polished file. Works from any folder - you do **not** need to be inside the school workspace.

## Pipeline (four stages)

1. **Inventory the source** - read every relevant file in the course material (folders, PDFs, slides) and build an exhaustive, structured list of topics, definitions, theorems, formulas, and worked examples actually present.
2. **Author the notes** - for each topic write the substance: what it is (first principles), properties/rules, worked example(s) (reuse the source's if present, else construct them), tips/tricks for pattern-recognition, and connections between topics. Domain-agnostic - math gets the same rigor as programming.
3. **Format & compile** - choose the format and produce the final file (see below).
4. **Audit & fix-loop** - verify the produced notes are faithful to the source, then loop fixes until they are (see **Audit loop** below). The work is **not done** until this passes.

**Delegation:** if the school `cs-*` agents are available in this session (you're in/under the school workspace), delegate each stage to them - `cs-material-researcher` (stage 1), `cs-notes-author` (stage 2), `cs-notes-formatter` (stage 3), `cs-notes-auditor` (stage 4). If they are **not** available (e.g. the chat was opened directly in an owncloud course folder), perform the stages yourself, optionally via general-purpose subagents (haiku to inventory, sonnet to author/audit).

## Audit loop (stage 4 - do not skip)

A subagent cannot call another subagent, so **you (the orchestrator) drive the loop**:

1. Run `cs-notes-auditor` on the finished notes - it compares the notes against the inventory **and** the original source and returns a discrepancy report ending in `VERDICT: FAITHFUL` or `VERDICT: NEEDS FIXES`. Each finding names a **fix owner**.
2. If `VERDICT: FAITHFUL` → done, stop. Report the clean result to the student.
3. If `VERDICT: NEEDS FIXES` → dispatch the fix owners to correct **exactly** the cited findings:
   - need the correct value/example re-pulled from the source first → `cs-material-researcher` (re-extract the right information), then
   - content errors / omissions / inventions / improved explanations → `cs-notes-author` (rewrite or add the affected sections), and
   - loss or breakage from formatting/compilation → `cs-notes-formatter` (reformat/recompile).

   Then go back to step 1 and **re-audit the whole document** (a fix can introduce a new defect).
4. Repeat the cycle - audit → retrieve/rewrite → re-audit - until the auditor returns `FAITHFUL`. Safeguard: if it hasn't converged after ~4 rounds, stop and report the remaining findings to the student rather than looping forever.

Only when the auditor returns `FAITHFUL` is the task complete.

## Format choice

- **Typst** - default for math/CS notes: fast, lightweight, great math. Its own package ecosystem (cetz, etc.) is auto-fetched by `typst`.
- **LaTeX** - when the doc needs it; compiled with **Tectonic** (fetches only the packages each doc uses - no multi-GB TeX Live).
- **Markdown → PDF** - via `pandoc --pdf-engine=tectonic`.

## Document setup conventions

Both formats have a mandatory standard template - see `./typst-and-latex-document-templates.md` for the full copy-paste code. Adapt the metadata placeholders (`SUBJECT`, `CHAPTERS_LABEL`, `LANG`, `SUBTITLE_TOPICS`, `YEAR`) but keep the structure and style intact.

### Personal additions

**Any content not from the professor / not from iCorsi is a personal addition.** This includes extra explanations, expanded calculations, self-constructed examples, analogies, and mnemonics - anything you cannot point to on a slide or iCorsi PDF.

These MUST be wrapped in the `personal-addition` block defined in the template. The auditor flags unmarked non-source material as an **invention defect**.

Rule: if you cannot cite the exact slide or PDF page → wrap it in `personal-addition`.

## The `cs-notes` environment (how to compile)

All compilation tools live in ONE Nix dev environment so nothing has to be installed in course folders. **Always invoke tools through it**, and **always redirect the (potentially large, one-time) build log to a file so it never floods context** - see `./compiling-in-the-cs-notes-env.md` for the exact, copy-paste recipes (env path, the redirect-and-tail pattern, per-format commands, and the ad-hoc-package rule).

Key points (full detail in that file):
- Compile via `nix develop "$HOME/nix/templates/krit/dev-environments/language-combined/cs-notes" --command <tool> …`.
- First use builds the env once; **redirect that build to a logfile and surface only `READY` / a short failure tail** - token cost stays ~zero regardless of build size.
- **Ad-hoc tools:** if you need a tool not in the env, use it one-off with `nix shell nixpkgs#<pkg> --command …` (redirect the build), then **tell the user to add `<pkg>` to the flake** at `…/language-combined/cs-notes/flake.nix` so it's permanent next time.

## Output location

Write the notes (and the compiled PDF) **in the course folder the work is about** - i.e. the current working directory, or wherever the user points. No scratch-and-move dance is needed; the env is invoked by path, the output lands where the course is.

## Update / incremental mode (existing notes present)

If notes for this course already exist (new slides/chapters were added, not a fresh start), **do not regenerate** - append the delta:
1. **Bootstrap `_notes.md` if it doesn't exist.** If there is no `_notes.md` in the course folder (notes were produced before the pipeline tracking system), have `cs-material-researcher` read the existing notes file first and write a `## Existing coverage` section to `_notes.md` listing every topic already covered. This is a one-time cost that makes all future incremental runs and resumptions free. Do this before inventorying any new material.
2. Inventory **only the new material** - don't re-read source already covered.
3. Read the **existing notes** (already compact, cheap) so the author can place new topics in the right order and link "connections" to what's there.
4. Author **only the new topics** and insert them in source order; leave existing sections untouched unless the new material corrects them.
5. Compile, then **audit only the new sections** (plus spot-check the connections into existing ones). Notes have no page cap, so appending is cleanly additive.

Trigger this when the user says "add/append the new chapter", "update the notes with these slides", etc. It turns a full rebuild into a delta-sized job.

## Persistent pipeline file (`_notes.md`)

`cs-material-researcher` writes its inventory to **`_notes.md`** in the course folder; `cs-notes-author` appends a coverage-status section; `cs-notes-auditor` appends each audit round's findings. This file persists across sessions and reboots - any new chat can read it to resume, and the student can feed it to NotebookLM or any other tool. Never overwrite it; always append.

## Faithfulness

Cover every topic in the source; follow its structure and depth. Reuse the source's own examples (cite them); only add material beyond the course explicitly. Never silently drop hard topics.
