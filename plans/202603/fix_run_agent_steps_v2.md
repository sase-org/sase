---
create_time: 2026-03-29 17:33:13
status: done
---
# Fix: `sase run` agents show no workflow steps in TUI (v2)

## Problem

After the previous fix (writing initial `workflow_state.json` in `run_agent_runner.py`), agents launched via `sase run` still show no workflow steps in the TUI. The agent shows as `[agent] (RUNNING)` with no step count and "Workflow: run" instead of the actual workflow name.

## Root Causes

There are two distinct root causes that the previous fix missed:

### Root Cause 1: TUI workflow scanner doesn't scan `run/` artifacts directory

The `sase run` CLI (inline) path creates artifacts in `~/.sase/projects/<project>/artifacts/run/<timestamp>/`. The TUI's `_iter_workflow_timestamp_dirs()` in `_workflow_loaders.py` (line 49-53) only scans directories matching `workflow-*` or `ace-run`:

```python
if not (
    workflow_dir.name.startswith("workflow-")
    or workflow_dir.name == "ace-run"
):
    continue
```

It does NOT scan `run/`. So `workflow_state.json` files written by WorkflowExecutor in `run/<timestamp>/` are completely invisible to the TUI. No WORKFLOW entry is ever created for inline `sase run` agents.

### Root Cause 2: `dedup_running_vs_workflow()` doesn't match workflow name `"run"`

Even if the TUI did scan `run/`, the dedup function in `_dedup.py` (line 264) only matches:
```python
agent.workflow.startswith("ace(run)") or agent.workflow == "ace-run"
```

The inline `sase run` path claims workspace with workflow name `"run"` (see `_query.py` line 603), which matches neither pattern. So the RUNNING entry would never be replaced by the WORKFLOW entry.

### Root Cause 3 (minor): Race between parent and child for ace TUI agents

For ace TUI agents (launched via `launcher.py` → `run_agent_runner.py`), the workspace claim happens in the parent process while the initial `workflow_state.json` is written in the child process. There's still a small race window during child startup. The fix should move the initial write to the parent.

## Evidence

Tracing the data flow:

**Inline `sase run` (`_query.py`):**
- `create_artifacts_directory("run")` → `~/.sase/projects/<project>/artifacts/run/<ts>/`
- `claim_workspace(..., "run", ...)` → RUNNING field entry with workflow="run"
- WorkflowExecutor writes `workflow_state.json` in `run/<ts>/`
- TUI scans `ace-run/` and `workflow-*/` — skips `run/`
- No WORKFLOW entry created → no dedup → RUNNING entry persists
- Result: `[agent] (RUNNING)` with no step count

**Ace TUI agents (`launcher.py` → `run_agent_runner.py`):**
- `create_artifacts_directory("ace-run", ...)` → `~/.sase/projects/<project>/artifacts/ace-run/<ts>/`
- `claim_workspace(..., "ace(run)-<ts>", ...)` in parent process
- Child process writes initial `workflow_state.json` after startup delay
- TUI scans `ace-run/` — finds `workflow_state.json` (if child has started)
- Dedup matches `ace(run)` prefix → RUNNING replaced by WORKFLOW
- Result: works correctly AFTER child starts, but brief flicker during startup

## Fix

### Phase 1: Add `"run"` to TUI workflow scanner

**File: `src/sase/ace/tui/models/_loaders/_workflow_loaders.py`**

In `_iter_workflow_timestamp_dirs()` (line 49-53), add `"run"` to the directory name check:

```python
if not (
    workflow_dir.name.startswith("workflow-")
    or workflow_dir.name == "ace-run"
    or workflow_dir.name == "run"
):
    continue
```

This allows the TUI to read `workflow_state.json` from `run/<timestamp>/` directories, creating WORKFLOW entries for inline `sase run` agents.

### Phase 2: Add `"run"` to `dedup_running_vs_workflow()` pattern

**File: `src/sase/ace/tui/models/_dedup.py`**

In `dedup_running_vs_workflow()` (line 264), add `"run"` to the workflow name match:

```python
and (agent.workflow.startswith("ace(run)") or agent.workflow in {"ace-run", "run"})
```

This allows inline `sase run` RUNNING entries to be deduped against their WORKFLOW counterparts.

### Phase 3: Move initial `workflow_state.json` write to parent process

**File: `src/sase/agent/launcher.py`**

In `spawn_agent_subprocess()`, after spawning the child process (line 122) and before claiming workspace (line 130), write an initial `workflow_state.json` in the parent process. This eliminates the race condition entirely for ace TUI agents and `sase run -d`.

The parent already has all needed values:
- `artifacts_timestamp` (line 128)
- `project_name` parameter
- `process.pid` from subprocess.Popen
- `cl_name` parameter

Compute `artifacts_dir` as `~/.sase/projects/{project_name}/artifacts/ace-run/{artifacts_timestamp}/`, create the directory, and write the initial `workflow_state.json`.

For home mode agents, use `project_name = "home"` (already handled by the caller).

**Remove the duplicate write from `run_agent_runner.py`** (lines 122-137) since the parent now handles it. Keep the write in `run_agent_helpers.py` for follow-up agents (they're created by the child process, not the parent).

## Files to modify

1. `src/sase/ace/tui/models/_loaders/_workflow_loaders.py` — add `"run"` to directory filter
2. `src/sase/ace/tui/models/_dedup.py` — add `"run"` to `dedup_running_vs_workflow()` pattern
3. `src/sase/agent/launcher.py` — write initial `workflow_state.json` in parent process
4. `src/sase/axe/run_agent_runner.py` — remove now-redundant initial `workflow_state.json` write

## Risks

- Adding `"run"` to the scanner means more directories scanned during TUI refresh. However, `load_done_agents()` already scans `run/` for `done.json`, so the incremental cost is minimal.
- For completed inline runs, both `done.json` and `workflow_state.json` produce entries. The dedup pipeline handles this correctly — `dedup_running_vs_workflow` merges the RUNNING(DONE) entry from done.json into the WORKFLOW(DONE) entry from workflow_state.json.
