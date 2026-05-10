# Code Conventions and Gotchas

- **Always define short options** (e.g., `-m`, `-f`) for every argument on all `sase` CLI subcommands
- When changing keymaps, leader mode keys, or any configuration values, don't forget to update the keymap configuration
  in the `src/sase/default_config.yml` file if necessary.
- All supported agent runtimes (Claude, Gemini, Codex, etc.) have the same capabilities: they all support hooks, skills,
  and the same commit workflow. Do NOT introduce runtime-specific special cases or branching logic that assumes one
  runtime lacks a capability that others have. Treat all runtimes uniformly.
- By default, the coder agent does NOT inherit the planner's chat transcript (the plan file is the hand-off artifact).
  Set `SASE_CODER_INHERIT_PLANNER_CHAT=1` to restore the old behavior and prepend `#resume:<planner_name>` to the coder
  prompt.
- Spawn-on-retry is **opt-in** via `ProviderRetryConfig.spawn_new_agent` (default `False`). In legacy in-process retry
  mode, `prepare_workspace()` runs between attempts and wipes uncommitted file edits unless `preserve_workspace=True`.
  In spawn mode the workspace is preserved by design — the child skips `prepare_workspace()` and inherits the parent's
  in-progress edits via the transferred workspace claim. If spawning fails (e.g. workspace transfer fails), the legacy
  in-process retry runs as a fallback so the user is never worse off.
- Memory xprompt `keywords` support a `!` prefix for **negative keywords**: each negative keyword masks its matched
  spans out of the prompt before positive-keyword matching runs, so a memory is excluded only when every positive hit
  fell inside a masked region (e.g. `keywords: [foo, "!/foo/"]` matches `"update foo and /path/to/foo/"` via the
  standalone `foo` but not `"update /path/to/foo/"`). A negative hit that doesn't cover any positive hit is a no-op. In
  YAML, `!`-prefixed entries MUST be quoted (`"!vendor"`) — an unquoted `!foo` is parsed as a YAML tag directive and
  errors at load time.
- **Workspace claim failures** raise `WorkspaceClaimError` (a `RuntimeError` subclass exported from
  `sase.running_field`). The retry wrapper in `launch_executor._spawn_slot_with_workspace_retry` catches by type rather
  than string-prefix matching the exception message. `claim_workspace`, `release_workspace`, and
  `transfer_workspace_claim` return `ClaimResult(success, error)` — the `error` field carries the Rust outcome's reason
  or `repr(exc)` so failures surface a real diagnosis instead of a bare `False`.
- **Never call `traceback.format_exc()` outside an active `except` block** — it returns the literal string
  `"NoneType: None"` (because `sys.exc_info()` is empty). Capture the traceback inside the `except` (use
  `axe.lumberjack._capture_traceback`) or set an explicit placeholder for non-exception failures (subprocess nonzero
  exits, etc.). The lumberjack `_handle_error` fallback no longer calls `format_exc()` — every error-bearing
  `_ChopResult` is responsible for carrying its own captured traceback.
