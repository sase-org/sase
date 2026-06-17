---
create_time: 2026-06-17 07:21:46
status: done
prompt: sdd/prompts/202606/remove_leader_x_bulk_kill_edit.md
---
# Plan: Move Marked Kill-And-Edit Back To `,x`

## Context

The Agents tab currently has two leader-mode kill-and-edit paths:

- `,x` / `kill_and_edit`: kills or dismisses the focused agent, then opens its prompt for editing.
- `,X` / `kill_marked_and_edit`: kills or dismisses marked agents, then opens one editable prompt pane per marked agent.

The `,X` leader binding should not exist. The marked-agent behavior should be owned by `,x`: when one or more agents are
marked, `,x` should operate on the marked set; otherwise it should keep the existing focused-row behavior.

This should not affect the direct `X` key that opens the Agents cleanup panel.

## Current Shape

Relevant code paths:

- Defaults:
  - `src/sase/default_config.yml`
  - `src/sase/ace/tui/keymaps/types.py`
- Leader dispatch:
  - `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`
- Focused single-agent edit:
  - `src/sase/ace/tui/actions/agent_workflow/_entry_points.py`
- Marked-agent bulk edit:
  - `src/sase/ace/tui/actions/agents/_marking.py`
- Footer/help/command-palette surfaces:
  - `src/sase/ace/tui/widgets/_keybinding_modes.py`
  - `src/sase/ace/tui/modals/help_modal/agents_bindings.py`
  - `src/sase/ace/tui/commands/catalog.py`
  - `src/sase/ace/tui/commands/availability.py`

The bulk implementation is already mostly correct: it preserves explicit mark order, prunes stale marks, aborts before
killing when any marked agent lacks prompt content, uses the shared bulk kill/dismiss modal, and seeds prompt panes
without splitting embedded `---`.

## Proposed Changes

1. Retire `kill_marked_and_edit` as a built-in leader key.

   Remove it from `default_config.yml` and `LeaderModeKeymaps` defaults. Also remove the related leader command
   label/tab/availability entries and help/footer references that advertise a separate `,X` action.

2. Route `,x` based on marks.

   Update the `kill_and_edit` dispatch in `LeaderModeMixin` so that on the Agents tab:
   - if `_marked_agents` is non-empty, dispatch to `_bulk_kill_marked_agents_and_edit()`;
   - otherwise, dispatch to `_kill_and_edit_agent()` as today.

   This keeps the existing single-agent behavior intact while making marked agents take precedence, matching how other
   Agents-tab actions already treat marks as the active bulk target.

3. Prevent old `kill_marked_and_edit` overrides from reviving the removed command.

   Because built-in mode loading currently deep-merges user-provided leader keys, a stale config entry could otherwise
   reintroduce a `leader.kill_marked_and_edit` command even after the default is removed. Add targeted filtering for
   this retired leader action id during leader-mode loading or command generation, without changing generic custom-mode
   behavior.

4. Update user-facing text.

   Adjust footer/help/copy to describe `,x` as contextual, for example `kill & edit` with no marks and
   `kill marked & edit (N)` with marks. Keep direct `x` and direct `X` labels unchanged where they refer to kill/dismiss
   and cleanup-panel behavior.

5. Update tests.

   Replace the tests that assert `,X` exists with tests asserting:
   - default leader keymaps do not include `kill_marked_and_edit`;
   - `kill_and_edit` remains bound to `x`;
   - `,x` dispatches to the bulk marked-agent flow when marks exist;
   - `,x` still dispatches to the focused-agent flow when no marks exist;
   - the leader footer shows `x` with a marked-count label when marks exist and does not show `X` for this behavior;
   - command palette/catalog/availability no longer exposes `leader.kill_marked_and_edit`;
   - stale user config for `kill_marked_and_edit` does not recreate the command.

6. Preserve existing bulk behavior tests.

   Keep the existing bulk kill-and-edit behavioral tests, but rewrite their descriptions/comments from `,X` to
   marked-agent `,x`. Those tests should continue to cover mark order, one pane per prompt, cancel behavior, stale-mark
   pruning, and missing-prompt aborts.

## Validation

Run targeted tests first:

```bash
pytest tests/test_keymaps_defaults.py \
  tests/test_keymaps_registry_loading.py \
  tests/test_command_catalog.py \
  tests/test_command_availability.py \
  tests/ace/tui/test_show_agent_run_log_keymap.py \
  tests/ace/tui/widgets/test_keybinding_footer_kill_marked_edit.py \
  tests/ace/tui/test_agent_bulk_kill_edit.py
```

Because this repo requires full checks after code changes, run:

```bash
just install
just check
```

## Risks

- Stale user config needs deliberate handling so the removed `,X` action does not remain visible through the command
  palette.
- Footer/help tests may need careful updates because direct `X` still means cleanup panel and must not be removed.
- The leader repeat command should remember raw `x`; repeating should naturally re-evaluate current marks, which is
  consistent with other contextual actions.
