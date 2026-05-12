---
create_time: 2026-05-12 12:00:27
status: done
prompt: sdd/prompts/202605/remove_local_xprompt_workflows.md
bead_id: sase-34
tier: epic
---
# Remove config-local xprompt workflow support

## Goal

Remove support for standalone xprompt workflows defined under top-level `workflows:` in `sase*.yml` config files, and
move the current `sase_athena.yml` workflows into this repo's file-backed `xprompts/` directory.

The final system should have one workflow definition model:

- `.md` xprompts and `.yml` workflows live in `xprompts/` directories, package resources, or plugin xprompt resources.
- `sase.yml`/`sase_*.yml` may still define ordinary `xprompts:`, snippets, lumberjacks, providers, and other config.
- `sase.yml`/`sase_*.yml` must no longer define standalone xprompt workflows under top-level `workflows:`.
- Scheduled `sase_athena.yml` agents should invoke repo-backed workflows via a VCS/project selector, for example
  `#gh:sase-org/sase #!sase/refresh_docs(...)`.

## Current State

The only real top-level config workflows found are in chezmoi:

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
  - `refresh_docs`
  - `audit_recent_bugs`
  - `audit_recent_improvements`

No sibling plugin repo currently appears to define top-level config workflows.

In this repo, `xprompts/refresh_docs.yml` is a retired placeholder that says the workflow lives in config. The Python
loader currently keeps config workflows first-class through `load_workflows_by_source()` and
`_load_workflows_from_config()`. Tests and docs explicitly assert that overlay config workflows remain global.

In `../sase-core`, the Rust xprompt catalog loader has a parallel `load_config_workflows()` implementation for LSP and
mobile/editor catalog behavior.

## Phase 1 - Migrate Athena Workflows To Repo Files

Owner scope: this repo plus the chezmoi repo only.

1. Replace `xprompts/refresh_docs.yml` with the workflow currently in `sase_athena.yml`.
2. Add `xprompts/audit_recent_bugs.yml`.
3. Add `xprompts/audit_recent_improvements.yml`.
4. Remove the top-level `workflows:` block from `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`.
5. Update all `sase_athena.yml` lumberjack agent prompts that invoke these workflows:
   - `#gh:sase ... #!refresh_docs` -> `#gh:sase-org/sase ... #!sase/refresh_docs`
   - sibling repo refresh-docs jobs should still run the outer workflow from the `sase` repo, passing `project`,
     `gh_ref`, and `threshold` as workflow inputs.
   - `#!audit_recent_bugs` -> `#!sase/audit_recent_bugs`
   - `#!audit_recent_improvements` -> `#!sase/audit_recent_improvements`
6. Preserve marker paths and nested agent behavior. The `project` input should continue to choose the marker path under
   `~/.sase/projects/<project>/...`; the `gh_ref` input should continue to choose the nested `#gh:<gh_ref>` target.

Validation:

- From this repo, verify the migrated workflows load as project-scoped file workflows:
  `sase xprompt list | jq '.[] | select(.name | test("^sase/(refresh_docs|audit_recent_)"))'`
- Explain each migrated workflow: `sase xprompt explain sase/refresh_docs`,
  `sase xprompt explain sase/audit_recent_bugs`, `sase xprompt explain sase/audit_recent_improvements`.
- In chezmoi, run `just check`.
- In this repo, run `just install` then `just check`.
- After committing chezmoi changes in the later commit phase, run `chezmoi apply --force`.

## Phase 2 - Harden VCS-Selected Project Workflow Discovery

Owner scope: this repo, with `../sase-core` only if editor/catalog parity requires it.

This phase proves that embedding `#gh:sase-org/sase` in an agent prompt is enough to expose workflows in this repo's
`xprompts/` directory, even when the agent was launched from home mode or from a sibling repo context.

1. Add focused Python regression tests for launch and foreground paths:
   - `#gh:sase-org/sase #!sase/refresh_docs(...)` resolves the VCS ref, switches/targets the `sase` project, and finds
     the `xprompts/refresh_docs.yml` workflow through the known-project workspace fallback.
   - `#gh:sase-org/sase #!sase/audit_recent_bugs` and `#!sase/audit_recent_improvements` resolve the same way.
   - A prompt that targets a sibling refresh job still uses the `sase` workflow file and passes the sibling target via
     workflow args, rather than trying to load `refresh_docs.yml` from the sibling repo.
2. Check both relevant code paths:
   - `sase run`/foreground path: `_resolve_vcs_cwd()` plus `get_all_workflows()`.
   - background/TUI path: `launch_agents_from_cwd()`, known-project VCS refs, and spawned runner CWD/env setup.
3. Normalize the project key if needed. If `#gh:sase-org/sase` currently produces a project key like `sase-org/sase`
   instead of the registered project name `sase`, fix the resolver or fallback matching so full GitHub refs map to the
   known project workspace.
4. Ensure the xprompt browser/catalog can see these workflows for a VCS-selected project. If Python catalog behavior is
   correct but Rust LSP/mobile catalog behavior diverges, mirror the fix in `../sase-core`.

Validation:

- Targeted Python tests around `tests/test_xprompt_processor_workflow_vcs.py`, `tests/test_workflow_loader_project.py`,
  and launch tests.
