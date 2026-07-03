# Compiling in the `cs-notes` Nix environment

All LaTeX/Typst/Markdown/diagram/plot tooling lives in one Nix devShell so nothing is installed in course folders. Invoke every tool **through** it.

## Env path (cross-platform)

```bash
CSNOTES="$HOME/nix/templates/krit/dev-environments/language-combined/cs-notes"
```

`$HOME` resolves correctly on both Linux (`/home/krit`) and macOS (`/Users/krit`). The flake provides: `typst`, `typstyle`, `tectonic`, `pandoc` (+ `pandoc-crossref`), `graphviz`, `d2`, `plantuml`, `mermaid-cli`, `gnuplot`, `poppler-utils`, `ghostscript`, `imagemagick`, `qpdf`, `librsvg` (`rsvg-convert`), `inkscape`, `jq`, `hunspell` (EN+IT dicts), and a Python 3.13 stack (numpy, scipy, sympy, matplotlib, seaborn, pandas, statsmodels, scikit-learn, networkx, ipython, pygments).

## Step 1 — ensure the env is built (silent, token-safe)

The **first** use on a machine builds/downloads the closure once (~1.5 GB, cached → minutes, not interactive). Redirect that build to a logfile so its output never enters context — surface only a one-word status:

```bash
nix develop "$CSNOTES" --command true > /tmp/cs-notes-env.log 2>&1 && echo READY || tail -n 30 /tmp/cs-notes-env.log
```

- `READY` → env is built; proceed. Subsequent calls are instant and silent.
- Otherwise the `tail` shows only the last 30 log lines (the actual error), not the whole build.

Do **not** run a bare `nix develop … --command true` without the redirect — a cold build would dump thousands of progress lines into the conversation.

## Step 2 — compile (small output; keep visible for real errors)

Once `READY`, run the format-specific command. These print little, so no redirect is needed (you want to see compile errors):

```bash
# Typst (default)
nix develop "$CSNOTES" --command typst compile notes.typ            # -> notes.pdf

# LaTeX via Tectonic
nix develop "$CSNOTES" --command tectonic -X compile notes.tex      # -> notes.pdf

# Markdown -> PDF (Tectonic engine), with cross-references
nix develop "$CSNOTES" --command pandoc notes.md -o notes.pdf \
  --pdf-engine=tectonic --filter pandoc-crossref

# A figure from Python (matplotlib/sympy/networkx), then embed the PNG/PDF
nix develop "$CSNOTES" --command python3 make_figure.py

# A diagram
nix develop "$CSNOTES" --command dot -Tpdf graph.dot -o graph.pdf
nix develop "$CSNOTES" --command d2 diagram.d2 diagram.svg
```

If a *compile* itself triggers a large download (rare — e.g. Tectonic fetching many LaTeX packages the first time), apply the same redirect-and-tail wrapper as Step 1.

## Step 3 — need a tool that isn't in the env?

Use it **ad-hoc** for this run (redirect the one-off build so it stays token-safe):

```bash
nix shell nixpkgs#<pkg> --command <cmd> > /tmp/cs-notes-adhoc.log 2>&1; tail -n 20 /tmp/cs-notes-adhoc.log
```

Then **prompt the user** to make it permanent:

> "I needed `<pkg>` (used it ad-hoc via `nix shell nixpkgs#<pkg>`). To have it ready next time, add `<pkg>` to the cs-notes flake at
> `~/nix/templates/krit/dev-environments/language-combined/cs-notes/flake.nix`
> (top-level `packages` list, or inside `python313.withPackages` if it's a Python package), then rebuild is not needed — it's a standalone flake, just `git add` it."

This both unblocks the current task and lets the user grow the env over time.

## Notes

- The flake must be **git-tracked** for Nix to see it (it already is). If you ever create a *new* standalone flake, `git add` it before `nix develop`.
- Write output files in the course folder the work is about (the cwd), not in a scratch dir.
