---
create_time: 2026-05-01 14:40:52
status: done
prompt: sdd/prompts/202605/fix_vcs_project_workflows.md
---
# Plan: Resolve VCS-scoped standalone workflows from the target project

## Problem

The `sase_fix_just` chop is configured as:

```text
#gh:sase #!sase/fix_just
```

but the live agent snapshot shows the stored xprompt as:

```text
#cd:~ #gh:sase #!sase/fix_just
```

That means SASE treated the prompt as having no recognized workspace tag, injected the default home-directory `#cd:~`
wrapper, and then ran a normal home-mode agent. From `~`, the repo-local `xprompts/fix_just.yml` workflow is not
discoverable, so `#!sase/fix_just` remains text instead of executing the standalone workflow.

A previous `sase_pylimit_split` fix worked around the same class of failure by changing that chop to:

```text
#cd:/home/bryan/projects/github/sase-org/sase #!sase/pylimit_split %approve
```

That avoids the failure, but it is a config-level workaround. The real invariant should be: if a prompt contains a VCS
project ref such as `#gh:sase`, standalone workflows defined by the `sase` repo should resolve even when the launcher is
currently running from `~` or another SASE workspace clone.

## Root Cause

Workflow lookup is still too dependent on the current process CWD and the set of installed workspace-provider plugins.

The relevant paths are:

- `normalize_default_vcs_workflow()` only recognizes registered workspace providers. If a process can see `cd` but not
  `gh`, `#gh:sase` is not treated as a workspace ref, so `#cd:~` is injected.
- `launch_agent_from_cwd()` and the TUI workflow path resolve VCS refs through registered provider patterns. If `gh` is
  unavailable or the workflow is looked up before changing to the target workspace, `#!sase/fix_just` is not found.
- `get_all_workflows(project="sase")` namespaces CWD-local workflows, but it does not load `xprompts/*.yml` from the
  known primary checkout recorded in `~/.sase/projects/sase/sase.gp` unless the current CWD is already that checkout.

The result is brittle: the same prompt works when run inside the `sase` checkout but can silently fall back to a home
agent when run by a background axe/chop process from another environment.

## Design

Make project-scoped repo workflows discoverable by project name, independent of CWD.

1. Extend workflow loading with a project-local workspace source.

- Reuse `get_known_project_workspaces()` to map project names to primary workspace directories from
  `~/.sase/projects/*/*.gp`.
- Load `.yml` and `.yaml` workflows from that workspace's `.xprompts/` and `xprompts/` directories.
- Namespace those workflows as `{project}/{workflow_name}`, matching existing CWD-local namespacing.
- Keep normal priority semantics: CWD-local workflows still win over project-workspace fallback workflows; internal,
  plugin, config, and `~/.config/sase/xprompts/{project}` behavior should remain unchanged.

2. Teach default VCS normalization about known project refs.

- If a segment contains a generic VCS-looking ref such as `#gh:sase` and `sase` is a known project workspace, do not
  prepend `#cd:~` just because the `gh` provider is not registered in the current process.
- Keep `#cd:~` injection for genuinely bare prompts.

3. Add focused regressions.

- Workflow loader test: `get_all_workflows(project="sase")` includes `sase/fix_just` from a known `sase` workspace even
  when the test CWD is elsewhere.
- Parsing test: with only `cd` registered, `normalize_default_vcs_workflow("#gh:sase #!sase/fix_just")` preserves the
  prompt instead of prepending `#cd:~`.
- Launch behavior test: `launch_agent_from_cwd("#gh:sase #!sase/fix_just")` no longer becomes `#cd:~ ...` when `sase` is
  a known project, and the runner/workflow path can resolve the project-local standalone workflow.

4. Revert the `sase_pylimit_split` workaround after the core fix lands.

- Change both chezmoi source and applied config from the absolute `#cd:/home/bryan/projects/github/sase-org/sase ...`
  workaround back to a VCS-scoped prompt:

```text
#gh:sase #!sase/pylimit_split %approve
```

## Verification

- Run targeted tests around workflow loading, VCS parsing, and launcher behavior.
- Run `just install` if needed for this workspace, then `just check` in the SASE repo.
- Because the chezmoi config is also touched, run `just check` in `~/.local/share/chezmoi`.
- Run `chezmoi apply --force` after editing chezmoi source so the applied config matches.
