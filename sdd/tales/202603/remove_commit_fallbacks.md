---
status: done
create_time: 2026-03-26 19:21:26
prompt: sdd/prompts/202603/remove_commit_fallbacks.md
---

# Plan: Remove Commit Fallbacks & Proper Proposal Support

## Summary

Remove all fallback logic from `#commit`, `#propose`, and `#pr` xprompt workflows. If the stop hook + agent skill didn't
produce `commit_result.json`, the workflow fails instead of silently creating a commit. Additionally, change
`create_proposal` across all VCS providers to save a diff file and clean the workspace (instead of committing), and move
COMMITS entry writing into `CommitWorkflow` so that `sase commit` is fully self-contained.

## Design Decisions (from user)

1. Diff files saved to `~/.sase/diffs/` using existing naming conventions
2. `create_proposal` result (diff file path) stored in `commit_result.json` as `result`; diff path also added to COMMITS
   entry DIFF drawer
3. `sase commit` handles writing the COMMITS entry for both commits and proposals
4. Run `precommit_command` for proposals; skip bead closing and SASE_PLAN logic
5. After saving the proposal diff, clean workspace in a VCS-agnostic way (via `clean_workspace()`)
6. Changes apply to ALL VCS providers (git and retired Mercurial plugin)
7. No agent skill changes needed (same payload format works)
8. Diffs must include untracked (new) files and deleted files

## Phases

### Phase 1: Change git `create_proposal` to save diff + clean workspace

**Files:**

- `src/sase/vcs_provider/plugins/_git_common.py`

**Changes:**

Replace `vcs_create_proposal` (currently delegates to `vcs_create_commit` with `_skip_bead_amend`):

```python
# BEFORE (line 601-603):
@hookimpl
def vcs_create_proposal(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    return self.vcs_create_commit({**payload, "_skip_bead_amend": True}, cwd)

# AFTER:
@hookimpl
def vcs_create_proposal(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    """Save diff and clean workspace - proposals don't commit."""
    from sase.workflows.commit_utils.workspace import save_diff, clean_workspace

    cl_name = payload.get("name", "") or payload.get("_cl_name", "")
    diff_path = save_diff(cl_name, target_dir=cwd)
    if not diff_path:
        return (False, "No changes to save as proposal diff")

    clean_workspace(cwd)
    return (True, diff_path)
```

This mirrors exactly what `retired Mercurial plugin/plugin.py:368-380` already does.

**Why this works for untracked files:** `save_diff` calls `provider.add_remove(cwd)` (which runs `git add -A` for git)
before `provider.diff(cwd)` (which runs `git diff HEAD`). After staging, `git diff HEAD` includes new files. The
subsequent `clean_workspace` (`git reset --hard HEAD` + `git clean -fd`) restores the workspace.

### Phase 2: Move COMMITS entry writing into CommitWorkflow

**Files:**

- `src/sase/workflows/commit/workflow.py`

**Changes:**

1. Add a `_append_commits_entry` method to `CommitWorkflow` that calls `append_post_commit_entry`:

```python
def _append_commits_entry(self) -> str | None:
    """Append a COMMITS entry after successful commit/proposal. Returns entry_id."""
    from sase.workflows.commit_utils.post_commit import append_post_commit_entry

    mode = "proposal" if self._method == "create_proposal" else "commit"
    result = append_post_commit_entry(mode=mode)
    return result.entry_id if result.success else None
```

2. Update `_write_result_marker` to accept an optional `entry_id` parameter and include it in the JSON.

3. Restructure `run()` to:
   - Call `_append_commits_entry` after writing the initial result marker (for commit and proposal methods only)
   - Re-write the result marker with `entry_id` included

Revised `run()` tail (after VCS dispatch succeeds):

```python
    cs_name: str | None = None
    if self._method == "create_pull_request":
        cs_name = self._create_changespec(cl_url=result)

    # Write initial result marker (needed by append_post_commit_entry)
    self._write_result_marker(result, cs_name)

    # Append COMMITS entry for commit/proposal (not PR - it uses ChangeSpec)
    entry_id: str | None = None
    if self._method in ("create_commit", "create_proposal"):
        entry_id = self._append_commits_entry()
        if entry_id:
            self._write_result_marker(result, cs_name, entry_id=entry_id)

    return True
```

