---
create_time: 2026-04-25 23:24:56
status: done
prompt: sdd/prompts/202604/agent_tag_empty_enter_delete.md
---
# Plan: Empty-Enter Deletes Agent Tag (mirror `w` keymap behavior)

## Problem

The `N` keymap on the Agents tab opens `AgentTagModal` to set or clear an agent's tag. Today, clearing requires `Ctrl+D`
— pressing Enter on an empty input box raises an error notification ("Tag name cannot be empty") instead of clearing.

The `w` keymap on the Agents tab (`action_reword` → `_wait_agent` → `WaitModal`) follows a friendlier convention: the
modal opens prefilled with the current `waiting_for` value, the user can erase the contents (or open it on an empty
value), press Enter, and the empty submission is interpreted as "delete the wait state" (the caller writes `ready.json`,
releasing the agent). Empty-Enter is the natural "this field has no value, please clear it" gesture in this codebase,
and the user wants `N` to feel the same way.

## Goal

Make Enter on an empty `AgentTagModal` input dismiss with an `unset` result, semantically identical to `Ctrl+D`.
`Ctrl+D` stays as an explicit shortcut so muscle memory keeps working. Tags with whitespace only also count as empty
(the current `.strip()` already enforces that).

## Non-goals

- No change to the `w` / `WaitModal` flow.
- No change to tag persistence (`set_tag` / `unset_tag`) or the `_apply_agent_tag_change` handler — both already handle
  the `unset` action and are idempotent.
- No new keybindings, no rewording of `N` itself, and no help-modal changes beyond the in-modal hint text.

## Reference: how `w` does it

`src/sase/ace/tui/modals/wait_modal.py:71-73`

```python
def on_input_submitted(self, event: Input.Submitted) -> None:
    self.dismiss(event.value.strip())
```

`src/sase/ace/tui/actions/agents/_wait_resume.py:105-143` interprets the returned empty string as "run now" — i.e. clear
the wait state. The modal itself doesn't gate on emptiness; the caller decides what an empty value means.

The hint text in `WaitModal.compose` already documents this:

> "Enter agent name to wait for, or press Enter to run now."

## Reference: how `N` does it today

`src/sase/ace/tui/modals/agent_tag_modal.py`

- L49–52: `BINDINGS` registers `Ctrl+D` → `action_unset_tag`.
- L86–88: Hint reads `"Enter set · Ctrl+D clear · Tab complete\nType a tag name without the '@' prefix."`
- L130–132: `on_input_submitted` calls `_submit_set`.
- L134–136: `action_unset_tag` dismisses with `AgentTagModalResult(action="unset", tag=None)`.
- L138–149: `_submit_set` rejects empty input via `self.notify(..., severity="error")`.

The downstream handler `_apply_agent_tag_change` in `src/sase/ace/tui/actions/agents/_tagging.py:99-150` already
branches on `result.action`, so accepting empty-Enter as `unset` requires no handler changes.

## Design

Single-file behavior change in `agent_tag_modal.py`:

1. In `_submit_set`, replace the empty-input error path with
   `self.dismiss(AgentTagModalResult(action="unset", tag=None))`. This is exactly what `action_unset_tag` already
   returns — so empty-Enter becomes a strict alias for `Ctrl+D`.
2. Update the hint label (L86) to document the new gesture, e.g.
   `"Enter set (or clear if empty) · Ctrl+D clear · Tab complete"`. Keep it within the existing two-line layout.
3. Update the class docstring (L43–47) to reflect that empty-Enter now clears.

No changes to:

- `BINDINGS` (Ctrl+D stays).
- `_TagInput` or its tab-completion logic.
- `action_cancel` (Escape still cancels and returns `None`).
- The `default_tag` prefill path: an agent opened with `default_tag` and no `current_tag` will still seed the input; the
  user can backspace it away and Enter to clear (or Ctrl+D from the start). Since the agent has no current tag in that
  case, "clear" is a no-op — matching the existing Ctrl+D behavior in the same scenario.

## Edge cases to think through

- **Agent already untagged + empty-Enter.** Returns `unset`; downstream `unset_tag` is a no-op. Same as Ctrl+D today; no
  regression.
- **Bulk operation on marked agents, prefill empty, empty-Enter.** Returns `unset`; `_apply_agent_tag_change` clears
  tags on every affected agent. This is a behavior expansion — today the user must press Ctrl+D for bulk clear; after
  this change, Enter also works. The hint text covers this.
- **Whitespace-only input.** `raw = tag_input.value.strip()` already collapses to empty; treated as `unset`. Consistent
  with `w` modal, which also `.strip()`s.
- **Validation errors (non-empty but invalid).** Unchanged: still notify and stay open.

## Test plan

Add to `tests/ace/tui/test_agent_tag_modal_pilot.py` (existing pilot tests already cover Ctrl+D, set-on-prefill, and
bulk prefill):

1. `test_modal_empty_enter_unsets_when_untagged` — open with `current_tag=None`, no `default_tag`; press Enter; expect
   `AgentTagModalResult(action="unset", tag=None)`.
2. `test_modal_clear_then_enter_unsets_existing_tag` — open with `current_tag="name_level"`; press a key that empties
   the input (e.g. select-all already happens on mount, then `delete` or `backspace`); press Enter; expect `unset`.
3. `test_modal_whitespace_only_enter_unsets` — type a space, press Enter; expect `unset`.

Existing tests that should continue to pass without modification:

- `test_modal_prefill_then_ctrl_d_clears_in_one_keystroke`
- `test_modal_enter_on_prefill_emits_set_for_existing_tag` (non-empty prefill + Enter still sets)
- `test_modal_prefill_pinned_when_untagged_with_default` (default_tag prefill + Enter still sets)

No handler-level test changes are needed; `_apply_agent_tag_change` is unchanged.

## Files touched

- `src/sase/ace/tui/modals/agent_tag_modal.py` — `_submit_set` empty branch, hint text, class docstring.
- `tests/ace/tui/test_agent_tag_modal_pilot.py` — three new pilot tests.

## Validation

After the change:

1. `just install && just check` in the workspace (per `memory/short/workspaces.md`).
2. Manual TUI smoke (optional, since pilot tests cover the modal):
   - `N` on a tagged agent → Backspace through prefill → Enter → tag cleared, `Cleared tag …` notification.
   - `N` on an untagged agent → Enter → no-op clear, no error.
   - `N` → type valid tag → Enter → tag set (regression check).
   - `N` → Ctrl+D (regression check).
