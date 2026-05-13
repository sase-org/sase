---
create_time: 2026-05-12 20:41:14
status: done
prompt: sdd/prompts/202605/qwen_stop_hook_dedup.md
---
# Plan: Fix Qwen commit stop-hook deduplication

## Problem

Agent `r9` used the Qwen provider and made uncommitted changes, but the global `sase_commit_stop_hook` did not block the
agent and prompt it to commit.

The hook log shows that the hook did run:

- `2026-05-12T20:35:18-04:00`
- `runtime: "qwen"`
- `project_dir: "/home/bryan/projects/github/sase-org/sase_101"`
- `session_id: "20260512202751"`
- followed immediately by `event: "qwen_dedup_skip"`

The corresponding agent record confirms `r9` was a Qwen run with artifacts timestamp `20260512202751`, so this log entry
is the r9 stop-hook execution.

## Root Cause

`src/sase/scripts/sase_commit_stop_hook.py` currently treats Qwen and Gemini the same:

```python
if runtime in ("gemini", "qwen") and hook_input.get("stop_hook_active"):
    _jlog(f"{runtime}_dedup_skip")
    return _exit(0, reason=f"{runtime}_dedup")
```

That assumption is wrong for Qwen. Qwen Code fires the Claude-style `Stop` event and includes `stop_hook_active` in the
first Stop payload. In the r9 run, this caused the hook to skip before calling `build_commit_details()`, so it never
checked the worktree and never emitted the commit-block payload.

The existing marker file (`native_marker_path(session_id)`) is still the correct once-per-session deduplication
mechanism after a block is emitted.

## Scope

Implement a narrow runtime fix:

1. Keep Qwen runtime detection and Qwen-shaped JSON block output as-is.
2. Stop using `stop_hook_active` as a Qwen dedup signal in `sase_commit_stop_hook.py`.
3. Keep Gemini's existing `stop_hook_active` dedup behavior unchanged.
4. Add tests proving a Qwen hook invocation with `stop_hook_active: true` still checks for changes and emits a
   deny/block payload, then dedups on the marker file after the first block.
5. Check whether the repo-local sibling hook has the same latent issue for Qwen. If it does, apply the same narrow fix
   and add a subprocess test.
6. Update docs only where they currently imply Qwen uses the same `stop_hook_active` dedup semantics as Gemini.

## Validation

Run focused tests first:

```bash
pytest tests/test_commit_stop_hook.py tests/test_sibling_commit_stop_hook.py
```

Then, because this repo requires it after file changes, run:

```bash
just install
just check
```

If `just check` fails for a pre-existing unrelated visual snapshot or environment issue, report the exact failure and
the focused test result.
