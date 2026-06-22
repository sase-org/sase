---
create_time: 2026-06-22 09:38:37
status: done
prompt: sdd/prompts/202606/global_prompt_stash_restore.md
---
# Global Prompt Stash Restore Keymap

## Context

The prompt input widget already supports destructive prompt-stash restore through `gP` / insert-mode `<ctrl+g>P`. That
flow posts `PromptInputBar.RestoreRequested(..., destructive=True)` and the app-side `PromptBarStashMixin` handles the
real work: reading stash entries off the Textual event loop, opening `StashedPromptsModal`, popping selected entries
with `pop_prompt_stash`, and loading the restored prompts into either an existing prompt bar or a newly mounted
home-mode prompt bar.

The requested change should make the same destructive restore path reachable from every main TUI tab with a bare `@`
keypress. This should not revive the old leader-mode `,P` restore binding; it should be a normal app-level binding.

## Goals

- Add a default app-level `@` keymap that works from PRs, Agents, and Axe tabs.
- Reuse the existing destructive restore behavior so selected prompts are popped from the stash, just like `gP` /
  `<ctrl+g>P`.
- When no prompt bar is mounted, restore should mount the prompt input widget and load the restored prompt(s), matching
  the existing `_load_restored_entries` behavior.
- Keep the TUI event loop responsive by relying on the existing async/off-thread stash read/pop implementation.
- Keep keymap configuration, help, command catalog, and tests in sync.

## Non-Goals

- Do not add a new prompt-stash storage path or modal.
- Do not reintroduce the retired leader-mode `,P` key.
- Do not add non-destructive global load behavior; this request is specifically for the pop-and-restore behavior
  matching `gP`.

## Proposed Implementation

1. Add an app-level keymap/action for prompt-stash restore.
   - Add an `AppKeymaps` field such as `restore_prompt_stash`.
   - Add the action to `_BINDING_META` with a label like `Restore Prompt Stash`.
   - Add `restore_prompt_stash: "at"` to `src/sase/default_config.yml`.
   - Add the fallback `Binding("at", "restore_prompt_stash", ...)` to `src/sase/ace/tui/bindings.py`.

2. Implement the action in the prompt-stash app glue.
   - Add `async def action_restore_prompt_stash(self) -> None` near the existing restore handlers in
     `PromptBarStashMixin`.
   - Have it call `await self._open_prompt_stash_restore(destructive=True)`.
   - Do not pass a forced `bar_mode`; letting `_open_prompt_stash_restore` inspect the mounted bar preserves the
     existing prompt-only guard for feedback / approve-prompt bars while defaulting to prompt mode when no bar is
     mounted.

3. Keep keymap and palette metadata aligned.
   - Add command catalog metadata for `restore_prompt_stash`, scoped to all tabs, probably in the `Agents` category with
     aliases such as `stash`, `restore`, and `gP`.
   - Confirm the catalog guard remains useful: every `AppKeymaps` field still has command metadata.
   - Keep `_RETIRED_LEADER_KEYS` filtering intact so stale leader-mode `restore_prompt_stash` overrides cannot revive
     `,P`.

4. Update user-facing help.
   - Add `@ Restore stashed prompt` (wording can be tuned) to the existing workflow/agent sections for PRs, Agents, and
     Axe tabs.
   - Do not add this to the footer unless it becomes conditional; the footer explicitly excludes always-available global
     bindings.

5. Handle key conflict expectations.
   - Bare `@` is represented as Textual key name `at`, and display helpers already render it as `@`.
   - Existing user configs that override `start_custom_agent` to `at` will now conflict with the new default. The
     current duplicate-key logic should revert that user override to `start_custom_agent`'s default (`plus`), which
     reserves `@` for restore. Update the old test that expected the `at` override to be honored.

## Tests

- Keymap defaults:
  - `restore_prompt_stash` defaults to `at`.
  - app bindings include `at -> restore_prompt_stash`.
  - `_BINDING_META` and `AppKeymaps` remain in sync.
  - stale leader-mode `restore_prompt_stash` overrides are still dropped.

- Registry conflict behavior:
  - `start_custom_agent: "at"` now conflicts with the new default and reverts to `plus`, leaving `restore_prompt_stash`
    on `at`.

- Help and command catalog:
  - Help sections for all three tabs list `@` for restore.
  - `app.restore_prompt_stash` appears in the command catalog with key display `@`, all-tab applicability, and an
    app-action executor.

- Action behavior:
  - Calling `action_restore_prompt_stash()` opens a destructive `StashedPromptsModal` when the stash has entries.
  - Existing restore-confirm tests continue to prove that selected entries are popped and loaded into the mounted or
    newly mounted prompt bar.

## Validation

After implementation, run focused tests first:

```bash
pytest tests/test_keymaps_defaults.py tests/test_keymaps_registry_loading.py tests/test_keymaps_display_help.py tests/test_command_catalog.py tests/ace/tui/actions/test_prompt_stash_restore.py
```

Because this repo requires it after code changes, run:

```bash
just check
```
