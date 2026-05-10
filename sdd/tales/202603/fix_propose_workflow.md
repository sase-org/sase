---
create_time: 2026-03-26 15:26:15
status: done
prompt: sdd/prompts/202603/fix_propose_workflow.md
---

# Plan: Fix fix-hook proposal creation

## Problem Statement

Three related bugs in the fix-hook agent's `#propose` workflow:

1. **Hook suffix shows CL URL instead of entry ID** — The `(6d)` entry's hook status line shows
   `(http://cl/878602590 | deal_check_line_chart_test failed remotely (exit code 3).)` instead of just `(6d)`.
2. **Missing CHAT and DIFF drawers** — The `(6d)` entry is missing its CHAT and DIFF sub-fields that other proposals
   (6a-6c) have.
3. **Propose workflow commits to CL** — The `#propose` workflow amends the CL via `vcs_create_proposal` when it should
   only save a diff file for later application by the user.

## Root Cause Analysis

### Bug 1: CL URL as proposal_id

**Flow:** `fix_hook_runner.py:228-233` reads `proposal_id` from the `propose` step's context output. The `propose` step
in `propose.yml:36-37` outputs `proposal_id={d.get('result', '')}` from `commit_result.json`. For the Hg plugin,
`vcs_create_proposal` returns `http://cl/<number>` as the result. So `proposal_id` becomes the CL URL instead of the
entry ID like `6d`.

The `_append_entry` step does correctly produce `entry_id=6d`, but `fix_hook_runner.py` never reads from that step's
output.

### Bug 2: Missing CHAT and DIFF drawers

**Flow:** `_append_entry` calls `append_post_commit_entry(mode="proposal")` (`post_commit.py:53`), which uses
`_find_best_diff_path()` and `_find_best_response_path()` to scan `prompt_step_*.json` markers in the artifacts
directory. For the fix-hook flow, no `prompt_step_*.json` markers exist (the fix-hook runner doesn't write them), so
both `diff_path` and `response_path` are `None`. The entry is created without CHAT or DIFF sub-fields.

### Bug 3: Propose workflow commits to CL

**Flow:** The `propose` step's fallback path (`propose.yml:40-44`) creates `CommitWorkflow(method="create_proposal")`,
which dispatches to `vcs_create_proposal` on the HgPlugin (`retired Mercurial plugin/plugin.py:368`). The HgPlugin's
`vcs_create_proposal` calls `vcs_create_commit` (which runs `retired_mercurial_plugin_amend` — amending the CL), then cleans the
workspace with `hg update --clean`. This pushes the agent's changes to the CL.

The same bug exists for the stop-hook path: if the commit stop hook fires during a `#propose` workflow, it tells the
agent to use the commit skill, which also calls `CommitWorkflow(create_proposal)` → `vcs_create_proposal` → amends CL.

Contrast with the correct flow in `change_actions.py:178-224` (TUI interactive proposals): `save_diff()` →
`add_proposed_commit_entry()` → `clean_workspace()`. This saves a diff file without amending the CL.

## Changes

### 1. `../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py` — Save diff instead of amending CL

Change `vcs_create_proposal` to save a diff file and clean the workspace instead of amending the CL. This fixes both the
background-agent (propose.yml) and stop-hook paths, since both dispatch through `CommitWorkflow` → VCS provider.

```python
@hookimpl
def vcs_create_proposal(self, payload: dict, cwd: str) -> tuple[bool, str | None]:
    """Save diff and clean — proposal saves changes without amending the CL."""
    from sase.workflows.commit_utils.workspace import save_diff, clean_workspace

    cl_name = payload.get("name", "") or payload.get("_cl_name", "")
    diff_path = save_diff(cl_name, target_dir=cwd)
    if not diff_path:
        return (False, "No changes to save as proposal diff")

    # Clean workspace (revert local changes)
    clean_workspace(cwd)

    return (True, diff_path)
```

This returns the diff file path (e.g. `~/.sase/diffs/pat_line_chart_component-260326_143258.diff`) instead of the CL
URL.

### 2. `src/sase/workflows/commit_utils/post_commit.py` — Add fallbacks for diff_path and response_path

Update `append_post_commit_entry` to:

- **diff_path fallback**: If `_find_best_diff_path()` returns None, check `commit_result.json` for a `result` field that
  looks like a diff path (ends with `.diff`).
- **response_path fallback**: If `_find_best_response_path()` returns None, check `SASE_AGENT_CHAT_PATH` env var.

```python
# After existing diff_path lookup
diff_path = _find_best_diff_path(artifacts_dir)
if not diff_path:
    # Fallback: check commit_result.json result if it's a diff path
    result_value = commit_result.get("result", "") or ""
    if result_value.endswith(".diff"):
        diff_path = result_value

# After existing response_path lookup
response_path = _find_best_response_path(artifacts_dir)
if not response_path:
    # Fallback: check SASE_AGENT_CHAT_PATH env var
    response_path = os.environ.get("SASE_AGENT_CHAT_PATH")
```

### 3. `src/sase/axe/fix_hook_runner.py` — Use entry_id and set chat path env var

Two changes:

**a) Set `SASE_AGENT_CHAT_PATH` before running post-steps** (after the agent runs, the chat file exists):

