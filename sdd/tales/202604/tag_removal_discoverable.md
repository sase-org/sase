---
create_time: 2026-04-25 18:11:35
status: done
prompt: sdd/prompts/202604/tag_removal_discoverable.md
---
# Plan: Make agent-tag removal discoverable in `sase ace`

## Problem

In the Agents tab of `sase ace`, removing an existing tag from an agent is technically supported but practically
invisible. From the user's snapshot:

```
══ @name_level 1 agent · 1 running ════════════
── sase / sase 1 agent · 1 running ────────────
[agent] sase (RUNNING) (4 steps) @name_level @m
```

The user wanted to drop `@name_level` and reported they could not find a way. The footer hint `t tag` doesn't allude to
removal, and even after pressing `t` the modal opens with an empty input — so removing a known tag forces the user to
retype its full name and then press the (undocumented in the footer) Ctrl+D shortcut.

## Diagnosis (already verified)

The wiring is correct: `AgentTagModal` declares `Binding("ctrl+d", "remove_tag", priority=True)` on the screen
(`src/sase/ace/tui/modals/agent_tag_modal.py:51`) and `_submit("remove")` forwards the result to
`_apply_agent_tag_change` which calls `agent_tags.remove_tags`. A textual `run_test()` pilot — typing `name_level` then
pressing `ctrl+d` — dismisses the modal with `AgentTagModalResult(action='remove', tag='name_level')`. Priority on the
screen overrides `Input`'s default `delete,ctrl+d → delete_right`, so this is **not** a binding-shadowing bug.

The root cause is purely UX:

1. The footer label `t tag` reads as "add tag" only.
2. The modal's empty input forces the user to retype an existing tag to remove it.
3. The "Enter=add, Ctrl+D=remove" hint is one small line, easy to miss.
4. The "Current: @name_level" label is informational, not actionable.

## Goal

When a user opens the modal on an agent that already has a tag, removing that tag should be a **single keystroke** and
the option should be discoverable without reading fine print.

## Design

### Decision: defer the "numbered chips" stretch idea

The numbered-chip idea (render `Current: [1] @name_level [2] @triage` and bind `1..9` to remove) is genuinely nicer for
multi-tag agents. It is **deferred** for now because:

- The vast majority of agents in the snapshot have at most one tag; the prefill+Ctrl+D path already collapses removal to
  one keystroke for that case.
- It introduces real complexity (digit-key bindings collide with the Input widget unless we move the digits to a
  non-Input widget; chip rendering needs Rich markup; the 1..9 bindings interact with Input focus). That's not justified
  by current usage.
- The deferred design composes cleanly on top of v1 — we'd add new bindings and a chips widget, not undo any of v1's
  changes.

If multi-tag agents become common, revisit and ship the chips widget as a follow-up.

### v1 — three small changes

**1. Prefill the input with the primary tag (single-agent path only).**

In `AgentTagModal.compose`, when `self._current_tags` has at least one entry and the modal was opened for a single agent
(vs. bulk), set the `_TagInput` initial value to `self._current_tags[0]` and select the text so the first keystroke
replaces it.

