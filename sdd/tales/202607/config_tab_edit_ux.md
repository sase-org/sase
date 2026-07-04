---
create_time: 2026-07-04 12:47:50
status: wip
prompt: sdd/prompts/202607/config_tab_edit_ux.md
---
# Plan: Make Config-Field Editing WAY Nicer in the Admin Center Config Tab

## Goal

Improve the experience of _editing_ SASE configuration fields from the **Config** tab of the **SASE Admin Center** TUI
panel. Every change below is an objective win: it fixes a dead key, makes currently-invisible state visible, moves
feedback earlier, or removes keystrokes — without changing the deliberate two-stage edit → preview → write safety
design, and without touching backend edit semantics (which live in the Rust core / `sase.config` pipeline).

## Context (current state)

The Config tab (`src/sase/ace/tui/modals/config_pane_widget.py`) is a three-region browser (source rail / field tree /
detail) over the schema-driven config inventory. Pressing `e` or `enter` on a leaf opens `ConfigEditModal`
(`src/sase/ace/tui/modals/config_edit_modal.py` + `config_edit_rendering.py`), which has:

- typed editors chosen by schema (`config_edit_helpers.py::editor_kind_for`): key-driven bool/enum, single-line `Input`
  for int/number/string, `TextArea` for string-lists and raw YAML;
- a write-scope target (`ctrl+t` cycles writable layers, `ctrl+n` creates an overlay, `ctrl+r` toggles
  reset-to-default);
- a preview stage (Rust-planned diff + validation + effective before→after) confirmed with `enter`/`ctrl+s`.

This v1 shipped the pipeline from `sdd/research/202606/sase_config_tui_panel_ux_consolidated.md`. The remaining pain is
concentrated in the modal's _interaction_ layer and a few dead/missing keys in the pane. This plan is presentation-only:
no changes to `sase.config` planning/apply APIs or the Rust core are required.

## Problems → Improvements

### Phase 1 — Edit modal: show the state the user is acting on

1. **The modal never shows the current effective value or where it came from.** `ConfigEditModalBase._info_text()` shows
   type/enum/constraints/default/description — but not the value being changed or its winning layer, and the modal
   covers the detail pane that had them. Once the user types, the original value is gone. → Add a
   `current: <value> · <winning-layer badge>` line to the modal info block (reuse `render_*`/badge helpers and the
   `ConfigPaneView` provenance lookups already passed into the modal). Structured values render via the existing
   capped/truncated block helpers.

2. **Enum editing is blind, forward-only cycling.** `space` advances `_enum_index`; the option set is only visible as a
   comma-joined string in the info line; there is no way to move backwards or pick directly. → Render all enum options
   as a vertical option list with the active row marked. Navigation: `j`/`k` (and arrows) move, digits `1`–`9` pick
   directly (when ≤9 options), `space` keeps cycling for muscle-memory compatibility, and rows are mouse-clickable. Bool
   fields render as the same two-option list (`true` / `false`), so `space` still toggles. Implementation stays
   key-driven on the screen (the modal already runs with `AUTO_FOCUS = None` and screen bindings for bool/enum);
   `j`/`k`/digit actions are guarded to bool/enum editor kinds, which never mount an `Input`/`TextArea`, so there is no
   conflict with typing in text editors.

3. **The scope choice — the single most consequential decision in the modal — is invisible.** `_scope_text()` shows only
   the active target plus a `[ctrl+t: N targets]` count; users cycle blind through layers whose list-merge semantics
   differ (`replace` vs `concatenate`). → Render _all_ writable targets as a compact selector (one row per target: name,
   kind badge, list strategy, `· new` marker), active row highlighted, with the active target's resolved write path
   underneath (as today). `ctrl+t` still cycles; rows are mouse-clickable. This is a direct implementation of the
   research doc's "Scope Selector — the write target must always be visible".

4. **Validation feedback arrives too late.** Constraint/parse errors (`'x' is not an integer`, `must be ≥ 1`) only
   appear after attempting to build the preview (`_start_plan` → `_current_op`). → Validate live: on `Input.Changed` /
   `TextArea.Changed`, run the existing pure helpers (`parse_editor_value` + `check_constraints` — in-memory, no I/O;
   event-loop-safe per the TUI perf rules) and show the error inline immediately, clearing it when the text parses.
   Preview remains blocked on the same errors as today — nothing new can fail. For the raw-YAML editor, skip live
   parsing when the buffer exceeds the existing highlight caps (16 KB) to keep keystrokes cheap.

5. **Editing a short scalar requires manually clearing the seeded value.** The `Input` opens with the cursor at the end
   of the current value; changing `3` to `5` means backspacing first. → Select-all on open (`Input.select_all()`,
   available in Textual 8): typing replaces, while arrows/home/end still allow in-place editing. This matches standard
   settings-form behavior.

6. **Multiline string values break the single-line editor.** `editor_kind_for` maps every non-enum string to the
   one-line `Input`, mangling values containing newlines. → When the current value contains a newline (or the field
   allows long text via a large `max_length`), use the `TextArea` editor for strings. Parsing/`check_constraints`
   already handle arbitrary strings.

7. **The raw-YAML editor is a plain unhighlighted textarea.** → Set `language="yaml"` on the `TextArea` (the
   `textual[syntax]` extra with tree-sitter YAML is already an installed dependency — verified). Zero-cost readability
   win for exactly the fields that are hardest to edit.

### Phase 2 — Preview & write: feedback and control

