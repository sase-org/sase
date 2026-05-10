---
create_time: 2026-03-24 05:54:47
status: wip
prompt: sdd/prompts/202603/sase_9_gaps.md
---

# Plan: sase-9 Implementation Gaps

## Background

After reviewing the sase-9 spec (`specs/unified_vcs_commit.md`), plan (`plans/unified_vcs_commit.md`), and all 9 commits
against the actual code, I found several gaps between what was planned and what was implemented. All 5 phases are marked
done in `sdd/beads/issues.jsonl` but the epic is still open.

## Gap Summary

| #   | Gap                                                            | Severity | Scope                     |
| --- | -------------------------------------------------------------- | -------- | ------------------------- |
| 1   | sase-github missing 3 VCS dispatch hooks                       | Critical | ../sase-github/           |
| 2   | retired Mercurial plugin missing 3 VCS dispatch hooks                       | Critical | ../retired Mercurial plugin/ (complex) |
| 3   | bare_git `vcs_create_pull_request` missing ChangeSpec creation | Medium   | sase core                 |
| 4   | No tests for CommitWorkflow or VCS dispatch                    | Medium   | sase core                 |
| 5   | Stop hook sibling repo check uses old `/commit` skill          | Bug      | sase core                 |
| 6   | JSON payload not validated in CommitWorkflow                   | Low      | sase core                 |
| 7   | Old `/commit` skill (ccommit) coexists with new VCS skills     | Low      | chezmoi                   |

---

## Phase 1: sase-github VCS dispatch hooks + tests

**Goal**: Implement the three missing dispatch hooks in the sase-github plugin so that `sase commit` works when
`SASE_VCS_PROVIDER=github`.

**Scope**: `../sase-github/`

### Implementation

**File: `../sase-github/src/sase_github/plugin.py`** — Add 3 `@hookimpl` methods to `GitHubPlugin`:

1. **`vcs_create_commit(payload, cwd)`** — Same as bare_git: `git add` → `git commit -m` → `git push`. Can share logic
   with `GitCommon` or just duplicate the ~15 lines from bare_git. Since `GitHubPlugin` already inherits from
   `GitCommon` and `GitCommon` provides `_run()` and `_to_result()`, the pattern is identical.

2. **`vcs_create_proposal(payload, cwd)`** — Delegates to `vcs_create_commit` (same as bare_git, since "proposal" has no
   distinct meaning for GitHub).

3. **`vcs_create_pull_request(payload, cwd)`** — Creates branch, commits, pushes, then creates a GitHub PR:
   - `git checkout -b <name>`
   - `git add <files>` (or `-A`)
   - `git commit -m <message>`
   - `git push -u origin <name>`
   - `gh pr create --title <title> --body <message>` (this is the key difference from bare_git)
   - Extract PR URL from `gh pr create` output and return it

   Note: The existing `vcs_mail` hook already does `gh pr create --fill` as a fallback. The new method should use the
   payload's message for the PR body rather than `--fill`.

**File: `../sase-github/tests/test_github_plugin.py`** — Add tests following existing patterns (`@patch` on
`subprocess.run`):

- `test_vcs_create_commit_success` / `test_vcs_create_commit_add_fails` / `test_vcs_create_commit_specific_files`
- `test_vcs_create_proposal_delegates_to_commit`
- `test_vcs_create_pull_request_success` / `test_vcs_create_pull_request_pr_create_fails`

### Verification

- `just check` passes in `../sase-github/`
- New tests cover success and failure paths for all 3 methods

---

## Phase 2: Core fixes — stop hook bug + CommitWorkflow tests

**Goal**: Fix the sibling repo stop hook bug and add missing tests for CommitWorkflow.

**Scope**: sase core (`sase_100/`)

### Part A: Stop hook sibling repo fix

**File: `tools/sase_commit_stop_hook`** — Line 104 currently says:

```bash
emit_block \
    "Stop hook blocked: sibling repos have uncommitted changes. Run /commit now." \
    "Uncommitted changes detected in sibling repo(s): ..."
```

Fix: Use the VCS-appropriate skill name (resolved via `resolve_commit_skill`) instead of hardcoded `/commit`:

```bash
local skill
skill="$(resolve_commit_skill)"
emit_block \
    "Stop hook blocked: sibling repos have uncommitted changes. Run ${skill} now." \
    "Uncommitted changes detected in sibling repo(s): ${repos_list}. Use your ${skill} skill to commit them."
```

### Part B: CommitWorkflow unit tests

**File: `tests/test_commit_workflow.py`** (new) — Test the dispatch flow:

- `test_commit_workflow_dispatches_create_commit` — Verify `provider.create_commit(payload, cwd)` is called
- `test_commit_workflow_dispatches_create_proposal` — Verify `provider.create_proposal(payload, cwd)` is called
- `test_commit_workflow_dispatches_create_pull_request` — Verify `provider.create_pull_request(payload, cwd)` is called
- `test_commit_workflow_invalid_method` — Returns False and prints error for unknown method
- `test_commit_workflow_provider_failure` — Returns False when provider returns `(False, "error")`
- `test_commit_workflow_reads_env_method` — Falls back to `$SASE_COMMIT_METHOD` env var

Mock `get_vcs_provider()` to return a mock provider. Test that the correct method is called with the right arguments.

### Part C: bare_git dispatch tests

**File: `tests/test_bare_git_plugin.py`** (extend or create) — Test the three dispatch hooks:

