---
create_time: 2026-03-24 09:55:49
status: wip
prompt: sdd/prompts/202603/commit_meta_output.md
---

# Plan: Propagate meta\_\* output variables from unified CommitWorkflow to TUI

## Problem

The new unified commit xprompts (`commit.yml`, `propose.yml`, `pr.yml`) replaced multi-step VCS-specific workflows
(`gcommit.yml`, `gpropose.yml`, `gchange.yml`) that had `report` post-steps outputting `meta_*` variables. The new
xprompts are minimal `prompt_part` stubs with no post-steps. The actual commit operation now happens imperatively via
`sase commit` CLI → `CommitWorkflow.run()` → VCS plugin dispatch. There is no mechanism to propagate the commit result
(PR URL, CL name, commit hash, changespec name) back to the xprompt framework as `meta_*` output variables.

### What's broken

1. **No `meta_new_pr` / `meta_new_cl` / `meta_new_commit` output** — the TUI metadata panel won't show the new
   CL/PR/commit information for agents that used the new commit xprompts.
2. **No `meta_changespec` output** — the "go to CL" keybinding (`Enter`/`L`) won't work since
   `get_meta_changespec_name()` finds nothing in `step_output`.
3. **No `diff_path` output** — the file panel won't show the diff for committed changes.

### How the old xprompts worked

The old xprompts (e.g., `gcommit.yml`) were multi-step embedded workflows:

```
inject (prompt_part) → injected into agent prompt
check_changes (post-step) → detected if changes were made
save_response (post-step) → saved prompt/response for ChangeSpec
commit (post-step) → ran sase_commit_workflow script
report (post-step) → output meta_new_commit, diff_path, etc.
```

Steps after the `prompt_part` are "post-steps" in the embedded workflow model (`get_post_prompt_steps()`). They run
after the agent completes. Their outputs are collected by `_collect_embedded_step_outputs()` and stored in
`step_state.output`, which the TUI reads to display metadata.

### How the new flow works (broken path)

```
#commit xprompt → sets SASE_COMMIT_METHOD env var, injects prompt_part
  → agent runs, makes code changes
    → stop hook fires, detects uncommitted changes
      → agent calls /sase_git_commit skill
        → agent runs `sase commit '{"message":"..."}' --method create_commit`
          → CommitWorkflow.run() → VCS plugin dispatch → returns (success, result)
          → CLI exits 0/1
    → agent completes
  → NO post-steps → step_state.output has NO meta_* fields
```

## Solution: Marker file bridge + xprompt post-steps

Use the same `$SASE_ARTIFACTS_DIR` marker-file pattern that `sase plan` and `sase questions` already use.

### Phase 1: CommitWorkflow writes a result marker file

**File**: `src/sase/workflows/commit/workflow.py`

After a successful dispatch, `CommitWorkflow.run()` writes a JSON marker file to
`$SASE_ARTIFACTS_DIR/commit_result.json`:

```python
def _write_result_marker(self, result: str | None, changespec_name: str | None) -> None:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return  # Not running inside an agent — skip silently

    marker = {
        "method": self._method,
        "result": result,         # PR URL, CL name+URL, commit hash, etc.
        "changespec_name": changespec_name,
    }
    marker_path = os.path.join(artifacts_dir, "commit_result.json")
    with open(marker_path, "w") as f:
        json.dump(marker, f)
```

Call this at the end of `run()` after the dispatch succeeds (and after `_create_changespec()` for PR flows, so we have
the changespec name).

The `_create_changespec()` method needs to return the changespec name so it can be passed to `_write_result_marker()`.

**Changes needed**:

