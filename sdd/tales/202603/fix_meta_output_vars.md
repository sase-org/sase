---
create_time: 2026-03-25 19:52:32
status: done
prompt: sdd/prompts/202603/fix_meta_output_vars.md
---

# Fix: `meta_` xprompt output variables broken in `pr.yml` and `commit.yml`

## Root Cause

When the commit stop hook fires during an agent run, it instructs the agent to commit changes _during the agent's turn_.
By the time post-steps run, there are no uncommitted changes left. The `check_changes` step returns
`has_changes: false`, and the `create`/`report` steps (gated on `{{ check_changes.has_changes }}`) are skipped. This
means `meta_changespec`, `meta_pr_url`, etc. are never set.

**Evidence from logpack** (`~/tmp/260325_193911/`):

- `commit_result.json` exists with `changespec_name: "eval_foobar_2"` and CL URL
- `prompt_step_pr__check_changes.json` shows `has_changes: false`
- No `prompt_step_pr__create.json` or `prompt_step_pr__report.json` markers exist (steps were skipped)
- `done.json` / `prompt_step_main.json` only have `meta_workspace` and `meta_project` — no CL metadata

## Prior Art

`propose.yml` already solved this exact problem by adding a `_has_commit_result` step:

```yaml
- name: _has_commit_result
  hidden: true
  python: |
    import os
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
    path = os.path.join(artifacts_dir, "commit_result.json") if artifacts_dir else ""
    print(f"exists={'true' if path and os.path.isfile(path) else 'false'}")
  output: { exists: bool }
```

And uses the compound condition: `if: "{{ check_changes.has_changes or _has_commit_result.exists }}"`

## Fix

Apply the same pattern to `pr.yml` and `commit.yml`.

### Step 1: Update `pr.yml` (`src/sase/xprompts/pr.yml`)

1. Add `_has_commit_result` step between `check_changes` and `create` (same as in `propose.yml`)
2. Change `create` step condition from: `if: "{{ check_changes.has_changes }}"` →
   `if: "{{ check_changes.has_changes or _has_commit_result.exists }}"`
3. Change `report` step condition from: `if: "{{ check_changes.has_changes }}"` →
   `if: "{{ check_changes.has_changes or _has_commit_result.exists }}"`

### Step 2: Update `commit.yml` (`src/sase/xprompts/commit.yml`)

Same pattern:

1. Add `_has_commit_result` step between `check_changes` and `create`
2. Update `if` conditions on `create` and `report` steps

### Step 3: Verify with `just check`

Run lint/test to ensure nothing is broken.

## Why This Fixes It

When the stop hook commits changes before post-steps run:

- `check_changes.has_changes` = `false` (no uncommitted changes)
- `_has_commit_result.exists` = `true` (commit_result.json was written by the commit)
- Compound condition evaluates to `true`
- `create` step runs but short-circuits (reads existing `commit_result.json`)
- `report` step runs and extracts `meta_changespec`, `meta_pr_url`, `meta_pr_header` from `commit_result.json`
- These meta fields propagate to the agent's `step_output` and display in the TUI
