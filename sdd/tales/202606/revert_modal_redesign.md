---
create_time: 2026-06-25 17:27:47
status: done
prompt: sdd/prompts/202606/revert_modal_redesign.md
---
# Redesign the Revert Agent Commits Confirmation Modal

## Goal

Make the `,r` "Revert Agent Commits" confirmation modal (`ConfirmRevertAgentModal`) genuinely beautiful and easy to
scan, on par with the project's best-styled dialog (`QuitConfirmModal`). This is a **presentation-only** change: the
revert backend, data models, intent flow, bindings, and the modal's public contract all stay exactly as they are.

## Why this is needed

Today the modal is effectively **unstyled**. `ConfirmRevertAgentModal` appears in _no_ CSS selector in
`src/sase/ace/tui/styles.tcss` — it is missing both the `align: center middle` rule and the `> Container` border /
background / width / padding rule that every other dialog gets. The result (see the reported screenshot):

- The dialog renders flush against the **top-left corner** with no border, no panel background, and no width constraint
  — it reads like a raw debug dump, not a dialog.
- Content is a stack of plain `Label`s built from hand-concatenated multi-line strings, all in the same default color.
- There is **no visual hierarchy and no semantic color**: revertable repos, the _blocked_ repo, SDD provenance, and the
  destructive-action warning are visually indistinguishable.