- `CommitWorkflow.run()`: Call `_write_result_marker()` after success
- `CommitWorkflow._create_changespec()`: Return `cs_name` (currently prints it but doesn't return it)
- Add `import json` to imports

### Phase 2: Add `report` post-steps to commit xprompts

Add a hidden `report` bash step after the `inject` prompt_part step in each xprompt. Since it comes after the
`prompt_part`, it's a post-step — it runs after the agent completes.

**File**: `src/sase/xprompts/commit.yml`

```yaml
steps:
  - name: inject
    prompt_part: |
      ---
      IMPORTANT: You should make the necessary file changes, but should NOT commit them yourself.

  - name: report
    hidden: true
    bash: |
      RESULT_FILE="${SASE_ARTIFACTS_DIR}/commit_result.json"
      if [ ! -f "$RESULT_FILE" ]; then
        exit 0
      fi
      METHOD=$(python3 -c "import json; d=json.load(open('$RESULT_FILE')); print(d.get('method',''))")
      RESULT=$(python3 -c "import json; d=json.load(open('$RESULT_FILE')); print(d.get('result','') or '')")
      CS_NAME=$(python3 -c "import json; d=json.load(open('$RESULT_FILE')); print(d.get('changespec_name','') or '')")

      if [ "$METHOD" = "create_commit" ] && [ -n "$RESULT" ]; then
        echo "meta_new_commit=$RESULT"
      fi
      if [ -n "$CS_NAME" ]; then
        echo "meta_changespec=$CS_NAME"
      fi
    output: { meta_new_commit: line, meta_changespec: word }
```

**File**: `src/sase/xprompts/propose.yml`

Same structure but outputs `meta_new_cl` or `meta_new_pr` depending on result:

```yaml
- name: report
  hidden: true
  bash: |
    # ... read commit_result.json ...
    # For create_proposal, the VCS plugin returns the CL/PR identifier
    if [ "$METHOD" = "create_proposal" ] && [ -n "$RESULT" ]; then
      echo "meta_new_pr=$RESULT"
    fi
    if [ -n "$CS_NAME" ]; then
      echo "meta_changespec=$CS_NAME"
    fi
  output: { meta_new_pr: line, meta_changespec: word }
```

**File**: `src/sase/xprompts/pr.yml`

```yaml
- name: report
  hidden: true
  bash: |
    # ... read commit_result.json ...
    if [ "$METHOD" = "create_pull_request" ] && [ -n "$RESULT" ]; then
      echo "meta_new_pr=$RESULT"
    fi
    if [ -n "$CS_NAME" ]; then
      echo "meta_changespec=$CS_NAME"
    fi
  output: { meta_new_pr: line, meta_changespec: word }
```

**Alternative**: Use a single shared `report` step via `use: shared/commit_report` to avoid duplication. Define the
shared step in `src/sase/xprompts/shared/commit_report.yml`. This is cleaner but adds a new file — decide based on
preference.

### Phase 3: Ensure VCS plugins return meaningful result strings

The `result` field from `vcs_create_*` hooks should contain a useful identifier:

**bare_git plugin** (`src/sase/vcs_provider/plugins/bare_git.py`):

- `vcs_create_commit`: Return `(True, commit_hash)` — capture the hash from `git rev-parse HEAD` after commit
- `vcs_create_proposal`: Same as `vcs_create_commit`
- `vcs_create_pull_request`: Return `(True, None)` — bare git has no native PR concept (result stays None)

**sase-github plugin** (`../sase-github/`):

- `vcs_create_pull_request`: Return `(True, pr_url)` — the PR URL from `gh pr create`

**retired Mercurial plugin plugin** (`../retired Mercurial plugin/`):

- `vcs_create_proposal`: Return `(True, "cl_name (cl_url)")` — matches the `meta_new_cl` format expected by
  `get_meta_changespec_name()` (parses `"name (url)"` → `"name"`)

### Phase 4: Tests

1. **Unit test for `_write_result_marker()`**: Verify marker file is written with correct fields when
   `SASE_ARTIFACTS_DIR` is set, and skipped when not set.
2. **Unit test for post-step execution**: Use the existing `test_done_agent_loader.py` pattern to verify that
   `meta_new_pr` / `meta_changespec` end up in `step_output` when `commit_result.json` exists.
3. **Update existing `test_commit_workflow.py`**: Verify `_write_result_marker()` is called on success path and
   `_create_changespec()` returns the name.
4. **Integration test**: Verify the end-to-end flow with `sase ace --agent` (optional, complex).

## Files to modify

| File                                        | Change                                                                  |
| ------------------------------------------- | ----------------------------------------------------------------------- |
| `src/sase/workflows/commit/workflow.py`     | Add `_write_result_marker()`, update `run()` and `_create_changespec()` |
| `src/sase/xprompts/commit.yml`              | Add `report` post-step                                                  |
| `src/sase/xprompts/propose.yml`             | Add `report` post-step                                                  |
| `src/sase/xprompts/pr.yml`                  | Add `report` post-step                                                  |
| `src/sase/vcs_provider/plugins/bare_git.py` | Return commit hash from `vcs_create_commit`                             |
| `tests/test_commit_workflow.py`             | Add tests for marker file writing                                       |

## Design notes

- **Why a marker file instead of stdout?** The `sase commit` CLI runs in a subprocess inside the agent's conversation.
  Its stdout is consumed by the LLM, not by the xprompt framework. A marker file in `$SASE_ARTIFACTS_DIR` is the
  established pattern (used by `sase plan` and `sase questions`).
- **Why post-steps instead of direct framework integration?** Post-steps are the standard mechanism for embedded
  workflows to output meta\_\* variables. Using the same mechanism keeps the architecture consistent and requires no
  framework changes.
- **Graceful degradation**: If `$SASE_ARTIFACTS_DIR` is not set (e.g., running `sase commit` outside an agent), the
  marker file is simply not written. The post-steps check for the file and exit silently if absent.
