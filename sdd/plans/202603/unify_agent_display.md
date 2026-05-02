---
create_time: 2026-03-27 15:00:32
status: done
prompt: sdd/prompts/202603/unify_agent_display.md
---

# Plan: Unify Agent Display Across Run Modes

## Problem

When an agent is launched via `sase run` (inline execution), the TUI shows degraded information:

- **ChangeSpec: unknown** — `run_query()` passes `cl_name=None` to `claim_workspace()`
- **No prompt file found** — `run_query()` never writes `raw_xprompt.md`
- **Missing model/VCS/name** — `run_query()` never writes `agent_meta.json`
- **Disappears after completion** — `run_query()` never writes `done.json`, and `"run"` is not in the TUI's scanned
  workflow dirs

By contrast, `sase run --daemon` and TUI-launched agents go through `run_agent_runner.py` which writes all these files.
The inline `sase run` path bypasses the runner entirely.

## Root Cause

The inline `sase run` path (`_query.py:run_query()`) creates an artifacts directory and claims a workspace, but:

1. Passes `cl_name=None` to `claim_workspace()` (line 548)
2. Never writes `raw_xprompt.md` (daemon runner writes this at line 134 of `run_agent_runner.py`)
3. Never writes `agent_meta.json` (daemon runner calls `extract_directives_and_write_meta()`)
4. Never writes `done.json` on completion
5. `_DONE_AGENT_WORKFLOW_DIRS` in `_artifact_loaders.py` doesn't include `"run"`

## Implementation Plan

### Step 1: Pass `cl_name` to `claim_workspace()` in `run_query()`

**File**: `src/sase/main/query_handler/_query.py` (around line 542-550)

Currently:

```python
claim_workspace(project_file, workspace_num, "run", os.getpid(), None, artifacts_timestamp=artifacts_timestamp)
```

Change to resolve `cl_name` from the project context. The project name can be extracted from `project_file` path
(`~/.sase/projects/<project>/<project>.gp` → `<project>`). If a VCS project was resolved (stored in `vcs_project`), use
that instead.

```python
# Resolve cl_name from project context
cl_name = vcs_project  # From _resolve_vcs_cwd(), may be None
if cl_name is None and project_file:
    cl_name = Path(project_file).parent.name
claim_workspace(project_file, workspace_num, "run", os.getpid(), cl_name, artifacts_timestamp=artifacts_timestamp)
```

Also update the `release_workspace()` call at line 581 to pass the same `cl_name`.

### Step 2: Write `raw_xprompt.md` before execution

**File**: `src/sase/main/query_handler/_query.py` (after artifacts_dir creation, before `execute_workflow()`)

Add immediately after the artifacts directory is created (around line 539):

```python
# Save raw prompt for TUI display (matches daemon runner behavior)
if artifacts_dir:
    raw_xprompt_path = os.path.join(artifacts_dir, "raw_xprompt.md")
    with open(raw_xprompt_path, "w", encoding="utf-8") as f:
        f.write(query)
```

This must use the original `query` (before the `full_prompt` transformation that adds previous_history), matching how
the daemon runner saves the raw prompt before preprocessing.

### Step 3: Write `agent_meta.json` before execution

**File**: `src/sase/main/query_handler/_query.py` (after writing raw_xprompt.md)

Write a minimal `agent_meta.json` so the TUI can display model/provider info:

```python
if artifacts_dir:
    from sase.llm_provider import get_default_model_and_provider
    from sase.xprompt._directives import extract_directives

    # Extract directives from query (e.g., %model:opus)
    directives = extract_directives(full_prompt)
    model, llm_provider = get_default_model_and_provider(directives)

    from sase.vcs_provider import detect_vcs_provider
    vcs_provider = detect_vcs_provider()

    agent_meta = {
        "pid": os.getpid(),
        "model": model,
        "llm_provider": llm_provider,
        "vcs_provider": vcs_provider,
    }
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(agent_meta, f, indent=2)
```

