---
create_time: 2026-04-20 13:23:51
status: wip
prompt: sdd/prompts/202604/fix_comment_check_workspace_gate.md
---

# Plan: Fix Silent Skip of Reviewer-Comments Check When Workspace Lookup Fails

## Problem

On machines using the `retired Mercurial plugin` plugin (Mercurial/CITC workflow), `sase axe` never adds a COMMENTS field to Mailed
ChangeSpecs, even when the underlying CL has reviewer comments. The MENTORS field is populated (mentor reviews run
independently), but the `[critique]` comment entry is never created, so mentors' questions on the CL are invisible
inside `sase ace`.

## Root Cause

`CheckCycleRunner._start_comment_checks()` in `src/sase/axe/check_cycles.py` (lines 246–255) gates the entire reviewer-
comments check on `workspace_dir` being truthy:

```python
try:
    workspace_dir = get_workspace_directory(changespec.project_basename)
except RuntimeError:
    workspace_dir = None

if not workspace_dir:
    return updates
```

For the hg/CITC workflow, `get_workspace_directory()` delegates to `HgWorkspacePlugin.ws_get_workspace_directory()`
(`../retired Mercurial plugin/src/retired_mercurial_plugin/workspace_plugin.py:94`), which shells out to `retired_mercurial_plugin_get_workspace <project> 1`.
This subprocess can fail (raising `RuntimeError`, caught and converted to `None`) or succeed with empty stdout
(`result.stdout.strip()` returning `""`) whenever the CITC client for workspace-num 1 isn't currently provisioned for
that project — which is routine for Mailed CLs whose workspace has been cleaned up or moved to a different number.

When `workspace_dir` ends up `None`/`""`, the early return silently skips starting the check. No log entry, no retry, no
error surfaces to the user.

The parallel `_start_cl_submitted_check()` method (same file, lines 199–233) has **no such gate** — it catches the
`RuntimeError` the same way, then passes `workspace_dir` (possibly `None`) straight through to
`start_cl_submitted_check()`. `_start_background_check()` (`src/sase/ace/scheduler/checks_runner.py:112–115`) already
accepts `workspace_dir: str | None` and passes it to `subprocess.Popen(cwd=workspace_dir)`, where `cwd=None` means the
subprocess inherits the axe process's cwd.

The generated script body for hg reviewer comments is `critique_comments <changespec_name> 2>&1`
(`../retired Mercurial plugin/workspace_plugin.py:92`), which takes only the changespec name — it looks up the CL number via the sase
project file, not via the current working directory. So the cwd requirement for this specific check is spurious.

## Changes

### 1. `src/sase/axe/check_cycles.py` — Drop the workspace_dir gate in `_start_comment_checks()`

Remove the `if not workspace_dir: return updates` guard and keep the `try/except RuntimeError` so the lookup still
doesn't propagate exceptions. The resulting flow mirrors `_start_cl_submitted_check()`: `workspace_dir` may be `None`
and is passed through to `start_reviewer_comments_check()` unchanged.

Behavior changes:

- hg projects whose workspace-num 1 is not currently provisioned will now correctly poll for reviewer comments.
- Other workflows are unaffected: GitHub still short-circuits inside `start_reviewer_comments_check()` via
  `supports_reviewer_comments(cl_url) is False`; bare-git has the same behavior.

### 2. `tests/test_check_cycles.py` (new) — Regression test for the workspace_dir path

Create a new test file that instantiates `CheckCycleRunner` with a mocked `get_workspace_directory` that (a) raises
`RuntimeError` and (b) returns `""`. In both cases, assert that `start_reviewer_comments_check` is called for a Mailed
hg-style ChangeSpec with no existing `[critique]` comment entry. Use `unittest.mock.patch` the same way
`tests/test_checks_runner.py` does (see `test_start_reviewer_comments_check_skips_for_git` at line 186 for the mocking
pattern).

Cover three cases:

- `get_workspace_directory` raises `RuntimeError` → check is still started.
- `get_workspace_directory` returns `""` → check is still started.
- `get_workspace_directory` returns `"/some/workspace"` → check is still started (existing happy path).

### 3. No changes required in `retired Mercurial plugin` or `sase-github`

The plugin implementations are correct as-is. This is purely a bug in the main sase repo's comment-cycle runner.

## Validation

- `just check` in the main sase repo (covers ruff + mypy + pytest).
- Manual verification on the Google machine: after installing the fix, confirm that `sase axe` logs
  `* bs_allow_model: Started reviewer_comments check` on its next comment cycle and that a COMMENTS entry with
  `[critique]` appears in the ChangeSpec within one poll interval.
