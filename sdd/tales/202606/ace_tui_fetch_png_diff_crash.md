---
create_time: 2026-06-17 08:11:43
status: done
prompt: sdd/prompts/202606/ace_tui_fetch_png_diff_crash.md
---
# Plan: Fix ACE TUI Crash on `#sshot` Fetch Step

## Problem

Opening the `fetch` bash step for the `#sshot` xprompt workflow crashes `sase ace` with a `UnicodeDecodeError`. The
selected row is a workflow child step whose output is:

```json
{ "local_path": "/home/bryan/tmp/screenshots/20260617_080200.png" }
```

The row nevertheless has `Agent.diff_path` set to that PNG path. The file panel then treats the value as a persisted
diff and calls `Path(...).read_text()`, which attempts to decode binary PNG bytes as UTF-8.

## Root Cause

ACE has a permissive fallback in several workflow loaders:

- `src/sase/ace/tui/models/_loaders/_workflow_step_loaders.py`
- `src/sase/ace/tui/models/_loaders/_workflow_loaders.py`
- `src/sase/ace/tui/models/_loaders/_workflow_snapshot_loaders.py`
- `src/sase/axe/run_agent_helpers_state.py`

When no explicit `diff_path` is present, these paths promote the first output field whose schema type is `"path"` into
`diff_path`. That conflates arbitrary file artifacts (`local_path`, `plan_path`, `project_file`, `response_path`, image
paths, etc.) with diff artifacts. For `#sshot`, `local_path` is a valid path-typed output, but it is not a diff.

There is a secondary hardening gap in `get_agent_diff()`: `src/sase/ace/tui/widgets/file_panel/_diff.py` only catches
`OSError` around `Path.read_text()`, so any binary or non-UTF-8 file that reaches `diff_path` can crash the TUI.

## Approach

1. Introduce a small shared helper for workflow diff-path extraction semantics.
   - Preserve explicit `diff_path` outputs and explicit marker-level `diff_path`.
   - Stop treating arbitrary `"path"` output fields as diffs.
   - Keep the helper in Python/TUI-side code unless existing boundaries show it belongs in `sase-core`; this behavior is
     presentation/loading glue for the Python ACE rows and runner finalization.

2. Update every current fallback site to use the helper.
   - Filesystem workflow root loader.
   - Filesystem workflow child-step loader.
   - Snapshot-aware workflow root and child-step loaders.
   - `extract_step_output_and_diff_path()` used during agent finalization, so bad values are not persisted into done
     markers.

3. Harden the file-panel diff read.
   - Read persisted diffs as UTF-8 with replacement, or catch `UnicodeDecodeError`, so malformed historical metadata
     cannot crash the TUI.
   - Return `None` for unavailable/unreadable persisted diff content, preserving the current “no diff panel content”
     behavior for completed rows.

4. Add focused regression tests.
   - A workflow child step with `output_types: {"local_path": "path"}` and a PNG path must load with
     `diff_path is None`.
   - Explicit `diff_path` outputs must still load as diffs.
   - Root workflow extraction must not promote unrelated last-step path fields.
   - The file-panel diff reader must not raise when pointed at binary bytes.
   - Update existing tests that currently encode the permissive “first path wins” behavior to reflect the corrected
     semantics.

5. Verify with targeted tests first, then run the required repository check after code changes.
   - Targeted pytest around workflow loaders, runner extraction, and file-panel diff handling.
   - `just install` if needed, then `just check` per project instructions after file changes.

## Expected Outcome

The `#sshot` `fetch` step remains visible and its `step_output` still shows the screenshot path in the prompt/detail
panel, but ACE no longer treats that PNG as a diff. Opening the row should not crash, and historical bad metadata should
also be guarded by the file-panel read hardening.
