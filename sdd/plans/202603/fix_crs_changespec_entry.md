---
status: done
created: 2026-03-27
create_time: 2026-03-27 15:44:57
prompt: sdd/prompts/202603/fix_crs_changespec_entry.md
---

# Fix CRS Agent ChangeSpec Entry Bugs

## Problem

When the `crs` agent runs in background (axe) mode, three things go wrong with the ChangeSpec entry it creates:

1. **COMMENTS suffix shows diff path instead of proposal ID**: Displays `(~/.sase/diffs/-260327_152253.diff)` instead of
   `(5d)`.
2. **No CHAT file on proposal entry**: The `(5d)` COMMITS entry has no `| CHAT:` line.
3. **Wrong note format**: The note is `[bug] Support AdX brands...` (agent's raw commit message) instead of
   `[crs (...)] Summary` (workflow-prefixed note matching other proposals).

## Root Causes

### Issue 1: `propose.yml` reads wrong field from `commit_result.json`

In `src/sase/xprompts/propose.yml:36`, the `propose` step reads:

```python
proposal_id = d.get('result', '') or ''
```

But `commit_result.json` has two distinct fields:

- `result`: VCS provider dispatch return value (for `create_proposal`, this is a diff path)
- `entry_id`: The actual proposal ID (e.g., `"5d"`)

The `_emit_proposal_id` step (line 70) already correctly reads `entry_id`, but `CrsWorkflow` (line 228-233) reads
`proposal_id` from the `propose` step output, which has the wrong value.

### Issue 2: `SASE_AGENT_CHAT_PATH` not set during agent execution

`CommitWorkflow._append_commits_entry()` (`workflow.py:454`) reads `SASE_AGENT_CHAT_PATH` for the chat path. In the CRS
background flow, the commit happens DURING `invoke_agent()` execution (via the commit stop hook), before the chat file
exists. The CRS runner only finds the chat file post-execution in the `finally` block, but by then the COMMITS entry is
already written.

Contrast: `fix_hook_runner.py:208-211` sets `SASE_AGENT_CHAT_PATH` before post-steps, but that works because fix-hook
commits happen in post-steps (after the agent), not during agent execution.

### Issue 3: No `[who]` prefix on proposal note

`CommitWorkflow._append_commits_entry()` (`workflow.py:447-452`) builds the note from the commit message first line with
no workflow prefix. There's no mechanism to inject the `[crs (...)]` identifier when the commit happens via the stop
hook.

Contrast: The interactive ACE flow uses `prompt_for_change_action()` (`change_actions.py:200-204`) which explicitly
builds `f"[{workflow_name}] {workflow_summary}"`.

## Fixes

### Fix 1: `src/sase/xprompts/propose.yml` — Read `entry_id` instead of `result`

**Line 36**: Change `d.get('result', '')` to `d.get('entry_id', '')`:

```yaml
- name: propose
  hidden: true
  if: "{{ check_changes.has_changes or _has_commit_result.exists }}"
  python: |
    import json, os
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
    result_file = os.path.join(artifacts_dir, "commit_result.json") if artifacts_dir else ""
    if result_file and os.path.isfile(result_file):
        with open(result_file) as f:
            d = json.load(f)
        print("success=true")
        print(f"proposal_id={d.get('entry_id', '') or ''}")
    else:
        print("success=false")
  output:
    success: bool
    proposal_id: word
```

**Impact check**: The `propose` step output is consumed by:

- `CrsWorkflow` (line 228-233): reads `proposal_id` — this is the broken path we're fixing
- `fix_hook_runner.py`: also reads from `ewf_result.context.get("propose", {})` — same fix applies there, and `entry_id`
  is the correct value since `CommitWorkflow` already writes the COMMITS entry

### Fix 2: `src/sase/workflows/crs.py` — Pre-set `SASE_AGENT_CHAT_PATH`

Before calling `invoke_agent()`, predict the chat path and set the env var. Chat files follow the naming pattern:
`~/.sase/chats/{branch_or_workspace}-{workflow}-{timestamp}.md`

The timestamp is already known (passed to `CrsWorkflow`). The branch is detectable. We can use
`_generate_chat_filename()` and `_get_chat_file_path()` from `sase.history.chat` to construct it:

```python
# Before invoke_agent():
from sase.history.chat import _generate_chat_filename, _get_chat_file_path
basename = _generate_chat_filename(workflow="crs", timestamp=self._timestamp)
predicted_chat_path = _get_chat_file_path(basename).replace(
    str(Path.home()), "~"
)
os.environ["SASE_AGENT_CHAT_PATH"] = predicted_chat_path
```

The file won't exist yet when the commit stop hook fires during `invoke_agent()`, but `add_proposed_commit_entry()` just
writes the path string — it doesn't check file existence. After `invoke_agent()` returns, the file WILL exist (created
by `postprocess_success()` or `_save_error_to_chat_history()`).

### Fix 3: `src/sase/workflows/commit/workflow.py` + `src/sase/workflows/crs.py` — `SASE_AGENT_WHO` env var

**a)** In `CommitWorkflow._append_commits_entry()`, when building the note for proposals, check for `SASE_AGENT_WHO` and
prepend `[{who}]`:

```python
def _append_commits_entry(self) -> str | None:
    ...
    note = (
        self._payload.get("note")
        or (self._payload.get("message", "").split("\n")[0])
        or "Manual changes"
    )

    # For proposals, prepend workflow identifier if available
    if self._method == "create_proposal":
        who = os.environ.get("SASE_AGENT_WHO")
        if who:
            note = f"[{who}] {note}"

    chat_path = os.environ.get("SASE_AGENT_CHAT_PATH")
    ...
```

**b)** In `CrsWorkflow.run()`, set `SASE_AGENT_WHO` before `invoke_agent()`:

```python
if self._who:
    os.environ["SASE_AGENT_WHO"] = self._who
```

The `who` is already built as `f"crs ({comments_ref})"` in `crs_runner.py:109-110`.

## Files Modified

| File                                    | Change                                                                    |
| --------------------------------------- | ------------------------------------------------------------------------- |
| `src/sase/xprompts/propose.yml`         | `propose` step: read `entry_id` instead of `result`                       |
| `src/sase/workflows/crs.py`             | Set `SASE_AGENT_CHAT_PATH` and `SASE_AGENT_WHO` before `invoke_agent()`   |
| `src/sase/workflows/commit/workflow.py` | `_append_commits_entry()`: prepend `SASE_AGENT_WHO` to note for proposals |

## Testing

- Run `just check` to verify lint/type/test pass
- Verify `propose.yml` change: the `entry_id` field is written by `_write_result_marker()` on the second call (after
  `_append_commits_entry()` returns), so `commit_result.json` will have the correct value when post-steps read it
- The `SASE_AGENT_WHO` env var is only checked for `create_proposal` method, so regular commits are unaffected
- The `SASE_AGENT_CHAT_PATH` prediction relies on the same timestamp being used by both the prediction and
  `invoke_agent()` — this is guaranteed since `self._timestamp` is passed to both
