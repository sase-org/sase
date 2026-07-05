---
create_time: 2026-07-05 06:36:06
status: wip
prompt: sdd/prompts/202607/config_edit_modal_large_value_overflow.md
---
# Plan: Fix Config Edit Modal Overflow for Large Object Values

## Problem

Opening the edit modal on a config field with a large structured value (e.g. `axe.lumberjacks`, an object whose YAML
rendering spans dozens of lines) blows the modal layout: the "current value" block fills the entire modal (which
saturates its `max-height: 90%`), and everything below it — the scope selector, list-strategy banner, the actual YAML
editor `TextArea`, the error line, and the hints line — is clipped off-screen. The modal is unusable for exactly the
fields that are hardest to edit. (Screenshot evidence: the modal shows only the truncated current-value YAML; no editor
or hints are visible.)

## Root cause (diagnosis)

The `current: <value>` info line added by the recent Config-tab edit UX change renders structured values via the shared
value-block helpers, but those helpers' truncation caps were designed for a different container:

1. `ConfigEditModalBase._append_current_value` (`src/sase/ace/tui/modals/config_edit_rendering.py`) calls
   `append_value_block(...)` for any structured current value.
2. `append_value_block` → `truncate_value_block` (`src/sase/ace/tui/modals/config_pane_rendering.py`) only bounds
   _pathological_ inputs: `_VALUE_BLOCK_RENDER_MAX_LINES = 1_000` lines / `_VALUE_BLOCK_RENDER_MAX_BYTES = 64_000`
   bytes. Those caps are correct for their original home — the detail pane — because that pane hosts the text inside
   `VerticalScroll#config-detail-scroll` (`config_pane_widget.py`), where long blocks just scroll.
3. The edit modal has no scroll region around the info block: `#config-edit-info` is a plain `Static` with
   `height: auto` inside `ConfigEditModal > Container` (`styles.tcss`), a **non-scrolling** `Container` with
   `height: auto; max-height: 90%`. When the info block alone exceeds the container's max height, Textual clips the
   overflow — hiding every later-composed child (scope, banner, editor, error, hints).

So any real object value larger than roughly a screenful — far below the 1,000-line pathological cap — starves the rest
of the modal. Two secondary contributors in the same class:

- **Soft-wrap expansion:** the modal content area is ~78 columns; long unbroken YAML lines (e.g. long `description:`
  strings) wrap into multiple display rows, so a naive "N lines" cap still under-counts rendered height. Line width must
  be budgeted too.
- **Uncapped `default:` line:** `_info_text` renders `format_value(field.default)` — one-line compact JSON that
  soft-wraps into many rows when the default is a large structure.

## Fix design

### Phase 1 — modal-appropriate caps for the current-value block (the actual fix)

1. Extend the pure helper layer with an explicitly bounded variant: add optional `max_lines` and `max_line_width`
   parameters to `truncate_value_block` / `append_value_block` (defaults preserve today's pathological caps, so the
   detail pane's behavior is unchanged). Lines longer than `max_line_width` are truncated with an ellipsis _before_
   highlighting so a "line" can never wrap into multiple display rows.
2. In `_append_current_value`, render structured values with a small modal budget (new module constant, e.g.
   `_MODAL_VALUE_BLOCK_MAX_LINES = 8`, line width ≈ modal content width minus indent), keeping the existing
   `… N more line(s)` dim suffix when truncated. Budget rationale: modal fixed overhead (title, info lines, scope
   selector at up to ~6 rows, banner, 8-row TextArea, error, hints, margins) is ~25–30 rows, so an 8-line value block
   keeps the modal within `max-height: 90%` on a typical 40+-row terminal.
3. Cap the `default:` line the same way: when the default is structured or long, render it with the existing
   `format_row_value_summary` single-line summary (e.g. `{...}` / `3 items` / truncated scalar) instead of full
   `format_value`. The full default remains visible in the detail pane.
4. The full current value stays reachable: for object/yaml fields the editor `TextArea` is seeded with the complete
   current YAML (internally scrollable), and the detail pane behind the modal renders the full block.

### Phase 2 — layout backstop so the editor can never be starved again

5. Add a defensive `max-height` (e.g. 14) to `ConfigEditModal #config-edit-info` in `styles.tcss`. With the Phase-1 caps
   this should never trigger; it exists so no future info-content growth (long descriptions, new info rows) can ever
   clip the editor/hints again. Document the intent with a comment.

### Phase 3 — preview-stage polish (same bug class, cosmetic)

6. In `_append_effective` (preview stage), the effective before/after values render via uncapped `format_value(...)`;
   for large objects this is a giant soft-wrapped JSON line. It cannot break the layout (the preview lives in
   `VerticalScroll#config-edit-preview-scroll`, max-height 24) but is unreadable — cap it with the same single-line
   summary helper used for row labels.

## Explicitly out of scope

- No change to the detail pane's pathological caps (1,000 lines / 64 KB) or its rendering.
- No scrollable info region inside the modal (keeps the modal key-driven and simple; caps + backstop suffice).
- No changes to edit planning/validation/write semantics (Rust core boundary untouched).

## Files expected to change

- `src/sase/ace/tui/modals/config_pane_rendering.py` — optional `max_lines`/`max_line_width` params on
  `truncate_value_block` / `append_value_block` (defaults unchanged).
- `src/sase/ace/tui/modals/config_edit_rendering.py` — bounded current-value block; summarized `default:` line; capped
  preview effective values.
- `src/sase/ace/tui/styles.tcss` — `max-height` backstop on `#config-edit-info`.

## Testing

- Unit (`tests/test_config_pane.py` / `tests/test_config_edit_modal.py`): `truncate_value_block` with
  `max_lines`/`max_line_width` (caps applied, defaults untouched, omitted-count correct, long lines ellipsis-truncated);
  info text for a large dict (e.g. 50 keys × long descriptions) stays within the modal line budget and shows the
  `… N more line(s)` marker; structured `default:` renders as a one-line summary.
- Widget (`tests/ace/tui/test_config_edit_modal_widget.py`): open the edit modal on a large-object field and assert the
  editor `TextArea` and `#config-edit-hints` are visible/laid out on screen (non-zero region), i.e. the regression
  cannot silently return.
- Visual PNG: extend the existing `object_value` fixture in
  `tests/ace/tui/visual/_ace_config_center_png_snapshot_helpers.py` (grow the `ace.lumberjack` object to enough
  keys/lines that the old code overflowed), add/refresh a snapshot in `test_ace_png_snapshots_config_center_edit.py`
  pinning the capped modal with editor + hints visible; accept intentional changes with
  `--sase-update-visual-snapshots`.
- Run `just install`, the focused suites above, then the required full `just check`.

## Performance & conventions compliance

- All new work is pure in-memory string truncation at modal-open/render time — no disk, no subprocess, no per-keystroke
  cost (TUI perf rules respected; no event-loop blocking paths added).
- No keymap changes; no `default_config.yml` changes; presentation-only, Rust core boundary untouched.
