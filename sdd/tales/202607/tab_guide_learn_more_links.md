---
create_time: 2026-07-05 06:54:47
status: wip
---
# Plan: Directly Relevant sase.sh Links in the Tab Guide "Learn more" Box

## Problem & Product Context

The new Tab Guide feature (`,?`) shipped with a "Learn more" card at the bottom of the AXE guide
(`AxeOnboarding._build_learn_card`, `src/sase/ace/tui/widgets/axe_onboarding.py`). Today that card links only to the
bare docs root:

```
https://sase.sh  full documentation.
```

Compare the PRs guide's "Learn more" card (`changespec_onboarding.py`), which already links three _specific_ docs pages
— `https://sase.sh/change_spec/`, `https://sase.sh/vcs/`, `https://sase.sh/plugins/` — each with a one-line description.
The AXE guide teaches lumberjacks, chops, hooks, mentors, and background automation, and the docs site (mkdocs,
`use_directory_urls: true`, so every page lives at `https://sase.sh/<page>/`) has dedicated pages for exactly those
topics. The bare root link wastes the moment: a user who just read the guide has specific questions ("how do I configure
a lumberjack?", "what is a mentor?") and gets dumped on the homepage.

The Agents guide's equivalent bottom card ("Get more help", `agent_onboarding.py::_build_help_card`) has the same gap —
bare `https://sase.sh` only — and is included here as a small consistency item so all three guides follow the same
pattern.

## Link Selection (the product decision)

### AXE guide "Learn more" card — add three topic links

All verified against `mkdocs.yml` nav / `docs/`:

1. **`https://sase.sh/axe/`** — _"the full Axe guide: lumberjacks, chops & configuration."_ The AXE Automation page
   covers the daemon architecture, default lumberjacks, chop fields, script/agent chops, chop run history, and the AXE
   tab views — the canonical deep-dive for everything this guide introduces. The must-have.
2. **`https://sase.sh/workflow_spec/`** — _"author the workflows that hooks & chops launch."_ The guide's hero and "What
   is Axe?" card describe Axe as the engine that keeps hooks, mentors & workflow checks moving; this page is where users
   learn to write those workflows.
3. **`https://sase.sh/mentors/`** — _"automated review mentors Axe keeps running."_ Mentors are named in the hero and
   the automation-loop card but never explained; this page covers profiles, matching, and the execution lifecycle that
   Axe drives.

The existing lines are kept: the `?` help-keycap row, the bare `https://sase.sh` "full documentation." row (still the
right entry point for everything else), and the closing `,?` works-on-every-tab row. The three new link rows are
inserted at the top of the card, mirroring the PRs card's links-first layout. Exact link descriptions may be tuned
during implementation to fit the card width cleanly.

**Considered and rejected** for this card:

- `notifications/` — notifications are a global surface (top-bar indicator, global modal), not AXE-tab-specific.
- `configuration/`, `cli/` — generic reference pages; lumberjack/chop configuration is already covered in depth on the
  `axe/` page itself.
- `commit_workflows/` — hooks _originate_ there, but it is PR-workflow territory; the PRs guide is its natural home.

### Agents guide "Get more help" card — two topic links (consistency item)

Inserted above the existing bare-docs row, accent `#87D7FF`:

1. **`https://sase.sh/ace/`** — _"the full ACE TUI guide, tab by tab."_ The complete keybinding + tab reference for the
   app the user is looking at.
2. **`https://sase.sh/xprompt/`** — _"supercharge prompts with #xprompts."_ The guide's first card is "Start from the
   prompt"; xprompts are the natural next step for prompt-driven agent launches.

The PRs guide's "Learn more" card is **unchanged** — it already has three directly relevant links.

## Technical Design

### Shared doc-link helper

`ChangeSpecOnboarding._append_doc_link` (url styled `bold {accent} link {url}`, then a dim description) is currently
private to the PRs widget. Hoist it into the shared helpers module:

- `src/sase/ace/tui/widgets/_onboarding_common.py`: new `append_doc_link(text, url, description, *, accent) -> None`
  with the identical rendering.
- `changespec_onboarding.py`: drop the private helper, call the shared one with `accent=_ACCENT` — a pure refactor with
  byte-identical rendered output.
- `axe_onboarding.py` / `agent_onboarding.py`: use the shared helper for the new rows.

### Files touched

| File                                                | Change                                                        |
| --------------------------------------------------- | ------------------------------------------------------------- |
| `src/sase/ace/tui/widgets/_onboarding_common.py`    | new `append_doc_link` helper                                  |
| `src/sase/ace/tui/widgets/changespec_onboarding.py` | refactor to shared helper (no rendering change)               |
| `src/sase/ace/tui/widgets/axe_onboarding.py`        | 3 new URL constants + link rows at top of `_build_learn_card` |
| `src/sase/ace/tui/widgets/agent_onboarding.py`      | 2 new URL constants + link rows in `_build_help_card`         |

URL constants follow the existing naming convention (`_AXE_DOCS_URL = "https://sase.sh/axe/"`, etc.), using the
directory-URL form already established by the changespec widget.

No modal, keymap, dispatch, CSS, or layout changes: both cards live inside `VerticalScroll` guides (and the Tab Guide
modal caps at 90% height), so a few extra lines simply scroll. No `sase-core` involvement — presentation-only copy.

## Testing

1. **App-free unit tests**
   - `tests/ace/tui/widgets/test_axe_onboarding.py` — extend the content test to assert the learn card contains
     `https://sase.sh/axe/`, `https://sase.sh/workflow_spec/`, and `https://sase.sh/mentors/`.
   - Agents onboarding widget tests — assert `https://sase.sh/ace/` and `https://sase.sh/xprompt/` in the help card.
   - Changespec onboarding tests — unchanged; they double as the regression check that the helper hoist did not alter
     rendering.
2. **PNG visual snapshots** — the changed copy alters existing goldens; regenerate intentionally with
   `--sase-update-visual-snapshots` and review the diffs:
   - `tab_guide_axe_120x40.png` and `tab_guide_agents_120x40.png`
     (`tests/ace/tui/visual/test_ace_png_snapshots_tab_guide.py`).
   - The Agents-tab empty-state onboarding snapshot(s), since the takeover page shares `_build_help_card` with the
     modal.
   - PRs onboarding and AXE-tab snapshots must **not** change (refactor-only / modal-only content respectively) — any
     diff there is a bug.

Run `just install`, then `just check` before finishing (per repo policy), plus the targeted visual lanes above.

## Implementation Phases

1. **Helper hoist** — add `append_doc_link` to `_onboarding_common.py`, refactor `changespec_onboarding.py`, confirm
   existing tests pass unchanged.
2. **AXE links** — the three new rows + constants + unit-test assertions.
3. **Agents links** — the two new rows + constants + unit-test assertions.
4. **Snapshots** — regenerate the affected goldens, verify PRs/AXE-tab goldens are untouched, full `just check`.

## Out of Scope

- Any change to the PRs guide's "Learn more" card (already link-rich).
- New docs pages or docs-site changes — all linked pages exist today.
- Deep links to page anchors (e.g. `axe/#chop-fields`) — top-level pages keep links stable as docs evolve.
