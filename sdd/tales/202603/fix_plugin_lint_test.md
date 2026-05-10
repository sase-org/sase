---
create_time: 2026-03-26 20:34:51
status: done
prompt: sdd/prompts/202603/fix_plugin_lint_test.md
---

# Plan: Fix `just lint` / `just test` in all plugin repos

## Status Summary

| Repo          | `just lint`      | `just test`    | Needs Fix? |
| ------------- | ---------------- | -------------- | ---------- |
| sase-github   | PASS             | FAIL (3 tests) | Yes        |
| retired Mercurial plugin   | PASS             | FAIL (1 test)  | Yes        |
| sase-telegram | FAIL (mypy)      | PASS           | Yes        |
| sase-nvim     | N/A (Lua plugin) | N/A            | No         |

## Issue 1: retired Mercurial plugin — stale `sase-hg` editable install

**Root cause**: The venv contains a stale editable install of the old `sase-hg` package (before it was renamed to
`retired Mercurial plugin`). The `.pth` file points to `/home/bryan/projects/github/bbugyi200/sase-hg/src` which no longer exists.
The stale `sase_vcs` entry point `hg = sase_hg.plugin:HgPlugin` conflicts with the current one.

**Fix**: Uninstall the stale package:

```bash
cd /home/bryan/projects/github/sase-org/retired Mercurial plugin
.venv/bin/pip uninstall sase-hg -y
```

Then verify `just test` passes.

## Issue 2: sase-telegram — mypy error from reused loop variable

**Root cause**: In `sase_tg_inbound.py`, the function `_handle_resume_command` has two consecutive `for` loops that both
bind to the variable `a`:

```python
for a in running:         # a: _RunningAgentInfo
    ...
for a in all_agents:      # a: Agent  ← mypy complains: incompatible assignment
    ...
```

Mypy infers `a` as `_RunningAgentInfo` from the first loop and then reports a type conflict on the second.

**Fix**: Rename the loop variable in one of the loops. The second loop (line 746) should use a different name, e.g.
`agent`:

```python
for agent in all_agents:
    name = agent.agent_name or agent.cl_name
    ...
```

This is the minimal change — rename `a` → `agent` in the second loop block (lines 746-775 approximately).

## Issue 3: sase-github — 3 test failures due to stale test mocks

Three tests fail because the upstream `_git_common.py` in `sase_100` added a `_validate_staged()` call (runs
`git diff --cached --quiet`) between `git add` and `git commit`. The tests don't account for this extra subprocess call.

### test_vcs_create_commit_success (line 372)

- Uses `mock_run.return_value` (single return for all calls)
- Returns `returncode=0` for everything, but `git diff --cached --quiet` returning 0 means "no staged changes" →
  function returns `(False, "No staged changes")`
- **Fix**: Switch to `side_effect` list with `returncode=1` for the `git diff --cached --quiet` call

### test_vcs_create_pull_request_success (line 429)

- Uses `side_effect` with 5 entries but the code now makes 6 calls (missing the `git diff --cached --quiet` validation
  call after `git add`)
- **Fix**: Insert a `MagicMock(returncode=1, ...)` entry after the `git add` mock for the validation step

### test_vcs_create_proposal_delegates_to_commit (line 416)

- The test name says "delegates to commit" but `create_proposal` no longer delegates to `create_commit`. It now calls
  `save_diff()` + `clean_workspace()` from `sase.workflows.commit_utils.workspace`.
- **Fix**: Rewrite the test to mock `save_diff` and `clean_workspace` instead of `subprocess.run`, and verify they are
  called correctly. Or, if the test is simply wrong/outdated, update it to test the current behavior.

## Execution Order

1. **retired Mercurial plugin** (quickest — just uninstall stale package, no code changes)
2. **sase-telegram** (simple rename of loop variable)
3. **sase-github** (most involved — update 3 tests)

For each repo, after fixing, run `just lint && just test` to verify the fix, then commit via `/sase_git_commit`.
