---
create_time: 2026-07-05 19:48:44
status: wip
prompt: sdd/prompts/202607/vim_text_area_adoption.md
---
# Plan: Adopt vim + readline editing across TUI input boxes

## Context

Commit `1c21d266a` ("feat(tui): add vim + readline editing to config edit inputs") extracted the prompt widget's vim
layer into two reusable widgets:

- `VimTextArea` (`src/sase/ace/tui/widgets/vim_text_area.py`) — a `TextArea` with the full vim tower (normal/visual
  modes, motions, operators, counts, registers, dot-repeat, surround) plus readline insert-mode bindings, self-contained
  mode display on the widget border, and overridable host hooks.
- `SingleLineVimTextArea` (`src/sase/ace/tui/widgets/single_line_vim_text_area.py`) — a one-line variant that behaves
  like Textual's `Input`: Enter posts `Submitted`, newlines are flattened, `o`/`O`/`ctrl+j` suppressed,
  `TextArea.Changed` drives live validation.

That commit adopted the widgets in `ConfigEditModal` and `_OverlayNameModal` only. This plan rolls the same editing
experience out to the rest of the TUI **where it is genuinely valuable**, and deliberately leaves alone the inputs where
vim semantics would hurt the interaction.

## Scope decision framework

The discriminator is: **does the user compose or edit meaningful text in this box?**

**Convert** — real text entry/editing (names, commands, queries, prose, YAML, paths, tags). Vim motions/operators pay
off, and the established "esc → NORMAL, esc esc → cancel" layering from the config-edit precedent is acceptable UX.

**Exclude** — live-filter / pick-list boxes and quick-fire numeric entries. Reasons:

1. The dominant flow is "type a few chars → pick a row → Escape out". Vim's two-stage Escape (INSERT → NORMAL → only
   then bubbles to the host) regresses the most common action: dismissal.
2. Several filter inputs forward keys to their host while typing (`[` / `]` switch Config Center tabs; bare digits jump
   to numbered tabs when the filter is empty; `tab` loads the highlighted row). These collide with NORMAL-mode vim
   semantics (counts, brackets).
3. Filter text is short and disposable; there is nothing to _edit_.

### Excluded sites (leave as plain `Input`)

- **All live-filter inputs**:
  - `FilterInput` base + subclasses (`src/sase/ace/tui/modals/base.py`)
  - Config Center panes: `ConfigFilterInput` (`config_pane_widget.py`), `BrowserFilterInput`
    (`xprompt_browser_filter_input.py`), `PluginsFilterInput` (`plugins_browser_input.py`), `_ProjectsFilterInput`
    (`projects_pane.py`)
  - Filter modals: `model_picker_modal.py`, `command_history_modal.py` (borderline — it can also accept a new command,
    but it is primarily a history filter), `command_palette_modal.py`, `xprompt_select_modal.py`,
    `xprompt_save_target_modal.py`, `xprompt_location_modal.py`, `prompt_history_modal.py`, `hook_history_modal.py`,
    `revive_agent_modal.py`, `project_select_modal.py`, `agent_cleanup_custom_modal.py` (search field)
- **`HintInputBar`** (`widgets/hint_input_bar.py`) — quick-fire hint selection ("3", "1 3 5"); two-stage Escape would
  slow the rapid select/cancel loop, and its bespoke `ctrl+d`/`ctrl+u` detail-panel scrolling and `ctrl+e`
  fill-placeholder integration would all need porting for little gain. Possible follow-up later if hooks-mode command
  entry warrants it.
- **`wait_modal.py`** — the agents field is completion-driven (`ctrl+n`/`ctrl+p` candidate list, Enter accepts a
  candidate); vim NORMAL mode would fight the completion flow, and values are short comma-separated names / durations.
- **`workspace_input_modal.py`, `duration_choice_modal.py`** (and its snooze / model-duration users) — 1–4 character
  numeric/duration entries; no editing value, keep single-Escape cancel.

## Shared infrastructure (do first)

1. **Placeholder support.** Textual 8.2.7's `TextArea` accepts `placeholder=`. Verify it renders correctly in
   `SingleLineVimTextArea` (empty single-line document, no line numbers) including NORMAL mode (`read_only=True`). Add a
   widget test. Nearly every conversion below carries a placeholder, so this is load-bearing. (Note: the
   `_OverlayNameModal` conversion dropped its `placeholder="work"` — restore it once verified.)