- If `../sase-core` changes, run its focused Rust tests for `xprompt_catalog`, then `just check` in `../sase-core`.
- Run this repo's `just install` and `just check`.

## Phase 3 - Remove Python Config Workflow Support

Owner scope: this repo.

1. Delete `load_workflows_by_source()` from `src/sase/config/core.py`, unless another non-runtime diagnostic path still
   needs a replacement that only reports unsupported config.
2. Remove `_load_workflows_from_config()` from `src/sase/xprompt/workflow_loader.py`.
3. Remove config workflows from `get_all_workflows()` priority order and docs/comments.
4. Update or delete tests that currently assert config workflow behavior:
   - `tests/test_config.py::test_load_workflows_by_source_includes_overlay_source`
   - `tests/test_workflow_loader_project.py` tests for global overlay config workflows and local config workflow
     namespacing.
5. Add negative coverage:
   - a config file containing top-level `workflows:` does not make `#!name` resolvable.
   - file-backed workflows in `xprompts/` still resolve and override lower-priority plugin/built-in workflows.
6. Decide whether unsupported `workflows:` should be silently ignored or produce a config diagnostic. Prefer a clear
   non-fatal diagnostic if an existing config-debug surface can expose it without adding new runtime complexity.

Validation:

- Targeted tests for config, workflow loader, xprompt list/explain.
- `just install`
- `just check`

## Phase 4 - Remove Rust/Core Catalog Support

Owner scope: `../sase-core`.

The Rust xprompt catalog is a separate implementation used by LSP/mobile/editor surfaces. It must stop advertising
config-defined workflows once Python runtime support is removed.

1. Remove or disable `CatalogLoader::load_config_workflows()`.
2. Remove the call from `load_all_workflows()`.
3. Keep `load_config_xprompts()` intact; ordinary config `xprompts:` remain supported.
4. Update catalog definition lookup and line-number tests that currently expect config workflow entries such as
   `plug_flow`.
5. Add parity coverage showing:
   - config `xprompts:` still appear.
   - config `workflows:` do not appear.
   - file-backed workflows from a known project workspace still appear when a project is supplied.
6. Check `.sase` project spec handling while touching known workspace loading. The Rust loader currently scans `.gp`;
   Python prefers `.sase` and falls back to `.gp`. If this blocks project workflow discovery in current setups, bring
   Rust into parity.

Validation:

- Focused Rust tests for `xprompt_catalog` and `sase_xprompt_lsp`.
- `just check` in `../sase-core`.

## Phase 5 - Documentation, Schema, And User-Facing Cleanup

Owner scope: this repo, with a final skim of chezmoi.

1. Remove the `workflows` top-level key from `config/sase.schema.json`.
2. Update `docs/xprompt.md`:
   - remove "Config-Based Standalone Workflows";
   - change the refresh-docs section to describe `#!sase/refresh_docs`;
   - clarify that workflow YAML belongs in `xprompts/*.yml`.
3. Update `docs/configuration.md` to remove the `workflows:` config section and the config workflow precedence band.
4. Update any TUI copy/help text that describes config-defined workflows, if found.
5. Confirm `sase_athena.yml` no longer has a top-level `workflows:` block.
6. Confirm no repo in scope contains real top-level config workflow definitions.

Validation:

- `rg -n "^workflows:|Config-Based Standalone Workflows|load_workflows_by_source|_load_workflows_from_config" .` should
  only show deliberate historical SDD material, if any.
- `just install`
- `just check`
- In chezmoi, `just check`.

## Phase 6 - End-To-End Scheduled Workflow Smoke Test

Owner scope: operational validation; no large code changes unless a bug is found.

1. Run explain/list checks from a home-mode or non-`sase` CWD using prompts shaped like the lumberjack agents:
   - `#gh:sase-org/sase #!sase/refresh_docs(project=sase-core, gh_ref=sase-org/sase-core, threshold=25)`
   - `#gh:sase-org/sase #!sase/audit_recent_bugs`
   - `#gh:sase-org/sase #!sase/audit_recent_improvements`
2. If a dry-run mode exists for lumberjacks/chops, use it to confirm the scheduled prompt strings are valid without
   launching long-running agents.
3. Run one low-risk manual foreground explain or no-op threshold case for `refresh_docs` so marker handling and argument
   defaults are exercised.
4. Record any remaining unsupported `workflows:` config warning behavior in docs or release notes.

Validation:

- No `#!refresh_docs`, `#!audit_recent_bugs`, or `#!audit_recent_improvements` unqualified scheduled references remain.
- New prompts resolve through `sase/` file-backed workflow names.
- No config-defined workflow is required for `sase axe` to start its configured lumberjack agents.

## Rollback Strategy

Phase 1 is the only migration that changes scheduled behavior. If discovery hardening fails, keep the repo workflow
files but temporarily leave the config `workflows:` block in `sase_athena.yml` until Phase 2 lands. After Phase 2 proves
`#gh:sase-org/sase #!sase/...` works everywhere, proceed with removal phases.

Do not remove Python or Rust config workflow support before the migrated Athena scheduled prompts are verified against
file-backed workflows.
