---
create_time: 2026-05-01 01:10:11
status: done
prompt: sdd/prompts/202605/refresh_docs_config_workflow.md
---
# Plan: Factor `refresh_docs` Into Athena Config

## Goal

Make the documentation-refresh workflow usable by SASE plugin repos without depending on the `sase` repo's project-local
`#!sase/refresh_docs` workflow.

The target shape is:

- `sase_athena.yml` owns one global standalone workflow named `refresh_docs`.
- All scheduled `refresh_docs` agent chops in `sase_athena.yml` invoke `#!refresh_docs(...)`.
- The main SASE scheduled chop (`sase_refresh_docs`) uses the same global workflow as the plugin repo chops.

## Current State

- The real workflow implementation lives only at `xprompts/refresh_docs.yml` in this repo.
- Because CWD-local YAML workflows are namespaced by detected project, that workflow resolves as `#!sase/refresh_docs`.
- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` already has a dedicated `refresh_docs` lumberjack and
  per-repo chops, but every chop still invokes `#!sase/refresh_docs`.
- Plugin repos can launch those chops, but the workflow name depends on the SASE repo's project-local xprompt catalog.
- SASE currently supports config-based inline xprompts under `xprompts:`, but it does not support config-based
  standalone YAML workflows. Putting a multi-step workflow directly in `sase_athena.yml` therefore requires a small SASE
  loader change.

## Design

### 1. Add Config-Based Workflow Loading

Add a top-level config section:

```yaml
workflows:
  refresh_docs:
    input:
      project: { type: line, default: "sase" }
      gh_ref: { type: line, default: "sase" }
      threshold: { type: int, default: 50 }
    steps: ...
```

Implement this as first-class standalone workflow discovery, not as an `xprompts:` entry. This avoids overloading inline
xprompt parsing and keeps `#!refresh_docs` semantics explicit.

Likely SASE changes:

- Add `load_workflows_by_source()` beside `load_xprompts_by_source()` in `src/sase/config/core.py`.
- Refactor `src/sase/xprompt/workflow_loader.py` so workflow parsing can load either:
  - a YAML file, or
  - a named config mapping from `workflows:`.
- Insert config workflows into `get_all_workflows()` with priority below file-based workflows and above plugin/internal
  workflows, matching config-based xprompt precedence.
- Namespace only local CWD `sase.yml` workflow entries when a project is detected. User config and overlay workflows
  remain global, so `sase_athena.yml` defines `refresh_docs`, not `sase/refresh_docs`.
- Add focused tests for config workflow loading, overlay source attribution, and `#!refresh_docs` resolution.

### 2. Move the Generic Workflow Body to `sase_athena.yml`

Copy the current generic implementation from `xprompts/refresh_docs.yml` into
`~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` under `workflows.refresh_docs`.

Keep the existing inputs and behavior:

- `project` selects `~/.sase/projects/<project>/refresh_docs_marker`.
- `gh_ref` is forwarded to the nested docs agent as `#gh:<gh_ref>`.
- `threshold` defaults to `50`; plugin repo chops keep passing `25`.
- `count_commits` and `update_marker` continue to use the current SHA-plus-timestamp marker fallback.

### 3. Update the Athena Refresh-Docs Chops

In `sase_athena.yml`, update the `refresh_docs` lumberjack's configured agent chops:

- Main SASE chop:
  - from `#gh:sase #!sase/refresh_docs`
  - to `#gh:sase #!refresh_docs`
- Plugin repo chops:
  - from `#gh:sase-org/<repo> #!sase/refresh_docs(project=..., gh_ref=..., threshold=25)`
  - to `#gh:sase-org/<repo> #!refresh_docs(project=..., gh_ref=..., threshold=25)`

This is the intended delegation boundary: every scheduled chop delegates to the same globally configured workflow.

### 4. Handle the Old Project-Local Workflow

Do not duplicate long-term logic in `xprompts/refresh_docs.yml`.

Preferred outcome:

- Remove or retire the repo-local workflow once all in-repo docs/tests/examples stop advertising `#!sase/refresh_docs`.
- Update documentation to describe `#!refresh_docs` as the global configured workflow.

Compatibility note:

- A wrapper `#!sase/refresh_docs` that internally calls `#!refresh_docs` is not currently supported by the workflow
  engine. Standalone workflows are deliberately rejected when embedded inside other workflow prompt text. Adding nested
  standalone-workflow execution would be a larger semantic change than this factoring task needs.
- If preserving the old name is required, the pragmatic short-term fallback is to leave `xprompts/refresh_docs.yml` in
  place temporarily as a duplicate and document `#!refresh_docs` as the canonical path. The implementation should prefer
  removing stale references over maintaining two active copies.

### 5. Validation

Run the relevant checks after implementation:

- In SASE: `just install` if needed, then `just check`.
- In chezmoi: `just check`.
- Run targeted sanity commands:
  - `sase xprompt explain refresh_docs`
  - `sase axe chop list` or `sase axe lumberjack list` to confirm chop config parsing.

If the chezmoi repo is committed later, run `chezmoi apply --force` after the commit per repo memory. This task does not
request a commit, so applying is optional unless we need the live config to pick up the new workflow immediately.

## Risks

- Config-based workflows are a new public config surface. Keep the feature narrow: top-level `workflows:` entries use
  the same schema as YAML workflow files, no new workflow semantics.
- Removing `#!sase/refresh_docs` can break old manual invocations. Search and update in-repo references; if external
  usage is a concern, keep the old workflow for one transition cycle and mark `#!refresh_docs` canonical.
- The applied `~/.config/sase/sase_athena.yml` will not change until `chezmoi apply` runs. Validation should either run
  against the source file via unit tests or apply after the user approves that live-config change.
