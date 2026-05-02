---
create_time: 2026-05-01 17:48:06
status: done
prompt: sdd/prompts/202605/known_project_xprompt_launch.md
---
# Plan: Fix known-project VCS xprompt launch resolution

## Problem

Agent chops such as `#gh:sase #!sase/fix_just` can launch as ordinary `home` agents instead of resolving and running the
repo-local `sase/fix_just` workflow. The live snapshot shows exactly that shape: `Project: home`, raw prompt
`#gh:sase #!sase/fix_just`, and an LLM reply rather than workflow step artifacts.

## Diagnosis

Current code has a partial fallback for missing VCS workspace providers:

- `normalize_default_vcs_workflow()` recognizes `#gh:sase` as a known project ref even when the `gh` provider is not
  installed, so it avoids prepending `#cd:~`.
- `get_all_workflows(project="sase")` can load repo-local workflows from the known primary checkout recorded in
  `~/.sase/projects/sase/sase.gp`.
- Foreground `sase run` has `_resolve_vcs_cwd()` and changes into that known checkout before workflow execution.

The broken path is background launch through `launch_agent_from_cwd()`, used by axe agent chops. When only built-in
providers such as `cd` and `git` are registered, `#gh:sase` is preserved but not resolved. The launcher falls through to
home mode and spawns:

- `project_file = ~/.sase/projects/home/home.gp`
- `project_name = home`
- `workspace_dir = ~`
- `workspace_num = 0`
- `is_home_mode = True`
- `vcs_ref = None`

That means the runner starts in `~`, writes home artifacts, and cannot reliably discover `xprompts/fix_just.yml` as a
repo-local workflow.

## Root Cause

Known-project VCS fallback is implemented in parsing and foreground query execution, but not in the shared background
agent launch context. Avoiding `#cd:~` is not sufficient; the launcher must also resolve the known project ref into the
target project file, project name, and checkout directory before spawning the agent runner.

## Implementation Plan

1. Add a focused launcher helper for known-project VCS refs.
   - Input: the normalized prompt.
   - Use `extract_known_project_vcs_ref()` plus `get_known_project_workspaces()`.
   - Return the workflow type, ref/project name, primary workspace path, and `~/.sase/projects/<project>/<project>.gp`.
   - Keep the helper narrow: it only handles refs where the ref is a known project, not arbitrary branch/changespec refs
     that require a real provider.

2. Apply that helper in `launch_agent_from_cwd()` after normal registered-provider resolution fails.
   - Set `project_file` to the known project `.gp`.
   - Set `project_name`, `cl_name`, and `history_sort_key` to the known project ref.
   - Set `workspace_dir` to the known primary checkout.
   - Set `workspace_num = 0`, `update_target = ""`, and `is_home_mode = False`.
   - Preserve the original prompt, including `#gh:sase`, so runner artifacts and xprompt expansion still see the user’s
     actual prompt.
   - Set `vcs_ref = (workflow_type, ref)` even when no preallocation env prefix exists, so downstream metadata and
     launch records know the prompt had an explicit VCS/project selector.

3. Make the same fallback available in the TUI launch body if needed.
   - The immediate axe chop bug is `launch_agent_from_cwd()`, but the TUI has a similar “known ref but home context”
     branch.
   - If the existing TUI workflow dispatch already handles project-local workflow execution through `project=...`, keep
     the change scoped to background launch. Otherwise update TUI context resolution consistently.

4. Add regression tests.
   - Update `test_launch_agent_from_cwd_known_project_ref_without_provider_is_not_home_wrapped` so it asserts the known
     project checkout is used instead of `~`.
   - Assert `project_name == "sase"`, `project_file` points at the known project gp file, `workspace_dir` is the known
     checkout, `workspace_num == 0`, `is_home_mode is False`, `vcs_ref == ("gh", "sase")`, and the prompt is unchanged.
   - Add or update a test that `#!sase/fix_just` is still discoverable from another CWD via
     `get_all_workflows(project)`.

5. Verify locally.
   - Reproduce the launch-plan behavior with a mocked `spawn_agent_subprocess`.
   - Run the focused launcher/xprompt tests.
   - Run `just install` first if the venv is stale, then `just check` before finishing because this repo requires it
     after changes.

## Expected Outcome

`#gh:sase #!sase/fix_just` launched from an environment without the GitHub workspace provider will run from the known
SASE checkout and be recorded under the `sase` project, allowing the standalone repo-local workflow to flatten and
execute instead of falling through to a home LLM prompt.
