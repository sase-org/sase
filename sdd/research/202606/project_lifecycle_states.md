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
- Other broad project scans worth filtering: `ChangeSpecSnapshotCache.find_all_changespecs_cached`
  (`src/sase/ace/changespec/cache.py`); xprompt catalog loading
  (`src/sase/xprompt/loader_sources.py`); mobile gateway project listing
  (`src/sase/integrations/_mobile_helper_beads.py`); bead workspace lookups
  (`src/sase/bead/workspace.py`). These are the surfaces that turn a UI-only feature into a real lifecycle
  contract.
- Project-spec metadata already has read/write precedent: `parse_workspace_dir()` / `parse_bare_repo_dir()` scan
  lines until the first `NAME:` (`src/sase/workspace_provider/utils.py`); `set_workspace_dir()` updates the field
  in-place under `changespec_lock()` with an atomic temp-file replace. A new `PROJECT_STATE:` field should follow
  this pattern verbatim.
- TUI filter precedent: `hide_reverted` / `hide_submitted` reactives are flipped by `.` and `x` in
  `src/sase/ace/tui/app.py` and applied at load time in `actions/changespec/_core.py`. State-mutation precedent:
  `StatusActionsMixin.action_change_status` in `src/sase/ace/tui/actions/status.py` dispatches through
  `_submit_background_task` so the modal stays responsive while the file write runs off the UI thread.
- There is no `sase project` command today. The project-adjacent CLI surface is only `sase changespec` and
  `sase workspace` (`src/sase/main/parser_commands.py`), so this work introduces a new top-level command group
  rather than extending an existing one.

There is no current project-level lifecycle state. "Archived" is already overloaded for terminal ChangeSpecs
(`<project>-archive.sase` produced by `src/sase/ace/changespec/archive.py`), so any project-level design must be
explicit about "project archived" vs the per-ChangeSpec archive file.

This is operational runtime state, not configuration. SASE's `~/.config/sase/sase.yml` is a 5-layer read-only
merge that nothing writes back to (`src/sase/config/core.py`); mutable runtime state lives in dedicated files
written atomically with a temp + `os.replace()` — the canonical examples are `~/.sase/llm_override.json`
(`src/sase/llm_provider/temporary_override.py`) and the ProjectSpec `RUNNING:` field itself. The lifecycle store
should follow that precedent and stay out of the config merge chain.

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
| ChangeSpec cache (`cache.py`) | active projects by default, keyed alongside per-file mtime/size | include archived/closed via the same flag that callers already pass through |
| Xprompt catalog (`loader_sources.py`) | load project-local xprompts from active projects | explicit per-project lookup may resolve archived/closed (read-only) |
| Mobile gateway helpers (`_mobile_helper_beads.py`) | active projects for "all known" scope | explicit project IDs still resolve archived/closed (read-only) |
| Bead workspace (`bead/workspace.py`) | active projects for all-known bead reads | explicit `-p` allowed; work-creating ops should refuse on archived/closed |
| Rust artifact scanner (`agent_scan/scanner.rs`) | accept an explicit allow-list computed by shared listing, or new `project_states` / `exclude_project_states` filters | callers can opt in by listing all states |

The "live RUNNING claim" exception matters: if a user archives a project while an agent is running, ACE should keep
showing that live row until the claim is released. Lifecycle state controls discovery and new work, not process
visibility.

### Transition Safety

`set-state active → archived|closed` should refuse when the project has live `RUNNING` claims or unfinished
artifact rows unless `-f|--force` is passed. The CLI message should list the offending claims so users can
release them deliberately. The TUI action should surface the same confirmation. Re-activation (`→ active`) is
always safe and needs no force flag.

### Legacy `.gp` Write Behavior

`preferred_project_spec_path()` already resolves the canonical `.sase` ahead of a legacy `.gp`. The writer should
update `PROJECT_STATE:` in whichever file is currently authoritative for the project rather than silently
migrating `.gp` → `.sase`; an explicit `sase changespec migrate-extension` step already exists for that
migration. Reading code should accept the field from either filename.

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

### Proposed Rust Core API

The lifecycle enum, parser, and transition rules should live in `../sase-core/crates/sase_core` alongside the
existing `project_spec.rs` helpers and be exposed through `sase_core_rs`. Sketch:

```rust
pub enum ProjectState { Active, Archived, Closed }

pub struct ProjectRecord {
    pub name: String,
    pub state: ProjectState,
    pub project_dir: PathBuf,
    pub project_file: Option<PathBuf>,   // canonical .sase or legacy .gp, whichever exists
    pub archive_file: Option<PathBuf>,
    pub workspace_dir: Option<PathBuf>,
    pub running_claims: u32,
    pub warnings: Vec<String>,           // e.g. unknown PROJECT_STATE value
}

pub fn list_project_records(
    projects_root: &Path,
    include_states: &[ProjectState],     // empty = all
    include_home: bool,
) -> Vec<ProjectRecord>;

pub fn read_project_state(project_file: &Path) -> Result<ProjectState>;

pub fn set_project_state(
    projects_root: &Path,
    project_name: &str,
    new_state: ProjectState,
    force: bool,                         // bypass live-claim refusal
) -> Result<ProjectRecord>;
```

Rules to encode in core: missing field → `Active`; unknown value → `Active` with a `warnings` entry, never written
back automatically; writes are atomic and re-use the existing `changespec_lock` discipline; records sort by name;
`home` is excluded unless `include_home=true`.

