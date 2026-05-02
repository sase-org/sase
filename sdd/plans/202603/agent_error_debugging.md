---
create_time: 2026-03-25 16:44:01
status: done
prompt: sdd/prompts/202603/agent_error_debugging.md
---

# Agent Error Debugging: Make Failures WAY Easier to Debug

## Problem Statement

When axe-spawned agents (CRS, fix-hook, mentor, summarize-hook) fail, the TUI shows "FAILED" with **no error message or
traceback**. The user must manually find and read the output log file to debug. This is because:

1. **`write_done_marker()` doesn't accept error details** — It only writes `outcome: "failed"` with no `error` or
   `traceback` fields. Compare with `build_done_marker()` (used by ace-run agents) which does include them.

2. **Axe runners catch exceptions but don't persist them** — e.g., `crs_runner.py:120-125` catches and prints the
   exception to stdout, but `write_done_marker()` at line 132 doesn't pass error info.

3. **Non-exception failures are completely opaque** — When `workflow.run()` returns `False` without raising, there's no
   error message at all.

4. **Output logs aren't linked** — Agent stdout/stderr goes to `~/.sase/workflows/*.txt` but this path isn't in
   done.json, so the TUI can't surface it.

5. **No error reports for axe runners** — `run_agent_runner.py` generates beautiful markdown error reports, but axe
   runners don't.

6. **Notifications lack error details** — CRS/fix-hook notifications say "failed" but don't include error info.

Meanwhile, ace-run agents (launched from the TUI via `@`) already have excellent error display: error + traceback in
done.json, error_report.md in artifacts, and ViewErrorReport notification action. The fix is to bring axe runners up to
parity.

## Affected Runners

| Runner         | File                                    | Uses `write_done_marker` |
| -------------- | --------------------------------------- | ------------------------ |
| CRS            | `src/sase/axe/crs_runner.py`            | Yes                      |
| Fix-hook       | `src/sase/axe/fix_hook_runner.py`       | Yes                      |
| Mentor         | `src/sase/axe/mentor_runner.py`         | Yes                      |
| Summarize-hook | `src/sase/axe/summarize_hook_runner.py` | Yes                      |

For reference, `run_agent_runner.py` uses `build_done_marker()` and already has full error capture.

## Implementation Plan

### Phase 1: Plumb error info through `write_done_marker`

**File: `src/sase/axe/runner_utils.py`**

Add optional `error`, `traceback_str`, and `output_path` parameters to `write_done_marker()`:

```python
def write_done_marker(
    artifacts_dir: str,
    cl_name: str,
    project_file: str,
    timestamp: str,
    exit_code: int,
    *,
    workspace_num: int | None = None,
    response_path: str | None = None,
    diff_path: str | None = None,
    error: str | None = None,          # NEW
    traceback_str: str | None = None,   # NEW
    output_path: str | None = None,     # NEW
) -> None:
```

Write the new fields to done.json when present:

```python
if error:
    done_data["error"] = error
if traceback_str:
    done_data["traceback"] = traceback_str
if output_path:
    done_data["output_path"] = output_path
```

This is backward-compatible — existing callers that don't pass these params continue to work.

### Phase 2: Extract shared error report utility

**File: `src/sase/axe/runner_utils.py`**

Move `_write_error_report()` from `run_agent_runner.py` to `runner_utils.py` as a public function:

```python
def write_error_report(
    artifacts_dir: str,
    *,
    agent_model: str | None,
    agent_llm_provider: str | None,
    workflow_name: str,
    cl_name: str,
    duration: str,
    error_summary: str,
    error_traceback: str | None,
) -> str | None:
```

Update `run_agent_runner.py` to import and use `write_error_report` from `runner_utils` instead of its local
`_write_error_report`.

### Phase 3: Capture and propagate errors in all axe runners

For each runner, the pattern is:

1. Add `error_summary` and `error_traceback_str` variables initialized to `None`
2. In the `except Exception` block, capture them:
   ```python
   error_summary = f"{type(e).__qualname__}: {e}"
   error_traceback_str = traceback.format_exc()
   ```
3. For non-exception failures (e.g., `workflow.run()` returns False), set a descriptive error:
   ```python
   if not workflow_succeeded:
       error_summary = "Workflow returned failure status (no exception raised)"
   ```
4. Pass to `write_done_marker()`:
   ```python
   write_done_marker(
       ...,
       error=error_summary,
       traceback_str=error_traceback_str,
       output_path=output_path,
   )
   ```
5. Write error report and attach to notification.

#### CRS Runner (`crs_runner.py`)