### Phase 3: Skip bead/plan handling for proposals in CommitWorkflow

**Files:**

- `src/sase/workflows/commit/workflow.py`

**Changes:**

Guard `_handle_beads` and `_handle_sase_plan` so they only run for `create_commit` and `create_pull_request`:

```python
    # Bead lifecycle and SASE_PLAN: skip for proposals
    if self._method != "create_proposal":
        self._handle_beads(cwd)
        self._handle_sase_plan(cwd)
```

### Phase 4: Remove fallback logic from xprompt workflows

**Files:**

- `src/sase/xprompts/commit.yml`
- `src/sase/xprompts/propose.yml`
- `src/sase/xprompts/pr.yml`

**Changes for all three:**

Replace the `create`/`propose` step to remove the fallback `CommitWorkflow` instantiation. If `commit_result.json`
doesn't exist, set `success=false`.

**commit.yml `create` step:**

```python
import json, os
artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
result_file = os.path.join(artifacts_dir, "commit_result.json") if artifacts_dir else ""
if result_file and os.path.isfile(result_file):
    with open(result_file) as f:
        d = json.load(f)
    print("success=true")
    print(f"new_commit={d.get('result', '') or ''}")
else:
    print("success=false")
```

**propose.yml `propose` step:** Same pattern, outputting `proposal_id` instead of `new_commit`.

**pr.yml `create` step:** Same pattern, outputting `pr_url` instead of `new_commit`.

### Phase 5: Remove `_append_entry` steps from xprompts and update emit steps

**Files:**

- `src/sase/xprompts/commit.yml`
- `src/sase/xprompts/propose.yml`

**Changes:**

1. **Remove `_append_entry` step** from both `commit.yml` and `propose.yml` (CommitWorkflow now handles this).

2. **Update `_emit_commit_id`** in `commit.yml` to read `entry_id` from `commit_result.json`:

```python
import json, os
artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
result_file = os.path.join(artifacts_dir, "commit_result.json") if artifacts_dir else ""
if result_file and os.path.isfile(result_file):
    with open(result_file) as f:
        d = json.load(f)
    entry_id = d.get("entry_id", "") or ""
    if entry_id:
        print(f"meta_commit_id={entry_id}")
```

3. **Update `_emit_proposal_id`** in `propose.yml` similarly (read `entry_id` from `commit_result.json`).

### Phase 6: Update tests

**Files:**

- `tests/workflows/test_commit_*.py` (CommitWorkflow tests)
- `tests/test_vcs_provider*.py` (VCS provider tests)
- Any tests that mock the fallback path

**Changes:**

- Update `test_vcs_provider_git_core.py` / `test_vcs_provider_git_integration.py`: test that `create_proposal` now saves
  a diff and cleans workspace instead of committing
- Update CommitWorkflow tests: verify proposals skip beads/plan, and that COMMITS entries are written by the workflow
- Remove/update any tests that rely on the fallback `CommitWorkflow` path in xprompts

## File Change Summary

| File                                           | Change                                                                                   |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `src/sase/vcs_provider/plugins/_git_common.py` | Rewrite `vcs_create_proposal` to save diff + clean                                       |
| `src/sase/workflows/commit/workflow.py`        | Add `_append_commits_entry`, skip beads/plan for proposals, include `entry_id` in marker |
| `src/sase/xprompts/commit.yml`                 | Remove fallback path, remove `_append_entry`, update `_emit_commit_id`                   |
| `src/sase/xprompts/propose.yml`                | Remove fallback path, remove `_append_entry`, update `_emit_proposal_id`                 |
| `src/sase/xprompts/pr.yml`                     | Remove fallback path                                                                     |
| Tests                                          | Update to match new behavior                                                             |

## Notes

- The `precommit_command` config key is used as-is (the user referred to it as "presubmit_command" in their decision,
  but the existing config key is `precommit_command` - confirm if rename is desired).
- `save_diff` already handles git correctly: `add_remove()` stages new/deleted files, then `diff()` captures everything
  including untracked files.
- The retired Mercurial plugin plugin (`../retired Mercurial plugin`) already implements the correct proposal behavior (`save_diff` +
  `clean_workspace`). No changes needed there.
- No agent skill changes needed - same JSON payload format works for all methods.
