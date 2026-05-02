---
create_time: 2026-03-24 17:16:54
status: wip
prompt: sdd/prompts/202603/gemini_commit_dispatch.md
---

# Fix: Re-add commit dispatch steps to unified xprompts for Gemini agents

## Problem

The `#pr` (and `#commit`, `#propose`) xprompts fail to create CLs/PRs when used with Gemini agents. The agent completes
file changes successfully, but no commit/CL is ever created.

### Root Cause

The commit/PR creation relies on the **stop hook mechanism** (`sase_commit_stop_hook`), which:

1. Detects uncommitted changes after the agent stops
2. Instructs the agent to use `/sase_git_commit` or `/sase_hg_commit` skill
3. The skill invokes `CommitWorkflow` which writes `commit_result.json`

**Gemini CLI doesn't support stop hooks.** So for Gemini agents, step 1 never happens, no commit is created, and
`commit_result.json` is never written. The `report` post-step checks for `commit_result.json`, finds nothing, exits 0
silently.

### Evidence from Logs

- `~/tmp/260324_170452/` logpack: agent `@j` (Gemini `gemini-3-flash-preview`) ran with `#hg:foobar ... #pr:foobar`
- `prompt_step_pr__report.json`: `"output": {}` — empty because `commit_result.json` doesn't exist
- `workflow_state.json`: Only has `main` step, no dispatch step
- Agent completed with `SUCCESS` but no CL was created

### History

Commit `37edb755` added dispatch steps to the xprompts as a fallback for non-stop-hook agents. This was reverted in
`fbf2a38`. The env var injection fix from `71b376c` (injecting embedded workflow `environment:` into `os.environ` in
`workflow_executor_steps_embedded.py`) survived the reverts and IS in the current codebase.

## Fix

### Step 1: Re-add `check_changes` + dispatch steps to `pr.yml`

**File:** `src/sase/xprompts/pr.yml`

Add between the `inject` and `report` steps:

```yaml
- name: check_changes
  use: shared/check_changes

- name: create
  hidden: true
  if: "{{ check_changes.has_changes }}"
  python: |
    import json, os
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
    result_file = os.path.join(artifacts_dir, "commit_result.json") if artifacts_dir else ""
    if result_file and os.path.isfile(result_file):
        d = json.load(open(result_file))
        print("success=true")
        print(f"pr_url={d.get('result', '') or ''}")
        raise SystemExit(0)
    from sase.workflows.commit import CommitWorkflow
    method = os.environ.get("SASE_COMMIT_METHOD", "create_pull_request")
    name = {{ name | tojson }}
    who = {{ who | default("agent") | tojson }}
    wf = CommitWorkflow(
        payload={"message": f"[{who}] Agent changes", "name": name},
        method=method,
    )
    ok = wf.run()
    if ok and result_file and os.path.isfile(result_file):
        d = json.load(open(result_file))
        print("success=true")
        print(f"pr_url={d.get('result', '') or ''}")
    else:
        print("success=false")
  output:
    success: bool
    pr_url: line
```

The key design: if `commit_result.json` already exists (stop hook handled it), short-circuit. Otherwise, invoke
`CommitWorkflow` directly.

### Step 2: Re-add dispatch steps to `commit.yml`

**File:** `src/sase/xprompts/commit.yml`

Same pattern, but using `create_commit` method and `new_commit` output field.

### Step 3: Re-add dispatch steps to `propose.yml`

**File:** `src/sase/xprompts/propose.yml`

Same pattern, but using `create_proposal` method and `proposal_id` output field.

### Step 4: Re-add env injection in CRS and fix_hook_runner

**Files:** `src/sase/workflows/crs.py`, `src/sase/axe/fix_hook_runner.py`

These standalone code paths execute embedded workflow post-steps but don't inject the workflow's `environment:` block.
Add env injection before the post-step execution loop:

```python
os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir
os.environ["SASE_COMMIT_METHOD"] = "create_proposal"  # or appropriate method
```

Without this, the dispatch steps in xprompts won't have `SASE_ARTIFACTS_DIR` set when invoked from CRS/fix_hook paths.

### Step 5: Validate

1. `just install && just check` — all tests, lint, etc.
2. Verify the `shared/check_changes` step definition exists at `src/sase/xprompts/steps/shared/check_changes.yml`
   (confirmed it does)
3. Verify the "use" step type is supported in the schema (confirmed via commit `f9936a4`)

### Files Changed

| File                              | Change                                         |
| --------------------------------- | ---------------------------------------------- |
| `src/sase/xprompts/pr.yml`        | Add `check_changes` + `create` dispatch steps  |
| `src/sase/xprompts/commit.yml`    | Add `check_changes` + `create` dispatch steps  |
| `src/sase/xprompts/propose.yml`   | Add `check_changes` + `propose` dispatch steps |
| `src/sase/workflows/crs.py`       | Re-add env injection before post-steps         |
| `src/sase/axe/fix_hook_runner.py` | Re-add env injection before post-steps         |

### Key Design Decisions

1. **Short-circuit on existing `commit_result.json`**: For Claude/Codex agents where the stop hook already handled the
   commit, the dispatch step detects the existing result file and exits immediately. This makes the dispatch steps a
   **no-op** for stop-hook agents and a **fallback** for Gemini.

2. **`shared/check_changes` guard**: Only runs the dispatch if the agent actually made changes. If there are no changes,
   skip dispatch.

3. **CRS/fix_hook env injection**: These standalone paths don't go through `_expand_embedded_workflows_in_prompt()`, so
   they need explicit env injection.