- `test_vcs_create_commit_success` — All 3 git commands succeed
- `test_vcs_create_commit_no_files_uses_add_all` — Empty files list → `git add -A`
- `test_vcs_create_commit_push_fails` — Returns error tuple
- `test_vcs_create_proposal_delegates` — Calls `vcs_create_commit`
- `test_vcs_create_pull_request_creates_branch` — `git checkout -b <name>`
- `test_vcs_create_pull_request_push_fails` — Returns error tuple

### Verification

- `just check` passes
- All new tests pass

---

## Phase 3: bare_git ChangeSpec creation for create_pull_request

**Goal**: Add ChangeSpec creation to `vcs_create_pull_request` for bare_git (and by extension, the CommitWorkflow layer)
so that `#pr` flows create a trackable ChangeSpec.

**Scope**: sase core

### Design Decision

ChangeSpec creation should happen in `CommitWorkflow.run()` AFTER the VCS hook succeeds, not inside the VCS hook itself.
This keeps the VCS hooks focused on VCS operations and makes ChangeSpec creation VCS-agnostic (it works the same for
bare_git and GitHub).

The `create_changespec_for_workflow()` function in `src/sase/workspace_provider/changespec.py` requires `prompt`,
`response`, `workflow_name`, `checkout_target`, and `branch_name`. Some of these aren't available in the current JSON
payload.

### Implementation

**Option A (recommended)**: Extend the JSON payload to include optional fields for ChangeSpec creation:

```json
{
  "name": "feature-branch",
  "message": "commit message",
  "files": [],
  "description": "Full ChangeSpec description",
  "checkout_target": "master"
}
```

Then in `CommitWorkflow.run()`, after the VCS hook succeeds and the method is `create_pull_request`:

```python
if self._method == "create_pull_request" and ok:
    self._create_changespec(cwd)
```

The `_create_changespec` method would:

1. Derive `project_name` and `project_file` from the workspace
2. Use `checkout_target` from payload (or default to detecting the main branch)
3. Use `name` from payload as the branch name
4. Call `add_changespec_to_project_file()` with the available fields
5. Skip chat history (prompt/response) since it's not available through `sase commit`

**Option B**: Have the `/sase_git_commit` skill create the ChangeSpec directly (before or after calling `sase commit`).
This keeps CommitWorkflow simple but duplicates logic across skills.

### Verification

- `just check` passes
- ChangeSpec file is created when `sase commit '...' --method=create_pull_request` runs
- ChangeSpec has correct name, description, and status

---

## Phase 4: retired Mercurial plugin VCS dispatch hooks

**Goal**: Implement the three dispatch hooks for Mercurial/Google VCS.

**Scope**: `../retired Mercurial plugin/`

### Complexity Note

This is the most complex gap. The old retired Mercurial plugin workflows (`retired_mercurial_plugin_commit_workflow`, `sase_propose_workflow`,
`sase_cl_workflow`) contained substantial Google-internal logic: `hg amend`, `hg addremove`, `hg commit --name`,
`hg fix`, `hg upload tree`, branch/CL number resolution, etc. These scripts still exist in the retired Mercurial plugin repo and can
be used as reference.

### Implementation

**File: `../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py`** — Add 3 `@hookimpl` methods:

1. **`vcs_create_commit(payload, cwd)`** — Port from `retired_mercurial_plugin_commit_workflow`:
   - Get CL name from branch
   - Save diff and chat history
   - Build note with `[who]` prefix
   - Call `hg amend` equivalent
   - Add COMMITS entry to project file

2. **`vcs_create_proposal(payload, cwd)`** — Port from `sase_propose_workflow`:
   - Create proposal entry on CL
   - Save diff and chat history
   - Clean workspace after

3. **`vcs_create_pull_request(payload, cwd)`** — Port from `sase_cl_workflow`:
   - Build CL name with project prefix
   - Stage files with `hg addremove`
   - Create Mercurial commit with `hg commit --name`
   - Run `hg fix` and `hg upload tree`
   - Create ChangeSpec entry

### Verification

- Tests pass in `../retired Mercurial plugin/`
- End-to-end verification with Mercurial workspace (if available)

---

## Phase 5: Cleanup

**Goal**: Address remaining minor gaps.

### Part A: Payload validation in CommitWorkflow

**File: `src/sase/workflows/commit/workflow.py`** — Add basic validation:

```python
if not isinstance(self._payload, dict):
    print_status("Payload must be a JSON object", "error")
    return False
if "message" not in self._payload and self._method != "create_pull_request":
    print_status("Payload missing required 'message' field", "error")
    return False
```

### Part B: Decide on old `/commit` skill

The old `/commit` skill (ccommit) is still used for repos that DON'T use the unified commit workflow (e.g., repos
without a VCS xprompt like `#git:repo`). Decision needed:

- **Keep both**: `/commit` for ad-hoc commits outside commit workflows, `/sase_git_commit` for unified workflow
- **Remove `/commit`**: Migrate all commit flows to the unified system

This is a user decision — flagging it for discussion.

### Verification

- `just check` passes
- Invalid JSON payloads produce clear error messages

---

## Recommended Execution Order

1. **Phase 2** (stop hook bug + tests) — Quick wins, no cross-repo changes
2. **Phase 1** (sase-github hooks) — High-impact, moderate effort
3. **Phase 3** (ChangeSpec creation) — Needs design decision on payload extension
4. **Phase 5** (cleanup) — Low risk
5. **Phase 4** (retired Mercurial plugin hooks) — Most complex, may need dedicated attention
