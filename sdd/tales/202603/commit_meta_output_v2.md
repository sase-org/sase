---
create_time: 2026-03-24 10:34:02
status: wip
prompt: sdd/prompts/202603/commit_meta_output_v2.md
---

# Plan: Workflow-specific meta output variables for commit xprompts

## Problem

Same root problem as the original `commit_meta_output.md` plan: the unified commit xprompts (`commit.yml`,
`propose.yml`, `pr.yml`) have no post-steps, so no `meta_*` variables flow to the TUI. This revision changes the meta
variable design to be **workflow-specific** rather than using a shared set of variables.

## Desired meta output per workflow

| Workflow      | Method                | Meta variable 1    | Meta variable 2       |
| ------------- | --------------------- | ------------------ | --------------------- |
| `commit.yml`  | `create_commit`       | `meta_new_commit`  | `meta_commit_message` |
| `propose.yml` | `create_proposal`     | `meta_proposal_id` | `meta_commit_message` |
| `pr.yml`      | `create_pull_request` | `meta_pr_header`   | `meta_pr_url`         |

Additionally, `pr.yml` outputs `meta_changespec` (the ChangeSpec name) so the TUI "go to CL" navigation continues to
work.

### Variable definitions

- **`meta_new_commit`**: Git commit hash (short or full) from `git rev-parse HEAD` after commit+push
- **`meta_commit_message`**: The commit message string from the payload's `message` field
- **`meta_proposal_id`**: Proposal identifier — CL number for Google (`http://cl/12345` → `12345`), commit hash for bare
  git (since bare git proposals are just commits)
- **`meta_pr_header`**: First line of the commit message (the PR title / description header)
- **`meta_pr_url`**: Full PR or CL URL (GitHub PR URL, Google CL URL, `None` for bare git)
- **`meta_changespec`**: ChangeSpec name (only for PR flows that create a ChangeSpec)

## Solution: Marker file bridge + workflow-specific post-steps

Same architecture as original plan — `$SASE_ARTIFACTS_DIR/commit_result.json` marker file written by
`CommitWorkflow.run()`, read by per-workflow `report` post-steps.

### Phase 1: CommitWorkflow writes an enriched result marker file

**File**: `src/sase/workflows/commit/workflow.py`

The marker file carries **all raw data**; each workflow's post-step extracts only what it needs.

```python
def _write_result_marker(self, result: str | None, changespec_name: str | None) -> None:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return  # Not running inside an agent — skip silently

    marker = {
        "method": self._method,
        "result": result,                           # commit hash, PR URL, CL URL, etc.
        "message": self._payload.get("message", ""),  # commit message
        "name": self._payload.get("name", ""),        # branch/PR name
        "changespec_name": changespec_name,
    }
    marker_path = os.path.join(artifacts_dir, "commit_result.json")
    with open(marker_path, "w") as f:
        json.dump(marker, f)
```

**Changes to `run()`**:

```python
def run(self) -> bool:
    # ... existing validation and dispatch ...

    cs_name: str | None = None
    if self._method == "create_pull_request":
        cs_name = self._create_changespec(cl_url=result)

    self._write_result_marker(result, cs_name)
    return True
```