2. **Shared CSS.** `styles.tcss` currently styles the two adopted single-line editors by ID (`#config-edit-input`,
   `#overlay-name-input`: `height: 3` + `border: solid $secondary` carrying the vim mode title). With ~20 more
   adoptions, add one type-selector rule for `SingleLineVimTextArea` (height, border, width) and delete the per-ID
   duplicates. The generic `VimTextArea.-vim-*` cursor rules from `1c21d266a` already cover all new sites.
3. **Activity gate.** `EventKeyboardMixin.on_input_changed` (`src/sase/ace/tui/actions/_event_keyboard.py`) records
   typing activity for input-quiescence timing because `Input` stops key events from bubbling. Add the
   `TextArea.Changed` counterpart (`on_text_area_changed` → `_record_input_event()`) so converted editors keep the
   activity gate accurate.
4. **`check_action` guard.** `AceApp.check_action` (`src/sase/ace/tui/app.py`, ~line 260) blocks `next_tab`/`prev_tab`
   while a `PromptTextArea` is focused. Broaden the isinstance check to `VimTextArea` (covers the prompt too) so the
   non-modal conversions below (frontmatter panel) don't trigger tab switches from NORMAL-mode keys that bubble.
5. **Document the adoption recipe** (docstring on `SingleLineVimTextArea` or a short note in the widget module) so
   future inputs follow it:
   - `Input` → `SingleLineVimTextArea`; read `.text` instead of `.value`
   - `on_input_submitted` → `on_single_line_vim_text_area_submitted`
   - `on_input_changed` → `on_text_area_changed` (filter by widget id)
   - focus seeding: `editor.focus()` + `editor._update_vim_mode_display()` on mount
   - prefill: pass initial text positionally, then `move_cursor` to end (and `select_all()` where the old code selected)
   - Escape layering: modal-level `escape → cancel` bindings keep working (NORMAL-mode Escape with nothing pending
     bubbles); update on-screen hints to "esc esc cancel"
   - multi-field modals: `TextArea`'s default `tab_behavior="focus"` preserves Tab field cycling — do not override it

## Phase 1 — multi-line editors (highest value)

1. **XPrompt content editor** — `src/sase/ace/tui/modals/xprompt_item_modal.py` (line ~164,
   `TextArea(id="xprompt-item-content", ...)`): switch to `VimTextArea`. Keep `soft_wrap=True`,
   `show_line_numbers=False` at INSERT; the widget flips line numbers on in NORMAL mode for multi-line documents, which
   is desirable here. `Ctrl+S` save binding is unaffected; Escape cancel becomes two-stage — update the modal's hint
   text. `on_text_area_changed` (line ~200) keeps working unchanged.
2. **Frontmatter raw-YAML editor** — `src/sase/ace/tui/widgets/frontmatter_panel.py` (line ~114,
   `TextArea(id="frontmatter-raw")`): switch to `VimTextArea`. Audit `widgets/_frontmatter_panel_raw.py` (its
   `TextArea.Changed` handling is compatible as-is) and the raw-mode enter/exit key layering — if raw mode currently
   exits on Escape, that becomes esc-esc; update any hints. This is a non-modal widget on the main screen, which is why
   the `check_action` guard in shared infra must land first.
3. **Frontmatter inline field editor** — `frontmatter_panel.py` (line ~113, `Input(id="frontmatter-inline")`): switch to
   `SingleLineVimTextArea`. Audit `widgets/_frontmatter_panel_editing.py` for `.value` reads and submit/cancel key
   handling. The inline editor is space-constrained; if a 3-row bordered box doesn't fit the panel layout, override
   `_update_vim_mode_display` to surface the mode in the panel's existing chrome instead of a border (the hook exists
   for exactly this — see `PromptTextArea`).

## Phase 2 — single-line modal editors (`Input` → `SingleLineVimTextArea`)

Apply the adoption recipe to each. Grouped by expected payoff:

**High value (long/editable content):**

- `query_edit_modal.py` — `_QueryInput`; ace query strings are long expressions, prime vim target
- `command_input_modal.py` — `_CommandInput` ("e.g., make test")
- `rename_cl_modal.py` — `_RenameInput` prefilled with the current name; editing an existing value is exactly what vim
  motions are for; place cursor at end on mount
- `user_question_modal.py` — `#user-question-other-input` and `#user-question-global-input` (prose answers / notes).
  Careful: the modal's `on_key` (~line 562) handles Escape-in-input-mode itself to hide the input and refocus the
  options list — with vim, first Escape must go to the widget (INSERT→NORMAL) and only a NORMAL-mode Escape should
  trigger the existing hide/refocus logic. Gate the modal's Escape branch on the editor's mode (or rely on event
  bubbling order) and cover with a test.
