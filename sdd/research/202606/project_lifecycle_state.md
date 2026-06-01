---
create_time: 2026-06-01
updated_time: 2026-06-01
status: research
---

# Project Lifecycle State Research

## Question

Users need a dynamic way to mark SASE projects as active, archived, or closed, and they need to do it from both the CLI
and the ace TUI. What storage model, command shape, and TUI integration should SASE use?

## Recommendation

Add first-class project lifecycle state with three values: `active`, `archived`, and `closed`.

Store the state as a ProjectSpec metadata field in the active ProjectSpec header:

```text
PROJECT_STATE: active
WORKSPACE_DIR: ~/projects/git/sase/
RUNNING:
  #10 | 12345 | run | sase_feature_1 | 260601_120000
```

Missing `PROJECT_STATE` means `active`, so existing projects need no migration. Use `PROJECT_STATE`, not `STATUS`, to
avoid colliding with ChangeSpec status fields and with the existing `<project>-archive.sase` ChangeSpec archive file.

Put the lifecycle enum, parsing/updating, transition validation, and filtering contract in `sase-core`, exposed through
`sase_core_rs`. Python CLI and TUI code should be thin callers. The practical migration path can keep the existing
Python `changespec_lock()` and `write_changespec_atomic()` host IO wrapper while moving the pure project-state parser and
content update logic into Rust.

Add a new `sase project` CLI group and a TUI project-management surface. Default daily views should show active projects
only. Inactive projects remain discoverable from explicit project-management commands and should be easy to reactivate.

## Current Model

There is no project lifecycle state today. A project is implicit: a directory under `~/.sase/projects/<name>/` with a
valid active ProjectSpec and, for launchability, a valid `WORKSPACE_DIR`.

Important current facts:

- `docs/project_spec.md:1` defines a ProjectSpec as the project-level `.sase` file, with optional project metadata
  before the first `NAME:` line.
- `docs/project_spec.md:60` lists the current metadata fields: `BARE_REPO_DIR`, `WORKSPACE_DIR`, and `RUNNING`.
- `src/sase/workspace_provider/utils.py:64` and `:93` scan the ProjectSpec header for project metadata.
- `src/sase/workspace_provider/utils.py:122` updates `WORKSPACE_DIR` under `changespec_lock()`, inserting before
  `RUNNING:` or `NAME:`.
- `src/sase/running_field/_operations.py:89` claims workspaces under the same ProjectSpec lock.
- `src/sase/ace/changespec/project_spec_path.py` and
  `../sase-core/crates/sase_core/src/project_spec.rs` agree on canonical `<project>.sase`, archive
  `<project>-archive.sase`, and legacy `.gp` fallback paths.
- `src/sase/main/parser.py:124` through `:160` registers top-level commands and has no `project` command today.

Broad scans currently walk all project directories:

- `src/sase/ace/changespec/__init__.py:142` and `cache.py:56` load ChangeSpecs across every project and archive file.
- `src/sase/ace/tui/modals/project_discovery.py:13` lists launchable projects by scanning `~/.sase/projects`.
- `src/sase/ace/tui/models/_loaders/_running_loaders.py:56` reads every ProjectSpec for `RUNNING` claims.
- `_done_loaders.py:181` and `_workflow_loaders.py:30` scan artifact directories across all projects.
- `../sase-core/crates/sase_core/src/agent_scan/scanner.rs:107` scans all project artifact directories and currently has
  only an `only_projects` include list.
- `src/sase/xprompt/loader_sources.py:380`, `src/sase/bead/workspace.py:43`, and
  `src/sase/integrations/_mobile_helper_beads.py:195` each maintain their own known-project scans.

So lifecycle state is a shared domain filter, not just a TUI picker feature.

## Lifecycle Semantics

Recommended initial behavior:

| State | Default visibility | Launch/work behavior | Workspace expectation | Intended use |
| --- | --- | --- | --- | --- |
| `active` | Included in normal CLI/TUI/xprompt/bead/mobile scans | Allowed | Required for launches | Current work |
| `archived` | Hidden from daily views; shown by explicit archived/all filters | Blocked until reactivated | Usually present | Dormant but likely useful again |
| `closed` | Hidden except explicit project management/history reads | Blocked until reactivated | Not required | Historical or no longer operational |

Safety rules:

- `home` should remain a system scope and not be configurable in the first implementation.
- Archive/close should refuse when the project has live `RUNNING` claims or active artifact markers, unless the user
  passes `--force`.
- Live agents and workflows from archived/closed projects must remain visible until they finish. Lifecycle hiding should
  not make active work disappear.
- Launching an archived or closed project should fail with a clear reactivation hint, rather than silently reactivating.

## Storage Options

### `sase.yml` Config

Rejected. The config layer is a read-only merge of bundled defaults, plugin defaults, user config, overlays, and optional
local config (`src/sase/config/core.py:1`). The ace TUI disables local config inheritance for its process. TUI-mutated
project lifecycle state should not rewrite user-authored or chezmoi-managed YAML.

### Moving Project Directories

Rejected. Many paths assume `~/.sase/projects/<project>/...`: ProjectSpecs, artifacts, branch maps, mobile context,
workspace helpers, and marker JSON. Moving directories would break historical references and would also overload the word
"archive", which already means terminal ChangeSpecs in `<project>-archive.sase`.

### Per-Project `project.json`

