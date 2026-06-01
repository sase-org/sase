# Project Lifecycle States

Date: 2026-06-01

## Question

Users need a way to dynamically configure which SASE projects are active, archived, or closed from both the command
line and the ACE TUI. What storage model and command/UI shape should SASE use?

## Current State

SASE discovers projects from `~/.sase/projects/<project>/`. The active ProjectSpec is
`<project>.sase`; terminal ChangeSpecs are moved to the adjacent `<project>-archive.sase` file. Legacy `.gp` files
remain readable through the same helpers.

Important current contracts:

- ProjectSpec metadata lives before the first `NAME:` line. Today documented fields are `BARE_REPO_DIR`,
  `WORKSPACE_DIR`, and `RUNNING` (`docs/project_spec.md`).
- `preferred_project_spec_path()` centralizes canonical `.sase` vs legacy `.gp` lookup in both Python
  (`src/sase/ace/changespec/project_spec_path.py`) and Rust (`sase-core/crates/sase_core/src/project_spec.rs`).
- ACE's launch picker uses `list_launchable_projects()` in
  `src/sase/ace/tui/modals/project_discovery.py`. It already filters out empty/stale/unlaunchable directories by
  requiring `WORKSPACE_DIR`, an existing workspace path, and successful `detect_workflow_type()`.
- `find_all_changespecs()` in `src/sase/ace/changespec/__init__.py` reads both active and archive ProjectSpec files
  for every project directory. Search and many cross-project helpers therefore treat project directories as the broad
  universe.
- The Agents tab loader uses `get_all_project_files()` in
  `src/sase/ace/tui/models/_loaders/_running_loaders.py`; it currently returns every active ProjectSpec it can find.
- Rust's artifact scanner walks `projects_root/<project>/artifacts/...` without lifecycle filtering
  (`sase-core/crates/sase_core/src/agent_scan/scanner.rs`). The Rust/Python boundary guidance means shared project
  lifecycle filtering should not be implemented separately in every frontend.

There is no current project-level lifecycle state. "Archived" is already overloaded for terminal ChangeSpecs, so any
project-level design must be explicit about "project archived" vs `<project>-archive.sase`.

## Recommendation

Add a project-level lifecycle metadata field to the active ProjectSpec:

```text
PROJECT_STATE: active
```

Allowed values:

- `active`: default when the field is missing. The project appears in default launch pickers and normal active scans.
- `archived`: hidden from default launch pickers and active dashboards, but still included when users ask for archived
  projects/history. Reopen is expected and cheap.
- `closed`: hidden from default launch and active scans, treated as intentionally retired. It remains queryable with an
  explicit `--include-closed` / TUI filter and can be reopened by setting state back to `active`.

Store the field in the active ProjectSpec rather than a separate file or directory rename. It matches the existing
metadata model, survives legacy `.gp` fallback, keeps all per-project state under the existing project directory, and
can reuse the existing ProjectSpec lock/atomic-write machinery. Unknown metadata before `NAME:` is currently ignored by
the ChangeSpec parser, so old readers continue to parse ChangeSpecs.

Because CLI and TUI both need the same lifecycle semantics, the authoritative enum/defaulting/filter rules should live
in `sase-core` and be exposed to Python through `sase_core_rs` if bindings are available for this area. The Python repo
should have only thin adapters for file locking and UI presentation.

## Semantics

Default behavior should optimize for active work:

| Surface | Default | Explicit expanded mode |
| --- | --- | --- |
| `sase project list` | active projects | `--all`, `--state archived`, `--state closed` |
| `sase ace` project picker | active launchable projects | a lifecycle filter/toggle in the picker |
| ACE Agents tab project scans | active projects plus any project with a live RUNNING claim | include archived/closed via filter |
| ChangeSpec search | active projects by default, with `--all-projects` / state filters if changed | include archived/closed |
| Workspace commands | infer/operate on explicit project regardless of state, but warn when archived/closed | no special flag needed for explicit `-p` |

The "live RUNNING claim" exception matters: if a user archives a project while an agent is running, ACE should keep
showing that live row until the claim is released. Lifecycle state controls discovery and new work, not process
visibility.

`home` should remain special. It should not be duplicated as a project picker `[P] home`; either leave it unmanaged or
permit the metadata field but ignore it for the explicit `[H] ~` option.

## CLI Shape

Add a new top-level command group rather than burying this under `changespec`, because the state belongs to projects,
not individual ChangeSpecs:

```bash
sase project list [-s|--state active|archived|closed] [-a|--all] [-j|--json]
sase project status [-p|--project <name>] [-j|--json]
sase project set-state <project> <active|archived|closed>
sase project archive <project>   # alias for set-state archived
sase project close <project>     # alias for set-state closed
sase project reopen <project>    # alias for set-state active
```

Keep short options where options exist, per repo convention (`-s`, `-a`, `-j`, `-p`). The aliases are worth adding
because they match how users think during cleanup, while `set-state` is better for scripts.

Human list output should show at least project name, state, launchable yes/no, workspace path, and active ChangeSpec
count. JSON should include stable fields:

```json
{
  "project": "sase",
  "state": "active",
  "launchable": true,
  "workspace_dir": "/path/to/primary",
  "active_changespec_count": 3,
  "archive_changespec_count": 42,
  "project_file": "/home/user/.sase/projects/sase/sase.sase"
}
```

State writes should create the active ProjectSpec if needed, but only when the caller explicitly names a project. The
write path should preserve all existing metadata and ChangeSpec blocks, inserting `PROJECT_STATE:` before `RUNNING:` or
the first `NAME:` when absent.