8. **The preview stage is mouse-only for scrolling and long diffs overflow.** In preview, focus is cleared and
   `#config-edit-preview-scroll` (max-height 24) has no key bindings. → Add `j`/`k`, `ctrl+d`/`ctrl+u`, and `g`/`G`
   scrolling for the preview scroll region (guarded to the preview stage), and update the hints line accordingly.

9. **A successful write is silent.** The modal dismisses and the pane refreshes, but nothing confirms what happened or
   where. → After the pane receives a non-None `AppliedResult` in `_on_edit_dismissed`, show a Textual toast
   (`app.notify`): `wrote <path> → <target file>` (with the chezmoi-apply note when relevant). The existing failure path
   (chezmoi apply error keeps the modal open) is unchanged.

10. **Hints lines must stay honest.** Update the modal `_hints()` for each stage/editor kind to reflect the new keys
    (option-list navigation, digits, preview scrolling), keeping them one line.

### Phase 3 — Pane: reaching the field you want to edit

11. **`g`/`G` are dead keys on the Config tab.** `ConfigCenterModal.on_key` already forwards `g`/`G` to the active
    pane's `action_scroll_to_top` / `action_scroll_to_bottom`, but `ConfigPane` doesn't implement them (other Admin
    Center panes do). → Implement both: jump the field tree cursor to the first/last visible row.

12. **No vim-style horizontal tree navigation.** The app-wide convention (Agents tab) uses `h`/`l` for collapse/reveal,
    but the Config tree only supports `j`/`k`/arrows. → Add `h` (collapse section / move to parent when on a leaf) and
    `l` (expand section / descend), mirroring standard vim tree navigation. These are widget-level `BINDINGS` like the
    existing `j`/`k`, so no `default_config.yml` keymap changes are needed.

13. **Leaf rows show no values, forcing a tree↔detail ping-pong while hunting for a field.** The research doc's
    recommended row shape includes the effective value per row. → Append the effective value to each leaf row label, dim
    and truncated to a fixed budget (single line; structured values render as a compact summary like `3 items` / `{…}`).
    Labels are computed once per tree rebuild in `render_row_label` (pure, in-memory), so per-frame cost is unchanged
    and highlight latency is unaffected.

14. **Filtering gives no result count.** When a `/` filter is active the header still reads
    `Configuration [N fields · M modified]`. → Show `matching X / N` in the title (or status line) while a filter or
    modified-only toggle is active — trivially computed from the already-built visible set.

## Explicitly out of scope (not objective / deliberately deferred)

- One-key toggles that write directly from the tree (bypasses the preview/validation safety flow).
- Live re-planning of the diff on every keystroke (Rust plan calls stay confirm-triggered and off-thread).
- Specialized editors (`ace.keymaps`, `linked_repos`, `axe.lumberjacks`, …), `$EDITOR` hand-off, deprecation one-key
  migrations, overlay rename/delete — all tracked as deferred work in the research doc; each is a real feature decision,
  not a clear-cut polish win.
- Any change to edit planning, validation, merge, or write semantics (Rust core boundary).

## Files expected to change

- `src/sase/ace/tui/modals/config_edit_rendering.py` — info/current-value block, option-list and scope-selector
  rendering, hints, preview-stage additions.
- `src/sase/ace/tui/modals/config_edit_modal.py` — new actions (option navigation, digit pick, preview scrolling),
  live-validation event handlers, select-all-on-focus.
- `src/sase/ace/tui/modals/config_edit_helpers.py` — multiline-string editor-kind rule; any pure formatting helpers for
  option rows / value summaries.
- `src/sase/ace/tui/modals/config_pane_rendering.py` — leaf-row value suffix, match-count text.
- `src/sase/ace/tui/modals/config_pane_widget.py` — `g`/`G`/`h`/`l` actions, filter-count wiring, write-success toast,
  hints line.
- `src/sase/ace/tui/styles.tcss` — styling for the option list / scope selector rows.

## Testing

- Extend the existing unit suites: `tests/test_config_edit_modal.py`, `tests/ace/tui/test_config_edit_modal_widget.py`,
  `tests/test_config_pane.py`, `tests/ace/tui/test_config_pane_widget.py` — cover enum option-list navigation (j/k,
  digits, space wrap), scope-selector rendering/click, live validation transitions (error appears on bad text, clears on
  fix), multiline-string editor selection, g/G/h/l tree behavior, filter count, and the write toast.
- Update the PNG visual snapshots that render these surfaces
  (`tests/ace/tui/visual/test_ace_png_snapshots_config_center_config.py`,
  `test_ace_png_snapshots_config_center_edit.py`), accepting intentional changes with `--sase-update-visual-snapshots`;
  add a snapshot for the enum option-list editor state.
- Run `just check` (after `just install`) before finishing.

## Performance & conventions compliance

- All new per-keystroke work is pure in-memory parsing/formatting (no disk, no subprocess, no schema reload) per the TUI
  perf rules; Rust plan/apply calls remain on threads via `run_worker(thread=True)` exactly as today.
- Tree row labels remain computed only at rebuild time; highlight-move latency is untouched.
- Hints lines (pane + modal) are updated in the same change as each new binding; the Admin Center panes are
  modal-hosted, so the main-app keybinding footer and help modal are unaffected.
- All new keys are widget/screen `BINDINGS` (like the existing `j`/`k`/`e`), not configurable keymaps, so
  `src/sase/default_config.yml` needs no changes.
