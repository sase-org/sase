---
create_time: 2026-06-02 13:27:25
status: done
prompt: sdd/prompts/202606/sibling_project_status.md
---
# Plan: Sibling Project Lifecycle State

## Context

SASE already has project lifecycle support split across two repos:

- `sase-core` owns parsing, normalizing, filtering, and listing `PROJECT_STATE` through the Rust `ProjectLifecycleState`
  contract and `sase_core_rs` bindings.
- This repo owns CLI/TUI host behavior, including `sase workspace open`, the Project Management modal, and the `@`
  launch/project picker.

Today the lifecycle contract has only canonical `active` and `inactive` states, with legacy `archived` and `closed`
normalized to `inactive`. Missing `PROJECT_STATE` defaults to `active`. The `@` picker already calls
`list_launchable_projects()` with active-only lifecycle filtering, while the Project Management modal explicitly loads
all project records and hardcodes `active`, `inactive`, and `all` filters.

The requested `sibling` state should represent SASE project records created for configured sibling repositories. These
records must be usable by `sase workspace open -p <sibling> <workspace_num>` but should not appear in normal launch
pickers such as the `@` keymap.

## Goals

1. Add `sibling` as a canonical project lifecycle state.
2. Teach `sase workspace open` to resolve a missing `-p/--project` value from configured `sibling_repos`.
3. When a sibling project record is auto-created, write the necessary ProjectSpec metadata with
   `PROJECT_STATE: sibling`.
4. Preserve active-only default discovery for launch surfaces, especially the `@` TUI picker.
5. Keep Project Management capable of seeing and managing sibling records intentionally.

## Non-Goals

- Do not auto-create arbitrary unknown projects from `workspace open`; only configured sibling repos qualify.
- Do not change the meaning of legacy `archived` or `closed`; they should continue to normalize to `inactive`.
- Do not make sibling projects launchable by default.
- Do not introduce Python-only lifecycle parsing that diverges from `sase-core`.

## Implementation Shape

### 1. Update the Rust lifecycle contract in `../sase-core`

Change `crates/sase_core/src/project_spec.rs`:

- Add `ProjectLifecycleState::Sibling`.
- Return `"sibling"` from `as_str()`.
- Accept `"sibling"` in `parse_target()`.
- Update lifecycle error text from "expected active or inactive" to include `sibling`.
- Ensure `include_state_filter()` and `list_project_records()` naturally support `sibling`.
- Keep `is_active()` true only for `Active`; keep `is_inactive()` true only for `Inactive`.
- In `build_project_record()`, keep `launchable` false for `Sibling` because it is not active.
- Add sibling-specific warning text such as `project is sibling` only if the existing warning model should surface
  non-active states uniformly.

Update Rust tests in the same file:

- Add lifecycle read/update coverage for `PROJECT_STATE: sibling`.
- Add list/filter coverage proving `"sibling"` returns sibling records and `"active"` does not.
- Keep legacy inactive tests unchanged.

The PyO3 binding code should not need structural changes because it serializes the existing wire records, but run the
binding-facing tests to confirm the new state crosses the boundary correctly.

### 2. Update Python lifecycle wire helpers

Change `src/sase/core/project_lifecycle_wire.py`:

- Expand `PROJECT_LIFECYCLE_STATES` to `("active", "inactive", "sibling")`.
- Keep `PROJECT_LIFECYCLE_LEGACY_INACTIVE_STATES` as `("archived", "closed")`.
- Let `normalize_project_lifecycle_state()` accept `sibling`.
- Keep `is_inactive_project_lifecycle_state()` true only for `inactive`.
- Ensure `normalize_project_lifecycle_state_filter("all")` expands to all three canonical states.

Review call sites that compare `record.state == "active"` or use inactive helpers. Most active-only checks should stay
as-is, because sibling should behave as non-launchable by default.

### 3. Add sibling project materialization for `sase workspace open`

Extend `src/sase/main/workspace_handler.py` with a missing-project path used by `_resolve_project_context()`:

- First preserve existing behavior for known projects with `WORKSPACE_DIR`.
- If the project file is missing or lacks `WORKSPACE_DIR`, look for a matching entry in the merged/project-local
  `sibling_repos` configuration.
- Match by `sibling_repos[].name` exactly. Do not infer from arbitrary paths.
- Resolve the sibling primary checkout path relative to the current project's primary workspace directory, reusing the
  same resolution semantics as `src/sase/sibling_repos.py`.
- Validate the sibling primary checkout exists and is a Git repo when the active project is Git-backed.
- Create `~/.sase/projects/<sibling>/<sibling>.sase` if needed.
- Write or update metadata before the first `RUNNING:` or `NAME:` line:
  - `PROJECT_STATE: sibling`
  - `WORKSPACE_DIR: <resolved primary checkout path>`
  - provider-specific metadata only when required by the active VCS provider

