---
name: link_to_sase_sh
status: draft
create_time: 2026-05-10 13:15:22
prompt: sdd/prompts/202605/link_to_sase_sh.md
---

# Plan: Make repo documentation point to sase.sh in appropriate places

## Goal

Make sure that visitors to this repo (on GitHub, on PyPI, or in the source tree) consistently know that the canonical
documentation lives at <https://sase.sh/>. The README link in particular should be impossible to miss — currently the
only mention is buried as a parenthetical inside the "Keep reading" section.

## Current state

- `README.md` mentions sase.sh once on line 72 ("The full documentation lives at [sase.sh](https://sase.sh/).") inside
  the "Keep reading" section. Each subsequent bullet links to a sase.sh subpage. There is no link near the top of the
  README, no badge, and no tagline.
- `CONTRIBUTING.md` does not mention sase.sh at all. It only shows shell commands and a one-line bd note.
- `pyproject.toml` has **no `[project.urls]` section**, so the PyPI sidebar will not link to the docs or homepage when
  the package is published.
- `docs/index.md` is the docs-site landing page itself, so linking back to sase.sh from there is unnecessary.
- `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` are agent-only context files and should not advertise the marketing site.
- `docs/development.md` already mentions `https://sase.sh/` once (in the deploy workflow description). That mention is
  about deploy smoke-testing, not a doc-discovery pointer, so we leave it alone.
- `docs/acknowledgements.md` is linked from the README but does not need a sase.sh self-link (it is hosted on sase.sh
  already).

## Proposed changes

### 1. `README.md` — make the link prominent (primary change)

Add a clearly visible "Documentation" pointer that a reader cannot miss when landing on the repo. Two complementary
moves:

1. **Docs badge in the badge row (top of file).** Add a Material-for-MkDocs–style shield linking to <https://sase.sh/>
   alongside the existing Ruff / mypy / pytest / tox badges, e.g.
   `[![Docs](https://img.shields.io/badge/docs-sase.sh-3b82f6?logo=readthedocs&logoColor=white)](https://sase.sh/)`.
   Badges are the first thing GitHub readers scan, and a docs badge is a recognized convention.
2. **Callout line directly under the tagline paragraph.** A single bold sentence such as **"Full documentation:
   [sase.sh](https://sase.sh/)."** placed between the lede paragraph and the overview image. This guarantees the link is
   above the fold even for readers who ignore the badges.

Leave the existing "Keep reading" section as-is (per-subpage links are still useful), but optionally promote the sase.sh
sentence inside it to bold so the second mention also stands out.

### 2. `CONTRIBUTING.md` — point contributors at the docs site

Add a short top-of-file pointer ("For project background and how the system fits together, see <https://sase.sh/>") and
link the development-page deep link (<https://sase.sh/development/>) once near the development-workflow section.
Contributors who read CONTRIBUTING shouldn't have to bounce through README to discover the canonical docs.

### 3. `pyproject.toml` — add `[project.urls]`

PyPI uses `[project.urls]` to populate the sidebar links shown on the package page. Add:

- `Homepage = "https://sase.sh/"`
- `Documentation = "https://sase.sh/"`
- `Repository = "https://github.com/sase-org/sase"`
- `Issues = "https://github.com/sase-org/sase/issues"` (optional but conventional)

This means anyone arriving via `pip install sase` / pypi.org will see sase.sh as the canonical home.

### 4. (Optional) GitHub repo "About" / metadata

GitHub also exposes a "Website" field on the repository About panel. That is set in the GitHub UI, not in a checked-in
file, so it is out of scope for this plan but worth flagging to the user as a follow-up they may want to do manually
once this lands.

## Out of scope

- Rewriting any docs page content beyond linking. The docs site itself is the destination, not a target for editing
  here.
- Changes to `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` — agent context, not user-facing documentation.
- Touching every SDD tale or research note that already mentions `sase.sh`. Those are historical artifacts.
- Updating `docs/index.md` to link to sase.sh (it _is_ sase.sh).
- Setting the GitHub repository "Website" field (UI-only, not a tracked file).

## Verification

1. Render `README.md` mentally / via a Markdown preview: confirm the docs badge and bold callout sentence are visible
   without scrolling past the tagline.
2. Confirm the new badge URL renders (the shields.io URL pattern is the same one used by the existing badges).
3. `python -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('pyproject.toml').read_text())"` to confirm the
   `[project.urls]` table parses.
4. Run `just check` after the file edits, per repo memory (skipping it would only be appropriate for bead-only changes).
