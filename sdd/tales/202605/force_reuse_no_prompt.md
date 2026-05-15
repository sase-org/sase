---
create_time: 2026-05-14 22:29:23
status: done
---
# Stop TUI confirmation for `%name:!<name>`

## Goal

When a user launches an agent prompt from the TUI with `%name:!<old_name_to_overwrite>`, SASE should not show the extra
`Reuse Agent Name` y/n confirmation modal. The bang syntax is already explicit destructive intent, so the launch path
should wipe the previous owner and continue directly.

## Current behavior

- `%name:!foo` is parsed as `name="foo"` plus `name_force_reuse=True`.
- `src/sase/agent/launch_validation.py` provides the shared helpers:
  - `force_reuse_owner_names(...)`
  - `wipe_names_for_forced_reuse(...)`
  - `rewrite_force_reuse_name_directives(...)`
  - `launch_prompts_need_force_reuse_confirmation(...)`
- The TUI starts in `src/sase/ace/tui/actions/agent_workflow/_launch_start.py`.
  - `_finish_agent_launch()` detects force-reuse prompts.
  - It pushes `ConfirmActionModal(title="Reuse Agent Name", ...)`.
  - On yes, it wipes owners, rewrites `%name:!foo` to `%name:foo`, then recursively calls `_finish_agent_launch(...)`.
  - On no, it records the prompt as cancelled.
- The later TUI launch body validates rewritten prompts with `validate_launch_name_requests(...)`.
- Non-TUI generic launch paths still reject `%name:!foo` unless callers do their own wipe-and-rewrite handshake.
  `sase bead work` already does that explicitly.

## Proposed behavior

Treat `%name:!<name>` in the TUI prompt as the confirmation. `_finish_agent_launch()` should:

1. Detect force-reuse names.
2. Wipe all requested prior owners immediately.
3. Rewrite force-reuse directives to ordinary `%name:<name>` directives.
4. Continue the existing launch flow with the rewritten prompt.
5. If wipe fails, notify the user with the existing error path and do not launch.

This keeps the destructive operation explicit in the submitted prompt while removing the second y/n interruption.

## Scope

### In scope

- Update `src/sase/ace/tui/actions/agent_workflow/_launch_start.py` to remove the confirmation modal branch and perform
  the same wipe-and-rewrite inline.
- Add focused TUI-level tests that verify:
  - `_finish_agent_launch("%name:!foo\n...")` does not call `push_screen`.
  - it calls `wipe_names_for_forced_reuse(["foo"])`.
  - it schedules launch using the rewritten `%name:foo` prompt.
  - wipe failures surface an error notification and do not schedule launch.
- Update docs/help text that says `%name:!<name>` asks for confirmation, at least:
  - `docs/xprompt.md`
  - `docs/ace.md`
  - `docs/blog/posts/xprompts-in-depth.md`
- Update any stale tests or comments that assert the old y/n confirmation contract.

### Out of scope

- Do not change generic non-TUI validation in `validate_launch_name_requests(...)` unless a failing test proves the TUI
  path needs it. The existing non-TUI protection remains useful for callers that have not deliberately implemented the
  wipe-and-rewrite handshake.
- Do not change the lower-level wipe semantics in `src/sase/agent/names/_wipe.py`.
- Do not change bead rendering. Beads already use `%name:!` and a separate non-interactive wipe-and-rewrite path.
- Do not move this logic into Rust core in this patch. The current behavior being changed is specifically the TUI
  presentation handshake; the shared wipe and validation helpers remain in Python.

## Implementation plan

1. Edit `_finish_agent_launch()` in `src/sase/ace/tui/actions/agent_workflow/_launch_start.py`.
   - Replace the `ConfirmActionModal` callback flow with a direct wipe-and-rewrite branch.
   - Use `force_reuse_owner_names([prompt])` once, store the result, and pass it to `wipe_names_for_forced_reuse(...)`.
   - After a successful wipe, assign `prompt = rewrite_force_reuse_name_directives(prompt)` and continue into the normal
     timestamp/scheduling path.
   - Keep the existing exception logging and user notification on wipe failure.
2. Add or extend a focused test module near `tests/ace/tui/test_agent_launch_non_blocking.py`.
   - Reuse the lightweight app fixture style already used for `_finish_agent_launch`.
   - Patch `reserve_launch_timestamp_batch` to avoid global state.
   - Patch `wipe_names_for_forced_reuse` and assert it is called.
   - Assert `push_screen` is not called for `%name:!foo`.
   - Assert the scheduled prompt is `%name:foo\n...`.
3. Update docs and inline comments.
   - Replace "after confirmation" with wording like "explicitly wipes" or "the `!` form confirms reuse".
   - Keep non-TUI docs clear: generic non-TUI launch surfaces still need a caller-owned explicit wipe path.
4. Run focused tests first:
   - `just install`
   - `uv run pytest tests/ace/tui/test_agent_launch_non_blocking.py tests/test_agent_launch_validation.py tests/test_agent_name_wipe.py`
5. Run the repo-required final check after edits:
   - `just check`

## Risks and mitigations

- Risk: removing the modal makes accidental destructive reuse easier.
  - Mitigation: only `%name:!foo` takes the direct path; `%name:foo` collisions still cancel and suggest a suffix.
- Risk: recursive `_finish_agent_launch(...)` behavior currently avoids validating force-reuse prompts later.
  - Mitigation: preserve the rewrite before launch scheduling so later validators still see `%name:foo`.
- Risk: multi-prompt force-reuse from the TUI may still reach later validation without this early single-prompt branch
  handling all embedded segments.
  - Mitigation: tests should cover the single prompt path requested here; if multi-prompt force-reuse still triggers an
    old confirmation or validation error, extend the same direct wipe-and-rewrite handling to the expanded segments in
    `_run_agent_launch_body`.