For GitHub-style repos, infer the remote identity from the current project and configured sibling name:

- If the current project remote is `git@github.com:sase-org/sase.git`, assume sibling repos use the same owner/org:
  `git@github.com:sase-org/<sibling>.git`.
- Prefer the actual sibling checkout's `origin` URL when available, because it is more reliable than inference.
- Keep this as metadata/validation, not as a network clone path; `workspace open` should materialize from the sibling
  primary checkout path.

For bare-git/local-path projects, keep existing local clone behavior. If `BARE_REPO_DIR` is required for the provider to
identify the project, derive it from the sibling checkout's `origin` when it is a local path or preserve any existing
`BARE_REPO_DIR`.

Make the creation path idempotent:

- Existing sibling ProjectSpecs should be updated only for missing metadata, not rewritten wholesale.
- Existing explicit non-sibling state should not be silently overwritten unless this was auto-created as a sibling
  record; emit a clear error or warning if a configured sibling project exists with a conflicting state.

### 4. Keep launch/project pickers active-only

The `@` keymap uses `ProjectSelectModal`, which loads project entries through
`project_discovery.list_launchable_projects()`. That helper already defaults to `include_states=("active",)` and checks
`record.state == "active"`.

After adding `sibling`, add regression coverage that:

- A `PROJECT_STATE: sibling` record is not returned by `list_launchable_projects()`.
- `is_launchable_project(<sibling>)` returns false under default active-only filtering.
- `ProjectSelectModal` does not include sibling project entries.

Avoid changing the `@` picker to use `"all"` or hardcoded state lists.

### 5. Update Project Management UI intentionally

The Project Management modal should remain the intentional place to inspect hidden projects. Update
`src/sase/ace/tui/modals/project_management_modal.py` and `project_management_rendering.py`:

- Add `sibling` to the filter cycle, likely `active -> sibling -> inactive -> all`.
- Update summary counts to include sibling.
- Add a distinct state style for `sibling`.
- Keep default filter as `active`.
- Decide whether `Enter` on sibling should activate it, matching current non-active behavior, or whether sibling should
  require explicit `a`. Prefer preserving current behavior unless product direction says sibling should be stickier.

Add modal tests for state filtering and rendering with sibling records.

### 6. Update CLI project-state surfaces

Change `src/sase/main/project_handler.py` and `src/sase/main/parser_project.py` as needed:

- Include `sibling` in `sase project list --state ...` choices.
- Allow `sase project set-state <project> sibling` if direct mutation is useful for correcting sibling records.
- Keep `activate` and `deactivate` aliases mapping only to active/inactive.
- Ensure output launchability remains `yes` only for active records.

If direct `set-state sibling` is allowed, document that it is intended for sibling repo bookkeeping and not normal
launch work.

### 7. Documentation and schema

Update docs that currently say only `active`/`inactive` are valid:

- `docs/project_spec.md`
- `docs/configuration.md`
- `docs/workspace.md`
- `docs/ace.md`
- `docs/cli.md`
- `docs/xprompt.md` where active/inactive discovery language should mention sibling as hidden from default discovery.

Update `config/sase.schema.json` only if project lifecycle state is represented there. The existing schema mainly covers
config, so this may be a no-op unless new sibling-repo config fields are introduced.

### 8. Test Plan

In `sase-core`:

- `cargo test -p sase_core project_spec`
- `cargo test -p sase_core_py project_lifecycle` or the closest binding-focused test target

In this repo:

- Focused Python tests:
  - `tests/main/test_workspace_handler_project_resolution.py`
  - `tests/main/test_workspace_handler_list_path.py`
  - `tests/ace/tui/modals/test_project_select_modal.py`
  - `tests/ace/tui/modals/test_project_management_modal_filtering.py`
  - `tests/ace/tui/modals/test_project_management_modal_states.py`
  - any project-handler parser/list tests
- End-to-end command smoke with a temp HOME and configured local `sase.yml`:
  - `sase workspace open -p <configured-sibling> 10`
  - assert the project spec exists, has `PROJECT_STATE: sibling`, and prints a materialized checkout path
  - assert an unconfigured unknown project still fails

After implementation changes in this repo, run:

- `just install`
- `just check`

## Risks and Open Questions

- The current request says "same VCS with the same organization." The safest implementation should prefer the actual
  sibling checkout remote when it exists, and fall back to org inference only when metadata is missing.
- If external workspace-provider plugins require provider-specific project metadata beyond `WORKSPACE_DIR`, this may
  need a small provider hook rather than hardcoding GitHub/bare-git behavior in `workspace_handler.py`.
- Auto-created sibling ProjectSpecs defaulting to `sibling` changes all-state Project Management visibility. That is
  intended, but the UI should make the state obvious so users do not mistake sibling records for ordinary inactive
  projects.
