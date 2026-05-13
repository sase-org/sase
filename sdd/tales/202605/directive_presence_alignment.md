---
create_time: 2026-05-13 11:10:15
status: done
prompt: sdd/prompts/202605/directive_presence_alignment.md
---
# Align Directive Presence Checks With Full Directive Parsing

## Review Conclusion

The `workspace_zero_default.md` plan proposed by `ug.cld` still identifies a live bug class, even after the separate TUI
workspace-claim transfer fix landed in `2467f5eb5`.

The transfer fix restored normal preclaimed workspace handoff from the TUI bridge to the child process. It did not
change the directive presence helpers that decide whether a prompt should be launched as a deferred workspace. In the
current code, those helpers still scan raw prompt text:

- `has_wait_directive()`
- `has_deferred_start_directive()`
- `has_model_directive()`
- `has_alt_directive()`

By contrast, `extract_prompt_directives()` protects fenced code blocks and disabled regions before parsing. That means a
prompt containing a fenced `sase ace` snapshot, `#resume` expansion, or example text with `%w:`, `%time:`, `%m:`, or
`%alt(...)` can still make early launch routing disagree with runtime directive extraction. The worst case remains the
deferred-workspace path: launch marks the agent as deferred and starts it in workspace `0`, while the runtime extracts
no wait directive and never claims the real workspace.

The runtime reconciliation backstop is also still missing. `run_agent_runner.py` skips workspace prep when
`SASE_AGENT_DEFERRED_WORKSPACE=1`, but if extracted wait metadata is empty it proceeds to run in the placeholder
workspace without warning or recovery.

## Scope

Implement the parser-alignment fix and one runtime safety net. Do not broaden this into stale workspace cleanup, TUI
error decoration, or workspace-claim architecture changes.

## Implementation Plan

1. Add a shared protection helper for cheap directive predicates.

   In `src/sase/xprompt/directives.py`, introduce a small local helper that applies the same protection sequence used by
   `extract_prompt_directives()`:
   - return quickly when the prompt contains no `%`
   - call `protect_fenced_blocks()`
   - call `protect_disabled_regions()`
   - run the existing predicate regex against the protected prompt

   Keep this helper private to the directive module unless another module already needs it.

2. Update quick directive predicates to use the protected prompt.

   Change these helpers so they ignore directives inside fenced blocks and disabled regions:
   - `has_wait_directive()`
   - `has_deferred_start_directive()`
   - `has_model_directive()`

   Move `has_alt_directive()` in `src/sase/xprompt/_directive_alt.py` onto the same protection behavior. Either
   duplicate the tiny protection helper there to avoid an import cycle, or move the helper to a private utility module
   under `src/sase/xprompt/` if that keeps the dependency graph cleaner.

   Preserve all existing positive top-level directive behavior.

3. Add runtime reconciliation for impossible deferred state.

   In `src/sase/axe/run_agent_runner.py`, after `has_wait` is computed from extracted directives, handle this condition:
   - `SASE_AGENT_DEFERRED_WORKSPACE=1`
   - non-home mode
   - extracted wait metadata is empty

   Treat it as a launch/runtime parser mismatch rather than silently continuing in workspace `0`. Prefer a fail-fast
   `RuntimeError` with a clear message naming the deferred env flag and empty wait metadata. Do not claim an arbitrary
   workspace in this branch unless product direction explicitly chooses recovery over loud failure; fail-fast is safer
   because it prevents concurrent edits in the primary repo and makes the root cause visible.

4. Keep existing launch behavior intact.

   The call sites in `launch_cwd.py`, `multi_prompt_launcher.py`, and the TUI launch actions should continue calling the
   same `has_deferred_start_directive()` API. The behavior change should come from parser alignment, not call-site
   branching.

## Tests

1. Extend `tests/test_directives_has_helpers.py`.

   Add negative cases proving each quick predicate ignores directive-looking text inside fenced blocks:
   - `%wait` / `%w`
   - `%time` / `%t`
   - `%model` / `%m`
   - `%alt(...)` / `%(...)`

   Add matching disabled-region cases for the deferred-start helper at minimum, and ideally for all four predicates.
   Keep the existing positive top-level cases.

2. Add a launch-level regression around deferred workspace classification.

   In an existing launch test file, cover a prompt with a fenced snapshot containing `%w:old_agent` but no top-level
   wait directive. Assert the launch context is not deferred and does not use placeholder workspace `0`.

3. Extend `tests/test_axe_run_agent_runner_deferred_workspace.py`.

   Add a test where `SASE_AGENT_DEFERRED_WORKSPACE=1` is set, the mocked directive extraction returns no wait metadata,
   and the runner fails before calling `run_execution_loop()` in non-home mode.

   Preserve the existing home-mode behavior and the valid deferred-wait behavior.

## Verification

Run:

```bash
just install
just test tests/test_directives_has_helpers.py tests/test_axe_run_agent_runner_deferred_workspace.py tests/test_cd_launch_from_cwd.py tests/test_multi_prompt_launcher_wait_vcs.py
just check
```

If `just check` still fails only on known pre-existing `pyvision` private-import violations under `src/sase/axe/*`,
report that separately from the directive fix.