## TUI Shape

Use the existing project picker (`ProjectSelectModal`) rather than a separate modal. The picker already centralizes
project selection for `@`, axe bg commands, and revive flows.

Recommended picker behavior:

- Default rows: active launchable `[P]` projects, `[H] ~`, and active ChangeSpecs as today.
- Add lifecycle chips or a compact mode toggle in the modal footer/header: `active`, `archived`, `closed`, `all`.
- Render archived/closed project rows dimmed and labeled, for example `[P] myproj [archived]`.
- Prevent launching into archived/closed projects by default. If selected from an expanded mode, either ask for a
  one-shot confirmation or offer "reopen and launch"; avoid silently starting work in a closed project.
- Add project-state actions on highlighted project rows: archive, close, reopen. These should call the same backend as
  the CLI, then refresh the modal list.

Do not use `ctrl+d` delete as the lifecycle UI. Delete currently removes empty project files and is more destructive
than archiving/closing.

## Storage Options Considered

### Option A: `PROJECT_STATE:` In ProjectSpec Metadata

Pros:

- Fits the documented ProjectSpec metadata model.
- No new file discovery path.
- Can use existing ProjectSpec locks and atomic writes.
- Keeps state next to `WORKSPACE_DIR`, which lifecycle filtering needs anyway.
- Missing field defaults cleanly to `active`, so no migration is required.

Cons:

- Updates touch a hot file that also stores `RUNNING` and ChangeSpecs.
- Need to clarify terminology because `<project>-archive.sase` already means archived ChangeSpecs, not archived
  project.
- Rust and Python helpers both need to learn the metadata field.

This is the recommended option.

### Option B: Sidecar `project.json`

Pros:

- Structured and extensible.
- Avoids editing ProjectSpec for lifecycle-only changes.
- Can carry audit fields later, such as `updated_at` or `updated_by`.

Cons:

- Adds another per-project file every scanner must read.
- More migration/repair states: ProjectSpec without sidecar, sidecar without ProjectSpec, stale sidecar.
- Existing project metadata becomes split between two files.

This is reasonable only if project metadata is expected to grow substantially beyond lifecycle state.

### Option C: Move Directories

Examples: `~/.sase/projects-archive/<project>` or `~/.sase/projects/<state>/<project>`.

Reject. Many artifacts, notifications, agent metadata, and saved selections store project-file paths or assume the
current `projects/<project>/...` layout. Directory moves would create avoidable path churn and migration risk.

### Option D: User Config Lists

Examples: `archived_projects: [...]` in `~/.config/sase/sase.yml`.

Reject. This is runtime state, not static configuration. The user asked for dynamic CLI/TUI updates; editing merged YAML
overlays would be surprising, hard to make atomic, and awkward across machines.

## Implementation Plan

1. Add core lifecycle model:
   - `ProjectState = active|archived|closed`.
   - Default missing/unknown handling: missing means active; unknown should surface a warning and behave as archived for
     launch safety, or fail validation in explicit `project status`.
   - Helpers to parse metadata before first `NAME:` and emit/update `PROJECT_STATE:`.

2. Add Python adapters:
   - `get_project_state(project_file)`.
   - `set_project_state(project_file, state)` using `changespec_lock()` and `write_changespec_atomic()`.
   - `list_projects(states=..., include_unlaunchable=...)` returning a structured record used by CLI and TUI.

3. Wire CLI:
   - New parser module `src/sase/main/parser_project.py`.
   - New handler `src/sase/main/project_handler.py`.
   - Register it in `src/sase/main/parser.py` and `src/sase/main/entry.py`.
   - Document in `docs/configuration.md`, `docs/cli.md`, and `docs/project_spec.md`.

4. Wire TUI:
   - Extend `project_discovery.py` to return records rather than only names.
   - Update `ProjectSelectModal` to filter by state and expose state actions.
   - Clear or invalidate saved last project selections when a project becomes archived/closed, similar to the current
     stale launchable-project handling in `_entry_points.py`.

5. Update scanning/search surfaces:
   - Agents tab: default to active projects, but retain live running claims from archived/closed projects.
   - ChangeSpec query/search: decide whether default search should remain "all known ChangeSpecs" for backward
     compatibility or move to active-only with an explicit all-state flag. If changed, do it as a documented behavior
     change.
   - Rust artifact scanning/index queries: add optional `project_states` / `exclude_project_states` only if the scan is
     responsible for filtering. Otherwise pass an explicit `only_projects` list computed by shared project listing.

6. Tests:
   - metadata parse/update preserves existing ProjectSpec content and inserts before `RUNNING:`/`NAME:`;
   - missing `PROJECT_STATE` defaults to active;
   - CLI list/status/set-state JSON and exit codes;
   - launch picker hides archived/closed by default and shows them in expanded mode;
   - saved last selection is cleared when its project is no longer active;
   - Agents tab still shows live agents for archived/closed projects.

## Open Decisions

- Whether `closed` should be purely a stronger hidden state or should also block explicit workspace commands. I
  recommend warning but allowing explicit commands; explicit `-p` is strong user intent.
- Whether ChangeSpec search defaults should stay cross-project/all-state for backward compatibility. I recommend not
  changing search defaults in the first phase; add state filters first, then revisit after users experience the project
  list and picker changes.
- Whether to record an audit trail for project state changes. If audit matters, add a small `PROJECT_STATE_HISTORY:`
  metadata section later rather than blocking the first implementation.

