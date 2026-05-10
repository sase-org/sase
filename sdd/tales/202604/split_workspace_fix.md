---
create_time: 2026-04-03 13:23:59
status: wip
prompt: sdd/prompts/202604/split_workspace_fix.md
---

# Plan: Fix `#split` xprompt workflow workspace setup

## Problem

The `#split` workflow's setup step (`sase_split_setup`) calls `retired_mercurial_plugin_update` to navigate to the target CL branch,
but this fails because:

1. No workspace has been claimed in the RUNNING field
2. The workflow executor hasn't `cd`'d into a Mercurial workspace directory (no `_chdir` output)
3. So `retired_mercurial_plugin_update` → `hg update` fails because the cwd isn't an hg workspace

The `#hg` workflow handles this correctly: its setup step (`hg_setup.py`) claims a workspace, prints
`_chdir=workspace_dir`, and subsequent steps run inside the workspace. The `#split` workflow needs equivalent logic.

## Constraint

Workspace claim/release must happen exactly once. Since `#split` is a standalone workflow (not wrapped by `#hg`), the
claiming and releasing should happen directly in `#split`. The `split_executor` agent step runs commands
(`retired_mercurial_plugin_update`, `sase commit`) directly in the workspace — it doesn't invoke `#hg` — so there's no double-claim
risk.

## Changes

### 1. `retired Mercurial plugin: sase_split_setup` — Add workspace claiming + `_chdir`

**File:** `src/retired_mercurial_plugin/scripts/sase_split_setup`

Add workspace claiming logic at the top of `main()`, before the existing `retired_mercurial_plugin_update` call:

- Support pre-allocated workspaces (`SASE_HG_PRE_ALLOCATED` env var) — same as `hg_setup.py`
- Otherwise, atomically claim the next available axe workspace via `claim_next_axe_workspace`
- Resolve the workspace directory via `get_workspace_directory_for_num`
- Print `_chdir=workspace_dir` so the executor changes cwd **before** `retired_mercurial_plugin_update` runs
- Use `os.getppid()` for the PID (same rationale as `hg_setup.py` — this script is a short-lived subprocess)
- Resolve the project via `resolve_ref(cl_name, "hg")`

New outputs to add: `workspace_num`, `project_file`, `should_release`, `workflow_name`.

The `_chdir` must be printed **before** calling `retired_mercurial_plugin_update`, since the executor processes `_chdir` as it parses
output, changing cwd for subsequent commands within the same step.

**Wait — actually, `_chdir` is processed after the step completes (the executor parses all output after the subprocess
exits).** So instead, the `sase_split_setup` script should `os.chdir(workspace_dir)` itself before calling
`retired_mercurial_plugin_update`. The `_chdir` output will then ensure subsequent workflow steps also run in the workspace.

### 2. `retired Mercurial plugin: split.yml` — Add outputs + release step

**File:** `src/retired_mercurial_plugin/xprompts/split.yml`

- Add `workspace_num`, `project_file`, `should_release`, `workflow_name` to the setup step's `output` block
- Add a final `release` step (after `execute_revert`) that releases the workspace, conditional on
  `setup.should_release`:
  ```yaml
  - name: release
    if: "{{ setup.should_release }}"
    python: |
      from sase.running_field import release_workspace
      release_workspace(
          {{ setup.project_file | tojson }},
          {{ setup.workspace_num }},
          {{ setup.workflow_name | tojson }},
          {{ setup.cl_name | tojson }},
      )
      print("released=true")
    output: { released: bool }
  ```
  This mirrors the release step in `hg.yml`.
