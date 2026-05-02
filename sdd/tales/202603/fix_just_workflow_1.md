---
create_time: 2026-03-29 14:53:28
status: done
prompt: sdd/prompts/202603/fix_just_workflow_1.md
---

# Plan: Fix `#sase/fix_just` Workflow `fix_fmt` Step Failure

## Problem

The `fix_fmt` step in `xprompts/fix_just.yml` fails with a misleading error message that shows `just`'s command echoes
instead of the actual error:

```
Bash step 'fix_fmt' failed: .venv/bin/ruff format src/ tests/
.venv/bin/ruff check --fix src/ tests/
prettier --write --prose-wrap=always --print-width=120 "**/*.md"
```

## Root Cause

Two bugs working together:

### Bug 1: Bash step error reporting shows stderr, hiding the real error

In `workflow_executor_steps_script.py:118-128`, when a bash step fails, the error handler uses `result.stderr` as the
error message if it's non-empty. Since `just` echoes every recipe command to stderr before executing it, stderr
**always** contains command echoes for any `just` invocation. The actual error (e.g., `git commit` returning "nothing to
commit") goes to stdout, which the handler ignores when stderr is non-empty.

Verified by running `just fmt` and capturing stdout/stderr separately:

- stderr: exactly the three command echoes (always present, even on success)
- stdout: all actual output (ruff results, prettier results, etc.)

### Bug 2: `fix_fmt` step fails when `just fmt` produces no file changes

The step runs:

```bash
just fmt && git add -A && git commit -m "chore: run \`just fmt\`" && git pull && git push
```

The `&&` chain means `git commit` must succeed. But `git commit` exits with code 1 when there's nothing to commit
(message goes to stdout, not stderr). This happens when:

- `just fmt-check` failed on a check that `just fmt` doesn't fully replicate (e.g., `fmt-check` short-circuits after
  `fmt-py-check` fails, so the failure could be from Python formatting that gets fixed, but the workspace already had
  correct formatting by the time `fix_fmt` runs)
- The formatting issue was transient or already resolved

## Proposed Changes

### Phase 1: Fix bash step error reporting

**File:** `src/sase/xprompt/workflow_executor_steps_script.py`

Change lines 118-128 to include both stderr and stdout in the error message, so the user always sees the real error
regardless of which stream it's on:

```python
if result.returncode != 0:
    parts = []
    if result.stderr.strip():
        parts.append(result.stderr.strip())
    if result.stdout.strip():
        parts.append(result.stdout.strip())
    error_msg = "\n".join(parts) if parts else f"Exit code {result.returncode}"
    raise WorkflowExecutionError(
        f"Bash step '{step.name}' failed: {error_msg}"
    )
```

This ensures that when `just` echoes commands to stderr but the actual error is in stdout (like `git commit`'s "nothing
to commit"), both are visible.

### Phase 2: Make `fix_fmt` step robust

**File:** `xprompts/fix_just.yml`

Change the `fix_fmt` bash command to check for staged changes before committing:

```yaml
- name: fix_fmt
  if: "{{ not _just_fmt_check.success }}"
  bash: |
    just fmt
    git add -A
    if ! git diff --cached --quiet; then
      git commit -m "chore: run \`just fmt\`"
      git pull --rebase
      git push
    fi
```

Key changes:

- Break the `&&` chain so `just fmt` failure is reported separately from git failures
- Use `git diff --cached --quiet` to check if there are staged changes before committing
- Use `git pull --rebase` instead of `git pull` to avoid merge commits
- If no changes to commit, the step succeeds silently (formatting was already correct)

## Files Modified

| File                                                 | Change                                           |
| ---------------------------------------------------- | ------------------------------------------------ |
| `src/sase/xprompt/workflow_executor_steps_script.py` | Include both stderr and stdout in error messages |
| `xprompts/fix_just.yml`                              | Make `fix_fmt` robust against nothing-to-commit  |
