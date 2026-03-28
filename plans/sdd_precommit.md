---
create_time: 2026-03-28 11:59:15
status: done
---

# Fix SDD file commit and ensure precommit runs for version-controlled plans

## Problem

When `sdd.version_controlled` is `true` and a user approves a plan, `_commit_sdd_files()` in `run_agent_exec_plan.py` is
supposed to commit the `plans/` and `specs/` markdown files via `sase commit`. However, **the function is broken**: it
passes a message string directly to `-m` (`--message-file`), which expects a **file path**. The `handle_commit_command`
handler tries to `os.path.isfile()` on the message string, fails, and calls `sys.exit(1)`. Because the subprocess uses
`check=False` and `capture_output=True`, this failure is **silent**.

Consequences:

- SDD files are **never committed** in the version-controlled path
- The `precommit_command` **never runs** (the subprocess exits before reaching `CommitWorkflow.run()`)
- The `#gh` pre-step's `git checkout . && git clean -fd` wipes the uncommitted SDD files, which is exactly what
  `_commit_sdd_files` was supposed to prevent

## Solution

Fix `_commit_sdd_files()` to write the commit message to a temporary file before invoking `sase commit -m <tmpfile>`.
This is the minimal fix that:

1. Makes the existing `sase commit` call work correctly
2. Gets precommit for free via `CommitWorkflow._run_precommit()` (already part of the `sase commit` pipeline)
3. Preserves VCS provider dispatching (commit + push behavior needed to survive `#gh` pre-step wipes)

## Changes

### 1. Fix `_commit_sdd_files()` in `src/sase/axe/run_agent_exec_plan.py`

Write the commit message to a `NamedTemporaryFile` and pass its path to `sase commit -m`. The temp file is auto-cleaned
by `handle_commit_command` (which deletes it after reading), so no cleanup is needed on our side.

Also add `check=True` (or at minimum log the failure) so silent failures don't happen again.

### 2. Add tests for `_commit_sdd_files()` in `tests/test_sdd.py`

- Test that `_commit_sdd_files` invokes `sase commit` with a valid temp file path for `-m`
- Test that the message file contains the expected commit message
- Test that `-f` flags are passed for existing spec/plan files
- Test that the function is a no-op when neither spec nor plan file exists

### 3. Add a test verifying precommit runs during SDD commit

In the commit workflow tests, add a test that confirms `_run_precommit()` executes when `sase commit` is called with the
SDD file pattern (files in `specs/` and `plans/`). This guards against future regressions.