Python callers become thin: the CLI handler decodes argv, calls the binding, and prints; the TUI calls the
binding inside `_submit_background_task` and refreshes the modal on completion. No parallel state machine in
Python.

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

### TUI Implementation Hooks

Reuse the precedents already in the codebase rather than inventing parallel ones:

- Visibility filter: model it on `hide_reverted` / `hide_submitted` — a reactive on `sase ace`'s app
  (`src/sase/ace/tui/app.py`) flipped by a key, with the filter applied at load time in the picker. A
  `hide_inactive_projects` reactive defaulting to `True` matches the existing UX.
- State-mutating actions: dispatch through `_submit_background_task` like
  `StatusActionsMixin.action_change_status` (`src/sase/ace/tui/actions/status.py`) so the lifecycle write does
  not block the UI thread, and refresh the modal on completion.
- Keymap registration: add the new bindings to `src/sase/default_config.yml` per the repo gotcha, update the
  help modal (`src/sase/ace/tui/modals/help_modal/`) and footer conditional-keymap convention so the new
  bindings are discoverable.
- Saved last-project state: the existing stale-launchable invalidation in `_entry_points.py` should be extended
  to drop a remembered selection whose project is no longer `active`.
- File-watch / refresh: a CLI-driven `set-state` while the TUI is open should be reflected without restart.
  Either watch the ProjectSpec via the existing change-notification path or piggy-back on the next
  picker/Agents-tab refresh tick. Document the expected latency rather than implementing a new watcher just for
  this field.

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

### Option E: Central Registry File

Example: `~/.sase/projects/registry.json` mapping project name → state, written atomically like
`~/.sase/llm_override.json` (`src/sase/llm_provider/temporary_override.py`).

Pros:

- Single place to read/write — no ProjectSpec parser changes; cheap to load.
- Matches the established mutable-state-file convention for runtime state.

Cons:

- Second source of truth that can drift from the directory listing (deleted/renamed projects leave stale
  entries; reconciliation logic needed).
- Not co-located with the project; moving/copying a project does not carry its state.
- Central-file write contention if both CLI and TUI write concurrently.

Viable as a fallback if there is strong resistance to editing the active ProjectSpec for a non-ChangeSpec
change, but loses the "lifecycle filter is nearly free where discovery already opens the file" property of
Option A.

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
- Whether `archived` and `closed` are both needed, or whether a single `inactive` state is enough. The
  semantics in this note assume both: archived = paused/returnable, closed = retired/non-launchable. Collapsing
  them later is easy (treat `closed` as alias for `archived`); splitting later is harder.
- Whether launching an archived/closed project from an expanded picker should auto-reactivate, require an
  explicit confirm, or remain blocked. Recommendation in this note: confirm-and-reopen for archived; refuse for
  closed without an explicit `sase project activate` first.
- Field name: `PROJECT_STATE:` vs `PROJECT_STATUS:` vs `STATE:`. `PROJECT_STATE:` is preferred because plain
  `STATE:` collides visually with ChangeSpec status, and `STATUS:` invites confusion with the ChangeSpec
  `STATUS:` block.

## Key References

| Concern | File:line |
|---|---|
| Projects dir root | `src/sase/core/paths.py` (`sase_projects_dir()`) |
| ProjectSpec format and metadata header | `docs/project_spec.md` |
| Project metadata read precedent | `src/sase/workspace_provider/utils.py` (`parse_workspace_dir`, `parse_bare_repo_dir`) |
| Project metadata write precedent | `src/sase/workspace_provider/utils.py` (`set_workspace_dir`) |
| Canonical `.sase` / legacy `.gp` resolution | `src/sase/ace/changespec/project_spec_path.py` (`preferred_project_spec_path`) |
| Rust path mirror | `sase-core/crates/sase_core/src/project_spec.rs` |
| Project discovery (launch picker) | `src/sase/ace/tui/modals/project_discovery.py` (`list_launchable_projects`) |
| TUI project modal | `src/sase/ace/tui/modals/project_select_modal.py` |
| TUI hide/show filter precedent | `src/sase/ace/tui/app.py` (`hide_reverted`, `hide_submitted`), `actions/changespec/_core.py` |
| TUI state-mutation precedent | `src/sase/ace/tui/actions/status.py` (`action_change_status`, `_submit_background_task`) |
| Default keymap registry | `src/sase/default_config.yml` |
| ChangeSpec all-project scan | `src/sase/ace/changespec/__init__.py` (`find_all_changespecs`) |
| ChangeSpec scan cache | `src/sase/ace/changespec/cache.py` (`ChangeSpecSnapshotCache`) |
| Per-ChangeSpec archive move (contrast) | `src/sase/ace/changespec/archive.py` |
| Xprompt all-project catalog | `src/sase/xprompt/loader_sources.py` |
| Mobile gateway project enumeration | `src/sase/integrations/_mobile_helper_beads.py` |
| Bead workspace enumeration | `src/sase/bead/workspace.py` |
| Rust artifact scan (all-project walk) | `sase-core/crates/sase_core/src/agent_scan/scanner.rs` |
| Mutable-state-file precedent | `src/sase/llm_provider/temporary_override.py` |
| Config merge (read-only, why not here) | `src/sase/config/core.py` |
| CLI parser registration | `src/sase/main/parser_commands.py`, `src/sase/main/parser.py`, `src/sase/main/entry.py` |
| Backend boundary rule | `memory/short/rust_core_backend_boundary.md` |
| Short+long option convention | `memory/short/gotchas.md` |