- The **most important, most actionable** information — a blocked repository and _why_ it is blocked ("Workspace has
  uncommitted changes; commit or discard them first") — is buried mid-panel in plain text with no warning treatment.
- Commit identity (short SHA) and commit subject are fused into one flat string, so the eye can't separate "which
  commit" from "what it was".
- Buttons are default-width and left-packed under the content, with no key-hint affordance and no default focus on the
  safe action.

The fix is to adopt the established design language already proven by `QuitConfirmModal`: a centered bordered panel, a
Rich-`Text` summary, a bordered scroll region of per-repo "cards" with glyphs and semantic color, distinct warning cards
for blocked repos, dim captions, a centered button row, and a key-hint line.

## Scope and boundaries

- **In scope:** `src/sase/ace/tui/modals/confirm_revert_agent_modal.py` (rendering), a new dedicated CSS block in
  `src/sase/ace/tui/styles.tcss`, the modal's unit tests, and a new PNG visual-snapshot test + goldens.
- **Out of scope / unchanged:** `revert_agent_models.py`, the preview/execute/intent backend, the `_revert.py` action
  layer, and the modal's constructor signature `ConfirmRevertAgentModal(preview)` / `ModalScreen[bool]` /
  `dismiss(bool)` result contract / `y` `n` `q` `escape` bindings. Callers and the task-queue flow must keep working
  untouched.
- **Rust core boundary:** none. Per `memory/rust_core_backend_boundary.md`, "presentation-only Textual state,
  keybindings, layout, widget rendering, and Python glue can stay in this repo." The shared revert _data_ already lives
  in the backend models; this change only restyles how the TUI renders that data. No `sase-core` changes.

## Reference design language (already in the codebase)

`QuitConfirmModal` (`src/sase/ace/tui/modals/quit_confirm_modal.py` + its CSS block in `styles.tcss`) is the gold
standard to match and stay consistent with:

- An `id`'d `Container` with `border: thick $primary; background: $surface; padding: 1 2;` and a parent
  `align: center middle;`.
- A bold, centered title `Label`.
- A `Static` rendering a Rich `Text` summary, using a glyph plus mixed styles (`bold`, `dim`, colored accents).
- A bordered `VerticalScroll` (`border: solid $secondary`) holding `Static` "cards", each a Rich `Text` with a status
  glyph, a colored chip/badge, and dim secondary text.
- A centered `Horizontal` button row (`min-width` widened) and a dim, centered key-hint line beneath it.
- `on_mount` focuses the **safe** button.

Follow the same conventions this file establishes: structural colors (borders/backgrounds) use `$`-theme tokens in the
`.tcss`; inline Rich `Text` styles use literal color names (e.g. `bold yellow`, `dim`, `bold black on cyan`) so the
pinned visual-snapshot fixtures stay deterministic.

## Target visual design

A centered panel (~76 cols wide, `max-width: 95%`, `max-height: 88%`) with a `thick $primary` border, laid out
top-to-bottom:

1. **Title** — bold, centered, prefixed with an undo/revert glyph (e.g. `⟲  Revert Agent Commits`).
2. **Subtitle caption** (dim, one line):
   - Single-agent: `Agent <name> · scope <agent|family>`.
   - Bulk: `<N> marked agents`.
3. **Summary line** (Rich `Text`): a glyph plus emphasized counts, e.g. `Reverting 3 commits across 3 repositories.`
   with the numbers in `bold` and the verb in the destructive accent.
4. **Scrollable body** — a bordered `VerticalScroll` (`border: solid $secondary`) of cards:
   - **Revertable repo card** — header row: a `●` glyph in a success/accent color, the repo label in `bold`, a small dim
     kind tag (`primary` / `linked`), and a right-aligned dim `N commit(s)` count. Beneath, one row per commit: the
     **short SHA** in a distinct accent color (commit identity) followed by the **subject** in `dim`. Commits that
     touched `sdd/` paths get a subtle `sdd` provenance marker on the row. The existing `_MAX_COMMIT_ROWS` cap and the
     `... and N more` collapse are preserved.
   - **Blocked repo card** — visually distinct **warning** treatment: a `▲` (or `⚠`) glyph in warning color, the repo
     label, a `bold` warning tag `BLOCKED · will be skipped`, and the blocked reason rendered prominently (wrapped)
     directly beneath so it is impossible to miss. Blocked cards sort/group after revertable cards.
5. **Provenance + semantics captions** (dim):
   - `SDD provenance: <paths>` (or `(none)`), preserving the `_MAX_SDD_PATHS` cap and `+N more` collapse.
   - Bulk only: `Skipped (no commits): <names>` preserving `_MAX_SKIPPED_TARGETS`.
   - The transaction-semantics sentence (single vs bulk wording) as a closing dim caption.
6. **Button row** — centered `Horizontal`, widened `min-width`: `Revert (y)` as `variant="error"` (destructive) and
   `Cancel (n)` as `variant="primary"`.
7. **Key-hint line** (dim, centered): `y revert · n/esc cancel · j/k scroll`.

Default focus on mount goes to the **safe** `Cancel` button (matching `QuitConfirmModal`), so an accidental `Enter` does
not perform a destructive revert.

### Semantic color roles (consistent across the modal)

- Destructive action / "Revert" verb → error (red).
- Revertable repo glyph + healthy state → success/accent.
- Blocked repo glyph, `BLOCKED` tag, and reason → warning (yellow).
- Short SHA (commit identity) → a single distinct accent color, subjects in `dim`.
- All secondary captions (subtitle, provenance, semantics, hints) → `dim` / `$text-muted`.

## Implementation outline

### 1. Restyle the modal (`confirm_revert_agent_modal.py`)

- Switch the bare `Container()` to an `id`'d container (e.g. `revert-confirm-container`) and lay out the structure above
  using `Container` / `VerticalScroll` / `Horizontal`, a title `Label`, and `Static` widgets fed Rich `Text`.
- Replace the plain string-concatenation `Label` helpers with `Text`-returning render helpers, e.g. a shared
  `_repo_card_text(repo)` / `_blocked_card_text(repo)` (mirroring `QuitConfirmModal._task_card_text`), plus
  `_summary_text()`, `_subtitle()`, and caption builders. Keep the single/bulk split (`_is_bulk`) and reuse the shared
  card core for both modes.
- Preserve all truncation/collapse constants and rules (`_MAX_COMMIT_ROWS`, `_MAX_SDD_PATHS`, `_MAX_SKIPPED_TARGETS`,
  `... and N more`, `+N more`).
- Add `j`/`k`/`down`/`up` scroll bindings for the body `VerticalScroll` (as `QuitConfirmModal` does, `priority=True`),
  and an `on_mount` that focuses `Cancel`. Keep `y`/`n`/`q`/`escape` and the `dismiss(bool)` result unchanged.

### 2. Add the dedicated CSS block (`styles.tcss`)

- Add `ConfirmRevertAgentModal { align: center middle; }` and a `ConfirmRevertAgentModal > #revert-confirm-container`
  block (width ~76, `max-width: 95%`, `height: auto`, `max-height: 88%`, `border: thick $primary`,
  `background: $surface`, `padding: 1 2`).
- Style the title (centered, bold), the summary, the bordered scroll body (`border: solid $secondary`,
  `scrollbar-gutter: stable`, capped `max-height`), the card margins, the centered button row (widened `min-width`), and
  the dim hint line — closely mirroring the `QuitConfirmModal` block so the two dialogs feel like siblings.

### 3. Update unit tests (`tests/ace/tui/test_confirm_revert_agent_modal.py`)

- The pure data-model tests (`test_preview_*`, `test_bulk_preview_ok_and_counts`, `test_preview_sdd_paths_*`) test
  `RevertPreview` / `BulkRevertPreview` and are **unaffected** — leave them as-is.
- Update the modal-rendering tests that currently assert against the old plain-string helpers (`_commit_lines`,
  `_repo_commit_lines`, `_blocked_summary`, `_sdd_summary`, `_skipped_summary`) so they assert against the new
  `Text`-returning helpers via their `.plain` text: still verify the same behaviors — commit-row truncation (10 + "and N
  more"), repo grouping, blocked repo + reason present, SDD `(none)` vs listed, bulk skipped summary, and `_is_bulk`
  detection. Keep the bindings test (`y`/`n`/`q`/`escape`).

### 4. Add a PNG visual snapshot (new `tests/ace/tui/visual/test_ace_png_snapshots_revert.py`)

- Mirror `test_ace_png_snapshots_quit_confirm.py`: build a representative **single-agent** `RevertPreview` matching the
  reported screenshot (three revertable linked repos each with one commit, one blocked `primary` repo with the
  uncommitted-changes reason, no SDD) and push `ConfirmRevertAgentModal`, then `assert_page_png` a `..._120x40` golden.
- Add a second case for the **bulk** `BulkRevertPreview` path (multiple targets, a skipped target, some SDD provenance)
  to lock in both layouts.
- Generate the goldens with `just test-visual --sase-update-visual-snapshots`, then re-run `just test-visual` to confirm
  exact-match stability. Goldens land under `tests/ace/tui/visual/snapshots/png/`.

## Risks and mitigations

- **Visual-snapshot nondeterminism.** Mitigation: use literal Rich color names and the pinned fixtures (color +
  fontconfig/Fira Code) exactly as `QuitConfirmModal`'s test does; generate goldens via the documented update flag.
- **Long content overflow** (many commits / many repos / very long blocked reason). Mitigation: keep the existing
  truncation caps for commit/SDD/skipped lists, and put repo cards inside a height-capped `VerticalScroll` with `j/k`
  scrolling so the panel never exceeds `max-height`.
- **Breaking existing unit tests** that reach into private string helpers. Mitigation: deliberately update those
  modal-rendering tests to the new helpers in the same change; leave the data-model tests untouched.
- **Accidental destructive confirm.** Mitigation: default focus to `Cancel`; keep `Revert` as `variant="error"` and the
  explicit `y` binding.

## Validation

- `just install` (ephemeral workspace), then targeted runs:
  - `pytest tests/ace/tui/test_confirm_revert_agent_modal.py`
  - `just test-visual` (after generating the new goldens)
- Finish with `just check` (lint + mypy + full suite + visual) before handing off.

## Out-of-scope follow-ups (not in this change)

- No change to revert semantics, claim/workspace orchestration, or which commits are discovered.
- No new configuration or keybinding surface beyond the in-modal scroll keys.
