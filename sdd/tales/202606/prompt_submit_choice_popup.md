---
create_time: 2026-06-17 11:26:28
status: done
prompt: sdd/prompts/202606/prompt_submit_choice_popup.md
---
# Plan: `<enter>` Submit-Choice Popup for Multi-Pane Prompt Stacks

## Goal

When the ACE prompt input is a **multi-pane prompt stack** (more than one prompt pane visible), pressing `<enter>`
should no longer silently launch the selected pane. Instead it should open a small, beautiful, keyboard-first **popup
panel** that lets the user choose, with a single keypress, how to submit:

- **Submit all** — launch every non-empty pane as one multi-agent xprompt (the existing `<ctrl+s>` behavior).
- **Submit current** — launch only the selected pane as a single agent (the _old_ `<enter>` behavior).

We also add a new `<ctrl+shift+s>` accelerator that performs "submit current" directly (the old `<enter>` behavior), so
power users draining a stack one pane at a time never have to round-trip through the popup.

Single-pane prompt bars, feedback bars, and approve-prompt bars are **unchanged**: `<enter>` submits directly as it does
today. The popup only ever appears for a genuine multi-pane prompt stack.

## Product Context & Motivation

The multi-agent prompt stack lets a user draft several prompts (`---`-separated) and launch them as parallel agents.
Today the two submit verbs collide on muscle memory:

- `<enter>` = launch just the selected pane (and keep the bar to drain the rest).
- `<ctrl+s>` = launch all panes together as a multi-agent xprompt.

`<enter>` is the most reflexive key, yet "launch only this one pane and pop it off the stack" is the _less_ common
intent for someone who deliberately built a multi-prompt stack — they usually want "launch them all." Reflexively
hitting `<enter>` therefore launches a single agent and quietly mutates the stack, which is surprising. Making `<enter>`
present an explicit, fast chooser removes that ambiguity at the exact moment it matters (only when a stack exists),
while `<ctrl+s>` / `<ctrl+shift+s>` remain as no-confirmation accelerators for users who already know what they want.

This mirrors the project's recent direction: `Shift+Enter` was intentionally removed as a whole-stack alias
(`sase_plan_remove_shift_enter_prompt_stack.md`) because reflexive keys were doing surprising whole-stack things. This
plan goes the complementary way — it makes the reflexive key _explicit_ rather than silently destructive.

## Current Behavior (precise)

Key handling lives in `src/sase/ace/tui/widgets/prompt_text_area.py::PromptTextArea._on_key` (lines ~333–350):

- `enter` → `action_submit_prompt()` → `PromptInputBar._handle_text_submission()` (`_prompt_input_bar_actions.py:36`).
  In a multi-pane stack this strips the selected pane, posts `Submitted(value, keep_bar=True)`, and rebuilds the stack
  so the bar stays mounted. In a single-pane bar it posts `Submitted(value)` and the app unmounts the bar. An empty
  selected pane is dropped without launching.
- `ctrl+s` → `action_submit_prompt_stack()` → `PromptInputBar._handle_whole_stack_submission()`
  (`_prompt_input_bar_actions.py:66`). Joins non-empty panes with `\n---\n` (`PromptStackState.join`) and posts
  `Submitted(value, whole_stack=True)`; the app unmounts the bar and routes through the multi-agent launch path.

Multi-pane detection already exists: `PromptInputBar.is_multi_pane()` (`_prompt_input_bar_stack_rendering.py:239`,
returns `len(self._stack) > 1`; feedback/approve-prompt bars are never stacks, so this implies prompt mode).

Both submit verbs already post the same `PromptInputBar.Submitted` message with `whole_stack` / `keep_bar` flags, and
the downstream launch path is unchanged. **The two underlying behaviors we need already exist** — this feature only adds
a disambiguation layer in front of them plus one new accelerator key.

### Rust core backend boundary

None of this crosses the boundary. This is purely Textual presentation / keybinding / widget glue: a new modal screen
plus a routing decision in the key handler. The actual submission verbs (`_handle_whole_stack_submission`,
`_handle_text_submission`) are unchanged, and the `---` join + fan-out planning that _does_ reach `sase_core_rs` happens
far downstream in the launch pipeline. No `sase-core` changes are needed.

## New Behavior & UX Design

### Trigger rules in `PromptTextArea._on_key`

`<enter>` branch becomes:

1. If file completion is active → accept completion (unchanged).
2. Else find the bar. If it is **multi-pane** _and_ the selected pane is **non-empty** → open the submit-choice popup.
3. Else → `action_submit_prompt()` (unchanged single-pane / final-pane / empty-pane behavior).

Rationale for the non-empty guard: pressing `<enter>` on an _empty_ pane currently drops it without launching (a quick
discard gesture, covered by `test_enter_on_empty_selected_pane_drops_it_without_submitting`). Popping a chooser whose
"submit current" option would do nothing is pointless, so we keep the legacy quick-discard for empty panes and only show
the chooser when there is something to submit. (Open to dropping this guard and always showing the popup if preferred;
the guard is the more polished default.)

