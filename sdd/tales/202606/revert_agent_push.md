---
create_time: 2026-06-15 10:34:40
status: done
prompt: sdd/prompts/202606/revert_agent_push.md
---
# Plan: Push Agents-Tab Revert Commits To GitHub

## Context

The Agents tab leader-mode `,r` flow already runs as tracked TUI work:

- `src/sase/ace/tui/actions/agents/_revert.py` submits a preview task, shows `ConfirmRevertAgentModal`, then submits a
  `revert_agent` execute task.
- `src/sase/ace/revert_agent.py` performs the git transaction for single-agent and marked-agent bulk reverts.
- The backend currently creates a single revert commit and calls `_maybe_push(workspace_dir)`.

The current weakness is that `_maybe_push()` returns only `bool`. That collapses three materially different outcomes:

- no `origin` remote or no branch, where skipping push is expected;
- successful push to `origin`;
- failed push to an existing remote, where the local revert commit exists but GitHub was not updated.

For the user-facing TUI action, a failed push to an available GitHub remote should not look like a successful revert. It
should surface a clear error while preserving the local revert commit.

## Goals

1. After the Agents-tab revert commit is created, attempt to push that commit to GitHub when an `origin` remote and
   current branch are available.
2. Preserve the existing atomic rollback behavior for revert/apply/commit failures.
3. Do not roll back a successfully-created revert commit merely because the post-commit push failed.
4. Distinguish "push skipped because no remote/branch exists" from "push attempted and failed".
5. Make the tracked TUI task report a push failure clearly, with enough detail for the user to recover manually.
6. Cover both single-agent and marked-agent bulk reverts with tests.

## Non-Goals

- Do not change the keymap or default config; `leader_mode.keys.revert_agent` already exists.
- Do not introduce synchronous TUI work; all git work must remain inside the existing tracked worker tasks.
- Do not add GitHub API calls. The right operation here is a normal `git push origin <branch>` from the workspace.
- Do not support mixed-workspace bulk reverts; the current rejection is correct.

## Proposed Design

### 1. Replace `_maybe_push()` with a structured push outcome

Add a small frozen dataclass in `src/sase/ace/revert_agent.py`, for example:

```python
@dataclass(frozen=True)
class PushOutcome:
    attempted: bool
    pushed: bool
    skipped_reason: str | None = None
    error: str | None = None
```

Change `_maybe_push(workspace_dir)` into `_push_revert_commit(workspace_dir) -> PushOutcome`.

Behavior:

- If `git remote get-url origin` fails or returns empty, return `attempted=False`, `pushed=False`,
  `skipped_reason="no origin remote"`.
- If `git symbolic-ref --short HEAD` fails or returns empty, return `attempted=False`, `pushed=False`,
  `skipped_reason="detached HEAD or no current branch"`.
- Otherwise run `git push origin <branch>`.
- If push succeeds, return `attempted=True`, `pushed=True`.
- If push fails, return `attempted=True`, `pushed=False`, `error=<stderr/stdout fallback>`.

Keep the direct git helper style used by the existing backend.

### 2. Surface push failure after local revert success

In `execute_agent_revert()` and `execute_agents_revert()`:

- Keep `_apply_revert_transaction()` as the boundary for rollback. Revert conflicts and commit failures still roll back
  to the captured `HEAD`.
- After `_apply_revert_transaction()` succeeds, call `_push_revert_commit()`.
- If `PushOutcome.error` is set, return a result that makes clear the local revert commit exists but the push failed.

Recommended result semantics:

- `success=False`, because the requested operation included pushing to GitHub and that did not complete.
- `message="Reverted <N> commit(s) ... locally, but push to GitHub failed: <detail>"`.
- `reverted_shas=ordered`, so callers/tests can tell the local revert happened.
- `pushed=False`.
- `error=<same push detail or "git push failed: ...">`.

This preserves the commit and forces the TUI tracked task to show an error instead of a false success.

For skipped push cases with no remote/branch, keep success as `True` and use the current concise message without "and
pushed". This keeps local-only test repos and non-remote development work usable.

### 3. Record push status in artifacts

Continue writing `revert_result.json` when `artifacts_dir` is provided. Include:

- existing fields: `agent_name`, `reverted_shas`, `pushed`, `reverted_at`;
- optional `push_error` when push was attempted and failed;
- optional `push_skipped_reason` when no push was attempted.

For bulk reverts, write the same outcome to each matched target artifact, as the current code already does for `pushed`.

### 4. Adjust TUI completion handling only where needed

The TUI already runs execution through `_submit_tracked_task(... notify_on_complete=True)`.

One small adjustment may be needed: on push failure the result should have `success=False` but still represent a
completed local revert. If the Agents tab needs to refresh after local revert creation, update `_on_complete` in both
single and bulk execute paths to schedule refresh when either:

- `completion.success` is true; or
- `completion.payload` exists and has non-empty `reverted_shas`.

This keeps UI state fresh without hiding the push failure.

### 5. Tests

Extend `tests/ace/test_revert_agent.py`:

- Single-agent revert pushes to a bare `origin` remote:
  - create source repo and bare remote;
  - add `origin`;
  - run `execute_agent_revert`;
  - assert `result.success is True`, `result.pushed is True`;
  - assert remote branch contains the new revert commit.

- Bulk marked-agent revert pushes to a bare `origin` remote:
  - same setup, using `execute_agents_revert`;
  - assert one local revert commit and remote branch updated.

- Push failure after local revert commit:
  - monkeypatch `_run_git` so `git push` returns nonzero after commit succeeds;
  - assert `result.success is False`, `result.pushed is False`, `result.reverted_shas` is populated;
  - assert the local `HEAD` advanced by one revert commit and worktree is clean;
  - assert `result.message` says the push failed after local revert.

- No-origin behavior remains a success with `pushed is False`.

Extend `tests/ace/tui/test_revert_agent_action.py` if the completion callback changes:

- Simulate a failed completion with a payload containing `reverted_shas`;
- assert `_schedule_agents_async_refresh(source="revert_agent")` is still called.

## Verification

Run focused tests first:

```bash
pytest tests/ace/test_revert_agent.py tests/ace/tui/test_revert_agent_action.py
```

If source files are changed, follow project instructions:

```bash
just install
just check
```

## Risks And Mitigations

- Push can fail after the local revert commit exists. The implementation should not hide this or attempt destructive
  rollback. The message and artifact should make the recovery path explicit.
- Push may be slow. It remains in the tracked worker task, satisfying the TUI performance rule to keep subprocess work
  off the Textual event loop.
- Some local repos intentionally have no remote. Preserve the existing skip behavior for no `origin` or no current
  branch.