```python
# After line 206 (os.environ["SASE_AGENT_PROJECT_FILE"] = project_file)
chat_path = find_chat_by_timestamp(timestamp)
if chat_path:
    os.environ["SASE_AGENT_CHAT_PATH"] = chat_path
```

**b) Prefer `_append_entry.entry_id` over `propose.proposal_id`** for the `proposal_id` used in the hook suffix:

After the post-steps loop (line 226), add:

```python
# Prefer entry_id from _append_entry (correct entry ID like "6d")
# over proposal_id from propose (which may be a CL URL or diff path)
append_result = ewf_result.context.get("_append_entry", {})
if isinstance(append_result, dict) and append_result.get("entry_id"):
    proposal_id = append_result["entry_id"]
    exit_code = 0
```

### 4. `src/sase/xprompts/propose.yml` — Pass `cl_name` to CommitWorkflow payload

The HgPlugin's updated `vcs_create_proposal` needs the CL name to generate the diff filename. The CommitWorkflow payload
should include it. Update the propose step's fallback `CommitWorkflow` call:

```python
# In the propose step, pass cl_name for diff naming
cl_name = os.environ.get("SASE_AGENT_CL_NAME", "")
wf = CommitWorkflow(
    payload={"message": f"[{who}] Agent changes", "_cl_name": cl_name},
    method=method,
)
```

## Files Modified

| File                                             | Repo        | Change                                                                      |
| ------------------------------------------------ | ----------- | --------------------------------------------------------------------------- |
| `../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py`       | retired Mercurial plugin | `vcs_create_proposal`: save diff + clean instead of amend + clean           |
| `src/sase/workflows/commit_utils/post_commit.py` | sase_101    | `append_post_commit_entry`: add diff_path and response_path fallbacks       |
| `src/sase/axe/fix_hook_runner.py`                | sase_101    | Set `SASE_AGENT_CHAT_PATH`; prefer `_append_entry.entry_id` for proposal_id |
| `src/sase/xprompts/propose.yml`                  | sase_101    | Pass `_cl_name` in CommitWorkflow payload                                   |

## Testing

- `just check` in sase_101 repo for lint + tests
- Verify `sase ace --agent` displays entries correctly (if fixture data available)
- Manual verification: run a fix-hook agent on a Google/Hg workspace and confirm:
  - Changes are saved as a diff file, NOT amended to the CL
  - The COMMITS entry shows the correct `(Nd)` format with CHAT and DIFF drawers
  - The hook status line shows `(Nd)` not a CL URL