New `<ctrl+shift+s>` branch (placed next to the `ctrl+s` branch): when the bar is multi-pane, swallow the key and call
`action_submit_prompt()` (old `<enter>` = launch selected pane, keep bar). Gated to multi-pane so the chord is
meaningful only where it applies; in single-pane bars it falls through (no-op), since plain `<enter>` already covers
that case. `<ctrl+s>` keeps doing `action_submit_prompt_stack()` unchanged.

### The popup: `PromptSubmitChoiceModal`

A new `ModalScreen[PromptSubmitChoice | None]` in `src/sase/ace/tui/modals/prompt_submit_choice_modal.py`, where
`PromptSubmitChoice = Literal["all", "current"]`.

It reuses the **existing single-keypress-choice visual vocabulary** already established by `DurationChoiceModal` /
`SnoozeDurationModal` (the polished snooze/override popups), so it looks native on day one: the shared
`.duration-choice-*` TCSS classes (`double $primary` border, centered, `$surface` background, bold centered title,
`$accent` tone on the primary row, dimmed subtitles). This keeps the popup consistent and beautiful without inventing a
new style language.

Layout (rendered with Rich markup `Static` rows, like `DurationChoiceModal._render_choice`):

```
        Submit prompt stack

  a   Submit all
      Launch all N prompts as one multi-agent xprompt.

  c   Submit current
      Launch only the selected prompt as a single agent.

  ^S all · ^⇧S current · esc cancel
```

- Title: "Submit prompt stack".
- Row `a` (primary tone / accent): **Submit all** — subtitle states the concrete count `N` of non-empty panes that would
  launch.
- Row `c` (default tone): **Submit current** — launch only the selected pane.
- Dimmed footer hint advertising the equivalent direct chords, so the popup _teaches_ the accelerators:
  `^S all · ^⇧S current · esc cancel`.

Single-keypress selection via `BINDINGS`, with the matching direct chords echoed inside the modal so muscle memory "just
works":

- `a` or `ctrl+s` → `dismiss("all")`
- `c` or `ctrl+shift+s` → `dismiss("current")`
- `escape` / `q` → `dismiss(None)` (cancel; bar and stack untouched)

