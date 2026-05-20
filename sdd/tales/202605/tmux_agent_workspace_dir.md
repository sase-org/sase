---
create_time: 2026-05-20 18:27:53
status: done
prompt: sdd/prompts/202605/tmux_agent_workspace_dir.md
---
# Fix ACE agent tmux workspace resolution

## Problem

On the Agents tab, pressing `t` should open tmux in the focused agent's effective workspace. For the reported
`@sase-3s.5` agent, the detail panel correctly shows `Workspace: #10`, but the tmux window opens in the primary checkout
`/home/bryan/projects/github/sase-org/sase/` instead of `/home/bryan/projects/github/sase-org/sase_10/`.

The live artifacts show why:

- `workflow_state.json` / prompt step metadata expose `meta_workspace: "10"`, which is what the detail panel renders.
- `prompt_step_gh__setup.json` also records the actual allocated workspace directory:
  `/home/bryan/projects/github/sase-org/sase_10/`.
- `agent_meta.json` still has `workspace_dir: /home/bryan/projects/github/sase-org/sase/`, because the parent anonymous
  workflow was launched from the primary checkout before the embedded `#gh` setup allocated workspace `#10`.
- `_open_agent_tmux_window()` passes `agent.workspace_dir` as a first-choice hint to `resolve_agent_workspace_dir()`.
  That helper returns the hint immediately if the directory exists, so it never resolves `#10` through the workspace
  provider.

This creates a split-brain state: the UI says `#10`, while tmux trusts stale parent launch metadata and opens primary.

## Scope

This is an ACE TUI behavior bug. The workspace provider itself can already resolve managed workspace numbers, and the
runtime artifacts already contain enough information to identify the effective workspace. The narrow fix should stay in
Python/TUI workspace selection and tests unless investigation shows a shared backend contract is missing.

## Implementation Plan

1. Make agent tmux resolution prefer the effective workspace number for managed workspaces.
   - In `src/sase/ace/tui/actions/agents/_panel_tmux.py`, call `resolve_agent_workspace_dir()` without
     `agent.workspace_dir` when opening a non-primary workspace with a positive `effective_workspace_num`.
   - Keep the explicit directory hint for directory-mode/no-number agents, where `workspace_dir` is the only meaningful
     location.
   - Keep `T` behavior pinned to the primary workspace.

2. Improve fallback behavior without regressing directory-mode agents.
   - If provider resolution fails for a numbered workspace and the agent has a usable `workspace_dir`, allow the
     existing helper to fall back to it only when no numbered workspace can be resolved. This preserves useful behavior
     for incomplete metadata while preventing stale primary paths from winning over `#10`.

3. Add focused coverage for the reported case.
   - Add a unit test around `AgentPanelTmuxMixin._open_agent_tmux_window()` using an agent whose
     `step_output["meta_workspace"]` is `10` and whose `workspace_dir` is the primary checkout.
   - Assert the `tmux new-window -c` argument uses the provider-resolved managed workspace, not the stale
     `agent.workspace_dir`.
   - Add coverage that a directory-mode agent with `workspace_num` unset/zero still uses `agent.workspace_dir`.

4. Run verification.
   - Run the focused new test file/test cases first.
   - Because this repo requires it after source changes, run `just install` and then `just check`.
   - If broad checks fail for unrelated existing issues, report the exact failing stage and keep the focused regression
     coverage passing.

## Expected Outcome

Pressing `t` on an ACE agent whose detail panel shows `Workspace: #10` should create/select a tmux window rooted at the
workspace provider's path for `#10`, e.g. `/home/bryan/projects/github/sase-org/sase_10/`. Pressing `T` should continue
to open the primary project checkout.