The single-vs-bulk distinction is already encoded at the call site (`_tagging.py`: bulk passes `current_tags=()`, single
passes the agent's full tag tuple), so checking `bool(self._current_tags)` inside the modal is sufficient — no new
constructor arg needed.

After this change:

- `t` → modal opens with `name_level` selected, hint visible → `Ctrl+D` removes. **Two keystrokes total**, one of them
  the keystroke that opened the modal.
- `t` → start typing → selection is replaced (textual Input does this natively when text is selected) → user is in the
  same flow they'd have today.
- `t` → `Enter` → no-op with the existing "already added" toast (already handled in `_apply_agent_tag_change`, lines
  119–124). Acceptable and informative.

**2. Tighten and emphasise the hint line.**

Current:

```
Type a tag name (no '@'). Enter=add, Ctrl+D=remove, Tab=complete.
```

Proposed (Rich markup, two visual rows, action verbs bolded):

```
[bold]Enter[/] add · [bold]Ctrl+D[/] remove · [bold]Tab[/] complete
Type a tag name without the '@' prefix.
```

Two-row layout pulls the action vocabulary out of prose. We keep the existing label id (`agent-tag-hint`) so any CSS
selectors still apply.

**3. Footer label: `tag` → `tag/untag`.**

`src/sase/ace/tui/widgets/_keybinding_bindings.py:151`:

```python
bindings.append((self._kd("start_tmux_mode"), "tag/untag"))
```

The slash form keeps the label short (≤9 chars) and signals bidirectionality. Per the conventions in
`src/sase/ace/AGENTS.md`: alphabetical sort is preserved (the label is sorted by its key character `t`, not by text);
the keymap remains conditional (Agents tab only, focused agent), so it stays in the footer.

### Help modal sync

`src/sase/ace/tui/modals/help_modal/bindings.py:320` currently shows:

```python
(d(a.start_tmux_mode), "Tag agent (or marked set)"),
```

Update to:

```python
(d(a.start_tmux_mode), "Tag/untag agent (or marked set)"),
```

The line stays well under the 32-char keybinding-description limit (24 chars). Box width (`_BOX_WIDTH = 57`) is
unaffected.

No other entries in `bindings.py` reference the agent tag modal.

### Files changed (summary)

| File                                                | Change                                                                                                         |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/modals/agent_tag_modal.py`        | Prefill `_TagInput.value` with primary tag (single-agent), select-all on mount, rewrite `agent-tag-hint` text. |
| `src/sase/ace/tui/widgets/_keybinding_bindings.py`  | Line 151 label: `"tag"` → `"tag/untag"`.                                                                       |
| `src/sase/ace/tui/modals/help_modal/bindings.py`    | Line 320 description: `"Tag agent (or marked set)"` → `"Tag/untag agent (or marked set)"`.                     |
| `tests/ace/tui/test_agent_tagging.py`               | Add prefill-related assertions; do not touch existing tests.                                                   |
| `tests/ace/tui/test_agent_tag_modal_pilot.py` (new) | Textual pilot test covering Enter/Ctrl+D paths and prefill behaviour.                                          |

## Implementation

### `src/sase/ace/tui/modals/agent_tag_modal.py`

1. In `compose`, change the `_TagInput` instantiation to:
   ```python
   initial = self._current_tags[0] if self._current_tags else ""
   yield _TagInput(
       value=initial,
       placeholder="tag-name",
       id="agent-tag-input",
   )
   ```
2. In `on_mount`, after focusing the input, select all text so the first typed character replaces the prefilled value:
   ```python
   def on_mount(self) -> None:
       tag_input = self.query_one("#agent-tag-input", _TagInput)
       tag_input.focus()
       if tag_input.value:
           tag_input.selection = (0, len(tag_input.value))
   ```
   Verify the exact API in textual 8.0.0 — if `selection` is unavailable, fall back to `tag_input.action_select_all()`
   or position the cursor at end and rely on the existing `ctrl+u` (delete-line) readline binding for users who want a
   fresh start.
3. Replace the single hint label with two stacked labels (or one label with `\n`-joined Rich markup). Keep
   `id="agent-tag-hint"` on the container/label so future CSS still applies.

### `src/sase/ace/tui/widgets/_keybinding_bindings.py`

Single-character edit at line 151: `"tag"` → `"tag/untag"`.

### `src/sase/ace/tui/modals/help_modal/bindings.py`

Single-character edit at line 320: `"Tag …"` → `"Tag/untag …"`.

### Tests

`tests/ace/tui/test_agent_tagging.py` — add two assertions, no existing test changes:

- In `test_action_pushes_modal_for_focused_agent` (line 83): after the modal is captured, assert the modal would render
  the prefilled value. Since this test does not actually mount the modal, add a sibling unit test that constructs
  `AgentTagModal` directly with `current_tags=("primary",)`, runs it under `App.run_test()`, and checks
  `query_one("#agent-tag-input").value == "primary"`.
- New test `test_modal_prefill_empty_for_bulk`: construct `AgentTagModal(current_tags=())`, mount, assert
  `_TagInput.value == ""`.

`tests/ace/tui/test_agent_tag_modal_pilot.py` (new file, follows the pattern of
`tests/ace/tui/widgets/test_prompt_file_completion.py`):

- `test_modal_prefill_then_ctrl_d_removes_in_one_keystroke`:
  1. Push `AgentTagModal(current_tags=("name_level",), …)`.
  2. `await pilot.press("ctrl+d")` (no typing — prefilled value stands).
  3. Assert the modal dismissed with `AgentTagModalResult(action="remove", tag="name_level")`.
- `test_modal_first_keystroke_replaces_prefill`:
  1. Push modal with prefilled `name_level`.
  2. Press a single character (e.g. `x`).
  3. Assert input value is `"x"` (selection-on-mount caused replacement).
- `test_modal_enter_on_prefill_emits_add_for_existing_tag`:
  1. Push modal with prefilled `name_level`.
  2. Press `enter`.
  3. Assert dismissed with `AgentTagModalResult(action="add", tag="name_level")`. The existing `_apply_agent_tag_change`
     no-op-toast handles the rest at the action layer.

If the textual 8.0.0 selection API differs from what's assumed, the second pilot test will fail fast; resolve by
switching to whichever API actually selects all text in `Input` (or accept that prefill is non-replacing and document
the trade-off in the hint).

### Manual verification

1. `just install && just check` in the workspace.
2. Launch `sase ace` against a project with at least one tagged agent (e.g. `@name_level`).
3. Focus the tagged agent. Confirm the footer reads `… t tag/untag …`.
4. Press `t`. Confirm:
   - Modal opens with the primary tag pre-filled and selected.
   - Hint text is on two visible rows with bolded action verbs.
5. Press `Ctrl+D` immediately. Confirm a notification "Removed @name_level on 1 agent" and the tag chip disappears from
   the row.
6. Re-tag the agent (`t`, type `name_level`, Enter). Press `t` again, then a letter — confirm the first keystroke
   replaces the prefilled value (does not append).
7. Press `?`. Confirm the help modal lists `t` as "Tag/untag agent (or marked set)" and the box width is unchanged.
8. Bulk path: mark two agents (`m m`), press `t`. Confirm input is empty (no prefill in bulk mode), per design.

## Out of scope

- Numbered-chip removal for multi-tag agents (deferred — see "Decision" above).
- Changing `t` to a different keymap.
- Tag behaviour on the AXE or ChangeSpecs tabs.
- Tag-store schema or `agent_tags.json` format changes.

## Risks

- **Selection API drift**: textual 8.0.0's `Input` may not expose `selection` directly. Mitigation: the v1 pilot test
  `test_modal_first_keystroke_replaces_prefill` will catch this; we can fall back to `action_select_all`, a
  `cursor_position = 0` + later select range, or simply cursor-at-end with no selection (then prefill is _additive_ on
  first keystroke, which is the acceptable degraded mode — Ctrl+U still wipes it).
- **Footer width**: `tag/untag` is 9 chars vs. `tag`'s 3. The footer line in the snapshot has ample room; if a workspace
  ever exceeds the panel floor (60-cols, recent change in `widen_agents_panel_diagnose`), this might wrap one slot
  earlier. Acceptable cost for the discoverability gain.
- **Bulk-path expectation**: prefill is single-agent-only. Bulk users won't see anything different. Documented in the
  "Manual verification" step 8.
- **Hint markup**: switching to Rich markup in a `Label` requires `Label(...)` to render markup by default (it does in
  textual 8.x). Pilot test will validate.