**Changes to `_create_changespec()`**: Return `cs_name` instead of `None` (currently prints it but doesn't return).

```python
def _create_changespec(self, cl_url: str | None) -> str | None:
    # ... existing logic ...
    cs_name = create_changespec_for_workflow(...)
    if cs_name:
        print_status(f"Created ChangeSpec: {cs_name}", "success")
    else:
        print_status("Skipping ChangeSpec: no new commits detected.", "info")
    return cs_name
```

**Imports**: Add `import json`.

### Phase 2: Add workflow-specific `report` post-steps

Each xprompt gets a hidden `report` bash post-step that reads `commit_result.json` and outputs its specific meta
variables.

**File**: `src/sase/xprompts/commit.yml`

```yaml
tags: rollover, commit

environment:
  SASE_COMMIT_METHOD: create_commit

steps:
  - name: inject
    prompt_part: |
      ---
      IMPORTANT: You should make the necessary file changes, but should NOT commit them yourself.

  - name: report
    hidden: true
    bash: |
      RESULT_FILE="${SASE_ARTIFACTS_DIR}/commit_result.json"
      [ -f "$RESULT_FILE" ] || exit 0
      eval "$(python3 -c "
      import json, sys
      d = json.load(open('$RESULT_FILE'))
      for k in ('result', 'message'):
          print(f'{k}={d.get(k, \"\") or \"\"}')
      ")"
      [ -n "$result" ] && echo "meta_new_commit=$result"
      [ -n "$message" ] && echo "meta_commit_message=$message"
    output:
      meta_new_commit: word
      meta_commit_message: line
```

**File**: `src/sase/xprompts/propose.yml`

```yaml
tags: rollover, propose

environment:
  SASE_COMMIT_METHOD: create_proposal

steps:
  - name: inject
    prompt_part: |
      ---
      IMPORTANT: You should make the necessary file changes, but should NOT commit or create a proposal yourself.

  - name: report
    hidden: true
    bash: |
      RESULT_FILE="${SASE_ARTIFACTS_DIR}/commit_result.json"
      [ -f "$RESULT_FILE" ] || exit 0
      eval "$(python3 -c "
      import json, sys
      d = json.load(open('$RESULT_FILE'))
      for k in ('result', 'message'):
          print(f'{k}={d.get(k, \"\") or \"\"}')
      ")"
      [ -n "$result" ] && echo "meta_proposal_id=$result"
      [ -n "$message" ] && echo "meta_commit_message=$message"
    output:
      meta_proposal_id: word
      meta_commit_message: line
```

**File**: `src/sase/xprompts/pr.yml`

```yaml
tags: rollover

input:
  - name: name
    type: word
  - name: bug_id
    type: int
    default: 0

environment:
  SASE_COMMIT_METHOD: create_pull_request
  SASE_BUG_ID: "{{ bug_id }}"

steps:
  - name: inject
    prompt_part: |
      ---
      IMPORTANT: You should make the necessary file changes, but should NOT create a commit, branch, or pull request yourself.

  - name: report
    hidden: true
    bash: |
      RESULT_FILE="${SASE_ARTIFACTS_DIR}/commit_result.json"
      [ -f "$RESULT_FILE" ] || exit 0
      eval "$(python3 -c "
      import json, sys
      d = json.load(open('$RESULT_FILE'))
      for k in ('result', 'message', 'changespec_name'):
          print(f'{k}={d.get(k, \"\") or \"\"}')
      ")"
      if [ -n "$message" ]; then
        header=$(echo "$message" | head -1)
        echo "meta_pr_header=$header"
      fi
      [ -n "$result" ] && echo "meta_pr_url=$result"
      [ -n "$changespec_name" ] && echo "meta_changespec=$changespec_name"
    output:
      meta_pr_header: line
      meta_pr_url: line
      meta_changespec: word
```

### Phase 3: Ensure VCS plugins return meaningful result strings

**bare_git plugin** (`src/sase/vcs_provider/plugins/bare_git.py`):

- `vcs_create_commit`: After successful commit+push, run `git rev-parse --short HEAD` and return `(True, commit_hash)`
- `vcs_create_proposal`: Delegates to `vcs_create_commit`, so inherits the commit hash return
- `vcs_create_pull_request`: After successful commit+push, run `git rev-parse --short HEAD` and return
  `(True, commit_hash)`. Bare git has no PR URL, but returning the commit hash lets `meta_pr_url` be empty (since a
  commit hash isn't a URL) — alternatively return `None` and let the post-step skip `meta_pr_url`.

Decision: `vcs_create_pull_request` returns `(True, None)` for bare git (no URL to show). The commit hash is available
via `git rev-parse` in the post-step if ever needed.

**sase-github plugin** (`../sase-github/`): Already returns `(True, pr_url)` — no change needed.

**retired Mercurial plugin plugin** (`../retired Mercurial plugin/`):

- `vcs_create_proposal`: Currently returns `(True, None)`. Should return `(True, cl_url)` where `cl_url` comes from
  `vcs_get_cl_number()` → `http://cl/{cl_number}`. The `meta_proposal_id` post-step will output the full URL as the
  proposal identifier.
- `vcs_create_pull_request`: Already returns `(True, cl_url)` — no change needed.

### Phase 4: Update `get_meta_changespec_name()` for new variable names

**File**: `src/sase/ace/tui/actions/agents/_notification_actions.py`

The current function checks `meta_new_cl` and `meta_new_pr`. Update it to check the new variable `meta_changespec`
directly (which is now the canonical source for all workflows):

```python
def get_meta_changespec_name(agent: Agent) -> str | None:
    step_output = agent.step_output
    if not step_output or not isinstance(step_output, dict):
        return None

    # New canonical path: meta_changespec contains the ChangeSpec name directly
    meta_changespec = step_output.get("meta_changespec")
    if meta_changespec:
        return str(meta_changespec).strip()

    # Legacy support: meta_new_cl format is "full_cl_name (url)"
    meta_new_cl = step_output.get("meta_new_cl")
    if meta_new_cl:
        value = str(meta_new_cl).strip()
        paren_idx = value.rfind(" (")
        if paren_idx > 0:
            return value[:paren_idx].strip()
        return value

    # Legacy support: meta_new_pr + meta_changespec
    meta_new_pr = step_output.get("meta_new_pr")
    if meta_new_pr:
        meta_cs = step_output.get("meta_changespec")
        if meta_cs:
            return str(meta_cs).strip()

    return None
```

The `meta_changespec` check at the top handles the new flow. The legacy checks below handle agents that ran with old
xprompts (their step_output was persisted to disk and may still be loaded).

### Phase 5: Tests

1. **Unit test for `_write_result_marker()`**: Verify marker file contents include `method`, `result`, `message`,
   `name`, and `changespec_name`. Verify no file written when `SASE_ARTIFACTS_DIR` is unset.
2. **Unit test for `_create_changespec()` return value**: Verify it returns `cs_name` on success and `None` on failure.
3. **Update `get_meta_changespec_name` tests**: Add test for `meta_changespec` direct lookup path.
4. **Integration test** (optional): Verify end-to-end with `sase ace --agent`.

## Files to modify

| File                                                       | Change                                                                       |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `src/sase/workflows/commit/workflow.py`                    | Add `_write_result_marker()`, update `run()` and `_create_changespec()`      |
| `src/sase/xprompts/commit.yml`                             | Add `report` post-step: `meta_new_commit` + `meta_commit_message`            |
| `src/sase/xprompts/propose.yml`                            | Add `report` post-step: `meta_proposal_id` + `meta_commit_message`           |
| `src/sase/xprompts/pr.yml`                                 | Add `report` post-step: `meta_pr_header` + `meta_pr_url` + `meta_changespec` |
| `src/sase/vcs_provider/plugins/bare_git.py`                | Return commit hash from `vcs_create_commit`                                  |
| `src/sase/ace/tui/actions/agents/_notification_actions.py` | Update `get_meta_changespec_name()` for new variable names                   |
| `../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py`                 | Return CL URL from `vcs_create_proposal`                                     |
| `tests/test_commit_workflow.py`                            | Add tests for marker file writing and `_create_changespec()` return          |

## Design notes

- **Why workflow-specific variables?** Each workflow produces fundamentally different artifacts. A commit produces a
  hash
  - message. A proposal produces an ID + message. A PR produces a title + URL. Shared variables like `meta_new_pr` that
    tried to serve multiple workflows led to confusion about format and consumers.
- **Why keep `meta_changespec` separate?** It's only relevant for PR flows (which create ChangeSpecs). Commit and
  propose flows don't create ChangeSpecs, so they don't output it.
- **Legacy compat in `get_meta_changespec_name()`**: Old agents may have persisted `meta_new_cl`/`meta_new_pr` in their
  step_output. The legacy checks ensure the "go to CL" keybinding works for those older runs.
- **Marker file carries superset**: The marker file includes `method`, `result`, `message`, `name`, and
  `changespec_name` — all the raw data. Each workflow's post-step cherry-picks what it needs. This keeps the
  CommitWorkflow generic.
