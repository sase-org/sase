---
create_time: 2026-06-19 22:19:43
status: done
prompt: sdd/prompts/202606/agent_tag_enter_clears.md
---
# Plan: Pressing `N` then Enter on a tagged agent should move it to `(untagged)`

## Problem

On the `sase ace` Agents tab, pressing `N` (the "tag/untag" keymap) on a **top-level tagged agent** and then pressing
**Enter** does nothing — the agent stays in its current tag group instead of moving to `(untagged)`.

The user's mental model: `N` is "delete this agent's group". They press `N`, see the current tag pre-filled and
highlighted in the input, press Enter expecting the selected text to clear, and the agent to drop into `(untagged)`.

## Root cause

The behavior is **working as currently designed and tested**, but the design contradicts the natural gesture. Two
recently-added features are in tension:

1. `feat: make agent-tag removal discoverable` (763232a6f) — the modal now **pre-fills the input with the focused
   agent's current tag** and selects it, so the first keystroke replaces it (rename) and `Ctrl+D` removes it in one
   keystroke.
2. `feat: empty-Enter clears agent tag` (255db37d6) — pressing Enter on an **empty** input dismisses with an `unset`
   result (moves the agent to `(untagged)`).

Because feature #1 guarantees the box is _never empty_ for an already-tagged agent, feature #2 (empty-Enter clears) is
**unreachable** in exactly the case the user hits. Concretely:

- `action_add_agent_tag` (`src/sase/ace/tui/actions/agents/_tagging.py`) opens the modal with `current_tag=agent.tag`.
- `AgentTagModal.compose` (`src/sase/ace/tui/modals/agent_tag_modal.py`) sets
  `initial = self._current_tag or self._default_tag or ""`, so the box is pre-filled with the existing tag; `on_mount`
  selects it.
- Pressing Enter routes to `_submit_set`, where the unchanged value (`"name_level"`) is non-empty, so the modal
  dismisses with `action="set", tag="name_level"` — **re-setting the same tag**.
- `_apply_agent_tag_change` sees `before == after`, counts `changed == 0`, shows a faint
  `"No tag set (already in target state)"` info toast, and returns without changing the group.

So Enter re-applies the existing tag (a no-op) rather than clearing it. Textual's `Input` treats Enter as "submit the
current value"; it does not delete the selected text, which is the crux of the surprise. The existing pilot test
`test_modal_enter_on_prefill_emits_set_for_existing_tag` encodes today's (unwanted) behavior.

## Goal

Make the user's exact gesture work: on a tagged top-level agent, `N` → Enter moves it to `(untagged)`. Preserve the
other workflows (tag an untagged agent, rename a tag, bulk tag/untag, `Ctrl+D` muscle memory).

## Proposed approach (recommended): the input holds the _desired_ tag, not the current one

Adopt one clean invariant: **the input box always holds the tag the agent should end up with; empty means
`(untagged)`.** The current tag is shown for context in the existing `Current: @<tag>` label, not in the editable box.

Changes:

- **`AgentTagModal` (`agent_tag_modal.py`)**: stop seeding the input with `current_tag`. For a tagged agent the box
  opens **empty** (current value still shown in the `Current:` label); for an untagged agent it still seeds
  `default_tag` (the `pinned` convenience). Effectively:
  `initial = "" if current_tag is not None else (default_tag or "")`. Keep `on_mount`'s `select_all` (harmless on an
  empty box; still selects the `pinned` default so the first keystroke replaces it). Keep `Ctrl+D` and the
  empty/whitespace-Enter → `unset` paths intact.
- **Hint text**: keep it accurate — Enter sets the typed tag or clears when empty; `Ctrl+D` clears; Tab completes.
  Adjust wording only if needed for clarity.
- No change needed in `_tagging.py` or `_apply_agent_tag_change`; once the modal returns `unset`, the existing
  apply/refilter path already moves the agent to `(untagged)`.

Resulting behavior:

| Scenario             | Box on open             | Enter does                   |
| -------------------- | ----------------------- | ---------------------------- |
| Tagged agent, remove | empty (`Current: @foo`) | **clears → `(untagged)`** ✅ |
| Tagged agent, rename | empty                   | type new tag → set           |
| Untagged agent       | `pinned` (default)      | pins                         |
| Bulk (marks)         | empty                   | type tag → set all           |

Renaming now costs a retype instead of an edit, mitigated by Tab-completion against known tags; this is the deliberate
trade to make removal-by-Enter intuitive. Removal stays discoverable via the `Current:` label, the hint, and `Ctrl+D`.

### Alternative considered (not recommended)

Keep the prefill, but make Enter **on the unmodified prefilled value** dismiss as `unset` instead of a no-op re-set.
This is more surgical (preserves edit-to-rename) but "magical": Enter would mean different things depending on whether
you touched the text, making an accidental Enter destructive. The recommended approach is more predictable. (If
preferred at review, this is a small, localized variant.)

## Tests

Update the pilot suite in `tests/ace/tui/test_agent_tag_modal_pilot.py` to encode the new contract:

- **Replace** `test_modal_enter_on_prefill_emits_set_for_existing_tag` with a test asserting a tagged agent's modal
  opens with an **empty** box and Enter dismisses with `unset` (moves to `(untagged)`).
- Update `test_modal_prefill_then_ctrl_d_clears_in_one_keystroke` and `test_modal_first_keystroke_replaces_prefill` for
  the empty-box-on-tagged-agent start state (Ctrl+D / typing still behave correctly).
- Keep passing: bulk-empty, untagged empty-Enter unset, whitespace-Enter unset, clear-then-Enter unset, and
  `default_tag="pinned"` → Enter sets `pinned`.
- Optionally add one higher-level Agents-tab pilot/integration check that `N` then Enter on a tagged root agent results
  in the agent appearing under `(untagged)`, to guard the end-to-end path (modal → `_apply_agent_tag_change` →
  refilter).

## Out of scope

- No keymap/binding changes (no `default_config.yml` edits); `N` stays bound to `add_agent_tag`.
- No change to bulk-tagging semantics or the `pinned` default for untagged agents.
- No Rust core changes — this is presentation-layer modal UX; the tag store (`agent_tags.json`) read/write path is
  unchanged.

## Validation

- `just install` then `just check` (lint + mypy + tests), per repo rules.
- Manually: in `sase ace`, tag a root agent, press `N` → Enter, confirm it moves to `(untagged)`; confirm rename,
  untagged-pin, bulk, and `Ctrl+D` still work.