**Note**: Need to verify the exact APIs for `get_default_model_and_provider()` and `detect_vcs_provider()` — these may
have different signatures. The daemon runner uses `extract_directives_and_write_meta()` from `run_agent_phases.py`, but
that function does more than we need (workspace preparation, name generation, etc.). We should either:

- (a) Extract a lighter helper from it, or
- (b) Call it directly if it's safe for the inline context

Option (b) is preferred if the function doesn't have side effects beyond writing the file. Need to check
`extract_directives_and_write_meta()` more carefully to determine this.

### Step 4: Write `done.json` on completion

**File**: `src/sase/main/query_handler/_query.py` (after `execute_workflow()` returns, before `release_workspace()`)

After the workflow execution completes, write a `done.json` marker so the agent appears in the TUI's completed agents
list:

```python
if artifacts_dir:
    done_marker = {
        "cl_name": cl_name or "unknown",
        "project_file": project_file,
        "timestamp": shared_timestamp,
        "artifacts_timestamp": artifacts_timestamp,
        "outcome": "completed",
        "workspace_num": workspace_num,
    }
    # Add model/provider if we wrote agent_meta
    if os.path.exists(os.path.join(artifacts_dir, "agent_meta.json")):
        with open(os.path.join(artifacts_dir, "agent_meta.json")) as f:
            meta = json.load(f)
        done_marker.update({
            "model": meta.get("model"),
            "llm_provider": meta.get("llm_provider"),
            "vcs_provider": meta.get("vcs_provider"),
        })
    # Add response path if available from result
    if result and result.response_text:
        response_path = os.path.join(artifacts_dir, "response.md")
        with open(response_path, "w", encoding="utf-8") as f:
            f.write(result.response_text)
        done_marker["response_path"] = response_path

    done_path = os.path.join(artifacts_dir, "done.json")
    with open(done_path, "w", encoding="utf-8") as f:
        json.dump(done_marker, f, indent=2)
```

Also handle the error case — if `execute_workflow()` raises an exception, write `done.json` with `"outcome": "failed"`
and the error details. This matches the daemon runner's error handling.

### Step 5: Add `"run"` to `_DONE_AGENT_WORKFLOW_DIRS`

**File**: `src/sase/ace/tui/models/_loaders/_artifact_loaders.py` (line 234)

```python
_DONE_AGENT_WORKFLOW_DIRS = [
    "ace-run",
    "run",        # <-- ADD THIS
    "fix-hook",
    "crs",
    "summarize-hook",
]
```

This ensures the TUI scans `~/.sase/projects/*/artifacts/run/*/done.json` for completed inline agents.

### Step 6: Verify `get_artifacts_dir()` handles workflow="run"

**File**: `src/sase/ace/tui/models/agent.py` (lines 371-397)

The current code has workflow="run" fall through to `workflow_name = workflow` (line 397), which correctly resolves to
`~/.sase/projects/<project>/artifacts/run/<timestamp>/`. No change needed here.

## Verification Steps

1. Run `sase run "hello"` and check TUI shows proper ChangeSpec, prompt, and model info
2. Run `sase run --daemon "hello"` and verify it still works as before
3. Launch agent from TUI and verify no regression
4. Verify completed `sase run` agents appear in the TUI Agents tab
5. Run `just check` to ensure no lint/type errors

## Files Modified

1. `src/sase/main/query_handler/_query.py` — Steps 1-4 (main changes)
2. `src/sase/ace/tui/models/_loaders/_artifact_loaders.py` — Step 5 (add "run" to workflow dirs)

## Risks

- **Step 3 (agent_meta.json)**: Need to verify the model/provider detection APIs work outside the daemon runner context.
  The inline `sase run` path may not have all the same environment variables set.
- **Step 4 (done.json)**: The `WorkflowResult` object from `execute_workflow()` may not expose response text in the same
  way as the daemon runner. Need to check the return type.
- **Step 5 (scanning "run" dir)**: If users have many old `sase run` artifacts without `done.json`, the scan will
  harmlessly skip them (it only loads dirs containing `done.json`).