(No cursor/`OptionList` navigation — single-key direct selection is the whole point, matching the duration-choice
pattern. `a`/`c` are mnemonic and collision-free with the modal's own keys.)

### Wiring the result back

Add `PromptTextArea._open_submit_choice_panel()`, modeled on the existing `_open_recursive_file_finder` push pattern in
the same file (`self.app.push_screen(Modal(...), callback)`, local import of the modal like `RecursiveFileFinderModal`):

- Compute `N` = count of non-empty panes (from `bar.all_prompt_texts()`), pass to the modal.
- Callback: `self._refocus_if_needed()` first (mirrors the recursive-finder callback), then:
  - `"all"` → `self.action_submit_prompt_stack()`
  - `"current"` → `self.action_submit_prompt()`
  - `None` → do nothing.

Because the choice routes through the existing `action_submit_prompt*` methods (which re-sync stack state from widgets
and operate on `bar._stack.selected_item`), selection and frontmatter re-attachment stay correct, and the existing
`Submitted` message contract (`whole_stack` / `keep_bar`) is preserved untouched. The modal is modal, so the stack can't
change between opening it and choosing.

## Implementation Steps

1. **New modal** — `src/sase/ace/tui/modals/prompt_submit_choice_modal.py`: `PromptSubmitChoiceModal` +
   `PromptSubmitChoice` literal, as designed above. Export both from `src/sase/ace/tui/modals/__init__.py`.

2. **Styling** — `src/sase/ace/tui/styles.tcss`: add `PromptSubmitChoiceModal` to the `align: center middle` selector
   group that currently lists `SnoozeDurationModal, _DurationPickerModal` (≈ line 705). Reuse the existing
   `.duration-choice-*` classes for everything else (no new rules needed; add a dedicated
   `#prompt-submit-choice-container` width override only if 54 cols looks off).

3. **Key handling** — `src/sase/ace/tui/widgets/prompt_text_area.py`:
   - Rework the `enter` branch in `_on_key` to route to `_open_submit_choice_panel()` for non-empty multi-pane stacks,
     else `action_submit_prompt()`.
   - Add a `ctrl+shift+s` branch (multi-pane → `action_submit_prompt()`).
   - Add `_open_submit_choice_panel()` helper.
   - Update the nearby comments to describe the new `<enter>` chooser and the `<ctrl+shift+s>` accelerator.

4. **Discoverability — subtitle** — `src/sase/ace/tui/widgets/prompt_input_bar.py::insert_mode_subtitle`: for the
   multi-pane branch, change `[Enter] send` → `[Enter] submit…` and append `[^⇧S] this` (keep `[^S] all` and the
   existing pane/move/nav/cancel hints so current substring assertions still pass). Single-pane subtitle and
   `normal_mode_subtitle` are unchanged.

5. **Discoverability — help modal** — `src/sase/ace/tui/modals/help_modal/binding_common.py::PROMPT_INPUT_SECTION`: add
   rows (≤32-char descriptions per the help-box rule), e.g.:
   - `("Enter", "Submit (chooser when stacked)")`
   - `("Ctrl+S", "Submit all panes (multi-agent)")`
   - `("Ctrl+Shift+S", "Submit current pane only")`

6. **User-facing docs** — `docs/ace.md`:
   - INSERT-mode table (≈ line 1614): update the `Enter` row to "Submit; in a prompt stack, open the submit chooser";
     keep `Ctrl+S`; add a `Ctrl+Shift+S` row ("Submit only the selected pane").
   - Prompt Stacks table (≈ line 1645) and surrounding prose (≈ line 1637): update the `Enter` row to describe the
     chooser, add `Ctrl+Shift+S` for the single-pane launch, and adjust the "pressing Enter immediately will launch that
     bottom pane" sentence to "pressing Enter opens the submit chooser." (`docs/xprompt.md` describes `Ctrl+S` for
     whole-stack submission and needs no change, but I'll grep to confirm.)

7. **Config check** — confirm `src/sase/default_config.yml` does not define these prompt-input keys (it doesn't appear
   to; they're hardcoded in `_on_key`). Per the keymap gotcha, verify and note — no change expected.

## Testing

Widget-level tests (`tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py` is the natural home; its `_CaptureApp`
hosts a bar and records `Submitted` messages and can `push_screen`):

- **Update** the enter-based multi-pane tests whose contract changes (`test_enter_submits_selected_pane_and_keeps_bar`,
  `test_enter_reattaches_frontmatter_to_single_pane_submit`, `test_enter_drains_stack_one_pane_at_a_time`): driving the
  single-pane launch now goes via `<ctrl+shift+s>` (or `<enter>` then `c`).
- **Keep unchanged**: `test_enter_on_empty_selected_pane_drops_it_without_submitting` (empty pane bypasses the popup),
  `test_enter_on_final_pane_submits_whole_bar` (single pane, no popup), `test_ctrl_s_submits_whole_stack_*`,
  `test_ctrl_s_is_noop_in_feedback_mode`, the `ctrl+c` cancel tests.
- **Add**:
  - `<enter>` on a non-empty pane in a multi-pane stack pushes `PromptSubmitChoiceModal` (and posts nothing yet).
  - Popup `a` (and `ctrl+s`) → `Submitted(whole_stack=True)`.
  - Popup `c` (and `ctrl+shift+s`) → `Submitted(keep_bar=True)` for the selected pane; bar stays mounted.
  - Popup `escape` → no submission, stack intact, bar mounted.
  - `<ctrl+shift+s>` directly (no popup) → `Submitted(keep_bar=True)`; in single-pane it does not break `<enter>`.
  - Subtitle assertions: multi-pane insert subtitle contains `[^⇧S] this` and still contains `[^S] all` / `[Esc] nav`;
    single-pane subtitle unchanged.

Visual snapshot (matches "make it beautiful"): add a PNG snapshot of the open popup to
`tests/ace/tui/visual/test_ace_png_snapshots_prompt_stack.py` (goldens under `tests/ace/tui/visual/snapshots/png/`),
generated with `--sase-update-visual-snapshots`, to lock in the rendered look.

## Validation

- `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + fast tests).
- `just test-visual` after adding/accepting the snapshot.
- Focused runs: `tests/ace/tui/widgets/test_prompt_stack_submit_cancel.py`,
  `tests/ace/tui/test_prompt_bar_stack_submit_handlers.py`, `tests/ace/tui/test_prompt_stack_launch_integration.py`.

## Risks & Caveats

- **Terminal delivery of `ctrl+shift+s`.** Like `ctrl+shift+h/l` and `ctrl+-`, the shifted chord relies on Kitty/CSI-u
  disambiguation and may not be received distinctly in every terminal. This is acceptable because `<enter>` → popup is
  the reliable primary path and `<ctrl+s>` covers "all"; `<ctrl+shift+s>` is a pure accelerator. The popup's footer and
  the help modal still teach it. (This is the same trade-off already accepted for the other shifted stack chords; it is
  the reason `Shift+Enter` was retired, so we lean on the popup as the dependable route.)
- **Behavior change for existing `<enter>` muscle memory.** Draining a stack one pane at a time now costs an extra key
  (`<enter>` then `c`) unless the user adopts `<ctrl+shift+s>`. This is the intended trade and is mitigated by the
  accelerator and by the subtitle/help advertising it.
- **Stale NORMAL-mode docs.** `docs/ace.md` Prompt Stacks table still lists retired `,j/,k/,J/,K` pane keys (now
  `Ctrl+H/L`); out of scope here, but I'll avoid contradicting the current keys when editing adjacent rows.