- `custom_model_input_modal.py` — `_ModelInput`; model ids are long dotted strings
- `project_alias_editor_modal.py` — `_ProjectAliasInput` (comma-separated alias list)

**Names / paths / tags (consistency + moderate value):**

- `agent_name_modal.py`, `xprompt_name_modal.py`, `local_xprompt_name_modal.py`, `snippet_name_modal.py`,
  `save_agent_group_modal.py` — `_NameInput`-style single fields
- `add_xprompt_modal.py`, `xprompt_filename_modal.py` — path/filename entry
- `agent_tag_modal.py`, `tag_input_modal.py` (two fields) — tag entry
- `xprompt_config_modal.py` (name + `arg_name type` fields), `input_item_modal.py` (four fields; its bespoke
  `ctrl+f`/`ctrl+b` readline bindings are subsumed by `VimTextArea`), `input_collection_modal.py`
  (`_InputCollectionInput` + `_PathField`) — multi-field forms; verify Tab cycles fields and Enter submit routing per
  field still works

Many of these define trivial `Input` subclasses only to add readline keys or placeholder behavior; delete the subclass
where `SingleLineVimTextArea` covers it.

## Phase 3 — memory review TUI (stretch, separate CL)

`src/sase/memory/review_tui/_modals.py` — `TextInputModal` wraps one plain `Input` reused for the filter box,
reject-reason entry, and target edits. Converting the single shared class is cheap and reject-reason/target entry is
real text composition; the filter usage inherits two-stage Escape, which is milder here than in pick-list modals because
the filter itself lives in a modal (Enter submits, esc esc cancels). Convert wholesale; keep the validator and
`select_all()`-on-mount behavior (`TextArea.select_all()` exists). If the esc-esc filter friction is deemed unacceptable
at review time, drop this phase — it is independent of everything else.

## Testing

- **Widget tests**: extend `tests/ace/tui/widgets/test_single_line_vim_text_area.py` with the placeholder rendering
  test; reuse the `VimEditorPage` harness from `sase.ace.testing`.
- **Per-modal integration tests**: follow the `tests/ace/tui/test_config_edit_modal_widget.py` patterns from
  `1c21d266a`. For each converted modal, cover at minimum: (a) typing + Enter submits the value, (b) esc → NORMAL then
  edit motions work (e.g. `0`, `cw`), (c) esc esc cancels the modal, (d) live-validation `Changed` handlers still fire.
  The `user_question_modal` Escape interplay and multi-field Tab cycling (`tag_input_modal`, `input_item_modal`,
  `input_collection_modal`, `xprompt_config_modal`) each need a dedicated test.
- **PNG snapshots**: converted inputs change geometry (height 1 → 3, new border with mode title), so affected goldens
  must be regenerated — at least `test_ace_png_snapshots_frontmatter_panel.py`,
  `test_ace_png_snapshots_models_panel_edit.py`, and any suite that renders a converted modal. Run `just test-visual`,
  inspect `.pytest_cache/sase-visual/` diffs, and use `--sase-update-visual-snapshots` only for the intentional changes.
- `just check` after each CL.

## Performance notes

- No synchronous work is added to key paths: the vim tower is pure in-memory state, and existing `Changed`-driven
  validation handlers are unchanged in frequency (`TextArea.Changed` fires per edit exactly as `Input.Changed` did).
- The excluded filter inputs are the per-keystroke hot paths (they re-filter lists on every `Changed`); leaving them as
  `Input` means zero risk there.
- The shared-infra `on_text_area_changed` activity hook keeps the input-quiescence gate accurate for converted editors.

## Suggested CL breakdown

1. **CL 1**: shared infrastructure (placeholder verification + test, shared CSS rule, activity gate, `check_action`
   broadening, recipe docs) + Phase 1 multi-line editors.
2. **CL 2**: Phase 2 high-value single-line modals.
3. **CL 3**: Phase 2 names/paths/tags batch.
4. **CL 4** (optional): Phase 3 memory review TUI.

Each CL is independently shippable; later CLs are mechanical applications of the recipe established in CL 1.

## Risks / open questions

- **Placeholder rendering in NORMAL mode**: if Textual's `TextArea` placeholder misbehaves with `read_only=True` or the
  vim cursor CSS, fall back to seeding placeholders as help text below the editor (the `_OverlayNameModal` precedent
  already shows a help-label pattern).
- **Modal height**: every converted single-line input grows the modal by 2 rows; spot-check small modals at 80×24
  terminals for overflow.
- **`user_question_modal` Escape layering** is the one conversion with nontrivial key-flow changes; it gets its own
  tests and can be deferred to the end of Phase 2 if it drags.
