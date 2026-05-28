---
create_time: 2026-05-28 07:14:08
status: done
---
# Move Agents Save/Dismiss Keymap To Lowercase `s`

## Goal

Move the Agents-tab save/dismiss-marked-agents trigger from uppercase `S` to lowercase `s`, while preserving existing
ChangeSpecs behavior:

- ChangeSpecs `s` continues to open the single-CL status modal.
- ChangeSpecs `S` continues to open the bulk status flow for marked CLs.
- Agents `s` saves/dismisses the marked agent set.
- Agents `S` no longer performs the Agents save/dismiss flow.

## Key Context

The ace TUI app-level keybindings are global rather than tab-scoped. Today, `bulk_change_status` is bound to `S` and
dispatches by active tab: ChangeSpecs uses it for bulk CL status, while Agents uses it for save/dismiss marked agents.
Lowercase `s` is already bound to `change_status`, so this change cannot be a simple default-config rewrite of
`bulk_change_status: "S"` to `"s"` without creating an ambiguous global binding and breaking ChangeSpecs semantics.

Textual supports multiple bindings for the same key and evaluates `check_action()` before dispatching an action. That
gives us a narrow path for tab-scoped behavior without inventing a broader keymap model: keep both default `s` bindings
and let `check_action()` enable only the action that applies on the current tab.

## Implementation Plan

1. Add a dedicated app action for Agents save/dismiss.
   - Add `save_marked_agents` to `AppKeymaps` and `_BINDING_META`.
   - Add `save_marked_agents: "s"` to `src/sase/default_config.yml`.
   - Add the fallback `Binding("s", "save_marked_agents", ...)` in `src/sase/ace/tui/bindings.py`.
   - Keep `change_status: "s"` and `bulk_change_status: "S"` unchanged.

2. Split action dispatch by tab.
   - Add `MarkingMixin.action_save_marked_agents()` that only handles the Agents tab and delegates to
     `_save_marked_agent_group()`.
   - Make `action_bulk_change_status()` CL-only again so uppercase `S` no longer triggers Agents save/dismiss.
   - Add a small guard to `action_change_status()` so direct calls on non-ChangeSpecs tabs no-op.
   - Update `AceApp.check_action()` so:
     - `change_status` is enabled only on ChangeSpecs.
     - `bulk_change_status` is enabled only on ChangeSpecs.
     - `save_marked_agents` is enabled only on Agents.

3. Update user-facing keymap surfaces.
   - Agents help modal should list `s` for "Save/dismiss marked agents".
   - Agents footer should show `s save/dismiss (N marked)`.
   - ChangeSpecs help/footer should continue to show `S` for bulk status.
   - Command palette should expose a separate Agents-only `app.save_marked_agents` command when marks exist, and keep
     `app.bulk_change_status` ChangeSpecs-only.

4. Update tests around the behavior contract.
   - Keymap registry/build tests for the new action, duplicate lowercase `s` defaults, and expected binding count.
   - Help/footer tests expecting Agents save/dismiss on `s` and ChangeSpecs bulk status on `S`.
   - Marking tests to call `action_save_marked_agents()` for the Agents flow and assert `action_bulk_change_status()` no
     longer saves on Agents.
   - Command catalog/availability/palette tests to use `app.save_marked_agents` for Agents.
   - Add or adjust a direct dispatch test proving lowercase `s` routes to save/dismiss on Agents while preserving
     ChangeSpecs `s` status behavior.

5. Verify.
   - Run the focused keymap and Agents marking tests first.
   - Because this repo requires it after code changes, run `just install` if needed and then `just check` before
     finishing.

## Risks And Mitigations

- Risk: duplicate lowercase `s` bindings could dispatch the wrong action.
  - Mitigation: gate all three related actions in `check_action()` and keep the binding order with `change_status`
    before `save_marked_agents`.

- Risk: command palette or help surfaces keep advertising the old uppercase Agents behavior.
  - Mitigation: update command metadata, availability predicates, help bindings, footer binding computation, and their
    tests together.

- Risk: user overrides that already customize these keys may interact with duplicate detection.
  - Mitigation: leave the global duplicate detection behavior intact for user overrides; only the bundled defaults use
    the intentional tab-scoped duplicate.
