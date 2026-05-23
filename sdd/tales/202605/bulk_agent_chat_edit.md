---
create_time: 2026-05-23 11:45:29
status: done
prompt: sdd/prompts/202605/bulk_agent_chat_edit.md
---
# Bulk Edit Marked Agent Chats

## Goal

Add Agents-tab support for using the existing `m` marks with the existing `e` keymap so a marked set opens its chat
transcripts in one editor invocation. The single-agent `e` behavior should remain unchanged when no agent marks exist.

## Current State

- Agents-tab marking already exists in `AgentMarkingMixin` and stores identities in `self._marked_agents`.
- Existing marked-set actions give marks precedence over the focused row:
  - `x` bulk kill/dismisses marked agents.
  - `W` / wait builds one `%w:` prompt from marked agents.
  - `A` aggregates artifacts for marked agents.
  - `N` tags/untags the marked set.
- `e` is already the app-level `edit_spec` keymap. On the Agents tab, `AgentPanelDetailMixin.action_edit_spec()` calls
  `_open_agent_chat()`, which currently opens only the selected `DONE` agent's `response_path`.
- The footer and help modal currently describe single-chat editing only.
- The command palette availability logic only considers the focused agent for `app.edit_spec`.

## Behavior Contract

1. On the Agents tab, marked agents take precedence over the focused row for `e`.
2. If marks exist, `e` resolves marked agents by iterating `self._agents_with_children` in order, matching the existing
   bulk kill/wait/artifact paths and avoiding nondeterministic set ordering.
3. A marked row contributes a transcript only when it has a usable `response_path` and represents a completed/resumable
   chat. Use the existing `is_resumable_done_status()` predicate so `DONE`, `PLAN DONE`, and `TALE DONE` rows with
   transcripts are handled consistently.
4. Expand `~` in paths and de-duplicate identical expanded paths while preserving first-seen order. This prevents
   opening the same transcript twice when related parent/child rows point at the same file.
5. Invoke the editor once with all resolved paths, e.g. `[editor, path1, path2, path3]`, inside `self.suspend()`.
6. If all marks are stale, warn `No marked agents remain`.
7. If marked agents remain but none has an editable transcript, warn `No chat files found in marked agents`.
8. If some marked agents are skipped because they have no editable transcript, still open the valid transcripts and then
   show a concise warning such as `Skipped 1 marked agent without a chat file`.
9. Do not clear marks after editing. Editing is non-destructive and should behave like the artifact picker, not like
   bulk kill/dismiss.

## Implementation Plan

1. Update `src/sase/ace/tui/actions/agents/_panel_detail.py`.
   - Add a small helper to collect marked chat paths and skipped counts from `self._agents_with_children`.
   - Add a helper to open one or more chat paths in the editor using the same editor selection convention as the current
     single-agent path (`$EDITOR` or `nvim`) and the existing `self.suspend()` lifecycle.
   - Route `_open_agent_chat()` through the marked-set path first when `self._marked_agents` is non-empty.
   - Keep the no-mark path focused on the selected agent, but use `is_resumable_done_status()` instead of the current
     literal `("DONE",)` check so the single-agent behavior aligns with the bulk eligibility rule.

2. Update footer discoverability in `src/sase/ace/tui/widgets/_keybinding_bindings.py`.
   - When `marked_count > 0`, include the `edit_spec` binding as `edit chats (<N> marked)`.
   - Keep existing `x`, `u`, and `A` marked-set labels.

3. Update help text in `src/sase/ace/tui/modals/help_modal/agents_bindings.py`.
   - Change the Agents-tab `e` entry from single-chat wording to marked-aware wording, for example
     `Edit chat(s) in editor`.

4. Update command palette availability in `src/sase/ace/tui/commands/availability.py`.
   - On the Agents tab, allow `app.edit_spec` when `ctx.mark_count > 0`, even if the focused row is not itself an
     editable completed agent. The action will do the precise transcript validation and warn if none are usable.
   - Preserve focused-agent availability when no marks exist.

5. Add focused tests.
   - Add unit tests for the marked `e` action:
     - opens three marked chat paths in one `subprocess.run` call;
     - ordering follows `self._agents_with_children`, not mark-set order;
     - stale marks are ignored;
     - marked agents without transcripts are skipped with a warning;
     - all-stale/all-missing cases warn and do not launch the editor;
     - no marks still opens the selected agent's chat.
   - Extend `tests/test_keybinding_footer_agent.py` to assert the marked footer advertises `edit chats`.
   - Update the help-modal assertion in `tests/test_keymaps.py`.
   - Add or adjust a command-palette availability unit test so `app.edit_spec` is available with agent marks.

## Verification

After implementation, run targeted tests first:

```bash
pytest tests/ace/tui/test_agent_bulk_chat_edit.py tests/test_keybinding_footer_agent.py tests/test_keymaps.py tests/test_command_palette_wiring.py
```

Then run the repo-required check sequence for source changes:

```bash
just install
just check
```

## Risks and Boundaries

- This is TUI presentation/glue behavior, so it should remain in the Python TUI layer and not cross into `sase-core`.
- The plan intentionally avoids changing key defaults because `e` and `m` already exist in `default_config.yml`.
- The editor command handling should follow existing local convention rather than introducing new shell parsing
  semantics.
