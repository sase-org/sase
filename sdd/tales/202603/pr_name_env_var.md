---
create_time: 2026-03-25 16:43:12
status: done
prompt: sdd/prompts/202603/pr_name_env_var.md
---

# Plan: Add `SASE_NAME` env var to `pr.yml` and enforce CL naming in stop hook

## Problem

When the `#pr` workflow is used with a `name` argument (e.g., `#pr:foobar`), the agent ignores it and invents its own CL
name (e.g., `add_foobar_field`). This happens because:

1. The `#pr` workflow sets `SASE_COMMIT_METHOD=create_pull_request` in the environment, but does NOT propagate the
   `name` input to the environment.
2. When the `sase_commit_stop_hook` fires and instructs the agent to commit, it tells the agent to use the commit skill
   but says nothing about which name to use.
3. The agent independently picks a name based on its changes.

## Solution

### Step 1: Add `SASE_NAME` to `pr.yml` environment

**File:** `src/sase/xprompts/pr.yml`

Add `SASE_NAME: "{{ name }}"` to the `environment` block:

```yaml
environment:
  SASE_COMMIT_METHOD: create_pull_request
  SASE_BUG_ID: "{{ bug_id }}"
  SASE_NAME: "{{ name }}"
```

This makes the user-provided name available as an env var for the stop hook to read.

### Step 2: Update `sase_commit_stop_hook.py` to include name instruction

**File:** `src/sase/scripts/sase_commit_stop_hook.py`

In the `main()` function, after building `commit_instruction` (~line 249), read `SASE_NAME` and
`SASE_AGENT_PROJECT_FILE` from the environment. If `SASE_NAME` is set:

1. Derive the project name from `SASE_AGENT_PROJECT_FILE` — the project file path is like
   `~/.sase/projects/eval/eval.gp`, so `Path(project_file).stem` gives us `eval`.
2. Append a name instruction to `commit_instruction` that says:
   - The `name` field in the commit payload MUST be set to the value of `SASE_NAME`.
   - The name MUST begin with `<project>_` (where `<project>` is the derived project name).

Concretely, add a helper function:

```python
def _build_name_instruction() -> str | None:
    sase_name = os.environ.get("SASE_NAME")
    if not sase_name:
        return None
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE", "")
    project = Path(project_file).stem if project_file else ""
    parts = [f'You MUST include "name": "{sase_name}" in your commit JSON payload.']
    if project:
        parts.append(f'The name MUST begin with "{project}_".')
    return " ".join(parts)
```

Then in `main()`, append this to `commit_instruction` if non-None.

### Step 3: Also add `SASE_NAME` to `commit.yml` and `propose.yml` environments

For consistency (in case agents use `#commit:name` or `#propose:name` in the future), we should check whether these
workflows also accept a `name` input. Currently they do NOT have a `name` input, so **no changes needed** for
`commit.yml` and `propose.yml`.

## Files to modify

1. `src/sase/xprompts/pr.yml` — Add `SASE_NAME` to environment block
2. `src/sase/scripts/sase_commit_stop_hook.py` — Read `SASE_NAME` + `SASE_AGENT_PROJECT_FILE`, build and append naming
   instruction to the commit instruction emitted to the agent

## Testing

- Verify `just lint` passes (ruff + mypy)
- Verify `just test` passes
- Manual verification: run an agent with `#pr:foobar` and confirm the stop hook output includes the name instruction
  with proper `<project>_` prefix requirement
