---
create_time: 2026-04-25 21:51:39
status: done
---
# Plan: Default `N`-keymap tag-input value to `pinned`

## Problem

In `sase ace`'s **Agents** tab, pressing `N` opens a small modal that lets the user set or clear the tag on the focused
agent (or, if marks exist, the marked set). Today the modal seeds its input box with:

- the agent's existing tag, when the agent already has one, **or**
- the empty string otherwise.

The "untagged" path forces the user to type the tag name from scratch. In practice the overwhelmingly common tag the
user types in that situation is `pinned` (used to surface agents on the dedicated Pinned panel). We want the modal to
reflect this so a single `N` + `<Enter>` pins the focused agent.

## Desired behavior

When `N` is pressed on the Agents tab with a single focused agent:

- **Agent already has a tag** → input is pre-filled with that tag (unchanged behavior).
- **Agent has no tag** → input is pre-filled with `pinned`.

In both cases the prefilled text should be selected (existing behavior), so the first printable keystroke replaces it.
`Ctrl+D` continues to clear the agent's tag in one keystroke regardless of what is pre-filled.

The `Current:` label inside the modal must continue to truthfully report the agent's actual current tag — e.g. it should
still display `(none)` for an untagged agent even when the input box shows `pinned`. The default is a _seed for the
input_, not a claim about state.

The bulk path (marks present) is **out of scope** for this change. Today it seeds the input with `""`; that behavior is
preserved so existing tests and muscle memory are unaffected.

## Design

Add an explicit "default seed" parameter to the modal so the caller controls the prefill, and keep the display of the
current tag separate.

### `src/sase/ace/tui/modals/agent_tag_modal.py`

- Extend `AgentTagModal.__init__` with a new keyword-only parameter `default_tag: str | None = None`.
  - Stored as `self._default_tag`.
- In `compose()`, change the input seed from `self._current_tag or ""` to
  `self._current_tag or self._default_tag or ""`.
- The `Current:` label keeps reading from `self._current_tag` only — no display change.

### `src/sase/ace/tui/actions/agents/_tagging.py`

- Define a module-level constant `DEFAULT_PINNED_TAG = "pinned"` for clarity (single source of truth, easy to find).
- Extend `_open_agent_tag_modal` with a `default_tag: str | None = None` keyword-only parameter; forward it to
  `AgentTagModal(...)`.
- In `action_add_agent_tag`, on the **single-agent** branch (after we have resolved `agent`), pass
  `default_tag=DEFAULT_PINNED_TAG`. The bulk branch intentionally does not pass it.

That's the entire production-code surface.

## Tests

The change is small but user-visible, so we add focused coverage and update an existing assertion.

### New test — `tests/ace/tui/test_agent_tag_modal_pilot.py`

Add `test_modal_prefill_pinned_when_untagged_with_default()`:

- Construct `AgentTagModal(target_label="agent-x", current_tag=None, known_tags=(), default_tag="pinned")`.
- Assert `tag_input.value == "pinned"`.
- Press `<Enter>` and assert the dismiss result is `AgentTagModalResult(action="set", tag="pinned")` — proves the
  one-keystroke pin flow.

The existing `test_modal_prefill_empty_for_bulk` continues to pass because it does not pass `default_tag`, so the seed
stays empty. No change required.

### New test — `tests/ace/tui/test_agent_tagging.py`

Add `test_action_seeds_pinned_for_untagged_focused_agent()` (or extend `test_action_pushes_modal_for_focused_agent`):

- Build the harness with a focused agent whose `tag` is `None`.
- Trigger `action_add_agent_tag()` and assert the pushed modal has both `_current_tag is None` and
  `_default_tag == "pinned"`.

Add a complementary assertion that the bulk path does **not** seed `pinned` (modal's `_default_tag` stays `None`) —
locks in the deliberate scope decision.

The existing `test_action_pushes_modal_for_focused_agent` (which uses an agent already tagged `primary`) continues to
pass: `current_tag` wins over `default_tag` in the seed expression.

## Edge cases / non-issues

- **`pinned` as a valid tag name.** `validate_tag_name` accepts plain lowercase ASCII identifiers, so `pinned`
  round-trips through the existing set path with no special handling.
- **`select_all` on mount.** The existing `on_mount` only calls `select_all()` when `tag_input.value` is non-empty. With
  the new default, the input has a value and selection happens, so the first keystroke still cleanly replaces `pinned` —
  preserving the test `test_modal_first_keystroke_replaces_prefill`'s underlying contract.
- **Help / docs.** The `?` help modal documents the `N` keymap as "Add agent tag"; the description remains accurate. No
  help text needs to change.
- **Footer.** `N` is a global Agents-tab keybinding (always available, not conditional), so per the footer convention in
  `src/sase/ace/AGENTS.md` it stays out of the footer regardless.

## Files touched (summary)

- `src/sase/ace/tui/modals/agent_tag_modal.py` — add `default_tag` param and thread it into the input seed.
- `src/sase/ace/tui/actions/agents/_tagging.py` — pass `default_tag="pinned"` on the single-agent path; constant for the
  literal.
- `tests/ace/tui/test_agent_tag_modal_pilot.py` — new prefill test.
- `tests/ace/tui/test_agent_tagging.py` — new handler assertion.

## Verification

- `just check` (lint + mypy + tests) from the workspace clone after `just install`.