- Add `error_summary` / `error_traceback_str` variables (init to `None`)
- Capture exception at line 120-125
- Handle non-exception failure at line 112-114 (workflow_succeeded=False)
- Pass error info to `write_done_marker()` at line 132
- Compute `output_path` from `get_workflow_output_path()` (same as starter.py does)
- After `write_done_marker`, call `write_error_report()` and attach to notification
- Read `agent_meta.json` to get model/provider info for the error report
- Update `notify_workflow_complete()` to include error summary in notes and error report in files

#### Fix-hook Runner (`fix_hook_runner.py`)

- Same pattern as CRS
- Capture LLMInvocationError at line 176-177 as an error
- Handle post-step failures
- Pass error info to `write_done_marker()` at line 254

#### Mentor Runner (`mentor_runner.py`)

- Same pattern
- Note: already catches `BaseException` at line 79 — add error capture there
- Pass error info to `write_done_marker()` at line 141

#### Summarize-hook Runner (`summarize_hook_runner.py`)

- Same pattern
- Two early-return paths with `write_done_marker()` (line 112 and 174) — handle both
- Note: has two `write_done_marker` call sites — the metahook early return (line 112) and the normal path (line 174)

### Phase 4: Enhanced notifications with error details

Update each runner's `notify_workflow_complete()` call to:

1. Include error summary in `notes` list (like `run_agent_runner.py` does at line 455-456):

   ```python
   notes = [f"CRS {'completed' if success else 'failed'} for {changespec_name}"]
   if not success and error_summary:
       notes.append(error_summary)
   ```

2. Use `ViewErrorReport` action for failures (instead of `JumpToChangeSpec`):

   ```python
   if not success and error_report_path:
       action = "ViewErrorReport"
       action_data = {"error_report_path": error_report_path, "cl_name": changespec_name}
   ```

3. Attach error report file and output log to notification files:
   ```python
   extra_files = [chat_path] if chat_path else []
   if not success:
       if error_report_path:
           extra_files.insert(0, error_report_path)
       if output_path and os.path.isfile(output_path):
           extra_files.append(output_path)
   ```

### Phase 5: Ensure output_path is discoverable

The output log path needs to be in done.json so the TUI can show it. The starter ( `starter.py`) computes output_path
via `get_workflow_output_path()`, but the runners receive it differently:

- **CRS runner**: stdout goes to the output_path from `starter.py`, but the runner doesn't receive this path as an arg.
  Solution: The runner knows its own stdout is being captured. Compute the expected path using the same logic as
  `starter.py` (or pass it as an env var). Simplest: pass it as an additional CLI arg.

  Actually, looking more carefully: `crs_runner.py` doesn't receive output_path at all. The `starter.py` opens a file
  and redirects stdout there, but the runner itself doesn't know the path. Two options:

  **Option A**: Pass output_path as env var `SASE_AGENT_OUTPUT_PATH` from `starter.py`. The runner reads it. **Option
  B**: Each runner computes it from the same function as `starter.py`.

  Option A is cleaner. Update all `_start_*` functions in `starter.py` to set `SASE_AGENT_OUTPUT_PATH` in the subprocess
  env, and update all runners to read it.

### Phase 6: Add output log keybinding to TUI (stretch)

**File: `src/sase/ace/tui/actions/agents_mixin.py` (or similar)**

Add a keybinding (e.g., `O` for "open Output log") on the Agents tab that opens the selected agent's output_path in
`$EDITOR`. This gives quick access to the full stdout/stderr for deeper debugging.

This is a nice-to-have — phases 1-5 already solve the core problem by showing error details inline.

## Summary of Changes

| File                                                 | Change                                                                                                |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `src/sase/axe/runner_utils.py`                       | Add `error`/`traceback_str`/`output_path` to `write_done_marker()`; add shared `write_error_report()` |
| `src/sase/axe/run_agent_runner.py`                   | Import `write_error_report` from runner_utils                                                         |
| `src/sase/axe/crs_runner.py`                         | Capture errors, pass to done marker, write error report, enhance notification                         |
| `src/sase/axe/fix_hook_runner.py`                    | Same                                                                                                  |
| `src/sase/axe/mentor_runner.py`                      | Same                                                                                                  |
| `src/sase/axe/summarize_hook_runner.py`              | Same                                                                                                  |
| `src/sase/ace/scheduler/workflows_runner/starter.py` | Pass `SASE_AGENT_OUTPUT_PATH` env var                                                                 |

## Design Principles

- **Parity**: Bring axe runners to the same error visibility as ace-run agents
- **Backward-compatible**: All new params are optional; existing done.json files without error fields continue to work
- **No TUI changes needed**: The TUI already renders `error_message` and `error_traceback` from done.json — we just need
  to populate them
- **Beautiful**: Error reports use the same markdown format as ace-run agents; tracebacks render with syntax
  highlighting in the TUI
