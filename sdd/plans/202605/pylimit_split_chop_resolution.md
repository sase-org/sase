---
create_time: 2026-05-01 12:55:43
status: done
prompt: sdd/prompts/202605/pylimit_split_chop_resolution.md
---
# Plan: Make the `sase_pylimit_split` chop resolve the real workflow reliably

## Problem

The live `sase_pylimit_split` chop is launching a normal home-directory LLM agent instead of executing the
`sase/pylimit_split` standalone workflow.

Evidence:

- The snapshot shows the raw xprompt as `#cd:~ #gh:sase #!sase/pylimit_split %approve`, while the agent prompt still
  contains `#gh:sase #!sase/pylimit_split`.
- The live chop registry records the chop under `project_name=home`, `workspace_num=0`, and `cl_name=~`.
- The live lumberjack process is running from `/home/bryan/projects/github/sase-org/sase_102/.venv/bin/sase`.
- That venv only exposes the built-in `bare_git` and `cd` workspace providers; it does not expose the `sase-github`
  plugin, so `#gh:sase` is not recognized.
- When `#gh:sase` is not recognized, SASE's default workspace normalization adds `#cd:~`. From `~`, the repo-local
  `xprompts/pylimit_split.yml` workflow is not discoverable, so the standalone workflow reference falls through to an
  ordinary LLM agent.

## Root Cause

The chezmoi chop config depends on the `#gh:sase` workspace provider to move the agent into the SASE repo before
resolving `#!sase/pylimit_split`. That dependency is brittle for recurring axe chops because axe can be started from a
local SASE development venv that does not have the `sase-github` plugin installed. In that case, the prompt silently
runs from `~` and the workflow is not found.

## Fix

Make the `sase_pylimit_split` chop use the built-in `#cd` workspace provider and an absolute path to the primary SASE
checkout:

```yaml
agent: "#cd:/home/bryan/projects/github/sase-org/sase #!sase/pylimit_split %approve"
```

This avoids the optional GitHub plugin for this infrastructure chop while still using the existing `sase/pylimit_split`
xprompt workflow. It is intentionally limited to `sase_pylimit_split`; the other refresh-docs chops still need GitHub
repo resolution across multiple repos.

## Implementation Steps

1. Update the chezmoi source config at `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`.
2. Keep the applied config in sync by running `chezmoi apply --force` after the edit.
3. Run `just check` in the chezmoi repo, per local memory.
4. Validate the prompt resolution from the current `sase_102` venv, because that is the environment that reproduced the
   bug.
5. Note that the running axe lumberjack must be restarted to pick up the changed config; changing chezmoi does not
   mutate an already-running process.

## Verification

- Confirm the applied config contains the `#cd:/home/bryan/projects/github/sase-org/sase` prompt.
- In the `sase_102` venv, monkeypatch `launch_agent_from_cwd`'s spawn function and verify the prompt resolves to
  `workspace_dir=/home/bryan/projects/github/sase-org/sase`.
- From `/home/bryan/projects/github/sase-org/sase`, run the real workflow foreground with
  `sase run '#!sase/pylimit_split'` or the repo venv equivalent and verify it reports `launched=0` when no files exceed
  the pylimit threshold.
