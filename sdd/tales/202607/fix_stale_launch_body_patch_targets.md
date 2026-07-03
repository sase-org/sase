---
create_time: 2026-07-03 10:09:28
status: wip
prompt: sdd/prompts/202607/fix_stale_launch_body_patch_targets.md
---
# Fix CI Failure: Stale `mock.patch` Targets After `_launch_body` Split Refactor

## Problem

GitHub Actions (`just test-cov`) fails with 2 test errors:

```
FAILED tests/ace/tui/test_prompt_stack_launch_integration.py::test_whole_stack_submit_routes_manual_multi_prompt_to_multi_prompt_launch
FAILED tests/ace/tui/test_prompt_stack_launch_integration.py::test_whole_stack_submit_with_multi_agent_xprompt_preserves_invocation
AttributeError: <module 'sase.ace.tui.actions.agent_workflow._launch_body'> does not have the attribute 'record_prompt_file_references'
```

Reproduced locally: running `pytest tests/ace/tui/test_prompt_stack_launch_integration.py` fails with the same
`AttributeError` raised by `unittest.mock.patch` at patch-target resolution time.

## Root Cause

Commit `4060a0a2f` ("ref: split agent launch body implementation") broke the large
`src/sase/ace/tui/actions/agent_workflow/_launch_body.py` module into smaller implementation helpers:

- `_launch_body.py` now only contains the `AgentLaunchBodyMixin` entry point, which delegates to `run_agent_launch_body`
  imported from `_launch_body_impl`.
- `_launch_body_impl.py` holds the orchestration body, including the multi-prompt history-write path that calls
  `record_prompt_file_references(submitted_xprompt)` (imported at module top level from `._launch_history`).
- `_launch_body_single.py` holds the single-agent path, which also imports and calls `record_prompt_file_references`.

Because the `record_prompt_file_references` import moved out of `_launch_body`, any
`mock.patch("sase.ace.tui.actions.agent_workflow._launch_body.record_prompt_file_references")` now raises
`AttributeError` (patch refuses to create missing attributes by default).

Two tests in `tests/ace/tui/test_prompt_stack_launch_integration.py` still patch the old location (lines 56–58 and
115–118). The analogous test in `tests/ace/tui/test_agent_launch_dispatch.py`
(`test_run_agent_launch_body_multi_agent_xprompt_history_uses_input`, line ~173) was already updated to patch
`_launch_body_impl.record_prompt_file_references` and passes — the refactor simply missed this second test file.

A repo-wide grep confirms these two patch calls are the only remaining references to the stale
`_launch_body.record_prompt_file_references` target; no other tests patch attributes that moved in the split.

## Fix

In `tests/ace/tui/test_prompt_stack_launch_integration.py`, update both patch targets from:

```python
patch(
    "sase.ace.tui.actions.agent_workflow._launch_body."
    "record_prompt_file_references"
)
```

to:

```python
patch(
    "sase.ace.tui.actions.agent_workflow._launch_body_impl."
    "record_prompt_file_references"
)
```

Both failing tests exercise the whole-stack multi-prompt submit path, whose `record_prompt_file_references` call lives
in `_launch_body_impl.run_agent_launch_body` (the name is bound into `_launch_body_impl`'s namespace at import time, so
it must be patched on that consuming module — not on `_launch_history` where it is defined). This matches the
already-passing pattern in `test_agent_launch_dispatch.py`.

No production-code changes are needed; the refactor itself is behaviorally sound (the other 15,014 tests pass, including
the dispatch tests that cover the same code paths).

## Verification

1. Run `pytest tests/ace/tui/test_prompt_stack_launch_integration.py` — all 5 tests in the file must pass (the 2 failing
   ones plus the 3 keep-bar tests).
2. Run `pytest tests/ace/tui/test_agent_launch_dispatch.py` to confirm the neighboring launch-body dispatch coverage
   still passes.
3. Run `just check` (required for any file changes in this repo).
