---
create_time: 2026-05-06 13:22:13
status: done
prompt: sdd/prompts/202605/github_xprompt_workspace_fallback.md
---
# Plan: Fix GitHub xprompt workspace fallback

## Problem

Agents launched from `#gh:sase` can silently run as `Git (bare)` with workspace `#0` when the launching Python
environment does not have the `sase-github` plugin installed. The observed bad agent (`pysplit.mobile_notifications`,
PID 774085) was spawned by `/home/bryan/projects/github/sase-org/sase_100/.venv/bin/python3`, whose entry points include
only the core `git` and `cd` workspace providers. In that process, `#gh:sase` could not resolve through the GitHub
workspace provider, so `launch_agent_from_cwd()` used the generic known-project fallback:

- `project_file` was resolved to `~/.sase/projects/sase/sase.gp`
- `workspace_dir` was set to the primary checkout
- `workspace_num` was set to `0`
- `update_target` stayed empty, so normal workspace preparation was skipped

The child also inherited stale `SASE_GH_PRE_ALLOCATED` values from the parent workflow, which is unsafe for nested
launches.

## Approach

1. Preserve the intended safety of the known-project fallback, but make it allocate a real numbered workspace for known
   project refs such as `#gh:sase` when the requested workflow plugin is absent.

2. Give known-project fallback launches the normal VCS default update target so the runner prepares the allocated
   workspace instead of running directly in the primary checkout.

3. Scrub inherited `SASE_*_PRE_ALLOCATED`, `SASE_*_WORKSPACE_NUM`, and `SASE_*_WORKSPACE_DIR` environment variables
   before applying the launch-specific preallocation env. This prevents nested launches from accidentally reusing their
   parent workflow workspace.

4. Add focused regression tests:
   - `#gh:sase` known-project fallback allocates a real workspace instead of workspace `0`
   - launch env scrubbing removes stale preallocation values and keeps the current launch values

5. Run targeted tests first, then `just check` because this repo requires it after source changes.

## Expected Outcome

Plugin-less `#gh:sase` launches will no longer appear as unassigned workspace `#0` agents. They will claim a numbered
workspace and prepare it before running. When the GitHub plugin is available in the runner environment, VCS metadata
will continue to show `GitHub`; if the environment truly lacks the plugin everywhere, the agent will still have an
isolated workspace rather than mutating the primary checkout.
