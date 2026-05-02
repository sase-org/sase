---
create_time: 2026-05-01 22:06:21
status: done
prompt: sdd/prompts/202605/retry_agent_name_suffix.md
---
# Plan: Retry Agent Names

## Goal

When the Agents-tab `,r` retry-edit action relaunches an existing agent's prompt, the relaunched agent should be named
`<name>.<N>`, where `<name>` is the selected agent's existing `agent_name` and `<N>` is the lowest positive integer that
keeps all visible active agent names distinct.

## Current Behavior

- The `,r` keymap dispatches through leader mode to `EntryPointsMixin._retry_edit_agent()`.
- `_retry_edit_agent()` reads the selected agent's raw xprompt content and passes it to `_edit_and_relaunch_agent()`.
- `_edit_and_relaunch_agent()` only formats the raw prompt and mounts the prompt input bar. It does not carry a retry
  naming intent.
- When the user submits, the normal launch path sends the prompt to the runner. The runner assigns names from `%name`
  directives first, then resume-derived names, repeat names, or auto names.
- Explicit `%name:<name>` collisions currently trigger `claim_agent_name(..., explicit=True)`, which can rename existing
  visible agents. That is not the desired retry behavior for `,r`.

## Design

Add a small retry-name allocation path that runs before the prompt input bar is mounted:

1. If the selected agent has no `agent_name`, keep the existing behavior.
2. If the selected agent has an `agent_name`, compute the lowest available `<agent_name>.<N>` using the same visible,
   non-dismissed active-name snapshot used elsewhere by `sase.agent.names`.
3. Rewrite the prompt shown in the prompt input bar so its first top-level `%name` / `%n` directive is replaced by
   `%name:<agent_name>.<N>`.
4. If the prompt has no top-level name directive, prepend `%name:<agent_name>.<N>`.
5. Leave fenced code blocks and disabled xprompt regions untouched when detecting/replacing name directives.

This keeps the normal runner path responsible for persisting `agent_meta.json`, prompt history, and final launch
behavior.

## Implementation Steps

1. Add a public helper in `sase.agent.names` for retry-derived names:
   - Suggested API: `allocate_retry_name(base: str, reserved: set[str] | None = None) -> str`.
   - It should inspect `get_active_agent_names()` and return the first `<base>.<N>` where no active name equals that
     candidate and no active descendant starts with `<candidate>.`.
   - It should add the chosen candidate to `reserved` when a caller provides a mutable set, matching the style of other
     allocation helpers.

2. Add a prompt rewrite helper near the TUI retry entry point:
   - Suggested private function in `src/sase/ace/tui/actions/agent_workflow/_entry_points.py`.
   - It should replace the first top-level `%name` / `%n` directive or prepend one if none exists.
   - Reuse existing directive parsing primitives where practical so fenced blocks and disabled regions are protected.

3. Update `_retry_edit_agent()`:
   - If `agent.agent_name` is set, call `allocate_retry_name(agent.agent_name)` and rewrite `raw_prompt` before passing
     it to `_edit_and_relaunch_agent()`.
   - If allocation/rewrite fails unexpectedly, surface a warning and fall back to the unmodified prompt rather than
     blocking the retry.

4. Add focused tests:
   - Name allocator returns `foo.1` when only `foo` exists.
   - Name allocator skips `foo.1` and descendants like `foo.1.plan`, returning `foo.2`.
   - `,r` retry prompt prepends `%name:foo.1` for a named agent with no name directive.
   - `,r` retry prompt replaces an existing top-level `%name:foo` or `%n:foo` with the retry name.
   - An unnamed selected agent preserves the current prompt behavior.

## Verification

- Run the focused pytest targets for agent naming and retry prompt behavior.
- Because this repo requires it after changes, run `just install` if needed and then `just check`.
