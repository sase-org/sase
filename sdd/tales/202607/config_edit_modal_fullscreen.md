---
create_time: 2026-07-05 19:24:19
status: wip
prompt: sdd/prompts/202607/config_edit_modal_fullscreen.md
---
# Plan: Near-Fullscreen Config Edit Modal (SASE Admin Center → Config tab)

## Problem

The `ConfigEditModal` (opened with `e`/`enter` on a field in the Config tab of the SASE Admin Center) is a fixed-width
84-column box with a small 8-row multiline editor and a preview pane capped at 24 rows. For structured fields (e.g.
`axe.lumberjacks`, a large YAML object), the editor shows only ~5 lines of a 50+ line value, and the preview stage can
show only a sliver of the diff. The modal should take up almost the entire screen so the input editor and the preview
panel get the vast majority of the vertical space.

## Current State

- `src/sase/ace/tui/styles.tcss` (~line 3532): `ConfigEditModal > Container` is
  `width: 84; height: auto; max-height: 90%`.
- `#config-edit-input` (single-line editor): fixed `height: 3`.
- `#config-edit-textarea` (multiline text / string-list / YAML editor): fixed `height: 8`.
- `#config-edit-preview-scroll` (plan/diff preview stage): `height: auto; max-height: 24`.
- The sibling `ConfigCenterModal > Container` (the Admin Center itself) already uses the near-fullscreen convention:
  `width: 95%; height: 90%`.
- `src/sase/ace/tui/modals/config_edit_rendering.py` holds compose + `_sync_visibility()`, which already toggles
  per-widget `display` based on stage (`edit` vs `preview`) and editor kind — exactly one of the editor/preview regions
  is visible at a time.

## Design

Expand the modal to near-fullscreen **conditionally**, only for the states that benefit, rather than always:

- **Expanded (~95% × ~95% of the screen)** when:
  - edit stage with a multiline editor (`text`, `string_list`, `yaml` kinds), and not in "reset to default" mode; or
  - preview stage (any editor kind) — the diff/validation pane is the payoff.
- **Compact (today's 84-col auto-height box)** for bool/enum option pickers, the single-line int/number/string editor,
  and the "reset to default" state. A fullscreen modal for a 2-option bool toggle would be mostly empty space.

Inside the expanded modal, the editor/preview become flexible (`height: 1fr`) so they absorb all remaining vertical
space after the fixed-height metadata rows (title, info, scope, banner, error, hints). Since `_sync_visibility()`
guarantees only one of textarea/preview is displayed at a time, both can carry `1fr` without competing.

This is presentation-only Textual CSS + a class toggle; it does not cross the Rust core backend boundary. It also
complies with the TUI perf rules: the only Python change is a cheap, synchronous `set_class` call on the existing render
path (no I/O, no new refresh paths).

An alternative considered and rejected: making the modal unconditionally 95%×95%. Simpler CSS, but bool/enum/reset
states would render as a huge, mostly-empty box, and 3 of the 5 existing PNG goldens would churn for no user-visible
benefit.

## Implementation

### 1. CSS — `src/sase/ace/tui/styles.tcss`

Keep the existing `ConfigEditModal` rules as the compact baseline and add an `-expanded` variant (class set on the
screen):

```tcss
/* Near-fullscreen when a multiline editor or the preview needs room. */
ConfigEditModal.-expanded > Container {
    width: 95%;
    height: 95%;
}

ConfigEditModal.-expanded #config-edit-textarea {
    height: 1fr;
}

ConfigEditModal.-expanded #config-edit-preview-scroll {
    height: 1fr;
    max-height: 100%;
}
```

### 2. Class toggle — `src/sase/ace/tui/modals/config_edit_rendering.py`

In `ConfigEditModalBase._sync_visibility()` (already invoked by every `_render_all()`), compute and apply the expansion
state:

```python
expanded = self._stage == "preview" or (
    self._stage == "edit" and not self._op_unset and self._uses_textarea()
)
self.set_class(expanded, "-expanded")
```

Also seed the class before the first paint (e.g. in `ConfigEditModal.on_mount` prior to the deferred `_initialize`, or
at the end of `compose`) so a YAML/text field opens expanded immediately instead of flashing the compact size for one
frame. All state needed (`_stage`, `_op_unset`, `_editor_kind`) is set in `__init__`.

### 3. Widget test — `tests/ace/tui/test_config_edit_modal_widget.py`

Add a test asserting the class logic across states:

- YAML/multiline field → modal has `-expanded` in edit stage; toggling reset (`ctrl+r`) drops it; un-reset restores it.
- Scalar string field → no `-expanded` in edit stage; after `action_confirm()` (preview stage) it gains `-expanded`;
  `escape` back to edit drops it.
- Bool/enum field → never expanded in edit stage.

Existing tests should keep passing unchanged, notably `test_large_yaml_value_keeps_editor_and_hints_visible` (editor +
hints both visible at 120×40) and `test_preview_scroll_keys_move_preview_region` (an 80-line diff still overflows the
expanded preview at 120×24, so scrolling still engages).

### 4. PNG visual goldens — `tests/ace/tui/visual/`

Two of the five edit-modal snapshots capture expanded states and must be regenerated with
`just test-visual --sase-update-visual-snapshots` (inspect `.pytest_cache/sase-visual/` artifacts first to confirm the
new layout is intentional):

- `config_center_edit_preview_120x40` (preview stage)
- `config_center_edit_object_value_120x40` (YAML editor)

The other three (`config_center_edit_modal`, `config_center_edit_normal_mode`, `config_center_edit_enum`) cover compact
states and should remain byte-identical — treat any change to them as a regression.

### 5. Verify

- `just install` (fresh workspace), then `just check`.
- Manual smoke: open the Admin Center → Config tab, edit a large object field (e.g. `axe.lumberjacks`) and confirm the
  editor fills most of the screen in both the edit and preview stages, then edit a bool/enum field and confirm the
  compact layout is unchanged.

## Out of Scope

- `AliasEditPreviewModal` (Models panel) copies the same 84-col style; leaving it as-is. Can follow up if the same
  treatment is wanted there.
- Raising the capped "current value" block in the info header (`_MODAL_VALUE_BLOCK_MAX_LINES = 3` in
  `config_edit_rendering.py`, the "… 52 more line(s)" text). The expanded space is deliberately given to the
  editor/preview; bumping this cap would eat into it. Possible follow-up.
- Any change to the Admin Center container or other Config-tab panes.