Viable, but not the best MVP storage. It is structured, extensible, and avoids touching ChangeSpec text. The problem is
coordination: lifecycle transitions must be race-safe with `RUNNING` claims, and those claims already use the ProjectSpec
lock. A sidecar would need either a second lock plus strict lock ordering, or it would still need to take the ProjectSpec
lock while reading/writing sidecar state. It also adds drift handling for "metadata exists but ProjectSpec does not" and
requires every scanner to join two files.

Use a sidecar later only if project metadata grows beyond a small lifecycle field.

### ProjectSpec Header Field

Recommended. It is co-located with the project record, follows existing metadata precedent, defaults cleanly when absent,
and can share the same lock as `RUNNING` so archive/close and launch/claim decisions are serialized. The only real cost
is that changing project state updates the active ProjectSpec mtime and invalidates the ChangeSpec parse cache for that
file. Lifecycle changes should be rare enough that this is acceptable.

## Core Contract

Add a Rust-owned project lifecycle module and expose it through the Python binding:

```rust
enum ProjectLifecycle {
    Active,
    Archived,
    Closed,
}

struct ProjectRecordWire {
    name: String,
    lifecycle: ProjectLifecycle,
    project_dir: String,
    project_file: Option<String>,
    archive_file: Option<String>,
    workspace_dir: Option<String>,
    has_running_claims: bool,
    warnings: Vec<String>,
}
```

Suggested operations:

- `read_project_lifecycle(project_file) -> ProjectLifecycle`
- `apply_project_lifecycle_update(content, lifecycle) -> updated_content`
- `list_project_records(projects_root, include_lifecycles, include_home=false)`
- `set_project_lifecycle(projects_root, project_name, lifecycle, force=false)`
- `filter_project_records(records, include_lifecycles)`

Rules:

- Missing `PROJECT_STATE` means `active`.
- Invalid stored values should return a warning and behave as `active` so a typo does not hide a project. Writers must
  reject invalid values.
- Records should be sorted by project name.
- Legacy `.gp` paths should follow the same preferred-path logic as existing ProjectSpec helpers.
- Launch/workspace-claim code should check lifecycle while holding the ProjectSpec lock before writing a new `RUNNING`
  claim.

## CLI Shape

Add a top-level `sase project` command rather than extending `workspace`. Workspace commands manage checkouts; lifecycle
state affects ChangeSpecs, agents, xprompts, beads, mobile helpers, and launch policy.

Recommended commands:

```bash
sase project list [-s|--state active|archived|closed|all] [-j|--json]
sase project show <project> [-j|--json]
sase project set-state <project> <active|archived|closed> [-f|--force]
sase project activate <project> [-f|--force]
sase project archive <project> [-f|--force]
sase project close <project> [-f|--force]
```

`list` should default to `active`. JSON output should include lifecycle, workspace path/health, active claim count, and
whether the state came from an explicit field or the missing-field default. Follow the repo convention that command-line
options have both short and long forms where possible.

## TUI Shape

Do not overload Ctrl+D deletion in `ProjectSelectModal`. Deletion is destructive; lifecycle is reversible metadata.

Recommended TUI design:

- Add a Project Management modal listing all projects with lifecycle, workspace health, active claim count, and basic
  ChangeSpec counts.
- Provide actions on the selected project to activate, archive, or close via the same backend mutation as the CLI.
- Keep the launch-oriented `ProjectSelectModal` active-only by default, with state badges if inactive projects are shown
  through an explicit filter.
- Add a filter/toggle for active, archived, closed, and all in the management modal.
- Run mutations through the existing background-task pattern used by status actions, then reload project records,
  ChangeSpecs, and relevant agent/project filters.
- Update help, footer bindings, command catalog, keymap types, and `src/sase/default_config.yml` when adding keybindings.

Manual refresh is enough for an MVP. A file watcher for ProjectSpec metadata can be added later if CLI changes need to
appear in a long-running TUI without refresh.

## Integration Points

Default broad scans should use active projects unless the caller explicitly asks for inactive/all projects:

- ChangeSpec discovery and cache: hide inactive projects by default; add an internal/all-states option for project
  management and explicit history queries.
- TUI project selection: list active launch targets by default.
- Agent loading: always load live `RUNNING` claims across all lifecycle states; completed/history artifacts can default
  to active projects with an explicit all-projects mode.
- Rust artifact scanner/index: add lifecycle filtering or accept a prefiltered project list, because current options only
  support `only_projects`.
- Xprompt known-project loading: default to active project workspaces; explicit project references can report that a
  project is archived/closed and suggest activation.
- Mobile and bead helpers: `all_known` should mean active by default; explicit project reads may include lifecycle in the
  response and block work/launch operations for inactive projects.
- CWD/project inference should still resolve archived/closed projects so users can reactivate them from inside a
  workspace, but work operations should enforce lifecycle policy after resolution.

## Rollout And Tests

1. Add core lifecycle enum, header parse/update helpers, and record listing.
2. Add the Python facade and CLI `sase project list/show/set-state`.
3. Update launch/workspace claim paths to enforce lifecycle under the ProjectSpec lock.
4. Update project discovery and ChangeSpec scans to default to active projects.
5. Add the TUI Project Management modal and active-only launch picker behavior.
6. Extend agent artifact, xprompt, bead, and mobile scans with intentional lifecycle filters.
7. Update `docs/project_spec.md` and user-facing CLI/TUI docs.

Test coverage should include Rust parsing/update tests, Python facade lock/write tests, CLI JSON shape, legacy `.gp`
fallback, ChangeSpec scan filtering, launch blocking for inactive projects, TUI modal actions, and proof that live agents
from archived/closed projects remain visible.

No bulk migration is needed because missing `PROJECT_STATE` means `active`.
